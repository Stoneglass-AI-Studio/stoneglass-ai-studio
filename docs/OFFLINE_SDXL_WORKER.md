# Phase 2B.2B: offline SDXL worker foundation

> Historical phase record. Current runtime/UI behavior and accepted offline scope
> are documented in [Stage 3](STAGE3_UI.md) and [Stage 3.1](OFFLINE_UI_ACCEPTANCE.md).
> Earlier unavailable features and security gates below describe that phase only.

Status: **source foundation implemented; approved AppContainer prototype is blocked
at strict network verification**. See [prototype findings](APPCONTAINER_PROTOTYPE.md).
No real SDXL checkpoint was loaded and no image was generated. Existing environments,
drivers, global firewall rules and the publication checkout remain unchanged.
The approved prototype created one new profile and changed permissions only on
new staged resources. The existing Generate button remains disabled. A production worker
must not be launched with ordinary `subprocess.Popen` as an isolation fallback.

## Modules and application integration

| Module | Responsibility |
| --- | --- |
| `inference/resources.py` | Schema-1 manifest, local-only path policy, full SHA256/size checks, bounded safetensors headers, SDXL configuration and tokenizer preflight. No optional framework imports. |
| `inference/resource_lease.py` | Windows read handles deny concurrent file writes/replacement while the adapter validates and loads resources. |
| `inference/offline.py` | Fresh child environment, offline flags, read-only token inspection, closed authorization gate. Does not provision Windows security. |
| `inference/protocol.py` | Bounded JSON messages over inherited pipes, without pickle or network IPC. |
| `inference/worker.py` | Typed launcher/channel contracts, owned pipe transport, deadlines, progress, cancellation and retryable process cleanup. Default launcher refuses to start. |
| `inference/_offline_worker.py` | `-I -S -B -X utf8` bootstrap; guard before adding the reviewed environment's site-packages. No `.pth`/sitecustomize execution. |
| `inference/worker_server.py` | Serialized operations, independent cancellation reader, progress/error serialization, engine cleanup. |
| `inference/sdxl.py` | Lazy pinned Diffusers adapter, metadata-only complete component shape conversion, local single-file load, conservative attention/precision, sampling callbacks, owned pending output. |
| `inference/process_backend.py` | Existing provider/backend/runtime-detector interfaces backed by the owned process. Explicit service factory; no automatic registration. |

`ModelSpec.resource_manifest` is optional and appended to preserve existing
constructor calls. SDXL requires it; legacy mocked/future model contracts remain
usable. Manifest-backed specifications use the stricter path validator before
legacy path resolution could follow a remote junction.

`InferenceService` retains its operation/status locks, lifecycle and cleanup
ownership. A structural `ResourceValidatingProvider` hook checks a replacement
before the old model is released or runtime selection begins. Typed project
errors retain actionable messages; arbitrary adapter/framework exception text is
still redacted. `ResultCommitter` optionally commits staged output after the
service's final cancellation check, with no cancellation check after commitment.

The explicit developer factory is `create_sdxl_service(project, data)`. It selects
`project/.venv-rocm/Scripts/python.exe`; it neither probes nor imports frameworks
on construction. Call its operations through existing `InferenceTasks` and
`TaskManager`, never directly on the GUI thread. The normal application registry
stays empty and the proposed provider declares `generation_available=False`.
This phase does not expose model selection, new active controls or generation.

## Local manifest and validation

A manifest is local JSON, at most 128 KiB, with exactly these fields:

- `schema`: integer `1`.
- `architecture`: `sdxl-base`.
- `checkpoint`: object with absolute local `path`, positive integer `bytes`, and
  reviewed lowercase 64-character `sha256`.
- `config_directory`: absolute local directory path.
- `resources`: exactly the 14 `{path, bytes, sha256}` entries below, using the
  listed relative paths. Duplicate/missing/extra entries and traversal fail.

```text
model_index.json
unet/config.json
vae/config.json
text_encoder/config.json
text_encoder_2/config.json
scheduler/scheduler_config.json
tokenizer/vocab.json
tokenizer/merges.txt
tokenizer/tokenizer_config.json
tokenizer/special_tokens_map.json
tokenizer_2/vocab.json
tokenizer_2/merges.txt
tokenizer_2/tokenizer_config.json
tokenizer_2/special_tokens_map.json
```

All component weights must be present in the complete safetensors checkpoint;
the manifest is not a list of external text encoder or VAE downloads. Only the
original SDXL-base LDM layout is supported initially. UNet-only, refiner, LCM,
extra adapters and differently shaped architectures fail. Header checks cover
dtype/shape byte counts, offsets, contiguous payload coverage and SDXL component
markers. After OS authorization, pinned conversion helpers operate on **meta
tensors**, comparing every expected component parameter name/shape before the
single-file loader reads weights. No real meta conversion was executed here;
automated tests mock its framework components.

The first profile whitelists SDXL pipeline/component classes, Euler epsilon
prediction, expected UNet/CLIP dimensions, VAE scaling and force-upcasting, and
CLIP BPE vocabularies, merge structure and special tokens. Custom/remote code
configuration is rejected. A pinned digest detects changes relative to the
reviewed manifest; it does not authenticate a model author, establish license
rights, prove finite tensor values or certify output quality. Do not automatically
approve a manifest by hashing an arbitrary unreviewed checkpoint.

UNC paths, mapped network drives, symlinks, junctions, reparse points, cloud-only
placeholders and non-absolute paths are rejected. Put fully resident resources
on a local disk. Hashing is cancellable by chunks and reports actual byte progress.
Validation repeats in the child under read leases before model loading; the
extra reads favor correctness over startup speed. Filesystem protection is not
a defense against a malicious machine administrator replacing trusted code.

Errors identify safe resource names, for example `tokenizer_2/merges.txt`, and
state that nothing was downloaded. Private absolute paths, prompts, tokens,
dependency exception messages and tracebacks are not serialized as diagnostics.

## Offline policy and current blocker

The child receives a fresh environment, excluding inherited credentials, proxies,
PYTHONPATH, shared Hugging Face caches and experimental ROCm attention settings.
Before dependency imports it requires:

```text
HF_HUB_OFFLINE=1
TRANSFORMERS_OFFLINE=1
HF_HUB_DISABLE_TELEMETRY=1
DO_NOT_TRACK=1
HF_HUB_DISABLE_IMPLICIT_TOKEN=1
HF_HUB_DISABLE_XET=1
```

Cache/temp directories are owned local worker directories, not the reference
application's data. The loader gets the validated local configuration directory,
`local_files_only=True`, `token=False` and safetensors explicitly. None of these
switches is an OS security boundary. The reviewed Diffusers version contains a
configuration fallback overriding local-only loading; complete preflight and
independent OS enforcement are both required. See the
[upstream single-file loader](https://github.com/huggingface/diffusers/blob/v0.40.0/src/diffusers/loaders/single_file.py).

`require_verified_isolation()` currently **always refuses authorization**.
`UnavailableLauncher` refuses before process creation. The actual `.venv-rocm`
entrypoint was tested without isolation: it returned `isolation_unavailable`
before PyTorch/Diffusers/Transformers imports. This is a negative safety check,
**not a successful test of an OS sandbox or blocked network traffic**. Read-only
AppContainer token inspection never authorizes execution. There is no bypass CLI
flag, environment variable, allow-network mode or download command.

Microsoft documents AppContainer as a per-process isolation option; launching it
requires a profile and explicit access setup. See
[AppContainer isolation](https://learn.microsoft.com/en-us/windows/win32/secauthz/appcontainer-isolation)
and [launching an AppContainer](https://learn.microsoft.com/en-us/windows/win32/secauthz/implementing-an-appcontainer).
A shared Python executable firewall rule would be insufficiently scoped and may
affect other applications. No firewall rule or other security-policy change was
attempted. Experimental Windows sandbox APIs are not a reviewed compatibility
foundation for this implementation.

### Security prototype scope — approved; findings recorded separately

The user approved this scope. The staged/profile prototype was executed without
GPU imports; its network evidence gate did not pass. The list below records the
approved design, not a claim that all validation steps succeeded. See
[the results and remaining diagnostic-access blocker](APPCONTAINER_PROTOTYPE.md).

1. Check fresh disk headroom and stage a **separate private runtime copy** under
   the development checkout's ignored `.local-data/offline-sandbox/` directory,
   using the reviewed interpreter/libraries and hashes. Use a separate source
   copy for the worker. Preserve existing environments' bytes **and ACLs**;
   recheck artifact licenses before any later redistribution. No models are
   needed for this prototype and none should be copied or loaded.
2. Create one uniquely named per-user `Stoneglass.OfflineInference.Dev.*`
   AppContainer profile with **zero network capabilities**. Grant only that
   profile SID read/execute on staged runtime/code and write access to its new
   cache/temp/output directories. Do not grant broad user/profile/network access,
   alter existing environment permissions, add loopback exemptions, change global
   firewall profiles or touch another application's configuration.
3. Implement the native launcher contract: create suspended with the intended
   security capabilities, restrict children, assign an owned kill-on-close job,
   inherit only IPC handles, inspect the actual process image/token/capabilities,
   reject applicable loopback exemptions and verify required OS services/policy
   before resuming. The worker independently verifies the same boundary before
   importing libraries. Unknown/failed checks must refuse execution.
4. Prove denial for IPv4/IPv6 TCP, UDP, DNS, native Winsock/WinHTTP and loopback
   against controlled test endpoints. Require OS access-denial evidence, not
   merely timeouts/unreachable hosts. Check no outbound traffic or child escape,
   and confirm an ordinary independent test process remains unaffected. These
   checks must use no model and must not start/contact the reference application.
5. Only after successful isolation tests, run the approved model-free GPU/import
   probes in the container. AppContainer compatibility with this AMD driver,
   PyTorch and native cache initialization is **unverified**. If it needs broader
   permissions, fail closed and request a separately scoped review.

Approval would cover the new per-app profile and ACLs on **new staged files only**.
It would not authorize global firewall changes, permissions on existing virtual
environments, checkpoint loading or generation. Record the exact created profile,
SIDs and grants privately. Rollback design: stop only owned processes, remove only
that profile/grants, and leave staged files for review. Do not delete original
files, rewrite history or make broad security changes.

## Execution, cancellation and output ownership

The existing Qt worker runs service/client methods; the future sealed child owns
all GPU/model work. Default startup deadline is 30 s, runtime probe 180 s, model
load and generation 900 s each. Hash progress is measured; slow import/load/native
initialization reports stage messages and waiting heartbeats without fabricated
sampling progress. A real pipeline callback reports actual sampling steps.

Cancellation travels over the control pipe to a separate reader, allowing checks
between stages and sampling steps. Native GPU calls can remain uninterruptible:
after a 3 s cancellation grace, the launcher must terminate/reap the owned job.
Timeouts, broken/malformed messages and errors also close the job. Cleanup cannot
be skipped by cancellation; failed process/pipe cleanup retains ownership for retry.

The adapter uses explicit ROCm device scopes, FP16 UNet/text encoders, preserved
VAE upcasting, eager attention, batch one and at most 1,048,576 pixels. It does
not enable compilation, quantization, experimental fused attention or specialized
schedulers. The first hardware/dependency profile is intentionally RX 9060 XT /
gfx1200 and the versions validated in Phase 2B.2A. CUDA/CPU need separate reviewed
profiles; the existing runtime enums/contracts remain available for them.

Future image output stays in a per-worker run directory until service commitment.
After the final cancellation check, the parent atomically moves it to its final
local destination. It removes only owned pending `.tmp`/`.png` files after process
termination; unexpected files are preserved with an actionable cleanup error.
Committed output is not undone by late cancellation. This path is tested with
plain-text ownership fixtures and mocked pipelines, not generated images.

Any user-initiated model acquisition must be a separate explicit service/process,
with separate network authorization, licensing and local bundle promotion. The
inference protocol has no download operation and must never invoke that service.

## Verification and exact remaining steps

Tests cover manifest/hashes, malformed headers/JSON, nonlocal/cloud paths, class
and tokenizer policy, read-lease sharing, mocked complete component shapes,
explicit loader options, default denial, actual denial entrypoint, bounded IPC,
progress, error redaction, cancellation, deadlines, retryable cleanup, replacement
preflight, pending output commitment and the original UI behavior. Full validation
passed **126/126 tests in offscreen Qt and 126/126 in native Windows Qt** using
the approved ROCm interpreter. Both `.venv-rocm` and the original `.venv` pass
`pip check`. Results are recorded in ignored `.test-artifacts/phase2b2b/`; no GPU/model is
required for these tests. There is no positive OS-isolation or real SDXL result.

Before a first real generation:

1. Approve and implement the scoped security prototype above, then pass native
   isolation, child restriction and model-free GPU/library checks.
2. Confirm exact model-version/config/tokenizer licensing and approve the chosen
   complete checkpoint. Review an immutable local bundle and its full hash-pinned
   manifest. Separately approve any model access grants or staging copies needed
   by the sandbox; do not weaken sandbox access automatically.
3. Obtain explicit approval for **real model loading and generation**. Validate
   strict component conversion, loader behavior, VAE upcasting and memory with
   that checkpoint inside the sealed worker. Current tests cannot certify these.
4. Run batch one, 512x512, fixed seed first with conservative Euler settings;
   inspect actual pixels, output integrity, memory, cancellation/unload and
   interrupted-output cleanup. Only then assess 1024x1024.
5. Enable the provider's generation capability and wire model selection/Generate
   only after those checks and a reviewed UI activation change. Keep unavailable
   features visibly unavailable until then.
