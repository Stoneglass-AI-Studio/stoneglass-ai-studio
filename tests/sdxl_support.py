# SPDX-License-Identifier: GPL-3.0-or-later
"""Synthetic metadata fixtures only. No usable checkpoint, model or image generation."""

import hashlib
import json
import struct
from pathlib import Path

from stoneglass.inference.resources import CONFIG_FILES, ResourceFile, SDXLManifest


def write_header(path: Path, tensors: dict) -> None:
    offset, header = 0, {}
    sizes = {"BOOL": 1, "F16": 2}
    import math
    for key, (shape, dtype) in tensors.items():
        end = offset + math.prod(shape) * sizes[dtype]
        header[key] = {"shape": list(shape), "dtype": dtype, "data_offsets": [offset, end]}
        offset = end
    encoded = json.dumps(header).encode()
    with path.open("wb") as stream:
        stream.write(struct.pack("<Q", len(encoded)))
        stream.write(encoded)
        # Sparse, metadata-only layout test; never passed to an inference loader.
        stream.truncate(8 + len(encoded) + offset)


def make_bundle(root: Path) -> SDXLManifest:
    checkpoint = root / "metadata-fixture.safetensors"
    write_header(checkpoint, {"unit_test_only": ((2, 2), "F16")})
    config = root / "config"
    index = {"_class_name": "StableDiffusionXLPipeline"}
    for name, library, cls in (("unet", "diffusers", "UNet2DConditionModel"), ("vae", "diffusers", "AutoencoderKL"),
                               ("scheduler", "diffusers", "EulerDiscreteScheduler"), ("text_encoder", "transformers", "CLIPTextModel"),
                               ("text_encoder_2", "transformers", "CLIPTextModelWithProjection"),
                               ("tokenizer", "transformers", "CLIPTokenizer"), ("tokenizer_2", "transformers", "CLIPTokenizer")):
        index[name] = [library, cls]
    symbols = [chr(0x100 + i) for i in range(256)]
    pairs = [(symbols[n // 256], symbols[n % 256]) for n in range(48894)]
    tokens = symbols + [a + b for a, b in pairs]
    tokens += [f"unit-token-{i}" for i in range(49408 - len(tokens) - 2)] + ["<|startoftext|>", "<|endoftext|>"]
    vocab = dict(zip(tokens, range(49408)))
    values = {
        "model_index.json": index,
        "unet/config.json": {"in_channels": 4, "out_channels": 4, "cross_attention_dim": 2048,
                             "addition_embed_type": "text_time", "projection_class_embeddings_input_dim": 2816,
                             "block_out_channels": [320, 640, 1280]},
        "vae/config.json": {"latent_channels": 4, "scaling_factor": 0.13025, "force_upcast": True},
        "scheduler/scheduler_config.json": {"_class_name": "EulerDiscreteScheduler", "prediction_type": "epsilon"},
        "text_encoder/config.json": {"hidden_size": 768, "num_hidden_layers": 12, "vocab_size": 49408, "max_position_embeddings": 77},
        "text_encoder_2/config.json": {"hidden_size": 1280, "num_hidden_layers": 32, "vocab_size": 49408, "max_position_embeddings": 77},
    }
    for name in ("tokenizer", "tokenizer_2"):
        values[f"{name}/vocab.json"] = vocab
        values[f"{name}/tokenizer_config.json"] = {"tokenizer_class": "CLIPTokenizer", "model_max_length": 77}
        values[f"{name}/special_tokens_map.json"] = {"bos_token": "<|startoftext|>", "eos_token": "<|endoftext|>", "unk_token": "<|endoftext|>"}
        values[f"{name}/merges.txt"] = "#version: 0.2\n" + "".join(f"{a} {b}\n" for a, b in pairs)
    for name, value in values.items():
        path = config / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False), encoding="utf-8")
    files = tuple(ResourceFile(name, (config / name).stat().st_size, hashlib.sha256((config / name).read_bytes()).hexdigest()) for name in CONFIG_FILES)
    return SDXLManifest(checkpoint, checkpoint.stat().st_size, hashlib.sha256(checkpoint.read_bytes()).hexdigest(), config, files)


def write_manifest(path: Path, manifest: SDXLManifest) -> None:
    from dataclasses import asdict
    path.write_text(json.dumps({"schema": 1, "architecture": "sdxl-base", "config_directory": str(manifest.config_directory),
                               "checkpoint": {"path": str(manifest.checkpoint), "bytes": manifest.checkpoint_bytes, "sha256": manifest.checkpoint_sha256},
                               "resources": [asdict(r) for r in manifest.resources]}), encoding="utf-8")
