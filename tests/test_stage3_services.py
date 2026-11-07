# SPDX-License-Identifier: GPL-3.0-or-later
"""Publication-safe fixtures for profile gating, bounded output and export integrity."""
import hashlib
import struct
import sys
import tempfile
import unittest
import zlib
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

from inference_support import Context, make_rig
from stoneglass.domain.settings import GenerationSettings
from stoneglass.inference.contracts import GenerationRequest, GenerationResult, ModelSpec, RuntimeKind
from stoneglass.inference.errors import InferenceError
from stoneglass.inference.process_backend import ProcessRuntimeDetector
from stoneglass.inference.resources import ResourceFile, SDXLManifest
from stoneglass.inference.reviewed_profile import CHECKPOINT_SHA256, RESOURCE_HASHES, require_reviewed_profile
from stoneglass.inference.worker import WorkerSettings
from stoneglass.services.generation import generate_once
from stoneglass.services.images import export_png, validate_png


def fixture_png(path: Path, pixel: bytes = b'\x10\x30\x50') -> None:
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    header = struct.pack('>IIBBBBB', 512, 512, 8, 2, 0, 0, 0)
    scanlines = (b'\x00' + pixel * 512) * 512
    path.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', header) + chunk(b'IDAT', zlib.compress(scanlines)) + chunk(b'IEND', b''))


class Stage3ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.png = self.root / 'fixture.png'; fixture_png(self.png)

    def tearDown(self): self.temp.cleanup()

    def test_png_integrity_dimensions_crc_and_truncation(self):
        info = validate_png(self.png, 512, 512)
        self.assertEqual(info.sha256, hashlib.sha256(self.png.read_bytes()).hexdigest())
        with self.assertRaises(InferenceError): validate_png(self.png, 768, 512)
        data = bytearray(self.png.read_bytes()); data[-5] ^= 1; self.png.write_bytes(data)
        with self.assertRaises(InferenceError): validate_png(self.png, 512, 512)
        self.png.write_bytes(data[:40])
        with self.assertRaises(InferenceError): validate_png(self.png, 512, 512)
        with self.assertRaises(InferenceError): validate_png(self.root / 'missing.png', 512, 512)

    def test_export_is_lossless_and_existing_file_requires_explicit_overwrite(self):
        info = validate_png(self.png, 512, 512); target = self.root / 'export.png'
        export_png(info, target)
        self.assertEqual(self.png.read_bytes(), target.read_bytes())
        target.write_bytes(b'preserve me')
        with self.assertRaises(FileExistsError): export_png(info, target)
        self.assertEqual(target.read_bytes(), b'preserve me')
        export_png(info, target, overwrite=True)
        self.assertEqual(validate_png(target, 512, 512).sha256, info.sha256)
        self.assertEqual(list(self.root.glob('*.tmp')), [])

    def test_changed_source_and_nonlocal_export_are_rejected(self):
        info = validate_png(self.png, 512, 512)
        fixture_png(self.png, b'\x70\x50\x30')
        with self.assertRaises(InferenceError): export_png(info, self.root / 'export.png')
        info = validate_png(self.png, 512, 512)
        with self.assertRaises(InferenceError): export_png(info, Path('//server/private/image.png'))
        self.assertFalse((self.root / 'export.png').exists())

    def test_exact_profile_rejects_unknown_checkpoint_and_config_without_library_imports(self):
        model = ModelSpec('unit', self.root/'unit.safetensors', resource_manifest=self.root/'manifest.json')
        resources = tuple(ResourceFile(name, 1, digest) for name, digest in RESOURCE_HASHES.items())
        manifest = SDXLManifest(model.path, 1, CHECKPOINT_SHA256, self.root, resources)
        with patch('stoneglass.inference.reviewed_profile.read_manifest', return_value=manifest):
            require_reviewed_profile(model)
        for changed in (replace(manifest, checkpoint_sha256='0'*64), replace(manifest, resources=resources[:-1])):
            with patch('stoneglass.inference.reviewed_profile.read_manifest', return_value=changed):
                with self.assertRaises(InferenceError): require_reviewed_profile(model)
        with self.assertRaises(InferenceError): require_reviewed_profile(replace(model, resource_manifest=None))

    def test_reviewed_runtime_filters_devices_and_closes_probe_on_error(self):
        settings = WorkerSettings(Path(sys.executable), self.root/'data', self.root/'output')
        device = {'kind':'rocm', 'index':0, 'name':'AMD Radeon RX 9060 XT', 'gcn_arch':'gfx1200'}
        report = {'torch_version':'2.13.0+rocm10.0.0','hip_version':'test','cuda_version':None,'devices':[device]}
        for changed in (dict(report, devices=[]), dict(report, torch_version='other'),
                        dict(report, devices=[dict(device, gcn_arch='gfx1100')]),
                        dict(report, devices=[dict(device, kind='cuda')])):
            client = Mock(); client.call.return_value = changed
            detector = ProcessRuntimeDetector(settings, reviewed_profile=True)
            with patch('stoneglass.inference.process_backend.WorkerClient', return_value=client):
                with self.assertRaises(InferenceError): detector.detect(Context())
            client.close.assert_called_once(); self.assertFalse(detector.requires_cleanup)

    def test_runtime_cleanup_failure_retains_owned_client_for_retry(self):
        settings = WorkerSettings(Path(sys.executable), self.root/'data', self.root/'output')
        client = Mock(); client.call.side_effect = RuntimeError('probe failure')
        client.close.side_effect = RuntimeError('cleanup failure')
        detector = ProcessRuntimeDetector(settings)
        with patch('stoneglass.inference.process_backend.WorkerClient', return_value=client):
            with self.assertRaises(RuntimeError): detector.detect(Context())
        self.assertTrue(detector.requires_cleanup)
        client.close.side_effect = None; detector.close()
        self.assertFalse(detector.requires_cleanup)

    def test_readiness_never_loads_weights_and_transaction_closes_before_return(self):
        model_path = self.root/'unit.safetensors'; model_path.write_text('fixture metadata only')
        rig = make_rig(model_path)
        ready = rig.service.validate_selection(rig.model, rig.context)
        rig.backend.load_model.assert_not_called()
        rig.backend.generate.return_value = GenerationResult(self.png, 12345, 512, 512, rig.model.model_id)
        result = generate_once(rig.service, ready, GenerationRequest('unit', '', GenerationSettings(512, 512), model_id=rig.model.model_id), rig.context)
        self.assertEqual(result.image.width, 512)
        rig.backend.unload.assert_called_once()
        self.assertFalse(rig.service.requires_cleanup)

    def test_failed_output_is_preserved_but_backend_always_unloaded(self):
        model_path = self.root/'unit.safetensors'; model_path.write_text('fixture metadata only')
        rig = make_rig(model_path); ready = rig.service.validate_selection(rig.model, rig.context)
        self.png.write_bytes(b'incomplete')
        rig.backend.generate.return_value = GenerationResult(self.png, 12345, 512, 512, rig.model.model_id)
        with self.assertRaises(InferenceError):
            generate_once(rig.service, ready, GenerationRequest('unit', '', GenerationSettings(512, 512), model_id=rig.model.model_id), rig.context)
        rig.backend.unload.assert_called_once(); self.assertTrue(self.png.exists())
