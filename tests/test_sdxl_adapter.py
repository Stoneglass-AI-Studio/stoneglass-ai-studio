# SPDX-License-Identifier: GPL-3.0-or-later

import contextlib
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from inference_support import Context
from sdxl_support import make_bundle, write_manifest
from stoneglass.inference.contracts import GenerationRequest, ModelSpec, RuntimeDevice, RuntimeKind, TaskCancelled
from stoneglass.inference.errors import ErrorCode, InferenceError
from stoneglass.inference.offline import OFFLINE_FLAGS
from stoneglass.inference.resources import TensorSpec, ValidatedSDXL
from stoneglass.inference.sdxl import SDXLAdapter, _dependencies, validate_component_shapes


class SDXLAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.manifest = make_bundle(cls.root)
        cls.path = cls.root / "manifest.json"
        write_manifest(cls.path, cls.manifest)

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def setUp(self):
        self.adapter = SDXLAdapter(self.root)
        self.model = ModelSpec("test", self.manifest.checkpoint, resource_manifest=self.path)
        self.runtime = RuntimeDevice(RuntimeKind.ROCM, 0, "AMD Radeon RX 9060 XT")
        self.context = Context()
        self.deps = Mock()
        self.deps.torch.cuda.device.side_effect = lambda _: contextlib.nullcontext()
        self.deps.torch.cuda.is_available.return_value = True
        self.deps.torch.version.hip, self.deps.torch.version.cuda = "test-hip", None
        self.deps.torch.cuda.get_device_properties.return_value = SimpleNamespace(name=self.runtime.name, gcnArchName="gfx1200")
        self.pipeline = self.deps.diffusers.StableDiffusionXLPipeline.from_single_file.return_value

    def test_missing_offline_policy_cannot_import_dependencies_or_load(self):
        with patch.dict(os.environ, {}, clear=True), patch("stoneglass.inference.sdxl._dependencies") as dependencies:
            with self.assertRaises(InferenceError) as caught:
                self.adapter.load_model(self.model, self.runtime, self.context)
            self.assertEqual(caught.exception.info.code, ErrorCode.OFFLINE_POLICY)
            dependencies.assert_not_called()
        with patch.dict(os.environ, {}, clear=True), patch("stoneglass.inference.sdxl.importlib.import_module") as importer:
            with self.assertRaises(InferenceError): _dependencies()
            importer.assert_not_called()

    def load_mocked(self, **changes):
        with patch.dict(os.environ, OFFLINE_FLAGS), \
             patch("stoneglass.inference.sdxl.validate_sdxl", return_value=Mock()) as validate, \
             patch("stoneglass.inference.sdxl.validate_component_shapes") as shapes, \
             patch("stoneglass.inference.sdxl._dependencies", return_value=self.deps):
            self.adapter.load_model(changes.get("model", self.model), changes.get("runtime", self.runtime), self.context)
            return validate, shapes

    def test_explicit_local_config_fp16_eager_attention_and_vae_policy(self):
        self.load_mocked()
        kwargs = self.deps.diffusers.StableDiffusionXLPipeline.from_single_file.call_args.kwargs
        self.assertEqual(kwargs["config"], str(self.manifest.config_directory))
        self.assertIs(kwargs["local_files_only"], True)
        self.assertIs(kwargs["token"], False)
        self.assertIs(kwargs["use_safetensors"], True)
        self.assertEqual(kwargs["dtype"], self.deps.torch.float16)
        self.pipeline.unet.set_attn_processor.assert_called_once()
        self.pipeline.vae.set_attn_processor.assert_called_once()
        self.pipeline.text_encoder.set_attn_implementation.assert_called_once_with("eager")
        self.pipeline.to.assert_called_once_with("cuda:0")
        self.pipeline.vae.to.assert_not_called()  # no forced FP16 VAE override

    def test_invalid_resources_never_call_pipeline_loader(self):
        with patch.dict(os.environ, OFFLINE_FLAGS):
            with self.assertRaises(InferenceError):
                self.adapter.load_model(replace(self.model, resource_manifest=None), self.runtime, self.context)
        self.deps.diffusers.StableDiffusionXLPipeline.from_single_file.assert_not_called()

    def test_runtime_mismatch_fails_before_pipeline_creation(self):
        self.deps.torch.version.hip = None
        with self.assertRaises(InferenceError): self.load_mocked()
        self.deps.diffusers.StableDiffusionXLPipeline.from_single_file.assert_not_called()

    def test_cancelled_loading_does_not_reach_pipeline_loader(self):
        self.context.cancel.set()
        with self.assertRaises(TaskCancelled): self.load_mocked()
        self.deps.diffusers.StableDiffusionXLPipeline.from_single_file.assert_not_called()

    def test_unload_releases_partial_pipeline_and_owned_pending_file_only(self):
        self.adapter._deps = self.deps
        self.adapter._device = self.runtime
        self.adapter._pipeline = self.pipeline
        pending = self.root / "unit-test-owned.tmp"
        pending.write_text("unit-test output cleanup fixture")
        self.adapter._pending_output = pending
        self.adapter.unload()
        self.adapter.unload()
        self.assertIsNone(self.adapter._pipeline)
        self.assertFalse(pending.exists())
        self.assertTrue(self.manifest.checkpoint.exists())

    def test_meta_preflight_checks_all_four_components_and_rejects_missing_parameters(self):
        bundle = ValidatedSDXL(self.manifest, {"unit": TensorSpec("F16", (2, 2))},
                               {f"{name}/config.json": {} for name in ("unet", "vae", "text_encoder", "text_encoder_2")})
        deps = Mock()
        deps.accelerate.init_empty_weights.side_effect = contextlib.nullcontext
        tensor = SimpleNamespace(shape=(2, 2), is_floating_point=lambda: True, is_meta=True)
        models = [deps.diffusers.UNet2DConditionModel.from_config.return_value,
                  deps.diffusers.AutoencoderKL.from_config.return_value,
                  deps.transformers.CLIPTextModel.return_value,
                  deps.transformers.CLIPTextModelWithProjection.return_value]
        for model in models: model.state_dict.return_value = {"weight": tensor}
        converters = [deps.conversion.convert_ldm_unet_checkpoint, deps.conversion.convert_ldm_vae_checkpoint,
                      deps.conversion.convert_ldm_clip_checkpoint, deps.conversion.convert_open_clip_checkpoint]
        for convert in converters: convert.side_effect = lambda *args, **kwargs: {"weight": tensor}
        validate_component_shapes(bundle, deps)
        self.assertTrue(all(convert.called for convert in converters))
        converters[0].side_effect = lambda *args, **kwargs: {}
        with self.assertRaisesRegex(InferenceError, "parameter names/shapes"):
            validate_component_shapes(bundle, deps)

    def test_meta_validation_matches_pinned_clip_prefix_normalization(self):
        bundle = ValidatedSDXL(self.manifest, {"unit": TensorSpec("F16", (2, 2))},
                               {f"{name}/config.json": {} for name in ("unet", "vae", "text_encoder", "text_encoder_2")})
        deps = Mock()
        deps.accelerate.init_empty_weights.side_effect = contextlib.nullcontext
        tensor = SimpleNamespace(shape=(2, 2), is_floating_point=lambda: True, is_meta=True)
        for factory in (deps.diffusers.UNet2DConditionModel.from_config, deps.diffusers.AutoencoderKL.from_config):
            factory.return_value.state_dict.return_value = {"weight": tensor}
        deps.transformers.CLIPTextModel.return_value = SimpleNamespace(state_dict=lambda: {"embeddings.weight": tensor})
        deps.transformers.CLIPTextModelWithProjection.return_value = SimpleNamespace(
            text_model=object(), state_dict=lambda: {"text_model.embeddings.weight": tensor})
        deps.conversion.convert_ldm_unet_checkpoint.return_value = {"weight": tensor}
        deps.conversion.convert_ldm_vae_checkpoint.return_value = {"weight": tensor}
        deps.conversion.convert_ldm_clip_checkpoint.return_value = {"text_model.embeddings.weight": tensor}
        deps.conversion.convert_open_clip_checkpoint.return_value = {"text_model.embeddings.weight": tensor}
        report = validate_component_shapes(bundle, deps)
        self.assertTrue(all(component["matched"] for component in report.values()))
        # Unexpected parameters remain a strict failure after normalization.
        deps.conversion.convert_ldm_clip_checkpoint.return_value["text_model.unexpected"] = tensor
        with self.assertRaises(InferenceError): validate_component_shapes(bundle, deps)

    def test_sampling_callback_cancellation_never_reaches_image_encoding(self):
        self.adapter._pipeline = self.pipeline
        self.adapter._deps = self.deps
        self.adapter._device, self.adapter._model = self.runtime, self.model
        self.deps.torch.inference_mode.side_effect = contextlib.nullcontext
        def sample(**kwargs):
            self.context.cancel.set()
            kwargs["callback_on_step_end"](None, 0, None, {})
        self.pipeline.side_effect = sample
        from stoneglass.domain.settings import GenerationSettings
        request = GenerationRequest("PRIVATE", "", GenerationSettings(width=512, height=512, seed=1))
        with patch.dict(os.environ, OFFLINE_FLAGS), \
             patch("stoneglass.inference.sdxl.tempfile.mkstemp") as encode:
            with self.assertRaises(TaskCancelled): self.adapter.generate(request, self.context)
        encode.assert_not_called()
        self.assertEqual(self.pipeline.call_args.kwargs["num_images_per_prompt"], 1)
