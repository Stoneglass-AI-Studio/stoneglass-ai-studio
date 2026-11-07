# Standalone physical-disconnection acceptance test

Status: Stage 2's operator-run backend test passed physical-disconnection execution
and evidence review on November 7, 2026, for its recorded source/resources/runtime.
This document describes that backend launcher. **For Stage 3.1 desktop acceptance,
use the separate [offline UI procedure](OFFLINE_UI_ACCEPTANCE.md).** New executions
of either launcher require their own current receipt and evidence review.
The operator runs this test independently of Codex/chat.
No network access, accounts, administrator privileges or external services are
required by the launcher. It never changes adapters, firewall/security settings,
packages, models, original resources, ComfyUI, or the publication checkout.

## Preparation while connected

From ordinary Windows PowerShell 5.1 or PowerShell 7, run:

```powershell
& '.\scripts\test-offline.ps1' -PrepareOnly
```

Preparation checks the existing GUI Python, dedicated `.venv-rocm` Python
3.13.12 x64, exact reviewed ROCm/library versions, installed required package files,
local PNG decoder, and `pip check` without contacting an index. It verifies the
complete checkpoint SHA256 and all 14 configuration/tokenizer resource hashes
through Stoneglass's existing validator. The default manifest is
`.local-data/sdxl-bundles/base-initial/manifest.json`.

A fresh production worker is checked for ready/unload/close with normal exit and
owned-job cleanup. **Preparation does not load weights, initialize the GPU, or
generate an image.** Installed dependency file/metadata checks do not replace
actual GPU execution; that was validated in Stage 2 and is exercised by the later
offline run.

Wait for `PREPARATION PASSED`, exit code 0, and review its `result.json`. A receipt
is saved under `.test-artifacts/offline-acceptance/prepared.json`. The receipt pins
the application/test source hashes, manifest, checkpoint and dependency profile.
Source, resource or dependency changes require preparation/review again. No model
or supporting resource is acquired if a prerequisite is missing. Existing
environments are never repaired or upgraded automatically.

This test profile specifically uses the reviewed AlbedoBase XL v3.1-Large
checkpoint. It is not a general model selector or an alternate inference backend.
Its complete local bundle is separate from the test's new empty Hub cache.

## Operator execution while physically disconnected

1. Close any previous acceptance-test process and preserve its results. Use an
   ordinary local PowerShell window; Codex does not need to remain connected.
2. Physically disconnect Ethernet, turn off Wi-Fi, and disconnect any other
   internet-bearing connection/tether manually. The script does not inspect or
   change network adapters and does not contact an external address to test them.
3. Run the exact command below while still disconnected:

```powershell
& '.\scripts\test-offline.ps1'
```

4. Type **`DISCONNECTED`** at the confirmation prompt. Any other response cancels
   before inference. This records the operator's declaration, not automated proof
   of the physical network state. Do not confirm while connected.
5. Leave networking disconnected until the launcher prints its final pass/fail
   message and exits. Allow several minutes: cold ROCm initialization, the first
   sampling step and VAE decode were slow in Stage 2. Waiting messages recur during
   native work; sampling progress represents real completed steps. Ctrl+C attempts
   owned cleanup and saves cancellation evidence. Abrupt console/process termination
   may leave a `running`/incomplete result; that must never be treated as a pass.
6. Reconnect manually when desired. Ask Codex to review the printed evidence
   directory after connectivity is restored.

The existing local execution policy must allow the script, as verified during
preparation on this machine. If Windows blocks execution, stop and report that
message. Do not change/bypass execution policy or other security settings.

## What the offline run does

Each invocation creates a unique ignored directory:

```text
.test-artifacts/offline-acceptance/offline-execution-<time>-<unique-id>/
  launcher.log
  launcher-result.json
  python-console.log
  console.log
  progress.jsonl
  dependencies.json
  result.json
  diagnostics.log                     # on a Python failure
  dependency-probe/                   # owned metadata-check cache/temp
  worker-state/
    inference-worker/huggingface/hub/ # initially empty; never prefilled
    generated/
      stoneglass-<unique>.png         # preserved after worker exit
```

No prior run, cache or output is deleted or reused. The run rechecks local
prerequisites, checks that its owned Hub cache begins empty, and launches a fresh
production worker through `SDXLProcessBackend`/`LocalWorkerLauncher`. All model
loading, complete meta-device validation and inference use Stoneglass's current
SDXL adapter in `.venv-rocm`, with the established offline-library environment.
No fake generator, separate pipeline, UI activation, optimizer or model conversion
export is used.

The exact fixed request is:

| Setting | Value |
| --- | --- |
| Prompt | A photorealistic red sports car parked beside a mountain lake at sunset. |
| Negative prompt | Empty |
| Resolution | 512x512 |
| Steps | 20 |
| CFG | 5.0 |
| Seed | 12345 |
| Batch | 1 |

FP16, existing eager attention, VAE upcasting and the reviewed local scheduler
remain unchanged. No compilation, quantization or experimental optimization is
enabled. The parent runner uses `.venv` for local Qt PNG verification; it does not
perform inference or import Torch/Diffusers/Transformers.

The image is atomically committed outside the worker's temporary directory. The
runner verifies PNG format, full Qt decoding, 512x512 dimensions and nonuniform
content, then unloads/closes the worker and checks normal exit plus owned-job
cleanup. It verifies the saved image and its SHA256 again after shutdown. The
final PNG remains available even if a later validation/cleanup check fails.
Diagnostic responses retain timing and GPU/host counters; known live-worker
allocation-retention limitations from Stage 2 remain documented. Full backend
unload terminates the worker job instead of claiming `empty_cache()` frees every
live-process allocation.

## Results and online review

Exit 0 with `LOCAL TEST PASSED` means the local generation, output and shutdown
checks completed. `result.json` records operator confirmation, initially empty
cache, actual image path/hash, timings, memory counters, owned-process exit codes,
cleanup and any error. It deliberately leaves `offline_acceptance_passed: false`
and marks acceptance as **pending online review**. A preparation pass, mock unit
test, or a connected-state generation is not offline acceptance.

Nonzero exit means failed/cancelled/incomplete. Preserve the whole run directory;
do not install anything or alter model files to make it pass. Errors appear in the
console and local logs. A failure before Python starts is still recorded in
`launcher.log`/`launcher-result.json`. The latest Python-run locations are also
recorded in `latest-preparation.json` and `latest-run.json` under the artifact root.

After reconnecting, provide the evidence path and confirm that networking remained
physically disconnected for the whole run. Codex will inspect the results, logs,
saved image, initial-cache evidence and cleanup before reporting acceptance.
Fixed seed is not a promise of bit-identical images across fresh ROCm workers.

The inference flags/local-only validation are library safeguards, not an OS
network sandbox. No AppContainer, WFP, elevated inspection, auditing, tracing or
firewall work is involved. Stage 2 physical-disconnection acceptance passed with
operator execution and evidence review on November 7, 2026. Its raw evidence is
preserved. Stage 3 enables the reviewed profile in the UI; this standalone launcher
continues to use the same production service/worker. Source changes invalidate an
old preparation receipt, so prepare again before any new disconnected execution.
No source commit, push or publication is performed.

Model credit: [AlbedoBase XL v3.1-Large](https://civitai.com/models/140737?modelVersionId=1041855)
by [albedobond](https://civitai.com/user/albedobond), under the
[original published license](https://civitai.com/models/license/1041855).
