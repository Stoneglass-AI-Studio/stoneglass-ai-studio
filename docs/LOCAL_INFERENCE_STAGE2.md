# Stage 2: first real local SDXL image

> Historical phase record. Current runtime/UI behavior and accepted offline scope
> are documented in [Stage 3](STAGE3_UI.md) and [Stage 3.1](OFFLINE_UI_ACCEPTANCE.md).
> Earlier unavailable features and security gates below describe that phase only.

Developer-only integration testing has produced a real SDXL image through the
production ordinary-user worker and the existing `.venv-rocm`. Generate remains
disabled, the normal UI has no registered inference provider, and no dependencies,
drivers, model weights, original resources, or publication checkout were changed.
This work does not activate a normal generation UI or a model-download service.

## Original model provenance and terms

Model: [AlbedoBase XL v3.1-Large](https://civitai.com/models/140737?modelVersionId=1041855).
Creator: [albedobond](https://civitai.com/user/albedobond).
License: [original version-specific terms](https://civitai.com/models/license/1041855).

The original Civitai model/version APIs confirm model 140737, version 1041855,
the publisher, SDXL 1.0 base, publication on November 11, 2024, and the exact file
SHA256. The original license page was retrieved and reviewed, rather than relying
only on the mirror's OpenRAIL++ label. It contains CreativeML Open RAIL++-M terms,
use restrictions and additional creator-credit and model/merge sale restrictions.
No explicit restriction prohibiting the benign private test was found; required
credit is retained in the local report and image presentation. This is not a claim
of unrestricted use or permission to redistribute/sell weights. Model terms remain
distinct from Stoneglass GPL source licensing.

The existing checkpoint and complete 14-resource bundle were used unchanged.
No weights were copied, relocated, downloaded or redistributed. Public-source
metadata snapshots, machine paths and full integrity evidence remain ignored in
the local Stage 2 audit directory. The generated images are ignored local output,
not repository branding or published assets.

## Complete pre-load component validation

All checkpoint/configuration integrity checks ran before conversion and before
loading weights. The conversion used meta-device tensors, with exact parameter
name/shape/dtype checks against all four configured component models:

| Component | Expected/converted parameter tensors | Result |
| --- | --- | --- |
| UNet | 1,680 / 1,680 | All match |
| VAE | 248 / 248 | All match |
| CLIP-L | 196 / 196 | All match |
| CLIP-G | 517 / 517 | All match |

Every converted tensor was floating point and on the meta device. There were no
missing, unexpected or mismatched parameter shapes in the successful check.
Standalone component validation ran through the production worker, loaded no
weights, and exited normally. The adapter repeated this validation during load.

The initial validation correctly blocked a naming mismatch: Transformers 5's
CLIP-L class has flattened parameter names. The pinned Diffusers loader already
normalizes the legacy `text_model.` prefix for that class. Stoneglass's validator
was corrected to use the same conditional normalization; it still rejects extra
or missing parameters. A regression test covers that normalization and strict
rejection. No dependency, configuration, architecture, or model change was needed.

## First image and measurements

Exact requested parameters: 512x512, one image, 20 steps, CFG 5.0, seed 12345,
empty negative prompt, and:

> A photorealistic red sports car parked beside a mountain lake at sunset.

The developer harness calls the existing `SDXLProcessBackend`; pipeline loading
and generation execute in the production worker, not in the harness process.
The normal provider's generation capability stays unavailable. The first PNG was
atomically committed under
`.local-data/local-inference-stage2/first/generated/`. Its exact filename/path and
SHA256 are in the private report. Qt decoded it as 512x512 RGB content; it was
nonuniform, visually inspected, and shown in chat.

| Measurement | First run |
| --- | --- |
| Backend load wall time | 39.907 seconds, including preflight/startup |
| Weight loading through GPU readiness | 13.263 seconds |
| Generation through image decoding | 152.495 seconds, excluding final PNG persistence |
| Generation wall time including output handling | 152.714 seconds |
| Peak Torch GPU allocation during generation | 10,452,637,184 bytes / 9.735 GiB |
| Peak Torch GPU reservation during generation | 11,047,796,736 bytes / 10.289 GiB |
| Worker lifetime peak resident working set | 7,616,180,224 bytes / 7.093 GiB |
| Worker lifetime peak commit | 15,076,970,496 bytes / 14.042 GiB |
| Saved PNG | 512x512, 391,610 bytes, valid Qt decode |
| Normal worker exit | 0 |

Host peaks come from Windows process counters and cover the worker's lifetime;
they are not generation-only RAM deltas. GPU figures are PyTorch allocator
counters, not complete system-wide VRAM including desktop/driver allocations.
Observed Windows ROCm startup, first sampling and VAE decode latency varies
substantially between worker launches; these timings are not steady-state promises.

Conservative FP16, eager attention, VAE upcasting, the existing local Euler
scheduler, and batch one were retained. No experimental fused attention,
compilation, quantization, CPU offload or untested optimization was enabled.
The harness parent imported no Torch/Diffusers/Transformers.

## Cleanup, cancellation and limitations

The first normal backend unload closed the production worker with exit 0 and
reaped its owned job; the private run directory was removed and the committed
image was preserved. Cancellation during actual weight loading and after the
first sampling step both stopped their owned jobs and removed temporary run
directories. Expected forced termination uses Windows exit code 1223; it is not
reported as a normal exit or a generated image. A fresh worker then reloaded and
completed the same image request, unloaded, and exited normally with code 0.
The fixed-seed recovery image was valid but not pixel-identical: mean absolute
channel difference was about 0.80 on the 0-255 scale. Bitwise determinism is not
certified; no unreviewed optimization or determinism setting was introduced.

An important distinction: adapter-only unload reported approximately 1.37 GiB of
Torch allocation and 1.50 GiB reserved before process exit. Therefore a live
persistent worker's allocator cleanup is **not certified as zero**. The existing
backend lifecycle closes the worker on unload, and its job cleanup verifies no
owned processes remain. Investigate retained in-process references before offering
persistent-worker model swapping or treating `empty_cache()` as complete cleanup.
No dependency/architecture change was made to hide those measurements.

New diagnostic operations and local counter helpers provide component results,
load/generation timing, and GPU/host memory without serializing prompts, model
paths or weights in diagnostic responses. The fixed public test prompt is
intentionally documented by the developer harness; normal prompt persistence and
logging behavior are unchanged.

All **161 automated tests passed** in each of offscreen/native Windows Qt modes
in both `.venv` and `.venv-rocm` (four full runs). Both `pip check` runs passed.
The added coverage checks actual Windows counter sampling and strict CLIP prefix
normalization; existing UI/branding/settings/worker tests remain included.

## Physically disconnected acceptance remains pending

No network adapter, firewall, profile, audit or tracing configuration was changed.
Inference used complete local resources and existing offline-library settings;
no inference download operation or online fallback was added. Publisher research
used separate ordinary metadata requests, outside the inference worker.

The [standalone PowerShell procedure](OFFLINE_ACCEPTANCE.md) now provides the
canonical operator launcher, replacing the earlier private Stage 2 harness
instructions. Each run has a fresh worker, empty owned Hub cache and unique
evidence/output directory under `.test-artifacts/offline-acceptance/`. The operator
physically disconnects Ethernet and turns off other internet connections, runs
the launcher independently of Codex, then reconnects manually for evidence review.
The old Stage 2 artifacts remain historical records. No disconnected test has run
yet, and connected-state success is not presented as physical-disconnection
acceptance.

Stop for review before normal UI activation. Next decisions are the operator's
offline test window and follow-up investigation of live-worker unload retention.
Keep the existing experimental AppContainer/security artifacts untouched; no
further security experimentation or automatic cleanup is part of this stage.
