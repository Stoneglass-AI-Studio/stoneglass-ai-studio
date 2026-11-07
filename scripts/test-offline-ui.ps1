# SPDX-License-Identifier: GPL-3.0-or-later
# Windows PowerShell 5.1 / PowerShell 7. Ordinary user; no network/security changes.
[CmdletBinding()]
param([switch]$PrepareOnly, [string]$Manifest = '')

$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$artifacts = Join-Path $projectRoot '.test-artifacts\offline-ui-acceptance'
$runDirectory = $null
$exitCode = 1
$operatorConfirmed = $false
$visualConfirmed = $false
$phase = if ($PrepareOnly) { 'preparation' } else { 'ui-execution' }

function Write-LauncherMessage([string]$Message) {
    Write-Host $Message
    if ($runDirectory) {
        Add-Content -LiteralPath (Join-Path $runDirectory 'launcher.log') -Value $Message -Encoding UTF8
    }
}

function Invoke-StoneglassPython([string]$PythonExecutable, [string[]]$PythonArguments, [string]$LogPath) {
    $savedPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        # Windows PowerShell 5.1 wraps redirected native stderr in ErrorRecord.
        # Normalize both streams before Tee/formatting, without dropping text or
        # using stderr presence as success/failure. The native exit code and
        # result.json remain authoritative below.
        & $PythonExecutable @PythonArguments 2>&1 |
            ForEach-Object { $_.ToString() } |
            Tee-Object -FilePath $LogPath | Out-Host
        return $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $savedPreference
    }
}

try {
    $ancestor = [IO.DirectoryInfo]$artifacts
    while ($null -ne $ancestor) {
        if ($ancestor.Exists -and (($ancestor.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0)) {
            throw 'Use a local checkout without junctions or directory symlinks.'
        }
        $ancestor = $ancestor.Parent
    }
    $name = '{0}-{1}-{2}' -f $phase, (Get-Date -Format 'yyyyMMdd-HHmmss'), ([Guid]::NewGuid().ToString('N').Substring(0, 12))
    $runDirectory = Join-Path $artifacts $name
    New-Item -ItemType Directory -Path $runDirectory -ErrorAction Stop | Out-Null
    Write-LauncherMessage 'Stoneglass Stage 3.1 - operator-run offline UI acceptance'
    Write-LauncherMessage "Evidence directory: $runDirectory"
    Write-LauncherMessage 'No downloads, installs, network probes, adapter changes, or administrator privileges.'
    $python = Join-Path $projectRoot '.venv\Scripts\python.exe'
    $support = Join-Path $PSScriptRoot 'offline_ui_acceptance.py'
    if (-not (Test-Path -LiteralPath $python -PathType Leaf) -or -not (Test-Path -LiteralPath $support -PathType Leaf)) {
        throw 'The existing GUI Python or local UI test driver is missing. Nothing will be installed.'
    }
    $arguments = @('-I', '-S', '-B', '-X', 'utf8', $support, '--run-directory', $runDirectory)
    if ($Manifest) { $arguments += @('--manifest', $Manifest) }
    if ($PrepareOnly) {
        Write-LauncherMessage 'PREPARATION ONLY: local resources, dependencies, native UI startup and model-free worker checks.'
        Write-LauncherMessage 'No GPU initialization, checkpoint loading, generation, or disconnected acceptance execution.'
        $arguments += '--prepare-only'
    } else {
        if (-not (Test-Path -LiteralPath (Join-Path $artifacts 'prepared.json') -PathType Leaf)) {
            throw 'UI preparation receipt missing. Run this script with -PrepareOnly while connected first.'
        }
        Write-LauncherMessage 'Manually disconnect Ethernet, Wi-Fi and any other internet-bearing connection now.'
        Write-LauncherMessage 'Keep networking disconnected through UI shutdown and the final confirmation below.'
        if ((Read-Host 'Type DISCONNECTED to confirm, or anything else to cancel') -cne 'DISCONNECTED') {
            throw 'Cancelled before inference: physical disconnection not confirmed.'
        }
        $operatorConfirmed = $true
        Write-LauncherMessage 'In Stoneglass: Validate model, switch to Generate, then click Generate. Keep the prefilled request unchanged.'
        Write-LauncherMessage 'Watch progress and inspect the actual preview. You may resize/collapse the sidebar.'
        Write-LauncherMessage 'Optional: Cancel an attempt, wait for cleanup, then Generate again. A final successful generation is required.'
        Write-LauncherMessage 'Choose Save PNG, paste this full filename into the real Save dialog:'
        Write-LauncherMessage (Join-Path $runDirectory 'exported-full-resolution.png')
        Write-LauncherMessage 'Wait for export, then close Stoneglass normally. Use Cancel/Close rather than terminating the console.'
        $arguments += '--operator-confirmed-disconnected'
    }
    $exitCode = Invoke-StoneglassPython -PythonExecutable $python -PythonArguments $arguments -LogPath (Join-Path $runDirectory 'python-console.log')
    $resultPath = Join-Path $runDirectory 'result.json'
    if (-not (Test-Path -LiteralPath $resultPath -PathType Leaf)) {
        throw 'Python exited without result.json. Preserve this incomplete evidence; acceptance is not established.'
    }
    $result = Get-Content -LiteralPath $resultPath -Raw | ConvertFrom-Json
    if (($exitCode -ne 0) -or (-not $result.local_checks_passed)) {
        if ($exitCode -eq 0) { $exitCode = 1 }
        Write-LauncherMessage "FAILED OR INCOMPLETE. See $resultPath and diagnostics.log."
    } elseif ($PrepareOnly) {
        Write-LauncherMessage 'PREPARATION PASSED. No image generated. Stop for review before disconnecting.'
    } else {
        Write-LauncherMessage 'Local automated checks passed. Confirm only if the image looked correct, UI stayed usable, and networking remained disconnected throughout.'
        $visualConfirmed = (Read-Host 'Type UI_CONFIRMED to attest those observations, or anything else to mark incomplete') -ceq 'UI_CONFIRMED'
        if (-not $visualConfirmed) { throw 'Operator confirmation missing. Evidence preserved; no acceptance is claimed.' }
        Write-LauncherMessage 'LOCAL OFFLINE UI TEST COMPLETED. Acceptance remains pending online evidence review.'
        Write-LauncherMessage "Preserved image: $($result.image.path)"
        Write-LauncherMessage 'You may reconnect manually and provide this evidence directory for review.'
    }
} catch {
    $exitCode = 1
    Write-LauncherMessage ('FAILED OR INCOMPLETE: ' + $_.Exception.Message)
} finally {
    if ($runDirectory -and (Test-Path -LiteralPath $runDirectory -PathType Container)) {
        @{ phase = $phase; exit_code = $exitCode; finished_at = (Get-Date).ToString('o');
           operator_confirmed_disconnected = $operatorConfirmed; operator_ui_and_continuous_disconnection_confirmed = $visualConfirmed;
           offline_acceptance_claimed = $false } | ConvertTo-Json |
            Set-Content -LiteralPath (Join-Path $runDirectory 'launcher-result.json') -Encoding UTF8
        Write-LauncherMessage "Finished with exit code $exitCode. Evidence: $runDirectory"
    }
}
exit $exitCode
