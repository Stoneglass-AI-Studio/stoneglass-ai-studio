# SPDX-License-Identifier: GPL-3.0-or-later

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from threading import Event, Thread

from inference_support import Context, make_rig
from stoneglass.domain.settings import GenerationSettings
from stoneglass.inference.contracts import (
    GenerationRequest, GenerationResult, InferenceState, ModelSpec, ModelVariant,
    ProgressStage, RuntimeRequest, TaskCancelled,
)
from stoneglass.inference.errors import ErrorCode, InferenceError
from stoneglass.services.inference import InferenceService


class InferenceServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.rig = make_rig(self.root)
        self.service = self.rig.service
        self.request = GenerationRequest("PRIVATE_POSITIVE", "PRIVATE_NEGATIVE", GenerationSettings())
        # Only a contract value; no image file is produced by any test.
        self.result = GenerationResult(self.root / "not-created.png", 17, 1024, 1024, "test-model")
        self.rig.backend.generate.return_value = self.result

    def load(self) -> None:
        self.service.load_model(self.rig.model, RuntimeRequest(), self.rig.context)

    def assert_error(self, code: ErrorCode, operation) -> InferenceError:
        with self.assertRaises(InferenceError) as caught:
            operation()
        self.assertEqual(caught.exception.info.code, code)
        return caught.exception

    def test_default_registry_cannot_load_or_generate(self) -> None:
        service = InferenceService(detector=self.rig.detector)
        self.assert_error(ErrorCode.BACKEND_UNAVAILABLE, lambda: service.load_model(
            self.rig.model, RuntimeRequest(), self.rig.context,
        ))
        self.rig.detector.detect.assert_not_called()
        self.assert_error(ErrorCode.NOT_READY, lambda: service.generate(self.request, self.rig.context))
        self.assertEqual(list(self.root.iterdir()), [])

    def test_load_and_same_model_reuse_and_generation_contract(self) -> None:
        self.load()
        status = self.service.status
        self.assertEqual(status.state, InferenceState.READY)
        self.assertTrue(status.can_generate)
        self.rig.backend.load_model.assert_called_once_with(
            replace(self.rig.model, path=self.root.resolve()), status.runtime, self.rig.context,
        )
        self.load()
        self.rig.provider.create.assert_called_once()
        self.assertIs(self.service.generate(self.request, self.rig.context), self.result)
        self.rig.backend.generate.assert_called_once_with(self.request, self.rig.context)
        self.assertEqual(self.service.status, status)
        self.assertEqual(list(self.root.iterdir()), [])
        self.assertNotIn("PRIVATE", repr(self.request))
        self.assertIn(ProgressStage.GENERATING, [e.stage for e in self.rig.context.events])

    def test_lcm_adapters_and_future_family_are_explicit_local_specs(self) -> None:
        adapter = self.root / "local-adapter"
        adapter.mkdir()
        model = replace(self.rig.model, architecture="future-family", variant=ModelVariant.LCM, adapters=(adapter,))
        status = self.service.load_model(model, RuntimeRequest(), self.rig.context)
        self.assertEqual(status.model.variant, ModelVariant.LCM)
        self.assertEqual(status.model.adapters, (adapter.resolve(),))

    def test_missing_or_network_model_and_unsupported_variant_do_not_replace_ready_model(self) -> None:
        self.load()
        original = self.service.status
        for path in (self.root / "missing", Path("//server/private/model")):
            self.assert_error(ErrorCode.INVALID_MODEL, lambda: self.service.load_model(
                replace(self.rig.model, path=path), RuntimeRequest(), self.rig.context,
            ))
        self.assert_error(ErrorCode.BACKEND_UNAVAILABLE, lambda: self.service.load_model(
            replace(self.rig.model, architecture="unsupported"), RuntimeRequest(), self.rig.context,
        ))
        self.assertEqual(self.service.status, original)
        self.rig.backend.unload.assert_not_called()

    def test_replacement_unloads_before_next_load(self) -> None:
        self.load()
        calls: list[str] = []
        self.rig.backend.unload.side_effect = lambda: calls.append("unload")
        self.rig.backend.load_model.side_effect = lambda *args: calls.append("load")
        self.service.load_model(replace(self.rig.model, model_id="replacement"), RuntimeRequest(), self.rig.context)
        self.assertEqual(calls, ["unload", "load"])
        self.assertEqual(self.service.status.model.model_id, "replacement")

    def test_load_error_cleans_partial_resources_and_redacts_adapter_error(self) -> None:
        self.rig.backend.load_model.side_effect = RuntimeError("PRIVATE_POSITIVE")
        with self.assertLogs("stoneglass.services.inference", level="ERROR") as logs:
            error = self.assert_error(ErrorCode.LOAD_FAILED, self.load)
        self.assertNotIn("PRIVATE", str(error))
        self.assertNotIn("PRIVATE", "\n".join(logs.output))
        self.assertTrue(error.__suppress_context__)
        self.rig.backend.unload.assert_called_once()
        self.assertEqual(self.service.status.state, InferenceState.EMPTY)
        self.assertEqual(self.service.status.error.code, ErrorCode.LOAD_FAILED)

    def test_cleanup_failure_retains_ownership_and_can_be_retried(self) -> None:
        self.load()
        self.rig.backend.unload.side_effect = RuntimeError("private diagnostic")
        with self.assertLogs("stoneglass.services.inference", level="ERROR"):
            self.assert_error(ErrorCode.CLEANUP_FAILED, lambda: self.service.unload(self.rig.context))
        self.assertTrue(self.service.requires_cleanup)
        self.assertFalse(self.service.status.can_generate)
        self.assertEqual(self.service.status.state, InferenceState.FAILED)
        self.assert_error(ErrorCode.CLEANUP_FAILED, self.load)
        self.rig.backend.unload.side_effect = None
        self.service.unload(self.rig.context)
        self.assertFalse(self.service.requires_cleanup)
        self.load()

    def test_cancelled_load_releases_partial_pipeline(self) -> None:
        self.rig.backend.load_model.side_effect = lambda *args: self.rig.context.cancel.set()
        with self.assertRaises(TaskCancelled):
            self.load()
        self.rig.backend.unload.assert_called_once()
        self.assertEqual(self.service.status.state, InferenceState.EMPTY)

    def test_cancelled_before_load_does_not_create_backend(self) -> None:
        self.rig.context.cancel.set()
        with self.assertRaises(TaskCancelled):
            self.load()
        self.rig.provider.create.assert_not_called()

    def test_cancelled_generation_unloads_even_with_cancelled_context(self) -> None:
        self.load()
        def cancel(*args):
            self.rig.context.cancel.set()
            return self.result
        self.rig.backend.generate.side_effect = cancel
        with self.assertRaises(TaskCancelled):
            self.service.generate(self.request, self.rig.context)
        self.rig.backend.unload.assert_called_once()
        self.assertEqual(self.service.status.state, InferenceState.EMPTY)

    def test_generation_failure_unloads_and_keeps_prompt_out_of_logs(self) -> None:
        self.load()
        self.rig.backend.generate.side_effect = RuntimeError("PRIVATE_POSITIVE PRIVATE_NEGATIVE")
        with self.assertLogs("stoneglass.services.inference", level="ERROR") as logs:
            self.assert_error(ErrorCode.GENERATION_FAILED, lambda: self.service.generate(self.request, self.rig.context))
        self.assertNotIn("PRIVATE", "\n".join(logs.output))
        self.assertFalse(self.service.requires_cleanup)

    def test_validation_rejects_invalid_settings_without_clamping_or_dropping_model(self) -> None:
        self.load()
        for settings in (
            GenerationSettings(width=257), GenerationSettings(height=4096),
            GenerationSettings(width=1024.0), GenerationSettings(steps=True),
            GenerationSettings(guidance=float("nan")), GenerationSettings(seed=-2),
        ):
            with self.subTest(settings=settings):
                self.assert_error(ErrorCode.INVALID_REQUEST, lambda: self.service.generate(
                    replace(self.request, settings=settings), self.rig.context,
                ))
        self.assert_error(ErrorCode.INVALID_REQUEST, lambda: self.service.generate(
            replace(self.request, model_id="another-model"), self.rig.context,
        ))
        self.rig.backend.generate.assert_not_called()
        self.assertTrue(self.service.status.can_generate)

    def test_backend_result_contract_failure_cleans_resources(self) -> None:
        self.load()
        self.rig.backend.generate.return_value = replace(self.result, width=512)
        with self.assertLogs("stoneglass.services.inference", level="ERROR"):
            self.assert_error(ErrorCode.GENERATION_FAILED, lambda: self.service.generate(self.request, self.rig.context))
        self.rig.backend.unload.assert_called_once()

    def test_load_only_backend_does_not_claim_generation(self) -> None:
        self.rig.provider.capabilities = replace(self.rig.provider.capabilities, generation_available=False)
        self.load()
        self.assert_error(ErrorCode.BACKEND_UNAVAILABLE, lambda: self.service.generate(self.request, self.rig.context))
        self.rig.backend.generate.assert_not_called()

    def test_close_ignores_cancellation_is_idempotent_and_prevents_new_work(self) -> None:
        self.load()
        self.rig.context.cancel.set()
        self.service.close(self.rig.context)
        self.service.close(self.rig.context)
        self.service.unload(self.rig.context)
        self.rig.backend.unload.assert_called_once()
        self.assertEqual(self.service.status.state, InferenceState.CLOSED)
        self.assert_error(ErrorCode.CLOSED, self.load)

    def test_overlapping_operations_fail_fast_while_status_remains_readable(self) -> None:
        entered, release = Event(), Event()
        errors: list[Exception] = []
        def block(*args):
            entered.set()
            if not release.wait(3):
                raise RuntimeError("Test barrier timed out.")
        self.rig.backend.load_model.side_effect = block
        def load():
            try:
                self.load()
            except Exception as exc:
                errors.append(exc)
        thread = Thread(target=load)
        thread.start()
        try:
            self.assertTrue(entered.wait(2))
            self.assertEqual(self.service.status.state, InferenceState.LOADING)
            self.assert_error(ErrorCode.BUSY, lambda: self.service.unload(Context()))
        finally:
            release.set()
            thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
