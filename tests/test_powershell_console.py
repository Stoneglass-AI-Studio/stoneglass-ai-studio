# SPDX-License-Identifier: GPL-3.0-or-later
"""Exercise the launcher's real stream helper in installed Windows shells."""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def ps_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


@unittest.skipUnless(sys.platform == "win32", "Windows PowerShell regression")
class PowerShellConsoleTests(unittest.TestCase):
    def check_streams(self, exit_code: int) -> None:
        shells = [path for name in ("powershell.exe", "pwsh.exe") if (path := shutil.which(name))]
        if not shells:
            self.skipTest("No installed PowerShell shell")
        for shell in shells:
            with self.subTest(shell=shell, exit_code=exit_code), tempfile.TemporaryDirectory(prefix="stoneglass-console-unit-") as temporary:
                directory = Path(temporary)
                log = directory / "console.log"
                script = directory / "exercise.ps1"
                child = ("import sys; print('stdout preserved', flush=True); "
                         "sys.stderr.write('INFO hardware inventory completed\\n'); "
                         "sys.stderr.write('ERROR diagnostic text preserved\\n'); "
                         f"sys.stderr.flush(); sys.exit({exit_code})")
                # Parse/extract the actual production function; never execute
                # the launcher's preparation/offline workflow in this test.
                script.write_text("\n".join((
                    "$ErrorActionPreference = 'Stop'",
                    "$tokens = $null; $parseErrors = $null",
                    "$ast = [System.Management.Automation.Language.Parser]::ParseFile(" + ps_literal(str(ROOT / 'scripts/test-offline-ui.ps1')) + ", [ref]$tokens, [ref]$parseErrors)",
                    "if ($parseErrors.Count -ne 0) { throw 'Launcher syntax invalid' }",
                    "$node = $ast.Find({ param($entry) $entry -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $entry.Name -eq 'Invoke-StoneglassPython' }, $true)",
                    "if ($null -eq $node) { throw 'Production helper missing' }",
                    "Invoke-Expression $node.Extent.Text",
                    "$childArguments = @('-I', '-S', '-B', '-c', " + ps_literal(child) + ")",
                    "$observed = Invoke-StoneglassPython -PythonExecutable " + ps_literal(sys.executable) + " -PythonArguments $childArguments -LogPath " + ps_literal(str(log)),
                    f"if ($observed -ne {exit_code}) {{ throw 'Native exit code was lost' }}",
                    "if ($ErrorActionPreference -ne 'Stop') { throw 'Caller preference changed' }",
                    "Write-Output ('EXIT_CODE=' + $observed)",
                )) + "\n", encoding="utf-8-sig")
                result = subprocess.run([shell, "-NoLogo", "-NoProfile", "-NonInteractive", "-File", str(script)],
                    capture_output=True, timeout=30)
                output = (result.stdout + result.stderr).decode(errors="replace")
                self.assertEqual(result.returncode, 0, output)
                self.assertIn(f"EXIT_CODE={exit_code}", output)
                raw_log = log.read_bytes()
                # Tee-Object uses UTF-16 in Windows PowerShell and UTF-8 in pwsh.
                logged = raw_log.decode("utf-16" if raw_log.startswith(b'\xff\xfe') else "utf-8-sig")
                for message in ("stdout preserved", "INFO hardware inventory completed", "ERROR diagnostic text preserved"):
                    self.assertIn(message, output); self.assertIn(message, logged)
                for decoration in ("NativeCommandError", "CategoryInfo", "RemoteException", "python.exe :"):
                    self.assertNotIn(decoration, output); self.assertNotIn(decoration, logged)

    def test_info_and_stderr_text_are_plain_and_success_exit_preserved(self):
        self.check_streams(0)

    def test_nonzero_exit_and_error_text_are_preserved(self):
        self.check_streams(7)
