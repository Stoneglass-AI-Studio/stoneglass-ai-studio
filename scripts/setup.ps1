# SPDX-License-Identifier: GPL-3.0-or-later

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$venvDirectory = Join-Path $projectRoot '.venv'
$venvPython = Join-Path $venvDirectory 'Scripts\python.exe'

if (-not (Test-Path -LiteralPath $venvPython)) {
    & python -c "import sys; assert sys.version_info >= (3, 11), 'Python 3.11 or newer is required'"
    if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.11 or newer and add it to PATH.' }
    & python -m venv $venvDirectory
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the project virtual environment.' }
}

& $venvPython -m pip install -e $projectRoot
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Review the pip output above.' }
Write-Output 'Stoneglass is ready. Launch with .\scripts\launch.ps1'
