# Stage 3 — local generation in the desktop interface

This development change connects the existing PySide6 interface to Stoneglass's
production ordinary-user worker and SDXL adapter. It does not add another
pipeline, dependencies, model acquisition, security configuration, or a backend
from another image-generation application. Publication and packaging remain
separate review steps.

## Operator workflow

1. Launch with the existing GUI environment: `.\.venv\Scripts\python.exe -m stoneglass`.
2. In **Models**, browse to the reviewed local `.safetensors` checkpoint and its
   matching schema-1 manifest. The existing development manifest is under
   `.local-data/sdxl-bundles/base-initial/manifest.json` if already prepared.
   No checkpoint is selected automatically and no resources are downloaded.
3. Choose **Validate model**. The background task checks complete local resources,
   hashes, architecture, and the installed ROCm runtime using an owned worker.
   It does not load weights. Validation can take minutes; Cancel remains available.
4. In **Generate**, set prompts, dimensions, steps, CFG, and seed, then choose
   **Generate** or press **Ctrl+Return**. Cancel or **Escape** stops active work.
5. The validated image appears after generation and owned-worker cleanup.
   **Save PNG** exports the original full-resolution bytes. The original remains
   under `generated/` in the application-data directory shown in Settings.

Selections and generation preferences persist; readiness is deliberately not
persisted. Validate again after restarting or changing either selection. Prompts
remain session-only. Existing dimensions, presets, sidebar preferences, theme,
branding and navigation are retained. Readiness does not change unrelated input.

## Initial supported profile

The initial UI intentionally requires the reviewed **AlbedoBase XL v3.1-Large**
checkpoint SHA256 and all 14 exact configuration/tokenizer resource hashes in
`inference/reviewed_profile.py`. The manifest must match the selected local
checkpoint; resource preflight independently verifies actual contents. Another
checkpoint or configuration is rejected, even if its filename says SDXL. Selecting
a different path is supported when it points to the same approved resources.

Runtime readiness requires the reviewed `.venv-rocm`, PyTorch
`2.13.0+rocm10.0.0`, a HIP build without CUDA, and a validated RX 9060 XT
`gfx1200`. No CUDA or CPU UI profile is offered yet. Windows adapter inventory
alone does not establish readiness. The default GUI dependency set remains small;
a missing optional runtime produces a local error and never starts installation.

The adapter retains batch one, FP16 weights, eager/math attention, VAE upcasting,
and the validated scheduler. Maximum image area is 1,048,576 pixels. Larger manual
dimensions remain saved but disable Generate with an explanation; the UI does not
silently reduce them. Existing request validation still applies. Seed `-1` selects
a random seed; preview reports the actual result seed. Memory requirements and
speed vary with dimensions and steps; broader performance certification remains
future work.

Model credit: [AlbedoBase XL v3.1-Large](https://civitai.com/models/140737?modelVersionId=1041855)
by [albedobond](https://civitai.com/user/albedobond). Model terms are separate from
Stoneglass's GPL source license; see the [publisher's license](https://civitai.com/models/license/1041855)
and [Stage 2 provenance review](LOCAL_INFERENCE_STAGE2.md). No model weights or
private local resource paths are added to the source distribution.

## Existing boundaries and new responsibilities

| Component | Responsibility |
| --- | --- |
| `ui/models_page.py` | Explicit local file selection, selected name/location, readiness and errors |
| `ui/generation_controller.py` | GUI state, buttons, actual-step progress, cancellation, preview and export coordination |
| `infrastructure/inference_tasks.py` | Existing TaskManager/QThread integration for readiness and generation transactions |
| `services/inference.py` | Serialized resource/runtime selection, model ownership and cleanup |
| `services/generation.py` | Load once, generate, validate committed output, collect metrics, unload/terminate before success |
| `services/images.py` | Bounded PNG structure/CRC/decompression/dimension validation and atomic lossless export |
| `inference/process_backend.py` | Existing IPC/backend, reviewed runtime gate, PNG verification before atomic commit, owned worker cleanup |
| `inference/reviewed_profile.py` | Explicit approved checkpoint and resource fingerprints |
| `inference/sdxl.py` | Existing production Diffusers adapter; adds decode/save progress events |
| `ui/image_preview.py` | Qt decode check, fit-to-window display retaining original resolution, functional Save action |

The UI process never imports Torch, Diffusers, or Transformers. Slow resource
hashing and runtime initialization run on existing task threads; GPU work runs in
the existing `.venv-rocm` worker. The resource/runtime probe closes before returning
readiness. Each generation revalidates resources and runtime before loading one
pipeline in a fresh worker. This favors correctness over repeated-startup cost.

Worker initialization, resource checks, loading, VAE decode, saving and cleanup use
indeterminate progress with descriptive text. Sampling alone uses actual completed
step counts. The last step callback announces decode before the pipeline's VAE
phase; saving events bracket actual PNG encoding. Completion requires PNG checks,
atomic commit, successful worker cleanup, and a successful Qt preview decode.

No conflicting inference action can be submitted through the UI. Cancellation
uses the existing bounded protocol and owned Windows job; it never enumerates or
kills unrelated Python processes. Closing the window defers destruction until
tasks and owned cleanup finish. Native calls can require termination instead of
cooperative cancellation. A cleanup failure blocks further generation and retains
ownership for retry rather than discarding handles. Cancel before the existing
result-commit boundary discards pending output; after commit, the valid image is
preserved and may complete successfully. Export preserves the original bytes and
does not alter image pixels, size or metadata.

Each successful generation closes its process before reporting completion. This
avoids relying on adapter-only unload, which retained approximately 1.37 GiB in
Stage 2. No warm persistent GPU worker, compilation, fused attention, quantization,
new scheduler, or runtime tuning is introduced.

## Offline behavior and limits

Existing strict local-path checks, full resource hashes/read leases, explicit local
Diffusers configuration, offline library environment, credential/proxy removal,
bounded IPC and prompt-safe error reporting remain in use. No discovery request,
remote configuration, authentication or automatic dependency/model download is
introduced. Future acquisition and grouped **No / Download** notices remain separate
milestones.

The ordinary-user worker is not an OS network sandbox. Stage 2 physical-disconnection
acceptance passed for its recorded source/runtime/resources. Stage 3.1 subsequently
passed the separate [operator-run offline UI workflow](OFFLINE_UI_ACCEPTANCE.md)
and evidence review on November 7, 2026, covering the recorded source/launcher/assets,
reviewed ROCm/SDXL profile, generation, preview, export and shutdown. Continuous
physical disconnection and UI usability are operator attestations; local evidence
independently verifies hashes, output and owned-worker cleanup. The legacy backend
launcher remains unchanged. Both procedures reject stale source fingerprints;
future source/resources/runtime changes require a fresh receipt and acceptance
before extending the claim. Historical AppContainer and diagnostic artifacts are
untouched.

Gallery indexing/browsing, arbitrary SDXL checkpoints, other architectures/hardware,
interactive editing, zoom, runtime installation, packaged binary distribution and
publication are outside this change. Private test evidence and images stay under
ignored `.test-artifacts/stage3-ui/`; no user settings or model data are bundled.

## Validation

Routine tests mock inference and use clearly identified static PNG fixtures; they
require no models or GPU. Coverage includes selection/readiness, unsupported
profiles, button gating, parameter forwarding and persistence, progress,
cancellation/recovery, output corruption, full-resolution export, cleanup retry,
shutdown and the existing owned-job tests. A separate native-window integration
exercise uses the actual Models and Generate controls, production services and
ROCm worker, and records output, timing/memory, preview/export and process cleanup.
Final execution results are retained in the local Stage 3 report.

Verified November 7, 2026: **188 tests passed in each of four runs** (GUI and ROCm
environments, offscreen and native Windows Qt); both environments passed
`pip check`. The final native UI generation used 512x512, 20 steps, CFG 5.0,
seed 12345, batch one, and the approved red sports car/lake prompt. It produced a
valid full-resolution PNG, displayed it, exported identical bytes, and closed all
three owned workers normally with exit code 0. Torch was not imported in the UI
process. Source fingerprints were recorded and independently rechecked.

| Measurement from the final UI integration run | Observed |
| --- | --- |
| Explicit readiness validation | 18.315 seconds |
| Whole generation task, including revalidation and cleanup | 239.920 seconds |
| Worker model load, including imports/component checks | 56.097 seconds |
| Weights through GPU readiness, within that load | 16.002 seconds |
| Inference through VAE decode, excluding PNG encoding | 150.038 seconds |
| Peak Torch GPU allocated / reserved | 9.735 / 10.289 GiB |
| Worker lifetime peak working set / commit | 7.075 / 14.042 GiB |

These are one Windows ROCm worker launch, not steady-state guarantees or total
system VRAM measurements. Native initialization and VAE decode can remain slow
while the interface stays responsive. Automated UI cancellation/recovery uses
mocked inference; the existing native owned-process tests and Stage 2's actual
model cancellation evidence remain separate from this successful UI generation.
