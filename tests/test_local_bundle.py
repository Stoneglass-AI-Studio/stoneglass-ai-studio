# SPDX-License-Identifier: GPL-3.0-or-later
"""Local bundle workflow tests with metadata fixtures, not usable model weights."""

import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from inference_support import Context
from sdxl_support import make_bundle
from stoneglass.inference.bundle import prepare_sdxl_bundle
from stoneglass.inference.contracts import TaskCancelled
from stoneglass.inference.errors import ErrorCode, InferenceError
from stoneglass.inference.resources import read_manifest


class LocalBundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="stoneglass-bundle-test-")
        cls.root = Path(cls.temp.name)
        cls.source = make_bundle(cls.root)
        cls.hashes = {r.path: r.sha256 for r in cls.source.resources}

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def prepare(self, destination, **kwargs):
        return prepare_sdxl_bundle(self.source.checkpoint, self.source.config_directory,
                                   destination, kwargs.get("hashes", self.hashes), kwargs.get("context", Context()))

    def test_new_bundle_preserves_bytes_pins_checkpoint_and_calls_full_validator(self):
        target = self.root / "complete"
        with patch("stoneglass.inference.bundle.checkpoint_header"), \
             patch("stoneglass.inference.bundle.validate_sdxl") as validate:
            manifest = read_manifest(self.prepare(target))
        self.assertEqual(manifest.checkpoint, self.source.checkpoint)
        self.assertEqual(manifest.checkpoint_sha256, hashlib.sha256(self.source.checkpoint.read_bytes()).hexdigest())
        self.assertEqual(len(manifest.resources), 14)
        for resource in manifest.resources:
            self.assertEqual((manifest.config_directory / resource.path).read_bytes(),
                             (self.source.config_directory / resource.path).read_bytes())
        self.assertEqual(validate.call_args.args[0], manifest)
        self.assertEqual(list(target.glob("*.safetensors")), [])

    def test_existing_bundle_is_preserved(self):
        target = self.root / "existing"
        target.mkdir()
        sentinel = target / "preserve.txt"; sentinel.write_text("preserve")
        with self.assertRaises(InferenceError): self.prepare(target)
        self.assertEqual(sentinel.read_text(), "preserve")

    def test_unreviewed_or_changed_resources_never_create_destination(self):
        for hashes in ({}, {**self.hashes, "model_index.json": "0" * 64}):
            target = self.root / "unreviewed"
            with patch("stoneglass.inference.bundle.checkpoint_header"), self.assertRaises(InferenceError):
                self.prepare(target, hashes=hashes)
            self.assertFalse(target.exists())

    def test_disk_and_cancellation_fail_before_copying(self):
        target = self.root / "no-space"
        with patch("stoneglass.inference.bundle.shutil.disk_usage", return_value=SimpleNamespace(free=0)), \
             self.assertRaisesRegex(InferenceError, "disk space"):
            self.prepare(target)
        self.assertFalse(target.exists())
        context = Context(); context.cancel.set()
        with self.assertRaises(TaskCancelled): self.prepare(target, context=context)
        self.assertFalse(target.exists())

    def test_validation_failure_never_publishes_readiness_manifest(self):
        target = self.root / "invalid"
        with patch("stoneglass.inference.bundle.checkpoint_header"), \
             patch("stoneglass.inference.bundle.validate_sdxl", side_effect=InferenceError(ErrorCode.INVALID_RESOURCES, "Invalid fixture")), \
             self.assertRaises(InferenceError):
            self.prepare(target)
        self.assertFalse((target / "manifest.json").exists())
