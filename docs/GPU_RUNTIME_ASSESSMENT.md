# Phase 2B.1: GPU runtime and dependency assessment

> Historical phase record. Current runtime/UI behavior and accepted offline scope
> are documented in [Stage 3](STAGE3_UI.md) and [Stage 3.1](OFFLINE_UI_ACCEPTANCE.md).
> Earlier unavailable features and security gates below describe that phase only.

Assessment date: 2026-11-06. **Assessment only; installation and backend
implementation require approval.** No dependency, model, driver, firewall rule,
application source or publication checkout was changed. No model was loaded and
no image was generated. All commands below are a proposed future procedure,
not a record of executed installations.

## Recommendation

Create a separate `.venv-rocm` using **CPython 3.13.12 x64** and the AMD Windows
ROCm 10.0.0 / PyTorch 2.13.0 `gfx1200` package family. Keep the current `.venv`
unchanged for development and rollback. Use AMD's official wheel index and
reviewed hashes rather than copying another application's virtual environment.
Do not upgrade to a newer ROCm/PyTorch release merely because it exists.

This is a candidate stack supported by local tensor and import checks, not a
completed SDXL pipeline certification. The proposed smaller dependency closure
has not been installed or validated as a fresh environment. First complete that
validation, local-resource preflight and strict offline enforcement, then obtain
approval for actual model loading/generation implementation.

The reference application was used only for installed library metadata and local
resources. Its server was not started or contacted; its source, requirements,
virtual environment and model files were not copied into Stoneglass. Stoneglass
will continue to use its own Python engine.

## Observed environments

Stoneglass uses Python 3.13.12 x64, PySide6-Essentials 6.12.0 and Shiboken6 6.12.0.
`pyproject.toml` requires Python >=3.11 and declares only PySide6 Essentials as a
runtime dependency. No PyTorch, Diffusers, Transformers, Accelerate, Safetensors,
NumPy or Pillow is installed in its `.venv`. Its `pip check` passes.

The read-only reference also uses Python 3.13.12 x64. Its `pip check` passes:

| Component | Reference version | Proposed first ROCm profile |
| --- | --- | --- |
| PyTorch | 2.13.0+rocm10.0.0 | Same, with `device-gfx1200` extra |
| Torchvision | 0.28.0+rocm10.0.0 | Same, matching target device extra |
| ROCm core/libraries/device packages | 10.0.0 | Same, `gfx1200` only |
| ROCm bootstrap | 0.1.0 | Same |
| `torch.version.hip` | 7.15.26333 | Observed HIP build identifier, not the ROCm package version |
| Diffusers | 0.40.0 | Same |
| Transformers | 5.16.1 | Same |
| Accelerate | 1.15.0 | Same |
| Safetensors | 0.8.0 | Same |
| Hugging Face Hub | 1.30.0 | Same; offline settings mandatory |
| Tokenizers | 0.23.2 | Same |
| NumPy / Pillow | 2.5.2 / 12.3.0 | Same |
| Torchaudio | 2.11.0.2+rocm10.0.0 | Omit; not needed for this SDXL assessment |
| SciPy / PEFT | 1.18.1 / 0.21.0 | Omit initially; revisit for a feature needing them |
| SentencePiece / Protobuf | 0.2.2 / 7.36.2 | Omit initially; CLIP uses existing BPE assets |
| xFormers / Triton | Not installed | Do not add for the first backend |
| Installer pip / setuptools | 26.2.1 / 81.0.0 | Pin candidate tooling to these versions |

Dependency metadata yielded a **55-package proposal**: ten GPU/runtime packages
and 45 common/UI packages, versus 178 packages in the reference environment.
Markers and version constraints were evaluated for Windows AMD64 / Python 3.13.
This excludes the reference application's frontend/server and unrelated extras.
The proposal is not an artifact hash lock or a license certification.

AMD documents this targeted PyTorch/Torchvision family and `gfx1200` extras in its
[PyTorch installation guide](https://rocm.docs.amd.com/projects/ai-ecosystem/en/latest/frameworks/pytorch/install.html).
ROCm runtime, library and device packages are separate; do not omit the device
kernels. See [ROCm 10 installation](https://rocm.docs.amd.com/en/docs-10.0.0/install/rocm.html).

## GPU and library checks actually performed

Windows reports AMD Radeon RX 9060 XT, driver **32.0.32015.7029**, on Windows 11
build 26200. The reference PyTorch detects **gfx1200**, HIP 7.15.26333, no CUDA
build, and **17,095,983,104 bytes / 15.922 GiB** total device memory. This memory
value came from PyTorch device properties, not Windows' unreliable inventory
memory field. HIP's CUDA-named API is not evidence of an NVIDIA device.

- Float32, float16 and bfloat16 matrix multiplication: passed, exact expected output.
- Float16 default and explicit math SDPA attention: passed, maximum difference 0.
- Float16 convolution: passed, expected output shape and values.
- SDXL pipeline, single-file loader, both CLIP text classes, CLIP tokenizer,
  Accelerate, Safetensors and Torchvision imports: passed offline, without models.
- Stoneglass's existing isolated probe executed by the reference interpreter:
  CPU and ROCm validated, no diagnostics, approximately 3.24 seconds.

An initial combined check timed out after 60 seconds. Stage-marked checks then
completed successfully: arithmetic took about 14 seconds; attention plus
convolution took about 109 seconds, including about 93 seconds in convolution.
The pipeline import alone took about 56 seconds. These timings are observations,
not steady-state benchmarks. Native runtimes can initialize user caches. Python
bytecode writing was disabled. No package/app/model files were intentionally
written. No reference application process was launched.

PyTorch warned that fused flash/memory-efficient attention on this GPU remains
experimental. The experimental environment switch was not enabled; the baseline
must not depend on it. Keep conservative attention until separately validated.
Basic kernels do not prove full UNet/VAE correctness, model memory fit or output
quality. Loading and cold initialization need worker execution, truthful progress,
cooperative cancellation and timeouts distinct from the short capability probe.

## Local checkpoints and direct Diffusers loading

Five safetensors files were found in the requested reference checkpoints folder.
Only headers were read. Tensor offsets, dtype/shape byte counts and file sizes
were consistent; full file hashes and tensor values were not validated.

The strongest first-test candidate is **`albedobaseXL_v31Large.safetensors`**:
6,938,040,682 bytes (6.462 GiB), 2,515 float16 tensors, SDXL base-shaped UNet,
CLIP-L, CLIP-G and VAE. Its conditioning dimensions match the cached base SDXL
configuration. Filename identity alone does not establish training provenance or
license terms. No license sidecar or license metadata key was found; the exact
model/version terms still need confirmation before its approved use or sharing.

Two other files have complete SDXL-shaped components but names suggesting
specialized distilled variants. DMD/DMD2 is not interchangeable with LCM; their
model-specific scheduler/settings require validation. Two files are UNet-only,
one with Diffusers-style keys and one with original LDM keys. Neither is a
complete standalone SDXL pipeline checkpoint. The private inventory contains all
filenames and component findings; do not select a model from its name alone.

Diffusers supports SDXL single-file loading. A compatible complete checkpoint
can be converted into pipeline components **in memory**, without rewriting it or
creating a second on-disk Diffusers model. An on-disk conversion is optional and
would require separate approval. A UNet-only state dictionary additionally needs
explicitly supplied text encoders, VAE, tokenizers and compatible configurations.
See [single-file loader documentation](https://huggingface.co/docs/diffusers/api/loaders/single_file).

A cached SDXL base snapshot already contains all 14 reviewed required resources:
pipeline index, UNet/VAE/two text encoder configs, scheduler config, and both
tokenizers' vocabulary, merges, tokenizer config and special-token map. Its
architecture is consistent with SDXL base: context 2048, CLIP widths 768/1280,
VAE scaling 0.13025, force-upcast enabled, Euler scheduler. Exact cache paths,
revision and file hashes are in ignored local evidence. No assets were copied.
Future use must validate them with the selected checkpoint and review their terms.

For a later approved loader, the API shape is:

```python
# Illustrative only: inside a verified offline worker, after resource preflight.
pipeline = StableDiffusionXLPipeline.from_single_file(
    local_checkpoint_path,
    config=validated_local_sdxl_config_directory,
    local_files_only=True,
    dtype=torch.float16,
    token=False,
)
```

This call does not itself enforce the offline policy. Do not infer a Hub repo ID,
fetch an original YAML, or enable downloads to repair a failed load. Preserve
the VAE configuration's upcasting behavior initially; do not copy application
launcher flags forcing a half-precision VAE without model-level validation.

## Strict offline inference: mandatory acceptance gate

Inspection of installed `diffusers/loaders/single_file.py` 0.40.0, around lines
430–448, found a fallback that retries configuration retrieval with
`local_files_only=False` when configs are missing. Therefore the flag alone is
insufficient. No such loading call was executed during this assessment. See also
the [upstream loader source](https://github.com/huggingface/diffusers/blob/v0.40.0/src/diffusers/loaders/single_file.py).

Before enabling a real backend:

1. Require an explicit, validated local resource manifest. Resolve paths and
   symlinks; reject URLs, Hub IDs, UNC shares and network-mounted resources.
   Whitelist pipeline/component classes; disable custom/remote code. Check
   checkpoint architecture, all component weights, tokenizer data and configuration
   consistency before invoking library loaders. Keep safetensors as the first
   supported format; do not add pickle checkpoint loading as an implicit fallback.
2. Pass a complete local config directory and local components explicitly. Give
   actionable relative missing-file errors before loading. Example: `Missing local
   SDXL resource: tokenizer_2/merges.txt. Select a complete configuration bundle.
   Nothing was downloaded.` Never suggest automatically retrying online.
3. Set process-local offline settings **before importing** inference libraries:

   ```powershell
   $env:HF_HUB_OFFLINE = '1'
   $env:TRANSFORMERS_OFFLINE = '1'
   $env:HF_HUB_DISABLE_TELEMETRY = '1'
   $env:DO_NOT_TRACK = '1'
   $env:HF_HUB_DISABLE_IMPLICIT_TOKEN = '1'
   $env:HF_HUB_DISABLE_XET = '1'
   ```

   Use Stoneglass-owned local cache paths, not an implicit shared user cache, in
   production. Do not persist these settings globally or change the reference
   environment. These switches constrain participating libraries; they are not
   a general networking security boundary. Hub offline mode does not govern
   arbitrary HTTP clients or native code. See [Hub settings](https://huggingface.co/docs/huggingface_hub/package_reference/environment_variables).
4. Establish and verify an OS-enforced no-network boundary for inference, including
   native transports and any allowed children. Prefer a dedicated inference
   worker process with local pipes and a restricted network policy; retain the
   existing Qt task manager for orchestration. Ordinary threads are not a network
   isolation boundary. A Python socket patch is useful in tests but cannot contain
   native transports. If policy establishment fails, fail closed before loading.
5. Windows program firewall rules require the actual executable path. A venv
   launcher/shared base Python can make a guessed per-venv rule insufficient or
   accidentally affect other applications. Confirm process images and policy
   coverage first; do not block the shared interpreter used by the reference app.
   A dedicated host executable or tested sandbox policy needs a separate design
   and approval. No firewall changes were made here. See [Microsoft's program-rule
   documentation](https://learn.microsoft.com/en-us/powershell/module/netsecurity/new-netfirewallrule?view=windowsdefender).
6. Test complete and incomplete resource sets with an empty unrelated cache,
   network-attempt traps and verified OS isolation. Cover missing configs,
   tokenizers, corrupt headers, cancelled loading, native transport paths and
   readable errors. Confirm no implicit connection attempts on normal inference
   paths and no outbound traffic. Environment flags alone do not pass this gate.

The existing `ModelSpec` needs a validated config/resource reference at the
adapter boundary; its checkpoint path alone is insufficient. An isolated worker
adapter can preserve the current service/provider interfaces. This assessment
does not implement or certify that boundary. Generation stays disabled until it
is implemented and tested.

Any future download feature must be a separate, explicitly invoked service/process
with separately granted network access, license/integrity review and atomic
promotion of a validated local bundle. The inference engine must never invoke it,
borrow its network access, or use an online endpoint as a fallback.

## Windows, storage and licensing risks

Use the exact native Windows CPU ABI and AMD target wheels. Standard PyPI CPU or
NVIDIA wheels cannot substitute for the HIP build. Prevent later dependency
resolution from replacing it. The observed Windows driver is functional for the
checks above but has not been matched to AMD's certified marketing release; a
successful smoke test is not vendor certification. Do not change drivers or a
system-wide ROCm/PATH installation. Consult the [versioned compatibility matrix](https://rocm.docs.amd.com/en/docs-10.0.0/compatibility/compatibility-matrix.html)
before a later change.

The project and reference volumes had about 22.40 GiB and 48.47 GiB free at assessment time. The reference GPU
package payload alone is about 4.01 GiB, excluding common dependencies, wheel
archives, temporary extraction, runtime caches and pagefile pressure. Check actual
download/resolution sizes and keep headroom. Reuse local checkpoints in place;
do not copy multi-gigabyte weights into the source tree or virtual environment.

Diffusers, Transformers and Safetensors have upstream Apache-2.0 license texts;
Apache-2.0 is compatible with GPLv3, with its notices preserved. This does not
certify every bundled dependency. Installed PyTorch metadata lists several
permissive component licenses. Several ROCm/device wheels have absent license
metadata and sparse packaged notices; obtain exact component notices/source
locations before redistributing their binaries. The existing Qt binary notice
review also remains open. See [Apache/GPL compatibility](https://www.apache.org/licenses/GPL-compatibility.html),
[Diffusers license](https://github.com/huggingface/diffusers/blob/v0.40.0/LICENSE),
[Transformers license](https://github.com/huggingface/transformers/blob/v5.16.1/LICENSE),
[Safetensors license](https://github.com/safetensors/safetensors/blob/v0.8.0/LICENSE),
and [ROCm component licensing](https://rocm.docs.amd.com/en/latest/about/license.html).

Model/configuration/tokenizer rights are separate from the application's GPL.
The base SDXL model uses CreativeML Open RAIL++-M, with use-based conditions;
fine-tunes can have additional terms. Local possession and safetensors format
do not grant redistribution rights. Do not bundle these weights in GitHub or a
release. See the [SDXL base license](https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/blob/main/LICENSE.md).

## Proposed PowerShell installation and validation plan — not executed

After approval, use a fresh candidate and reviewed, hash-locked wheels. The local
proposal inputs below were generated only from dependency metadata, not installed
into Stoneglass. They are ignored machine-assessment artifacts; promote reviewed
platform profiles into source control only in a later approved dependency change.
Abort on any command failure; never continue by upgrading packages ad hoc.

```powershell
# Run from your Stoneglass checkout root.
$ErrorActionPreference = 'Stop'
$env:PIP_NO_INPUT = '1'
$env:PIP_DISABLE_PIP_VERSION_CHECK = '1'
$assessment = Join-Path $PWD '.test-artifacts\phase2b1'
$candidate = Join-Path $PWD '.venv-rocm'
$wheelhouse = Join-Path $assessment 'wheelhouse-rocm-2.13.0'
if (Test-Path -LiteralPath $candidate) { throw 'Candidate already exists; review it first.' }
if (Test-Path -LiteralPath $wheelhouse) { throw 'Wheelhouse already exists; review it first.' }
Get-PSDrive -Name D,F
py -3.13 -c "import sys; assert sys.version_info[:3] == (3,13,12)"
if ($LASTEXITCODE) { throw 'Python does not match the assessed interpreter.' }
py -3.13 -m venv $candidate
if ($LASTEXITCODE) { throw 'Could not create candidate environment.' }
$candidatePython = Join-Path $candidate 'Scripts\python.exe'
& $candidatePython -m pip install --index-url https://pypi.org/simple 'pip==26.2.1' 'setuptools==81.0.0'
if ($LASTEXITCODE) { throw 'Candidate tooling installation failed.' }
New-Item -ItemType Directory -Path $wheelhouse | Out-Null
$gpuPins = Get-Content -LiteralPath (Join-Path $assessment 'proposed-runtime-rocm.txt')
$allPins = Join-Path $assessment 'proposed-all-pins.txt'

# Acquire AMD artifacts only from AMD; do not resolve unrelated dependencies there.
& $candidatePython -m pip download --no-cache-dir --only-binary=:all: --no-deps --index-url https://stable.repo.amd.com/rocm/whl-next/ --dest $wheelhouse @gpuPins
if ($LASTEXITCODE) { throw 'Approved AMD wheel acquisition failed.' }

# Resolve pure/UI dependencies with every proposed version pinned. Exact AMD
# local-version wheels are already in the reviewed local wheelhouse.
& $candidatePython -m pip download --no-cache-dir --only-binary=:all: --index-url https://pypi.org/simple --find-links $wheelhouse --dest $wheelhouse -r $allPins
if ($LASTEXITCODE) { throw 'Pinned dependency acquisition failed; review the resolver output.' }
$selection = Join-Path $assessment 'resolved-wheel-selection.json'
& $candidatePython -m pip install --dry-run --ignore-installed --no-index --find-links $wheelhouse --report $selection -r $allPins
if ($LASTEXITCODE) { throw 'Offline dependency resolution failed.' }
Get-ChildItem -LiteralPath $wheelhouse -File | Get-FileHash -Algorithm SHA256
```

Review origins, native wheel tags, package licenses, closure and hashes. Downloading
these library wheels is part of the proposed installation approval, not inference
and not a model download. Do not install an unreviewed resolver change. Generate
the complete artifact lock from the reviewed local selection:

```powershell
$lock = Join-Path $assessment 'approved-rocm-lock.txt'
@'
import json,sys
from pathlib import Path
selection=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
lines=[]
for item in selection['install']:
    digest=item['download_info']['archive_info']['hashes']['sha256']
    meta=item['metadata']
    lines.append(f"{meta['name']}=={meta['version']} --hash=sha256:{digest}")
Path(sys.argv[2]).write_text('\n'.join(sorted(lines))+'\n',encoding='utf-8')
'@ | & $candidatePython -B - $selection $lock
if ($LASTEXITCODE) { throw 'Artifact lock creation failed.' }
& $candidatePython -m pip install --no-cache-dir --no-index --find-links $wheelhouse --require-hashes -r $lock
if ($LASTEXITCODE) { throw 'Candidate dependency installation failed.' }
& $candidatePython -m pip install --no-index --no-deps --no-build-isolation -e .
if ($LASTEXITCODE) { throw 'Local project installation failed.' }
& $candidatePython -m pip check
if ($LASTEXITCODE) { throw 'Candidate dependency validation failed.' }
```

Then set the process-local offline flags above. Before any model loading, verify
the dedicated worker's network policy and resource preflight. For package/kernel
validation, rerun the bounded probe, arithmetic, attention and convolution checks
recorded in this assessment, then import the SDXL and CLIP classes offline.
The existing detector checks the candidate in an isolated, bounded child. Require
validated ROCm results, not merely a successful process exit. Saved diagnostic
scripts reproduce the assessment's model-free kernel and import checks:

```powershell
@'
from stoneglass.inference.runtime import TorchRuntimeDetector
from stoneglass.inference.contracts import RuntimeKind
class Context:
    def check_cancelled(self): pass
    def report_progress(self, percent, message): pass
    def report_event(self, event): pass
report=TorchRuntimeDetector(timeout=30).detect(Context())
assert report.torch_version == '2.13.0+rocm10.0.0', report
assert report.hip_version and report.cuda_version is None, report
assert any(d.kind is RuntimeKind.ROCM and '9060 XT' in d.name for d in report.devices), report
print(report)
'@ | & $candidatePython -B -
if ($LASTEXITCODE) { throw 'Expected ROCm runtime was not validated.' }
@'
import subprocess,sys
from pathlib import Path
root=Path('.test-artifacts/phase2b1')
for script, timeout in [('tensor_probe.py',180),('kernel_probe.py',180),('import_probe.py',90)]:
    subprocess.run([sys.executable,'-B','-u',str(root/script)],check=True,timeout=timeout)
'@ | & $candidatePython -B -
if ($LASTEXITCODE) { throw 'Candidate kernel/import validation failed.' }
$env:QT_QPA_PLATFORM = 'offscreen'
& $candidatePython -B -m unittest discover -s tests -v
if ($LASTEXITCODE) { throw 'Candidate application tests failed.' }
$env:QT_QPA_PLATFORM = 'windows'
& $candidatePython -B -m unittest discover -s tests -v
if ($LASTEXITCODE) { throw 'Native Windows tests failed.' }
```

After the offline worker, resource validation and real adapter are separately
approved and implemented, test the existing complete checkpoint at batch 1,
512x512 and a fixed seed first; then validate 1024x1024, cancellation, cleanup and
VRAM use. Use conservative float16 UNet/text encoders and the model's VAE upcast
configuration. Do not introduce compilation, quantization, experimental fused
attention, LCM or specialized distilled settings in the first baseline test.
No generation command is proposed against the current backend-free application.

### Future NVIDIA support

Use a separate `.venv-cuda` and the same reviewed common-library profile. Select
the exact official CUDA PyTorch/Torchvision wheels and compatible NVIDIA driver
when the RTX 3090 is available, using [PyTorch's installation selector](https://docs.pytorch.org/get-started/locally/).
Resolve, validate and hash its dependency closure separately; never reuse the AMD
artifact lock as a CUDA lock.
Validate `torch.version.cuda`, actual device operations and memory there; do not
install ROCm wheels into that environment or CUDA wheels into `.venv-rocm`.
CPU can have its own profile. Runtime choice is independent of model architecture;
the common engine contracts remain unchanged. Exact CUDA artifact compatibility
and redistribution terms have not been certified by this AMD-only assessment.

### Rollback

Keep `.venv` and the reference environment in place throughout. Stop only the
candidate process, preserve its logs/lock for diagnosis, and launch the original
environment again:

```powershell
# Run from your Stoneglass checkout root.
.\.venv\Scripts\python.exe -B -m pip check
.\.venv\Scripts\python.exe -B -m stoneglass
```

No uninstall, environment replacement, model move, Git reset or deletion is
needed. Leave the candidate and wheelhouse ignored for review. Process-local
offline flags disappear when their validation shell exits. Any future OS policy
must have its own narrowly scoped rollback and must not target shared Python.

## Assessment outcome

The observed Python 3.13 / ROCm 10 / PyTorch 2.13 stack is a reasonable independent
Stoneglass candidate. GPU kernels, imports, existing probe and local configuration
availability passed the read-only checks. Remaining gates are fresh-environment
validation, exact artifact/notice review, model-version license confirmation,
strict offline worker enforcement and real adapter/model validation. **Stop here
and obtain approval before acquiring/installing packages or implementing inference.**
