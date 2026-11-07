Stoneglass
Free, open-source AI image generation on your own computer.

Stoneglass is a local-first desktop image studio for Windows 11. It uses its own inference engine rather than relying on ComfyUI, AUTOMATIC1111, Forge, or a hosted image-generation service. Once the required software and model resources are installed, image generation can run without an internet connection, account, or subscription.
Development status: Stoneglass is an early-stage project, not a packaged general-purpose release. Real SDXL generation has been validated on a specific AMD Radeon RX 9060 XT / ROCm configuration with AlbedoBase XL v3.1-Large. Other models and hardware configurations are not yet enabled. The source checkout alone does not install a working inference runtime or model.

Features
- Local image generation: Run the validated SDXL pipeline on your own hardware.
- Generation controls: Enter positive and negative prompts; adjust dimensions, sampling steps, guidance, and seed.
- Model validation: Select local checkpoint and resource-manifest files, then check readiness before generating.
- Progress and cancellation: Follow actual sampling progress and cancel an active task.
- Preview and export: View completed images in the desktop interface and export the original full-resolution PNG without recompression.
- Private by design: No accounts, telemetry, cloud inference, or automatic runtime downloads.
- Offline operation: The tested interface and inference configuration passed a manually supervised physical-disconnection test.
The desktop interface includes Generate, Models, Gallery, and Settings. Gallery indexing, image editing, additional model families, and broader hardware support are planned rather than available today.
Current compatibility
The currently enabled generation profile is limited to the reviewed combination of:
- Operating system: Windows 11
- GPU: AMD Radeon RX 9060 XT (16 GB)
- Compute environment: Separately validated ROCm/PyTorch runtime
- Model: AlbedoBase XL v3.1-Large with its validated local configuration resources
This is a tested configuration, not a statement that other SDXL models or GPUs cannot work in the future. NVIDIA, CPU, LCM, and arbitrary SDXL model generation are not yet enabled in the application UI.

The project does not redistribute the model weights or the private, validated runtime bundle. See [GPU runtime assessment](docs/GPU_RUNTIME_ASSESSMENT.md) and [Stage 3 UI notes](docs/STAGE3_UI.md) for the technical requirements and current limitations.
Install and launch the desktop interface
Prerequisites: Windows 11 and 64-bit Python 3.11 or newer, available as python in PowerShell.

From the repository root, run:
```python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m stoneglass
```
Or use the included convenience scripts:
```.\scripts\setup.ps1
.\scripts\launch.ps1
```
The initial package installation may require internet access. These commands install and launch the desktop application; they do not install the ROCm inference environment, download model weights, or configure the currently validated generation profile. Without those separate resources, you can explore the interface, but Generate remains unavailable.

For development and runtime details, see [CONTRIBUTING.md](CONTRIBUTING.md), [GPU runtime assessment](docs/GPU_RUNTIME_ASSESSMENT.md), and [inference architecture](docs/INFERENCE_ARCHITECTURE.md).
Generate an image
On a system with the validated runtime and local resources already installed:
1. Open Models, select the supported local checkpoint and matching resource manifest, and choose Validate model.
2. Open Generate and enter a prompt. Adjust the available settings as needed.
3. Select Generate and follow the progress indicator. You can cancel an active generation.
4. Preview the completed image and choose Save PNG to export the original image.
Generation is enabled only after local model, resource, and runtime validation succeeds. Stoneglass does not silently download missing files. More approachable missing-resource guidance and opt-in downloads are under development.
Privacy and offline operation
Stoneglass is designed to keep image generation on your machine. The tested inference path uses local model files and an owned worker process; it does not require an account or cloud inference service. Prompts are not saved to application settings or application logs. Generated images and preferences are stored locally, by default under %LOCALAPPDATA%\Stoneglass.

Offline generation has been demonstrated through the desktop UI for the recorded AMD/ROCm/SDXL configuration. That test does not certify other hardware or software versions, and the worker is not an operating-system network sandbox. See [offline UI acceptance](docs/OFFLINE_UI_ACCEPTANCE.md) for the test scope and procedure.
Development and contributing
Stoneglass is actively being developed. Contributions, testing, and issue reports are welcome; see [CONTRIBUTING.md](CONTRIBUTING.md) before submitting changes.

Run the standard test suite from the repository root:
```
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m pip check
```
These routine tests use mocked inference and do not require a GPU or model weights. Real inference and offline acceptance are tested separately.

For implementation details, see [inference architecture](docs/INFERENCE_ARCHITECTURE.md), [UI refinement](docs/UI_REFINEMENT.md), and [Stage 3 UI integration](docs/STAGE3_UI.md).
License
Stoneglass's original source code and documentation are licensed under GNU GPL v3 or later (GPL-3.0-or-later), except where a file states otherwise. See LICENSE for the GPL v3 license text and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for third-party attribution and licensing notes.

Model weights and third-party dependencies have their own licenses and are not automatically covered by the Stoneglass project license. Binary packaging and redistribution require separate review.
