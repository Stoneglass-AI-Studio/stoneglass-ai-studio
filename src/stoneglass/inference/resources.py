# SPDX-License-Identifier: GPL-3.0-or-later
"""Versioned, hash-pinned local SDXL bundles; no inference-library imports or I/O online."""

import ctypes
import hashlib
import json
import math
import os
import re
import stat
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from stoneglass.inference.contracts import InferenceContext, ProgressEvent, ProgressStage
from stoneglass.inference.errors import ErrorCode, InferenceError

CONFIG_FILES = (
    "model_index.json", "unet/config.json", "vae/config.json",
    "text_encoder/config.json", "text_encoder_2/config.json", "scheduler/scheduler_config.json",
    *(f"{name}/{file}" for name in ("tokenizer", "tokenizer_2") for file in
      ("vocab.json", "merges.txt", "tokenizer_config.json", "special_tokens_map.json")),
)
_HEX = re.compile(r"[a-f0-9]{64}\Z")
_SIZES = {"F16": 2, "BF16": 2, "F32": 4, "I64": 8, "I32": 4, "BOOL": 1}
_MAX_JSON = 8 * 1024 * 1024


def _drive_type(anchor: str) -> int:
    function = ctypes.windll.kernel32.GetDriveTypeW
    function.argtypes, function.restype = [ctypes.c_wchar_p], ctypes.c_uint
    return int(function(anchor))


def invalid(message: str) -> InferenceError:
    return InferenceError(ErrorCode.INVALID_RESOURCES, message + " Nothing was downloaded.")


def strict_local(path: Path, *, directory: bool = False) -> Path:
    """Reject redirects/network/cloud placeholders *before* opening file contents.

    Deliberately reject symlinks/junctions instead of following potentially remote
    targets. Fixed/removable/RAM volumes only; mapped network drives are excluded.
    """
    if not isinstance(path, Path) or not path.is_absolute() or str(path).startswith(("\\\\", "//")):
        raise invalid("Select an absolute path on a local disk.")
    if ".." in path.parts or any(":" in part for part in path.parts[1:]):
        raise invalid("Use a local path without parent traversal.")
    if os.name == "nt":
        if _drive_type(path.anchor) not in (2, 3, 6):
            raise invalid("Network or unavailable drives cannot supply inference resources.")
    try:
        for part in (*reversed(path.parents), path):
            info = part.lstat()
            # OFFLINE, REPARSE_POINT, RECALL_ON_OPEN, RECALL_ON_DATA_ACCESS.
            if part.is_symlink() or getattr(info, "st_file_attributes", 0) & 0x441400:
                raise invalid("Use fully resident local files without symlinks, junctions or cloud placeholders.")
        if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
            raise OSError()
    except (OSError, ValueError):
        raise invalid("A required local resource is missing or unreadable. Select a complete local bundle.") from None
    return path


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate key")
        result[key] = value
    return result


def json_object(data: bytes) -> dict[str, Any]:
    try:
        value = json.loads(data, object_pairs_hook=_pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (ValueError, UnicodeError, RecursionError):
        raise invalid("A local JSON resource is invalid or contains duplicate keys.") from None


@dataclass(frozen=True)
class ResourceFile:
    path: str
    bytes: int
    sha256: str


@dataclass(frozen=True)
class SDXLManifest:
    checkpoint: Path
    checkpoint_bytes: int
    checkpoint_sha256: str
    config_directory: Path
    resources: tuple[ResourceFile, ...]
    schema: int = 1


@dataclass(frozen=True)
class TensorSpec:
    dtype: str
    shape: tuple[int, ...]


@dataclass(frozen=True)
class ValidatedSDXL:
    manifest: SDXLManifest
    tensors: dict[str, TensorSpec]
    configs: dict[str, dict[str, Any]]


def read_manifest(path: Path) -> SDXLManifest:
    path = strict_local(path)
    if path.stat().st_size > 128 * 1024:
        raise invalid("The SDXL manifest exceeds the supported size.")
    data = json_object(path.read_bytes())
    try:
        if set(data) != {"schema", "architecture", "checkpoint", "config_directory", "resources"}:
            raise ValueError()
        if type(data["schema"]) is not int or data["schema"] != 1 or data["architecture"] != "sdxl-base":
            raise ValueError()
        check = data["checkpoint"]
        if set(check) != {"path", "bytes", "sha256"} or not isinstance(check["path"], str):
            raise ValueError()
        if not isinstance(data["config_directory"], str) or not isinstance(data["resources"], list):
            raise ValueError()
        resources = []
        for item in data["resources"]:
            if set(item) != {"path", "bytes", "sha256"} or not isinstance(item["path"], str):
                raise ValueError()
            resources.append(ResourceFile(item["path"], item["bytes"], item["sha256"]))
        result = SDXLManifest(Path(check["path"]), check["bytes"], check["sha256"],
                              Path(data["config_directory"]), tuple(resources))
        _validate_manifest_fields(result)
        return result
    except (KeyError, TypeError, ValueError):
        raise invalid("Use a schema-1 SDXL-base manifest with explicit local paths, sizes and SHA256 values.") from None


def _validate_manifest_fields(manifest: SDXLManifest) -> None:
    if manifest.schema != 1 or len(manifest.resources) != len(CONFIG_FILES) or {
        r.path for r in manifest.resources
    } != set(CONFIG_FILES):
        raise invalid("The manifest must list exactly the 14 required SDXL configuration/tokenizer resources.")
    for size, digest in ((manifest.checkpoint_bytes, manifest.checkpoint_sha256),
                         *((r.bytes, r.sha256) for r in manifest.resources)):
        if type(size) is not int or size <= 0 or not isinstance(digest, str) or not _HEX.fullmatch(digest):
            raise invalid("Every resource needs a positive byte size and lowercase SHA256 digest.")


def checkpoint_header(path: Path) -> dict[str, TensorSpec]:
    """Parse bounded safetensors metadata; validate full coverage, not tensor values."""
    if path.suffix.lower() != ".safetensors":
        raise invalid("The initial SDXL adapter accepts safetensors checkpoints only.")
    try:
        size = path.stat().st_size
        with path.open("rb") as source:
            raw = source.read(8)
            if len(raw) != 8:
                raise ValueError()
            length = struct.unpack("<Q", raw)[0]
            if not 2 <= length <= 16 * 1024 * 1024 or length + 8 >= size:
                raise ValueError()
            header = json_object(source.read(length))
        tensors: dict[str, TensorSpec] = {}
        offsets: list[tuple[int, int]] = []
        for key, tensor in header.items():
            if key == "__metadata__":
                if not isinstance(tensor, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in tensor.items()):
                    raise ValueError()
                continue
            if not isinstance(tensor, dict) or set(tensor) != {"dtype", "shape", "data_offsets"}:
                raise ValueError()
            shape, bounds, dtype = tensor["shape"], tensor["data_offsets"], tensor["dtype"]
            if not isinstance(shape, list) or len(shape) > 8 or not all(type(n) is int and 0 < n <= 1_000_000 for n in shape):
                raise ValueError()
            if dtype not in _SIZES or not isinstance(bounds, list) or len(bounds) != 2 or not all(type(n) is int for n in bounds):
                raise ValueError()
            start, end = bounds
            if start < 0 or end - start != math.prod(shape) * _SIZES[dtype]:
                raise ValueError()
            tensors[key] = TensorSpec(dtype, tuple(shape))
            offsets.append((start, end))
        end = 0
        for start, next_end in sorted(offsets):
            if start != end:
                raise ValueError()
            end = next_end
        if not tensors or len(tensors) > 5000 or end != size - 8 - length:
            raise ValueError()
        markers = {
            "model.diffusion_model.input_blocks.0.0.weight": (320, 4, 3, 3),
            "model.diffusion_model.label_emb.0.0.weight": (1280, 2816),
            "conditioner.embedders.0.transformer.text_model.embeddings.token_embedding.weight": (49408, 768),
            "conditioner.embedders.1.model.token_embedding.weight": (49408, 1280),
            "first_stage_model.encoder.conv_in.weight": (128, 3, 3, 3),
        }
        if any(key not in tensors or tensors[key].shape != shape or tensors[key].dtype not in {"F16", "BF16", "F32"}
               for key, shape in markers.items()):
            raise invalid("Select a complete SDXL-base LDM checkpoint containing UNet, VAE and both text encoders.")
        return tensors
    except (OSError, KeyError, TypeError, ValueError, OverflowError):
        raise invalid("The safetensors header or payload layout is corrupt or unsupported.") from None


def _check_configs(configs: dict[str, dict[str, Any]]) -> None:
    def require(condition: bool, field: str) -> None:
        if not condition:
            raise invalid(f"Incompatible local SDXL configuration: {field}.")
    def reject_custom(value: Any) -> None:
        if isinstance(value, dict):
            require(not {"auto_map", "custom_pipeline", "trust_remote_code"}.intersection(value), "custom/remote code")
            for child in value.values():
                reject_custom(child)
        elif isinstance(value, list):
            for child in value:
                reject_custom(child)
    reject_custom(configs)
    index = configs["model_index.json"]
    require(index.get("_class_name") == "StableDiffusionXLPipeline", "model_index.json")
    for name, library, cls in (("unet", "diffusers", "UNet2DConditionModel"),
                               ("vae", "diffusers", "AutoencoderKL"),
                               ("scheduler", "diffusers", "EulerDiscreteScheduler"),
                               ("text_encoder", "transformers", "CLIPTextModel"),
                               ("text_encoder_2", "transformers", "CLIPTextModelWithProjection"),
                               ("tokenizer", "transformers", "CLIPTokenizer"),
                               ("tokenizer_2", "transformers", "CLIPTokenizer")):
        require(index.get(name) == [library, cls], f"model_index.json/{name}")
    require(not any(not k.startswith("_") and k not in {"unet", "vae", "scheduler", "text_encoder", "text_encoder_2", "tokenizer", "tokenizer_2", "force_zeros_for_empty_prompt", "add_watermarker"} for k in index), "pipeline components")
    unet = configs["unet/config.json"]
    require(all(unet.get(k) == v for k, v in {"in_channels": 4, "out_channels": 4,
            "cross_attention_dim": 2048, "addition_embed_type": "text_time",
            "projection_class_embeddings_input_dim": 2816, "block_out_channels": [320, 640, 1280]}.items()), "unet/config.json")
    vae = configs["vae/config.json"]
    require(vae.get("latent_channels") == 4 and vae.get("scaling_factor") == 0.13025
            and vae.get("force_upcast") is True, "vae/config.json (preserve VAE upcasting)")
    scheduler = configs["scheduler/scheduler_config.json"]
    require(scheduler.get("_class_name") == "EulerDiscreteScheduler"
            and scheduler.get("prediction_type") == "epsilon", "scheduler/scheduler_config.json")
    for name, hidden, layers in (("text_encoder", 768, 12), ("text_encoder_2", 1280, 32)):
        cfg = configs[f"{name}/config.json"]
        require(cfg.get("hidden_size") == hidden and cfg.get("num_hidden_layers") == layers
                and cfg.get("vocab_size") == 49408 and cfg.get("max_position_embeddings") == 77, f"{name}/config.json")
    for name in ("tokenizer", "tokenizer_2"):
        vocab = configs[f"{name}/vocab.json"]
        require(len(vocab) == 49408 and all(type(n) is int for n in vocab.values())
                and set(vocab.values()) == set(range(49408)), f"{name}/vocab.json")
        cfg = configs[f"{name}/tokenizer_config.json"]
        require(cfg.get("tokenizer_class", "CLIPTokenizer") == "CLIPTokenizer"
                and cfg.get("model_max_length") == 77, f"{name}/tokenizer_config.json")
        special = configs[f"{name}/special_tokens_map.json"]
        for key in ("bos_token", "eos_token", "unk_token"):
            token = special.get(key)
            if isinstance(token, dict):
                token = token.get("content")
            require(isinstance(token, str) and token in vocab, f"{name}/special_tokens_map.json")


def validate_sdxl(manifest: SDXLManifest, context: InferenceContext) -> ValidatedSDXL:
    try:
        return _validate_sdxl(manifest, context)
    except (OSError, ValueError, TypeError, KeyError, UnicodeError):
        raise invalid("A local SDXL resource is unreadable, malformed or incompatible. Restore the reviewed bundle.") from None


def _validate_sdxl(manifest: SDXLManifest, context: InferenceContext) -> ValidatedSDXL:
    _validate_manifest_fields(manifest)
    context.check_cancelled()
    checkpoint = strict_local(manifest.checkpoint)
    root = strict_local(manifest.config_directory, directory=True)
    files = [("checkpoint", checkpoint, manifest.checkpoint_bytes, manifest.checkpoint_sha256)]
    for resource in manifest.resources:
        path = root / resource.path
        try:
            strict_local(path)
        except InferenceError:
            raise invalid(f"Missing or nonlocal SDXL resource: {resource.path}. Select a complete local bundle.") from None
        files.append((resource.path, path, resource.bytes, resource.sha256))
    total = sum(size for _, _, size, _ in files)
    done, last = 0, -1
    configs: dict[str, dict[str, Any]] = {}
    for label, path, size, digest in files:
        if path.stat().st_size != size or label != "checkpoint" and size > _MAX_JSON:
            raise invalid(f"Size mismatch or unsupported resource size: {label}.")
        actual = hashlib.sha256()
        with path.open("rb") as source:
            while block := source.read(4 * 1024 * 1024):
                context.check_cancelled()
                actual.update(block)
                done += len(block)
                percent = done * 100 // total
                if percent != last:
                    context.report_event(ProgressEvent(ProgressStage.VALIDATING, percent, "Verifying local resource integrity"))
                    last = percent
        if actual.hexdigest() != digest:
            raise invalid(f"SHA256 mismatch: {label}. Restore the reviewed local resource.")
        if label.endswith(".json"):
            configs[label] = json_object(path.read_bytes())
        elif label.endswith("merges.txt"):
            text = path.read_text(encoding="utf-8")
            if not text.startswith("#version: 0.2") or len(text.splitlines()) != 48895:
                raise invalid(f"Invalid CLIP BPE merge resource: {label}.")
            pairs = [line.split() for line in text.splitlines()[1:]]
            if any(len(pair) != 2 for pair in pairs) or len({tuple(pair) for pair in pairs}) != 48894:
                raise invalid(f"Invalid or duplicate CLIP BPE merge pairs: {label}.")
    _check_configs(configs)
    return ValidatedSDXL(manifest, checkpoint_header(checkpoint), configs)
