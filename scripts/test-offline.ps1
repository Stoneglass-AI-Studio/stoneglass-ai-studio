# SPDX-License-Identifier: GPL-3.0-or-later
# Windows PowerShell 5.1 / PowerShell 7. No policy changes or downloads.
[CmdletBinding()]
param(
    [switch]$PrepareOnly,
    [string]$Manifest = ''
)

$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$artifacts = Join-Path $projectRoot '.test-artifacts\offline-acceptance'
$runDirectory = $null
$exitCode = 1
$phase = if ($PrepareOnly) { 'preparation' } else { 'offline-execution' }

function Write-LauncherMessage([string]$Message) {
    Write-Host $Message
    if ($runDirectory) {
        Add-Content -LiteralPath (Join-Path $runDirectory 'launcher.log') -Value $Message -Encoding UTF8
    }
}

try {
    # Reject existing redirects before creating any run directory.
    $ancestor = [IO.DirectoryInfo]$artifacts
    while ($null -ne $ancestor) {
        if ($ancestor.Exists -and (($ancestor.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0)) {
            throw 'Use a local checkout without junctions or directory symlinks.'
        }
        $ancestor = $ancestor.Parent
    }
    $runName = '{0}-{1}-{2}' -f $phase, (Get-Date -Format 'yyyyMMdd-HHmmss'), ([Guid]::NewGuid().ToString('N').Substring(0, 12))
    $runDirectory = Join-Path $artifacts $runName
    New-Item -ItemType Directory -Path $runDirectory -ErrorAction Stop | Out-Null
    Write-LauncherMessage 'Stoneglass standalone local SDXL acceptance test'
    Write-LauncherMessage "Phase: $phase"
    Write-LauncherMessage "Evidence directory: $runDirectory"
    Write-LauncherMessage 'No downloads, installs, network probes, adapter changes, or administrator privileges are used.'

    $python = Join-Path $projectRoot '.venv\Scripts\python.exe'
    $support = Join-Path $PSScriptRoot 'offline_acceptance.py'
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        throw 'The existing .venv Python is missing. Restore the approved local environment before testing; nothing will be installed.'
    }
    if (-not (Test-Path -LiteralPath $support -PathType Leaf)) {
        throw 'The local scripts\offline_acceptance.py support file is missing.'
    }
    $arguments = @('-I', '-S', '-B', '-X', 'utf8', $support, '--run-directory', $runDirectory)
    if ($Manifest) { $arguments += @('--manifest', $Manifest) }
    if ($PrepareOnly) {
        Write-LauncherMessage 'PREPARATION ONLY: checking local resources and worker startup; no weights will be loaded and no image generated.'
        $arguments += '--prepare-only'
    } else {
        if (-not (Test-Path -LiteralPath (Join-Path $artifacts 'prepared.json') -PathType Leaf)) {
            throw 'Preparation receipt missing. Run this launcher with -PrepareOnly while connected and review its result first.'
        }
        Write-LauncherMessage 'Preparation receipt found. Local resources will be rechecked before any model loading.'
        Write-LauncherMessage 'Manually disconnect Ethernet and turn off Wi-Fi and any other internet connection before continuing.'
        Write-LauncherMessage 'Keep networking disconnected until the test finishes. You will reconnect manually afterward.'
        $answer = Read-Host 'Type DISCONNECTED to confirm, or anything else to cancel'
        if ($answer -cne 'DISCONNECTED') {
            throw 'Cancelled: physical disconnection was not confirmed. No inference was started.'
        }
        $arguments += '--operator-confirmed-disconnected'
    }

    $previousErrorActionPreference = $ErrorActionPreference
    try {
        # Keep native startup stderr in the local log as well as the console.
        # Windows PowerShell represents redirected native stderr as error records.
        $ErrorActionPreference = 'Continue'
        & $python @arguments 2>&1 | Tee-Object -FilePath (Join-Path $runDirectory 'python-console.log')
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    $resultPath = Join-Path $runDirectory 'result.json'
    if (-not (Test-Path -LiteralPath $resultPath -PathType Leaf)) {
        throw 'Python stopped without a final result.json. Preserve this directory for review; acceptance is not established.'
    }
    $result = Get-Content -LiteralPath $resultPath -Raw | ConvertFrom-Json
    if (($exitCode -ne 0) -or (-not $result.local_checks_passed)) {
        $exitCode = if ($exitCode -eq 0) { 1 } else { $exitCode }
        Write-LauncherMessage "FAILED OR CANCELLED. See $resultPath and diagnostics.log."
    } elseif ($PrepareOnly) {
        Write-LauncherMessage 'PREPARATION PASSED. No image was generated. Stop for review before disconnecting.'
    } else {
        Write-LauncherMessage 'LOCAL TEST PASSED. Physical offline acceptance remains pending online evidence review.'
        Write-LauncherMessage "Preserved image: $($result.image.path)"
        Write-LauncherMessage 'Reconnect manually when ready, then ask Codex to review this evidence directory.'
    }
} catch {
    $exitCode = 1
    Write-LauncherMessage ("FAILED OR CANCELLED: " + $_.Exception.Message)
} finally {
    if ($runDirectory -and (Test-Path -LiteralPath $runDirectory -PathType Container)) {
        @{ phase = $phase; exit_code = $exitCode; finished_at = (Get-Date).ToString('o');
           offline_acceptance_claimed = $false } | ConvertTo-Json |
            Set-Content -LiteralPath (Join-Path $runDirectory 'launcher-result.json') -Encoding UTF8
        Write-LauncherMessage "Finished with exit code $exitCode. Evidence: $runDirectory"
    }
}
exit $exitCode
