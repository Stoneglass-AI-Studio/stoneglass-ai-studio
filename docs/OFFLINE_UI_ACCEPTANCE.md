# Stage 3.1 — operator-run offline UI acceptance

Status: **manual offline UI acceptance PASSED**, with operator execution and
evidence review on November 7, 2026. Scope: the recorded source/launcher/assets,
reviewed RX 9060 XT ROCm environment, AlbedoBase XL v3.1-Large checkpoint, complete
14-resource local bundle and fixed 512x512 workflow below. The operator declared
physical disconnection before execution and confirmed continuous disconnection,
correct preview and usable UI after export/shutdown. This is manual functionality
evidence, not an independent OS/network-isolation proof. Stage 2's backend pass,
Stage 3's connected integration and earlier incomplete UI runs remain separate,
preserved evidence. New versions or profiles need their own preparation/review.

The accepted run recorded exit 0, exactly 20 sampling steps, a valid 512x512 PNG
and identical-byte export, an empty owned Hub cache, and three normal worker exits
with owned process/job cleanup. Source/resource hashes and both PNG copies were
independently verified after shutdown. Runtime model load took 60.073 seconds;
inference through VAE decode took 162.340 seconds. Peak Torch allocated/reserved
memory was 9.735/10.289 GiB. These are one observed run, not steady-state promises.
Private evidence and review remain under the ignored test-artifacts tree; no
model weights or private audit reports are included in the public source.

The new launcher opens the existing Stoneglass desktop and observes its normal
signals. The operator alone clicks Validate model, Generate, Cancel and Save PNG.
No alternate pipeline, scripted generation clicks, simulated images, dependency
downloads, cloud services, accounts or administrator privileges are involved.
Windows network/security settings and adapters are never inspected or changed.

## Prepare while connected

```powershell
& '.\scripts\test-offline-ui.ps1' -PrepareOnly
```

Wait for `PREPARATION PASSED`, exit code 0, and review the evidence. Preparation
checks the full checkpoint SHA256, all 14 local resources and the exact reviewed
profile; Python/package versions, installed files, both environments' dependency
resolution and local PNG support; native desktop startup with Generate disabled;
and a fresh production worker's ready/unload/close lifecycle. The brief desktop
smoke check does not validate the GPU, load weights or generate an image.

This has a separate receipt under
`.test-artifacts/offline-ui-acceptance/prepared.json`. It pins application and
launcher source, UI stylesheet/branding, manifest/resources, and dependency
versions. A backend-test receipt cannot authorize UI acceptance. Changed source,
assets, configuration or dependencies require preparation again. Preparation
never repairs prerequisites or changes existing environments/resources.

Stop after preparation for the operator handoff. Do not run the disconnected
mode while connected or treat preparation as offline acceptance.

## Execute independently while disconnected

1. Close other Stoneglass windows. Keep a local PowerShell window open. Codex/chat
   need not remain available. Physically disconnect Ethernet, disable Wi-Fi using
   your normal manual controls, and disconnect other internet-bearing links.
2. While still disconnected, run:

   ```powershell
   & '.\scripts\test-offline-ui.ps1'
   ```

3. Type **DISCONNECTED** when asked. The script records this declaration, without
   a network probe. Keep networking disconnected until all final confirmations
   complete. Local prerequisites are rechecked before the window opens.
4. The window starts on Models with the reviewed checkpoint and matching manifest
   selected. Click **Validate model**. Wait for readiness. Then switch to Generate.
5. Keep the prefilled request unchanged: positive prompt **A photorealistic red
   sports car parked beside a mountain lake at sunset.**, empty negative prompt,
   **512x512, 20 steps, CFG 5.0, seed 12345, batch one**. Click **Generate**.
6. Observe initialization/loading, actual sampling steps, VAE decode, saving and
   completion. Allow several minutes for Windows ROCm cold work. Use normal page
   navigation, resize and sidebar collapse/expand to check responsiveness. Do not
   edit model selection or request values during this acceptance run.
7. Optional: cancel an attempt, wait for cleanup, then validate/retry as indicated.
   A final successful generation is required. A cancelled owned worker may exit
   with the existing code 1223; successful actions require normal exit 0. Any
   unexpected task/cleanup error makes the run fail for review. Cancellation after
   image commit may preserve a completed result, as documented in Stage 3.
8. Inspect the actual image in the preview. Choose **Save PNG**. The PowerShell
   window prints a full suggested filename ending in `exported-full-resolution.png`
   inside this run's evidence directory. Paste that filename into the real Save
   dialog, save, and wait for export completion. Export outside the evidence
   directory does not satisfy this controlled test.
9. Close Stoneglass normally. Do not terminate the console/process; use the UI's
   Cancel/Close controls. The window waits for owned work and cleanup.
10. Back in PowerShell, type **UI_CONFIRMED** only if the preview looked correct,
    the interface stayed usable, and networking remained disconnected throughout.
    Any other reply marks the run incomplete. Wait for the final exit code and
    evidence path. You may then reconnect manually.
11. Provide the evidence directory for online review, plus any problems observed.
    No new offline acceptance claim is made until that evidence is reviewed.

If local execution policy blocks the script, stop and report the error; do not
bypass/change policy or Windows security settings. No environment activation is
needed, and the command works from any current directory.

An `INFO` line such as `Hardware inventory completed: 1 display adapter(s)` is
normal startup logging. The launcher displays Python stdout/stderr as plain text
so Windows PowerShell 5.1 does not decorate stderr logs as `NativeCommandError`.
Diagnostic text is retained; failures still use Python's exit code, the structured
result and the launcher's final failure message. Do not infer success or failure
from a log's output stream alone.

## Evidence and pass criteria

Each invocation uses a unique, ignored directory:

```text
.test-artifacts/offline-ui-acceptance/
  preparation-<time>-<id>/
  ui-execution-<time>-<id>/
    launcher.log
    launcher-result.json                 # initial/final operator declarations
    python-console.log
    console.log
    progress.jsonl
    dependencies.json
    session-actions.json                 # UI actions and owned-worker exits
    generated-preview.png
    result.json
    diagnostics.log                      # on failure
    desktop-data/
      settings.json                      # isolated test preferences
      inference-worker/huggingface/hub/ # empty before every owned worker
      generated/stoneglass-<id>.png      # preserved after UI/worker exit
    exported-full-resolution.png
```

The application source, normal user settings, existing environments, original
models/configuration, prior security artifacts and publication checkout are not
modified. Images, test preferences and diagnostics remain local in this new tree.
Existing runs and caches are never deleted or recycled. The complete local bundle
is used directly, independently of the new empty Hub cache. Existing offline
library flags and strict local-resource validation remain the production path.

The driver verifies output PNG structure/dimensions/hash, full Qt decode, preview
state, successful real UI export, unchanged original/export hashes after shutdown,
closed owned jobs, normal successful worker exits, removed private output
directories and an empty Hub cache. It records timing and GPU/host diagnostics
from the same one-shot service used by Stoneglass. The UI process must not import
inference libraries. The launcher has a one-hour session deadline in addition to
existing bounded worker operations; unused/incomplete runs cannot pass.

Exit 0 means local checks and the final operator confirmation completed. Both
`result.json` and `launcher-result.json` are required. Python leaves
`offline_acceptance_passed: false`; the launcher never claims acceptance itself.
The operator's physical/visual declarations are manual evidence, not independent
OS proof. The ordinary-user worker is not a network sandbox. No new AppContainer,
firewall, auditing, tracing, capability or adapter work is involved.

Nonzero exit or a missing/incomplete result is a failure/incomplete test. Preserve
the directory. A valid committed image can survive a later error; its presence
alone is not a pass. Unexpected console/process termination may rely on the
existing kill-on-close owned job and leave incomplete evidence. Do not retry by
changing packages, drivers, model files, permissions or validation settings.

Model credit and separate model-license terms remain documented in
[Stage 2](LOCAL_INFERENCE_STAGE2.md). This test does not redistribute weights.
