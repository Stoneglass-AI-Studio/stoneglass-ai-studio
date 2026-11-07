# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit tests never provision profiles or grant permissions. Native evidence is separate."""

import ctypes
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from stoneglass.inference.errors import ErrorCode, InferenceError
from stoneglass.inference.windows_appcontainer import (
    DevelopmentProfile, ExtendedJobLimits, NativeProcess, PREFIX,
    SecurityCapabilities, StartupInfo, StartupInfoEx, api, create_development_profile,
    launch_prototype, validate_staged_paths, validate_token,
    network_denial_checks,
)


class AppContainerTests(unittest.TestCase):
    def setUp(self):
        self.profile = DevelopmentProfile(PREFIX + "unit-test", "S-1-15-2-1-2-3-4-5-6-7")
        self.details = {"appcontainer": True, "capability_count": 0,
                        "package_sid": self.profile.sid, "no_child_process_creation": True}

    def test_profile_namespace_and_package_sid_are_restricted(self):
        for name,sid in (("OtherApp",self.profile.sid),(PREFIX+'x'*64,self.profile.sid),(PREFIX+'test',"S-1-5-18")):
            with self.subTest(name=name), self.assertRaises(ValueError): DevelopmentProfile(name,sid)

    def test_invalid_profile_never_calls_windows(self):
        with patch('stoneglass.inference.windows_appcontainer.api') as native:
            with self.assertRaises(ValueError):create_development_profile('unrelated-app')
            native.assert_not_called()

    def test_token_requires_exact_identity_zero_capabilities_and_child_block(self):
        validate_token(self.details,self.profile)
        for changes in ({'appcontainer':False},{'capability_count':1},{'capability_count':False},
                        {'package_sid':'S-1-15-2-9-9-9-9-9-9-9'},{'no_child_process_creation':False}):
            with self.subTest(changes=changes),self.assertRaises(InferenceError):
                validate_token({**self.details,**changes},self.profile)

    @unittest.skipUnless(sys.platform=='win32' and ctypes.sizeof(ctypes.c_void_p)==8,'Windows x64 ABI')
    def test_native_structures_match_windows_x64_abi(self):
        self.assertEqual(ctypes.sizeof(SecurityCapabilities),24)
        self.assertEqual(ctypes.sizeof(StartupInfo),104)
        self.assertEqual(ctypes.sizeof(StartupInfoEx),112)
        self.assertEqual(ctypes.sizeof(ExtendedJobLimits),144)

    def test_only_private_staged_interpreters_and_code_are_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'.local-data/offline-sandbox'/('a'*32)
            (root/'runtime').mkdir(parents=True);(root/'code').mkdir()
            executable=root/'runtime/pythonw.exe';executable.write_text('unit fixture, never executed')
            script=root/'code/test.py';script.write_text('# unit fixture')
            self.assertEqual(validate_staged_paths(root,executable,script),(root,executable,script))
            outside=Path(directory)/'outside.py';outside.write_text('# not staged')
            with self.assertRaises(InferenceError):validate_staged_paths(root,executable,outside)
            with self.assertRaises(InferenceError):validate_staged_paths(root.parent,executable,script)

    def test_scope_failure_occurs_before_native_process_creation(self):
        with tempfile.TemporaryDirectory() as directory,patch('stoneglass.inference.windows_appcontainer.api') as native:
            root=Path(directory)
            with self.assertRaises(InferenceError):launch_prototype(self.profile,root,root/'python.exe',root/'probe.py',(),{})
            native.assert_not_called()

    def process(self,kernel):
        process=NativeProcess(100,200,300,Mock(),Mock(),Mock(),{})
        return process,patch('stoneglass.inference.windows_appcontainer.api',return_value=SimpleNamespace(kernel=kernel))

    def test_owned_job_termination_is_bounded_and_idempotent(self):
        kernel=Mock();kernel.WaitForSingleObject.side_effect=[258,0,0]
        kernel.TerminateJobObject.return_value=True
        def exit_code(handle,pointer):pointer._obj.value=1223;return True
        kernel.GetExitCodeProcess.side_effect=exit_code
        process,scope=self.process(kernel)
        with scope:process.kill_tree_and_wait(5);process.kill_tree_and_wait(5)
        kernel.TerminateJobObject.assert_called_once_with(200,1223)
        self.assertEqual(kernel.CloseHandle.call_count,2)

    def test_failed_termination_retains_process_ownership_for_retry(self):
        kernel=Mock();kernel.WaitForSingleObject.side_effect=[258,258]
        kernel.TerminateJobObject.return_value=True
        process,scope=self.process(kernel)
        with scope,self.assertRaises(InferenceError) as caught:process.kill_tree_and_wait(.1)
        self.assertEqual(caught.exception.info.code,ErrorCode.CLEANUP_FAILED)
        self.assertFalse(process._closed)
        kernel.CloseHandle.assert_not_called()

    def test_missing_windows_support_fails_closed(self):
        with patch('stoneglass.inference.windows_appcontainer.sys.platform','unsupported'):
            with self.assertRaises(InferenceError):api.__wrapped__()

    def test_timeouts_and_quiet_endpoints_never_certify_network_isolation(self):
        results={name:{'ok':False,'error':10060} for name in ('ipv4_tcp','ipv6_tcp','native_winsock','native_winhttp')}
        results['native_dns']={'status':5}
        checks=network_denial_checks(results,{'owned_endpoint':1},{'owned_endpoint':1})
        self.assertFalse(all(checks.values()))
        self.assertFalse(checks['ipv4_tcp'])
        self.assertFalse(checks['native_winhttp'])

    def test_udp_send_acceptance_cannot_be_reclassified_as_access_denial(self):
        results={name:{'ok':False,'error':10013} for name in ('ipv4_tcp','ipv6_tcp','ipv4_udp','ipv6_udp','native_winsock','native_winhttp')}
        results['native_dns']={'status':5}
        results['ipv4_udp']={'ok':True,'error':0}
        checks=network_denial_checks(results,{'udp':0},{'udp':0})
        self.assertFalse(checks['ipv4_udp'])
        self.assertFalse(all(checks.values()))

    def test_explicit_denial_gate_also_requires_unchanged_controlled_receipts(self):
        results={name:{'ok':False,'error':10013} for name in ('ipv4_tcp','ipv6_tcp','ipv4_udp','ipv6_udp','native_winsock','native_winhttp')}
        results['native_dns']={'status':5}
        self.assertTrue(all(network_denial_checks(results,{'endpoint':2},{'endpoint':2}).values()))
        self.assertFalse(all(network_denial_checks(results,{'endpoint':2},{'endpoint':3}).values()))
