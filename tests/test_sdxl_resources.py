# SPDX-License-Identifier: GPL-3.0-or-later

import json
import io
import os
import tempfile
import struct
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from inference_support import Context
from sdxl_support import make_bundle, write_header, write_manifest
from stoneglass.inference.contracts import TaskCancelled
from stoneglass.inference.errors import ErrorCode, InferenceError
from stoneglass.inference.resource_lease import ResourceLease
from stoneglass.inference.resources import (
    CONFIG_FILES, TensorSpec, checkpoint_header, json_object, read_manifest, strict_local, validate_sdxl,
)


class SDXLResourcesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.bundle = make_bundle(cls.root)
        cls.manifest_path = cls.root / "manifest.json"
        write_manifest(cls.manifest_path, cls.bundle)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def validate(self, manifest=None):
        # The tiny fixture intentionally contains no real SDXL weights. Layout
        # parsing is tested independently below; never instantiate an actual model.
        with patch("stoneglass.inference.resources.checkpoint_header", return_value={"test": TensorSpec("F16", (2, 2))}):
            return validate_sdxl(manifest or self.bundle, Context())

    def test_manifest_roundtrip_and_complete_bundle_hashes(self):
        self.assertEqual(read_manifest(self.manifest_path), self.bundle)
        self.assertEqual(len(self.validate().configs), 12)

    def test_missing_manifest_resource_is_actionable(self):
        file = self.bundle.config_directory / "tokenizer_2/merges.txt"
        data = file.read_bytes()
        file.unlink()
        try:
            with self.assertRaisesRegex(InferenceError, "tokenizer_2/merges.txt"):
                self.validate()
        finally:
            file.write_bytes(data)

    def test_checkpoint_and_config_corruption_fail_before_loader(self):
        for manifest in (replace(self.bundle, checkpoint_sha256="0" * 64),
                         replace(self.bundle, resources=(replace(self.bundle.resources[0], sha256="0" * 64), *self.bundle.resources[1:]))):
            with self.subTest(manifest=manifest.checkpoint_sha256):
                with self.assertRaisesRegex(InferenceError, "SHA256 mismatch"):
                    self.validate(manifest)

    def test_size_mismatch_and_non_safetensors_fail(self):
        with self.assertRaisesRegex(InferenceError, "Size mismatch"):
            self.validate(replace(self.bundle, checkpoint_bytes=1))
        with self.assertRaisesRegex(InferenceError, "safetensors"):
            checkpoint_header(self.root / "model.bin")

    def test_manifest_rejects_traversal_duplicates_and_extra_resources(self):
        for resources in (self.bundle.resources[:-1], (*self.bundle.resources[:-1], self.bundle.resources[0]),
                          (replace(self.bundle.resources[0], path="../outside.json"), *self.bundle.resources[1:])):
            with self.subTest(paths=[r.path for r in resources]):
                with self.assertRaises(InferenceError):
                    self.validate(replace(self.bundle, resources=resources))

    def test_paths_reject_relative_urls_unc_and_network_drives_before_access(self):
        for path in (Path("relative.safetensors"), Path("https://example.invalid/model.safetensors"), Path("//server/share/model.safetensors")):
            with self.subTest(path=path), self.assertRaises(InferenceError):
                strict_local(path)
        if os.name == "nt":
            with patch("stoneglass.inference.resources._drive_type", return_value=4), patch.object(Path, "lstat") as stat:
                with self.assertRaises(InferenceError):
                    strict_local(self.bundle.checkpoint)
                stat.assert_not_called()

    def test_cloud_or_reparse_resource_is_rejected(self):
        info = self.bundle.checkpoint.lstat()
        from types import SimpleNamespace
        with patch.object(Path, "lstat", return_value=SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400000)):
            with self.assertRaisesRegex(InferenceError, "cloud placeholders"):
                strict_local(self.bundle.checkpoint)

    def test_duplicate_json_and_unsupported_manifest_schema_fail(self):
        with self.assertRaises(InferenceError):
            json_object(b'{"schema":1,"schema":2}')
        data = self.manifest_path.read_text()
        try:
            self.manifest_path.write_text(data.replace('"schema": 1', '"schema": 2'))
            with self.assertRaises(InferenceError):
                read_manifest(self.manifest_path)
        finally:
            self.manifest_path.write_text(data)

    def test_invalid_component_configuration_and_custom_code_fail(self):
        from stoneglass.inference.resources import _check_configs
        values = self.validate().configs
        for key, change in (("unet/config.json", {"cross_attention_dim": 768}),
                            ("vae/config.json", {"force_upcast": False}),
                            ("scheduler/scheduler_config.json", {"_class_name": "LCMScheduler"}),
                            ("text_encoder/config.json", {"auto_map": {"x": "remote.py"}})):
            with self.subTest(component=key), self.assertRaises(InferenceError):
                _check_configs({**values, key: {**values[key], **change}})

    def test_hash_validation_is_cancellable(self):
        context = Context(); context.cancel.set()
        with self.assertRaises(TaskCancelled):
            validate_sdxl(self.bundle, context)

    def test_truncated_and_incomplete_headers_fail(self):
        path = self.root / "bad.safetensors"
        path.write_bytes(b"bad")
        with self.assertRaises(InferenceError):
            checkpoint_header(path)
        write_header(path, {"unet_only": ((2, 2), "F16")})
        with self.assertRaisesRegex(InferenceError, "both text encoders"):
            checkpoint_header(path)

    def test_sdxl_header_markers_and_contiguous_offsets(self):
        path = self.root / "metadata-only.safetensors"
        markers = {
            "model.diffusion_model.input_blocks.0.0.weight": ((320, 4, 3, 3), "F16"),
            "model.diffusion_model.label_emb.0.0.weight": ((1280, 2816), "F16"),
            "conditioner.embedders.0.transformer.text_model.embeddings.token_embedding.weight": ((49408, 768), "F16"),
            "conditioner.embedders.1.model.token_embedding.weight": ((49408, 1280), "F16"),
            "first_stage_model.encoder.conv_in.weight": ((128, 3, 3, 3), "F16"),
        }
        header, end = {}, 0
        import math
        for name, (shape, dtype) in markers.items():
            start, end = end, end + math.prod(shape) * 2
            header[name] = {"shape": list(shape), "dtype": dtype, "data_offsets": [start, end]}
        raw = json.dumps(header).encode()
        data = struct.pack("<Q", len(raw)) + raw
        from types import SimpleNamespace
        with patch.object(Path, "stat", return_value=SimpleNamespace(st_size=len(data) + end)), \
             patch.object(Path, "open", return_value=io.BytesIO(data)):
            self.assertEqual(len(checkpoint_header(path)), 5)
        with patch.object(Path, "stat", return_value=SimpleNamespace(st_size=len(data) + end + 5)), \
             patch.object(Path, "open", return_value=io.BytesIO(data)):
            with self.assertRaisesRegex(InferenceError, "corrupt"):
                checkpoint_header(path)

    @unittest.skipUnless(os.name == "nt", "Windows file-sharing contract")
    def test_read_lease_prevents_write_and_releases_after_failure(self):
        with self.assertRaisesRegex(RuntimeError, "unit-test"):
            with ResourceLease(self.bundle):
                with self.assertRaises(OSError):
                    self.bundle.checkpoint.open("wb")
                raise RuntimeError("unit-test")
        # Can open for append without changing bytes once lease handles close.
        with self.bundle.checkpoint.open("ab"): pass
