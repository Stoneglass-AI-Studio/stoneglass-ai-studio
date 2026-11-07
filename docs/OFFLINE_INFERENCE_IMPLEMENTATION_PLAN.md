# Local offline inference: revised implementation plan

> Historical phase record. Current runtime/UI behavior and accepted offline scope
> are documented in [Stage 3](STAGE3_UI.md) and [Stage 3.1](OFFLINE_UI_ACCEPTANCE.md).
> Earlier unavailable features and security gates below describe that phase only.

Status: architecture approved; Stage 1 implemented. See
[Stage 1 results and remaining gates](LOCAL_INFERENCE_STAGE1.md). This document
records the roadmap; its later real-model, download-UI and application-activation
steps have not been executed. Generate remains disabled.

## Direction and scope

The updated project requirements supersede the mandatory AppContainer/WFP gates
in the earlier worker and prototype documents. Normal inference will run in a
dedicated process under the current user's account, using the existing independent
`.venv-rocm`. Administrator privileges and OS network isolation are not product
prerequisites. No further AppContainer, WFP, auditing, tracing, firewall, or elevated
diagnostic work is proposed.

Offline means that a complete local installation can launch, inspect configured
local models, load a model, and generate with internet connectivity disconnected.
Inference must never initiate automatic acquisition. Cloud inference, telemetry,
mandatory accounts, and dependencies on another image-generation application
remain excluded.

Library settings, validated local resources, and regression tests reduce implicit
network behavior. They are **not an OS sandbox or a guarantee that arbitrary
third-party/native code cannot attempt networking**. Physical-disconnection tests
are a required acceptance check, rather than a substitute for local preflight.

This plan adds no new dependency or environment installation. It preserves the
existing UI design, inference contracts, GPU checks, and separate CUDA-profile
strategy for future NVIDIA hardware.

## What the planning checks established

- The existing `.venv-rocm` interpreter launches as an ordinary child process with
  `-I -S -B -X utf8`, an explicit executable, no shell, and a fresh offline
  environment. A protocol-only harness used the existing `WorkerEngine` and
  `run_protocol`, received `ready`, completed `close`, exited successfully, and
  was reaped. No Torch, Diffusers, Transformers, or Hub import occurred.
- The **unchanged production entrypoint still exits with `isolation_unavailable`**
  before inference imports. The harness did not patch that gate. This verifies
  interpreter/protocol viability, not a production launcher, GPU initialization,
  model loading, or inference readiness.
- Installed package metadata still reports Python 3.13.12 x64, Torch
  2.13.0+rocm10.0.0, ROCm SDK 10.0.0, Diffusers 0.40.0, Transformers 5.16.1,
  Accelerate 1.15.0, Safetensors 0.8.0, and Hub 1.30.0.
- All 14 local SDXL configuration/tokenizer resources remain resident, pass the
  existing local-path and configuration/BPE checks, and match the previously
  recorded SHA256 digests. Their combined size is 3,176,106 bytes.
- The existing complete SDXL-base candidate passes the current bounded
  safetensors header/offset/required-marker checks: 2,515 tensors. Its size and
  modification time match the earlier inventory. Full-file hashing and complete
  component-conversion checks remain pending; these checks do not certify weights.

Machine-specific paths, model identity, resource hashes, exact probe responses,
and preservation results are in ignored
`.test-artifacts/offline-direction-review/`. The previous model-free GPU/kernel
successes are historical Phase 2B.2A evidence; GPU tests were not repeated here.

## Implementation sequence

### 1. Replace mandatory isolation authorization with local startup policy

Keep the current layering:

`Generate/controller -> InferenceTasks/TaskManager -> InferenceService -> process backend -> worker -> SDXLAdapter`

| Existing module | Proposed change |
| --- | --- |
| `inference/worker.py` | Generalize `IsolatedLauncher` to a worker-launch interface; supply an ordinary Windows owned-process launcher. Keep `WorkerClient`, bounded JSON pipes, deadlines, cancellation, and cleanup retry. |
| New `inference/local_process.py` | Start only the configured local interpreter/entrypoint under the caller account. Own the process and a kill-on-close Windows Job Object for lifetime cleanup. |
| `inference/offline.py` | Keep fresh environment construction and import-order checks. Separate pre-import policy assertion from ongoing flag checks; neither requires AppContainer membership. Use an accurate offline-policy error instead of telling users to provision isolation. |
| `inference/_offline_worker.py` | Replace mandatory isolation authorization with local startup checks before dependency imports. Keep Python/profile validation and isolated startup flags. |
| `inference/sdxl.py` | Replace isolation calls at dependency/load/generate boundaries with the appropriate offline-policy checks. Preserve local validation, leases, conversion checks, and conservative inference behavior. |
| `inference/process_backend.py` | Inject the ordinary launcher through the current service factory. Keep model readiness and generation capability explicit. |
| Existing worker/resource tests | Replace the obsolete default-isolation rejection expectations with ordinary-launch and offline-policy expectations. Preserve meaningful cancellation, protocol, and integrity coverage. |

The launcher will use explicit arguments, `shell=False`, controlled inherited
pipe handles, hidden console creation, and no prompts/tokens in command lines.
Create the worker suspended, establish owned-job cleanup, then resume it; on a
launch/job/pipe failure, stop and reap that owned process. Job ownership is for
lifecycle cleanup, not a network or token sandbox. Do not use AppContainer token
attributes, capability changes, ACL changes, child-process security mitigations,
global environment changes, or admin APIs. Do not kill by a saved PID or terminate
unrelated Python processes. Test nested-job compatibility and parent-exit cleanup.

Create and validate owned cache/temp/run/output directories before startup; never
reuse the AppContainer staged copy. Keep inference libraries out of the Qt process.
Retain 30-second protocol startup, 180-second runtime probing, 900-second
load/generation deadlines, and bounded cooperative cancellation followed by owned
process termination. Report ongoing local initialization after ten seconds instead
of displaying invented sampling progress. Tune deadlines only from measured runs.

`-S` bypasses `.pth` processing, so manually add only the reviewed environment's
site-packages, as the current entrypoint does. Static inspection found Torch's own
`_rocm_init.initialize()` calls `rocm_sdk.initialize_process()`; no ROCm `.pth` hook
was present. Verify actual imports and kernels under the final minimal environment
before loading weights. Do not solve DLL issues by importing ComfyUI code, running
arbitrary `.pth` hooks, or changing existing environment/global PATH contents.

### 2. Prepare an explicit, complete local SDXL bundle

Use the existing complete SDXL-base LDM candidate recorded in the private review.
Its checkpoint includes UNet, VAE, and both CLIP text encoders. No separate CLIP,
VAE, or UNet weights should be acquired for this candidate. Exclude UNet-only and
specialized/distilled candidates from the first baseline.

Retain these exact required resource names:

| Resource group | Local files |
| --- | --- |
| Pipeline | `model_index.json` |
| Components | `unet/config.json`, `vae/config.json`, `text_encoder/config.json`, `text_encoder_2/config.json` |
| Scheduler | `scheduler/scheduler_config.json` |
| Each of `tokenizer/` and `tokenizer_2/` | `vocab.json`, `merges.txt`, `tokenizer_config.json`, `special_tokens_map.json` |

After approval, copy **only these 14 small resources** into a new ignored
Stoneglass-owned bundle, preserving exact bytes, and write a schema-1 manifest.
Do not depend on a user's shared Hub cache remaining populated. Do not copy the
checkpoint: reference its existing local path read-only. Do not modify the source
cache, models, ComfyUI installation, or existing environments. Check disk space
before bundle/output creation; keep machine-specific manifests out of Git.

Compute and record the full checkpoint SHA256 using cancellable chunked reads,
along with every resource's size/hash. A locally computed digest detects later
changes; it does not establish publisher authenticity or settle model licensing.
Retain provenance separately and resolve the candidate's exact license/use terms
before the real-model test. No weights or cached third-party resources are proposed
for source publication or redistribution.

Run existing local-path, resident-file, byte-size, SHA256, safetensors layout,
pipeline/component/configuration, BPE, and custom-code rejection checks. Aggregate
all missing-resource names for the readiness UI instead of exposing only the first
failure. Existing strict validation remains the final gate. Revalidate inside the
worker under read leases immediately before model loading. No remote identifiers,
URLs, UNC paths, cloud placeholders, or inferred configuration acquisition paths
are accepted as inference resources.

### 3. Keep library loading explicitly local

Preserve these child-only settings before inference-library imports:

```text
HF_HUB_OFFLINE=1
TRANSFORMERS_OFFLINE=1
HF_HUB_DISABLE_TELEMETRY=1
DO_NOT_TRACK=1
HF_HUB_DISABLE_IMPLICIT_TOKEN=1
HF_HUB_DISABLE_XET=1
TOKENIZERS_PARALLELISM=false
```

Use owned `HF_HOME`, `HF_HUB_CACHE`, `XDG_CACHE_HOME`, `TEMP`, and `TMP`; do not
inherit credentials, proxies, `PYTHONPATH`, or experimental GPU flags. Do not let
inference invoke pip, download helpers, installers, or a prerequisite resolver.

The installed Diffusers 0.40.0 `loaders/single_file.py` contains a missing-config
fallback that retries with `local_files_only=False` (lines 430-448). An existing
explicit local config directory takes a separate branch (lines 468 onward).
`single_file_utils.py` also has a URL-based original-config `requests.get` branch.
The adapter must supply the validated absolute checkpoint **and** complete local
config directory, `local_files_only=True`, `token=False`, `use_safetensors=True`,
and `add_watermarker=False`. Reject missing resources before calling the loader;
never retry with inferred Hub IDs, remote original-config URLs, or online mode.

The installed Hub 1.30.0 request hook raises `OfflineModeIsEnabled` before its
HTTP transport when offline mode is enabled. This is library-specific behavior,
not protection for every HTTP client or native extension. Tests must exercise
negative paths with transport/download functions instrumented to fail on use,
including a missing-config case and an empty owned cache. Re-review these pinned
source paths if versions change; do not modify third-party installed code.

References: [Hub environment settings](https://huggingface.co/docs/huggingface_hub/package_reference/environment_variables)
and [Diffusers single-file loading](https://huggingface.co/docs/diffusers/api/loaders/single_file).
Installed source, rather than newer online examples, controls this version review.

### 4. Separate missing-requirement consent from inference

Add a Qt-free readiness report to the application service layer for missing or
incompatible files/dependencies. A requirement entry describes its purpose,
verified source and revision, expected size when known, integrity information,
license/provenance, destination, and whether installation is manual/executable.
Readiness checks themselves are local and never fetch a catalog or contact a Hub.

The UI presents one grouped notification per selection, with **No** and
**Download** for requirements that have verified acquisition entries. Show the
exact items, sources, known sizes (or "unknown"), and destinations before consent.
No closes the dialog and performs no downloads; the model remains unavailable.
Do not repeat the prompt on every progress event or page change.

Download runs a separate, cancellable application download task, never inside the
inference worker. Approve only the displayed items; no additional resolver-selected
files, silent online fallback, or background update checks. Show progress, use
owned temporary files, verify against trusted expected integrity values before
atomic installation, and recheck local readiness afterward. Validate destinations
and sources/redirects against the reviewed acquisition record. Preserve usable
existing files on errors or cancellation.

If an item has no verified source/integrity record, identify it and offer manual
installation; do not invent URLs or provide an active unverified Download action.
Unknown sizes must be stated explicitly. Offline download failure offers retry
later or manual files, and never blocks launch or existing ready models. Executable
dependencies/installers require a separate explicit execution step; clicking
Download must not silently run them or modify the working ROCm environment.

All resources for the first candidate are already available locally, so this
download workflow need not delay the first developer-only inference test. Its
implementation can follow that milestone; missing requirements must still be
reported accurately and must prevent loading in the meantime.

### 5. Validate actual inference before normal UI activation

Implement a developer-only integration harness using the same service, launcher,
protocol, and adapter as the application. No alternate direct in-process pipeline
test counts as worker acceptance. Keep Generate disabled until actual success and
the UI integration review.

Retain FP16, batch one, eager UNet/VAE and CLIP attention, the local Euler epsilon
scheduler, VAE upcasting, no compilation/quantization/experimental fused attention,
and the current 1,048,576-pixel cap. Keep the initial RX 9060 XT/gfx1200 compatibility
check. Do not remove it to claim untested CUDA/CPU SDXL support; those remain
separate runtime profiles and later validation work.

| Stage | Procedure and acceptance evidence |
| --- | --- |
| Automated regression | All existing application tests plus revised launcher/policy tests, in offscreen and native Windows Qt. Both environments' `pip check`. Preserve sidebar, settings, branding, dimensions, and disabled Generate behavior. No dependency changes. |
| Local failures | Missing files/dependencies listed together; invalid hash, corrupt header, unsupported config/custom code, nonlocal paths fail before loader entry. No download callbacks or HTTP transports invoked; unrelated ready models/settings remain intact. |
| Worker lifecycle | Ready/close, ordered protocol, malformed/oversized frames, EOF/crash, cold startup progress, deadlines, cancellation before startup/during native stalls, owned-job cleanup, cleanup retry, and parent exit. Prompts never enter command lines/logs. |
| Model-free runtime | Final ordinary worker imports exact pinned libraries and verifies RX 9060 XT, HIP build, actual VRAM, FP32/FP16/BF16 arithmetic, math attention and convolution, and SDXL/CLIP imports. No checkpoint yet. |
| Complete preflight | Hash the real checkpoint and all 14 resources locally; validate every component's converted parameter names/shapes on the meta device before actual load. Report elapsed time and resource errors without online retries. |
| First real image | After approval, fixed benign prompt, fixed seed, batch one, 512x512, 20 steps, guidance 5.0. Record load/generation duration, peak allocated/reserved GPU memory and host memory, image dimensions/decodability, finite model outputs, visual result, output hash, unload and process cleanup. Black/invalid output or OOM is a failure, not a successful mock substitute. |
| Reliability | Repeat generation and unload/reload; cancel during load and sampling; test timeout/crash recovery and owned temporary-output removal. Increase to 1024x1024 only after the smaller run passes and memory headroom is measured. Do not auto-adjust to an experimental scheduler/backend. |
| Physically disconnected acceptance | Operator disconnects Ethernet and turns off Wi-Fi/other internet-bearing adapters using normal Windows UI before a fresh application/worker launch. With an empty owned Hub cache and complete explicit bundle, inspect local models, load, generate a real 512x512 image, unload/restart and repeat. Exercise missing-config/tokenizer/dependency errors while disconnected. Record local operator confirmation and outcomes; do not contact an external service to establish connectivity state. Restore the prior connection manually after testing. No scripted adapter/security-policy changes. |
| Consent UI | No performs zero transfers; grouped Download transfers only approved entries; unknown/untrusted sources offer manual installation; offline failure/retry, cancellation, corrupted downloads and destination failures preserve existing files. Use injected transports in automated tests, not real downloads. |
| Later application integration | Connect model selection/readiness and existing task signals to real loading/generation/cancel/output preview. Enable Generate only for a locally validated, loaded, compatible backend that passed integration testing and is idle. Keep page switching, persisted dimensions, keyboard access and both sidebar states working. |

Physical disconnection proves the tested path does not require a connection; it
does not prove that all possible third-party code paths are incapable of trying a
request. Instrumented regression tests add evidence against implicit acquisition.
Bit-for-bit identical generated images across drivers/runs are not assumed.

## Decisions and remaining blockers

1. Review this plan before changing launcher/policy/adapter/application code.
2. Confirm the privately identified complete checkpoint and its applicable
   license/provenance for the first local test. Ownership of a local file alone
   does not establish its use or redistribution terms.
3. Approve the small local-resource copy, full checkpoint hash/manifest creation,
   model-free ordinary-worker GPU validation, and first real checkpoint/image
   test as the next implementation scope. No acquisition or package installation
   is expected. If files have changed or a genuine dependency is missing, report
   it instead of installing automatically.
4. Coordinate the operator's physical network-disconnection window for acceptance;
   the application and test runner will not disable networking themselves.
5. Decide whether the optional consent/download UI is part of the next delivery or
   follows the first developer-only image. It is separate from inference either way.

The old AppContainer proof/console-startup issues are **not inference blockers**
under the revised requirements. The ordinary launcher, policy changes, full model
validation and actual generation are not implemented/verified by this plan.
Future binary distribution still needs the existing Qt/ROCm notice review; no
runtime binaries, model resources, or licensing assumptions are added to Git here.

## Preserve experimental artifacts and defer cleanup

Keep `windows_appcontainer.py`, its experimental tests, prior documents, private
reports, retained profile, and staged runtime. They must not be invoked by normal
startup or treated as inference authorization. Earlier diagnostic proposals are
historical and no longer next steps. No cleanup, profile query, elevated inspection,
or new security test is part of this plan.

For **separately approved** cleanup later: review the private prototype's exact
profile-name/SID/staging binding; confirm no owned prototype job remains without
acting on stale PIDs; review/dry-run its scoped rollback helper; remove only that
profile SID's grants on the newly staged tree; delete only the recorded development
profile; verify results and preserve evidence. The existing helper leaves staged
files in place. Any later staged-file deletion needs separate approval, verified
absolute paths inside `.local-data/offline-sandbox/`, and protection against
reparse traversal. Do not touch original environments/model ACLs, broaden
permissions, alter global policy, or automatically run rollback on launch/update.

Implementation rollback is simpler: keep the new provider opt-in and Generate
disabled, stop/reap only owned inference processes, and continue using the
unchanged `.venv` application. No uninstall, model move, Git reset, profile cleanup,
or changes to the publication checkout are required.
