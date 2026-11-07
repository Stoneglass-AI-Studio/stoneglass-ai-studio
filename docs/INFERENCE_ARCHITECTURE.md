# Phase 2A: independent local inference architecture

> Historical phase record. Current runtime/UI behavior and accepted offline scope
> are documented in [Stage 3](STAGE3_UI.md) and [Stage 3.1](OFFLINE_UI_ACCEPTANCE.md).
> Earlier unavailable features and security gates below describe that phase only.

This document records the Phase 2A foundation. Current guarded SDXL work and its
pending Windows isolation approval are documented in
[the Phase 2B.2B worker notes](OFFLINE_SDXL_WORKER.md). No real model has been loaded.

Phase 2A adds contracts and orchestration to the existing PySide6 application.
It does not ship an image-generation backend, load a real model, generate an
image, install PyTorch/Diffusers, or select an approved GPU software stack.
The production provider registry is empty and Generate remains disabled.

## Boundaries and ownership

| Module | Responsibility |
| --- | --- |
| `inference/contracts.py` | Immutable requests/results, local model specifications, runtime reports/selections, provider/backend protocols, state snapshots, typed progress and cancellation contracts. |
| `inference/errors.py` | Stable error codes and readable, prompt-safe errors. |
| `inference/validation.py` | Strict request validation and resolution of existing local model/adapter paths. No discovery, download or checkpoint parsing. |
| `inference/runtime.py` | Optional bounded runtime probe and selection from validated devices. |
| `inference/_torch_probe.py` | Child-process PyTorch import and tiny float32 arithmetic checks. No models. |
| `services/inference.py` | Owns one backend/pipeline, serializes operations, coordinates load/generate/unload and cleanup. No Qt imports. |
| `infrastructure/inference_tasks.py` | GUI-thread submissions to the existing `TaskManager`; no second thread pool. |
| `infrastructure/workers.py` | Owned Qt threads, queued delivery, cancellation, typed progress/error signals alongside existing signals. |

`ApplicationServices` composes an `InferenceService` without probing runtimes or
importing optional frameworks. The existing Windows display inventory remains
independent. `MainWindow.inference_tasks` is the background integration point.
`GeneratePage.generation_request(model_id)` snapshots current prompts and validated
UI preferences without persisting prompts. Status updates keep Generate disabled,
even if a unit-test adapter reports readiness. Preview and gallery remain empty.

The service is synchronous so it can be used without Qt; application callers must
submit expensive operations through `InferenceTasks`. Calls on one service are
serialized with a nonblocking lock. Overlapping operations receive `BUSY` rather
than starting a second pipeline or silently building a queue. Immutable status
snapshots can be read while an operation runs. Future UI readiness must consider
the task's busy state as well as `status.can_generate`.

## Model specification and extension

`ModelSpec` contains a stable model ID, an existing local path, an architecture
identifier, a variant and optional local adapter paths. Architecture IDs are
strings so another family does not require redesigning the service. `sdxl` is the
initial identifier. LCM is represented by `ModelVariant.LCM`, since it can be a
distilled variant or adapter configuration rather than a separate base family.
A future provider declares supported architectures, variants, runtimes and whether
it actually implements generation. SDXL/LCM pipelines and scheduler configuration
belong in those adapters, not in widgets or this orchestration service.

Paths are resolved in the worker. Missing references and UNC/network-share paths
are rejected; no repository/model identifier is resolved through a hub. This is
not a security sandbox: users must also keep paths off network-mounted drives.
Validating a local path does not certify checkpoint contents or a complete model.
Providers must validate their actual format, components and architecture in Phase
2B, use local-only loading and reject missing components instead of downloading.

## Model lifecycle

| State | Meaning and next operation |
| --- | --- |
| `EMPTY` | No owned pipeline. A supported local model may be loaded. |
| `LOADING` | Candidate backend owns partial allocations. Cancellation/failure unloads it. |
| `READY` | Loaded model; generation also requires the provider's generation capability. |
| `GENERATING` | One request in flight. No simultaneous model changes or generation. |
| `UNLOADING` | Mandatory release of pipeline resources. Cancellation cannot skip cleanup. |
| `FAILED` | Cleanup failed; ownership is retained. Retry unload/close before loading again. |
| `CLOSED` | Cleanup succeeded. Close/unload are idempotent; new work is rejected. |

A replacement is checked for local references, provider support and runtime
compatibility before releasing the old model. The same specification/device can
reuse the current pipeline. After releasing an old model, cancellation or failure
does not automatically reload it. Load/generation failures and cancellation release
partial resources and return to `EMPTY`; a cleanup failure instead retains the
backend in `FAILED` for a safe retry. Invalid requests leave a ready model intact.

Factories must be lightweight and allocate no model resources before returning.
Backend `load_model` owns allocations, `generate` owns temporary image files, and
`unload` must release references/resources idempotently and be safe to retry after
partial failure. Worker threads can differ between calls, so adapters must bind
their explicit runtime device on every call and must not rely on caller-thread
CUDA/HIP defaults. The service does not guess how to free a framework pipeline or
delete paths returned by an adapter. In Phase 2B the adapter must persist completed
images atomically, remove only its own failed temporary output, and return accurate
dimensions, model ID, absolute local path and resolved seed. Phase 2A checks the
result contract; it does not implement image encoding or claim to validate pixels.

## Runtime detection and selection

Probing is explicit, through `InferenceTasks.detect_runtimes()` or a worker load.
It does not run during normal startup or hardware inventory refresh. The probe
uses this Python environment's interpreter in a separate process with a 20-second
deadline. The parent polls at most every 100 ms; cancellation or timeout kills and
reaps only that child. Optional frameworks are never imported into the UI process
by detection. Missing/broken PyTorch, failed drivers, malformed probe output and
unsupported devices produce unavailable diagnostics, not guessed compatibility.
Raw process stderr and framework exception values are not displayed or logged.

The probe checks CPU arithmetic only if PyTorch imports successfully. For GPU
devices it requires availability, identifies HIP versus CUDA from the installed
PyTorch build, allocates a small float32 tensor on each explicit device, performs
arithmetic and synchronizes it. Devices failing the operation are excluded even
if enumeration or `is_available()` succeeded. HIP correctly uses `cuda:N` in
PyTorch; the service reports it as ROCm rather than incorrectly labeling it NVIDIA.

These checks establish basic tensor execution only. They do not certify SDXL/LCM,
attention operators, half precision, performance, available VRAM or a complete
pipeline. No VRAM is inferred from Windows inventory. An AMD adapter name does
not imply a working ROCm installation. Native Windows compatibility depends on
the exact supported GPU, Python, driver and PyTorch build; no standard Linux ROCm
installation or unverified compatibility workaround is assumed.

`RuntimeRequest()` selects a validated GPU supported by the chosen provider.
An explicit ROCm/CUDA request must succeed as requested; it never silently falls
back. CPU is selected with `RuntimeRequest(kind=RuntimeKind.CPU)`, or as an
automatic fallback only with `allow_cpu_fallback=True` and a CPU-capable provider.
Without PyTorch, CPU is also reported unavailable. Device indices can be specified.
Runtime selection does not install anything or make a production backend exist.

Primary references consulted for this boundary:

- [PyTorch HIP semantics](https://docs.pytorch.org/docs/stable/notes/hip.html): HIP reuses the CUDA API and has separate build identification.
- [AMD Windows compatibility matrix](https://rocm.docs.amd.com/projects/radeon-ryzen/en/latest/docs/compatibility/compatibilityrad/windows/windows_compatibility.html): verify the exact native Windows stack before Phase 2B installation.

## Progress, cancellation, errors and shutdown

`ProgressEvent` identifies the stage and a 0–100 stage percentage. Backends must
emit truthful, prompt-free messages at real callbacks. The architecture emits
lifecycle boundaries only; it does not simulate sampling or produce an image.
`TaskHandle.progress_event` and `.error` carry typed values alongside the existing
integer/text progress and readable failure signals. Delivery to GUI receivers is
queued; workers never access widgets.

Cancellation is cooperative between backend stages and inference callbacks.
Adapters must bound I/O and document uninterruptible driver calls. Inference owns
its cancellation/commit boundaries, so its tasks disable the generic worker's
implicit pre/post checks; this prevents a cleanup task being cancelled before
release or a committed result being discarded by a later generic check. The
service checks cancellation before resource allocation and after adapter work.
Once the service has committed a successful operation, later cancellation does
not undo it. Cleanup ignores cancellation and progress-observer failures.

Backend exceptions become stable `InferenceError`/`ErrorInfo` values. Adapter
exception strings and chained tracebacks are suppressed because they can contain
private prompts. Logs retain the operation error code and exception class. This
cannot prevent a third-party adapter from logging on its own: future adapters must
not log prompts, tokens or raw request objects containing private data. Request
representations omit prompt fields, and prompts remain session-only.

On window close, existing jobs are cancelled and awaited asynchronously. If an
inference model is owned, cleanup is submitted to the same worker manager before
closing. The GUI remains responsive. Failed cleanup leaves the window open with
a readable retry message; it does not spin, abandon ownership or forcibly kill a
Qt thread.

## Validation and Phase 2B

Tests inject `unittest.mock` providers, runtimes and child processes. No production
mock backend, image, checkpoint or download is included. The existing UI tests
continue to cover navigation, theme, presets, settings, branding and shutdown.
Run all tests and dependency validation using the existing PowerShell commands:

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -B -m pip check
```

Validation on 2026-11-06: all **83 tests passed** in both offscreen and native
Windows Qt modes (the original 49 tests plus 34 inference tests). `pip check`
reported no broken requirements. The real isolated runtime check reported
`torch_missing`, zero validated devices and no optional framework imports in the
parent process. Existing branding, settings schema, dependencies and test files
were unchanged; the separate publication checkout was verified unchanged.

Phase 2B needs approval for a specific GPU/Python/framework stack and any new
dependencies. Then implement and register a real local-only SDXL provider, add
model-format/component validation and LCM scheduler/adapter handling, implement
precision/memory policy and output ownership, and validate actual loading,
generation, cancellation, unloading and VRAM behavior on supported hardware.
Only after those checks should model selection and Generate be enabled. Preview
rendering and output persistence also need real result validation. No Phase 2B
backend, GPU installation, model acquisition or UI enablement is part of this work.
