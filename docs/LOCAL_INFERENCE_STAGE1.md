# Local inference implementation: Stage 1

> Historical phase record. Current runtime/UI behavior and accepted offline scope
> are documented in [Stage 3](STAGE3_UI.md) and [Stage 3.1](OFFLINE_UI_ACCEPTANCE.md).
> Earlier unavailable features and security gates below describe that phase only.

Stage 1 implements the approved ordinary-user Windows worker and local-resource
preparation. It does **not** load SDXL weights, generate images, download files,
enable Generate, or install/change dependencies. The normal application still has
an empty provider registry. These development changes have not been committed or
pushed to the separate publication checkout.

This replaces mandatory isolation authorization in normal inference, following
the [approved revised roadmap](OFFLINE_INFERENCE_IMPLEMENTATION_PLAN.md). The
AppContainer prototype and its diagnostic artifacts remain untouched experimental
history. Normal startup does not inspect or provision AppContainer profiles, WFP,
auditing, tracing, capabilities, firewall policy, or ACLs. No elevation is needed.

## Modules and ownership

| Module | Responsibility |
| --- | --- |
| `inference/local_process.py` | Create an ordinary-user process suspended, attach a kill-on-close job before resuming, inherit only three IPC handles, and own/reap that job tree. No token or network sandbox. |
| `inference/worker.py` | Default local launcher, owned directory setup, bounded queues/JSON frames, complete pipe writes, progress, deadlines, cooperative close, cancellation, termination and retryable cleanup. |
| `inference/pipe_input.py` | Bounded `PeekNamedPipe` polling and short `ReadFile` calls; interrupt idle waits on close without closing a borrowed standard handle. |
| `inference/_offline_worker.py` | Check offline settings before library imports, validate the isolated Python 3.13.12 x64 environment, configure its prefix/site path without executing `.pth` or `sitecustomize`, then serve the protocol. |
| `inference/offline.py` | Fresh child environment, pre-import checks and ongoing offline-flag checks. Historical isolation helpers remain unused by normal inference. |
| `inference/worker_server.py` | Serialized operations with independent cancellation input; explicit model-free validation operation, safe error responses and cleanup. |
| `inference/runtime_validation.py` | Small actual GPU arithmetic, attention and convolution checks plus SDXL/CLIP/supporting imports. No model construction or weight loading. |
| `inference/bundle.py` | Prepare a new hash-pinned local config/tokenizer bundle from reviewed resources; hash/reference the checkpoint without copying or loading its tensors. |
| Existing `process_backend.py` and `sdxl.py` | Preserve service/provider integration, leases and complete resource checks; replace isolation authorization with offline-library policy checks. Generation capability remains unavailable. |

The launcher owns actual process/job handles, not saved PIDs. Normal close permits
up to two seconds for a close reply and five seconds for native-runtime exit;
unresponsive work is terminated through the owned job. Forced cleanup checks both
the root process and the job's active-process count. Cleanup failures retain
ownership for retry. Descendants are cleaned up even if the root has already
exited. Other processes are not targeted. A parent-exit test verifies kill-on-close.

Startup/runtime/load/generation deadlines remain configurable and bounded at
30/180/900/900 seconds by default. Cancellation sends a control message, then stops
the owned worker after the configured grace period if it cannot cooperate. Long
initialization reports waiting status without resetting completed stage progress.
All this work remains off the Qt UI thread through the existing task architecture.

## Windows import and shutdown findings

Blocking background pipe input reproduced a native NumPy extension import stall
in this Windows stack. Importing the same Torch stack without that reader, or with
stream redirection alone, succeeded. A native blocking `ReadFile` also reproduced
the stall, so simply avoiding Python's buffered stdin was insufficient. The exact
native locking mechanism was not established; no driver or installed package was
changed to investigate it.

Polling for available bytes before short reads resolved the observed stall in
both the comparison probe and the actual worker. The reader also stops explicitly
at protocol shutdown, avoiding a standard-buffer lock failure at interpreter exit.
Separately, Python 3.13 `-S` omits normal virtual-environment prefix setup. The
entrypoint restores the validated environment prefix before library imports so
SDK script/DLL discovery uses that environment rather than the base interpreter.

The first successful GPU run needed longer than the initial one-second native
exit allowance and was safely terminated. With a five-second cooperative exit
allowance, the final model-free GPU worker exited normally with code 0.

## Offline behavior and resource preparation

Keep all six existing offline/privacy flags before importing libraries:
`HF_HUB_OFFLINE`, `TRANSFORMERS_OFFLINE`, `HF_HUB_DISABLE_TELEMETRY`, `DO_NOT_TRACK`,
`HF_HUB_DISABLE_IMPLICIT_TOKEN`, and `HF_HUB_DISABLE_XET`, each set to `1`.
Cache/temp paths are Stoneglass-owned. Credentials, proxies, `PYTHONPATH` and
experimental GPU flags are not inherited. Missing policy raises an actionable
`offline_policy` error; no prompt asks users to set up OS isolation.

The adapter still requires a complete validated local manifest, absolute resident
local paths, approved component configurations, byte sizes/SHA256, valid
safetensors layout, complete parameter-shape conversion checks, and read leases.
The pinned single-file loader receives the explicit local config directory,
`local_files_only=True`, `token=False`, and safetensors-only settings. There is no
download operation or online retry in Stoneglass's worker protocol.

An automated check against the installed Hub version verified that an offline
request raises before its HTTP transport and that a missing local file raises a
local-cache error. The HTTP transport was instrumented to fail on any use and was
never called. This complements resource-validation tests. It does not certify
every possible native/library code path. Library settings are **not OS-enforced
network isolation**. Actual generation with networking physically disconnected
remains a required later acceptance test. See the
[Hub offline settings](https://huggingface.co/docs/huggingface_hub/package_reference/environment_variables).

The ignored bundle is `.local-data/sdxl-bundles/base-initial/`, containing
`manifest.json` and exactly 14 resources under `config/`:

- Pipeline `model_index.json`.
- UNet, VAE, and both text-encoder `config.json` files.
- `scheduler/scheduler_config.json`.
- Each tokenizer's `vocab.json`, `merges.txt`, `tokenizer_config.json`, and
  `special_tokens_map.json`.

Combined configuration size: **3,176,106 bytes**. Only these small files were
copied; their original locations were not changed. The checkpoint remains at its
existing path and is referenced read-only. A full cancellable SHA256 pass was
followed by an independent full validation pass over the checkpoint and copied
resources under read leases. Both checkpoint hashes matched, and the configuration,
BPE and checkpoint-header/layout checks passed. No tensors were loaded. Machine
paths, checkpoint identity/hash, source provenance and manifest contents remain in
ignored local records, not public project assets.

## Model-free hardware results

The actual production launcher, worker entrypoint, protocol and validation
operation were used, with `.venv-rocm`; the Qt/application parent did not import
Torch, Diffusers or Transformers.

| Check | Result |
| --- | --- |
| GPU | AMD Radeon RX 9060 XT, `gfx1200` |
| Memory from PyTorch device properties | 17,095,983,104 bytes (15.922 GiB) |
| Runtime | Torch 2.13.0+rocm10.0.0, HIP 7.15.26333, CUDA build absent |
| Arithmetic and matrix multiplication | FP32, FP16 and BF16 passed; maximum error 0 |
| FP16 attention | Default versus explicit math comparison passed; maximum error 0 |
| FP16 convolution | Passed shape, finiteness and value checks; maximum error 0 |
| Imports | SDXL/single-file loader, CLIP tokenizer and both text classes, Diffusers, Transformers, Accelerate, Safetensors and Torchvision passed |
| Final worker validation | 92.599 seconds; normal exit code 0; no checkpoint loaded/image generated |

These are small model-free checks, not evidence of complete SDXL memory capacity,
image quality, real-load cancellation, or all Windows/AMD driver combinations.
The initial adapter still accepts only its reviewed RX 9060 XT ROCm profile.
Future NVIDIA and CPU profiles need separate validation; no mixed GPU stack was
installed.

## Verification and remaining approval

Automated coverage includes native startup/normal close, parent-exit and descendant
cleanup, suspended-launch failure, retained ownership on cleanup failure, bounded
input/short writes, offline admission, Hub offline behavior, local bundle copying,
changed hashes, disk exhaustion, cancellation, and preservation of existing bundles.
All existing application and experimental unit tests remain in the suite. Tests
never provision profiles, change permissions or run models. **158 tests passed in
each of offscreen and native Windows Qt modes, in both `.venv` and `.venv-rocm`**
(four full runs). Both environments passed `pip check`. Exact logs and preservation
results are recorded in the private Stage 1 report.

Remaining steps require review before execution:

1. Confirm the exact checkpoint's original publisher provenance and applicable
   model-specific terms. The local SHA matches a published mirror file; that alone
   does not establish the original publisher's complete terms. Model/configuration
   licenses remain separate from Stoneglass GPL source licensing; no model or
   dependency binaries are proposed for redistribution here.
2. Approve metadata-only complete component-conversion checks and the first actual
   checkpoint load through this same worker, then a conservative batch-one
   512x512 SDXL image test with memory, cancellation, cleanup and output checks.
3. Coordinate a physically disconnected fresh-launch/load/generation test with
   the operator. No networking changes were made in Stage 1.
4. Review later UI integration and optional consent/download service separately.
   Generate remains disabled and no download UI is presented as implemented.

Existing Qt/ROCm binary redistribution notice questions remain separate future
packaging work. AppContainer cleanup, including any staged-file removal, still
requires its own approval and was not performed.
