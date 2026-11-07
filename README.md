# Stoneglass

Stoneglass is a free, open-source AI image-generation studio for Windows 11. Designed for privacy and independence, it generates images directly on your computer without requiring cloud services, subscriptions, or user accounts.

With an intuitive desktop interface, Stoneglass lets you manage local AI models, customize generation settings, monitor progress, preview results, and export full-resolution images.

Unlike frontends built around ComfyUI, Automatic1111, or Forge, Stoneglass uses its own local inference engine. Once the required models and dependencies are installed, image generation works entirely offline.

**Current development status:** Stoneglass is in active development, with initial SDXL support validated on a specific AMD Radeon GPU configuration. Additional models, hardware compatibility, and features are planned.

## Desktop interface

Stoneglass features a desktop interface designed for local AI image generation.

- **Image generation:** Enter prompts and adjust resolution, aspect ratio, sampling steps, guidance, and seed.
- **Flexible dimensions:** Choose from common resolution presets, select an aspect ratio, or enter custom dimensions.
- **Image preview:** View generated images directly in the application.
- **PNG export:** Save generated images at their original resolution without quality loss.
- **Model management:** Select and validate locally installed models.
- **Hardware information:** View detected GPU and system information.
- **Customizable workspace:** Collapsible sidebar, persistent preferences, and keyboard navigation.

For detailed interface behavior, supported dimensions, and implementation notes, see the [UI refinement documentation](docs/UI_REFINEMENT.md).

## Project status and license

This development checkout includes the existing inference architecture, a separately validated ROCm environment, and Stage 3 UI integration. The source repository is [Stoneglass-AI-Studio/stoneglass-ai-studio](https://github.com/Stoneglass-AI-Studio/stoneglass-ai-studio). This source update includes the independent engine, reviewed UI integration and operator-run offline acceptance workflow. No runtime binaries, model weights, local bundle, generated output or private audit evidence are included. See [inference architecture decisions](docs/INFERENCE_ARCHITECTURE.md), the [revised offline roadmap](docs/OFFLINE_INFERENCE_IMPLEMENTATION_PLAN.md), [Stage 1 validation](docs/LOCAL_INFERENCE_STAGE1.md), [the first real SDXL test](docs/LOCAL_INFERENCE_STAGE2.md), and [Stage 3 UI behavior and limits](docs/STAGE3_UI.md).

The [scoped AppContainer prototype findings](docs/APPCONTAINER_PROTOTYPE.md) remain experimental history. OS network isolation is no longer a prerequisite for inference. The worker uses validated local resources and offline library settings; those settings are not an OS sandbox.

The [standalone offline acceptance procedure](docs/OFFLINE_ACCEPTANCE.md) provides a local PowerShell launcher with preparation-only checks, operator confirmation, a fresh worker/empty Hub cache, and preserved local evidence. Stage 2 passed operator-run physical-disconnection acceptance and evidence review on November 7, 2026. That acceptance covers its recorded source/runtime/resources.

**Stage 3.1 passed operator-run offline UI acceptance and evidence review on November 7, 2026**, for the recorded source, reviewed RX 9060 XT ROCm environment, AlbedoBase XL v3.1-Large checkpoint and complete local bundle. The operator completed model validation, generation, preview, PNG export and normal shutdown while declaring continuous physical disconnection. See the [offline UI procedure and scope](docs/OFFLINE_UI_ACCEPTANCE.md). This is manual offline functionality evidence, not OS network-isolation proof or certification of other profiles. Changed source/resources/runtime require fresh preparation and acceptance before extending that claim.

The proposed project license is **GNU GPL version 3 or, at your option, any later version** (`GPL-3.0-or-later`). Original Stoneglass code, scripts, and documentation use these terms, except files explicitly carrying other terms and unmodified third-party license texts. Copyright remains with the respective contributors. See [LICENSE](LICENSE) for the official, unmodified GPL v3 text; the “or later” choice is declared here and in package metadata. Stoneglass is provided without warranty under that license.

Dependencies retain their own licenses, and Stoneglass branding is approved by the project owner for inclusion. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for attribution and source-only licensing scope. Qt/ROCm dependency-artifact notices and packaged binary distribution remain separate reviews; no dependency implementation or binary is shipped here.

Contributor setup, change guidelines, and contribution licensing are in [CONTRIBUTING.md](CONTRIBUTING.md).

## Setup and launch in PowerShell

Use 64-bit Python 3.11 or newer on Windows 11. This phase was verified with Python 3.13.12 and PySide6 Essentials 6.12.0. Python must be available as `python` on PATH. Run the following commands from your checkout's root directory.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m stoneglass
```

The dependency installation requires network access to the Python package index. Once installed, the desktop runs offline. `PySide6-Essentials` supplies Qt Core, GUI, Widgets, and QtTest without WebEngine or multimedia bundles; its transitive runtime dependency is Shiboken. These default setup commands do not install PyTorch, Diffusers, compute runtimes, or models. Inference additionally requires the separately reviewed `.venv-rocm` installation and complete validated local resources; see [runtime assessment](docs/GPU_RUNTIME_ASSESSMENT.md). This experimental profile is not provisioned by cloning the repository: the private wheel hash lock, local manifest and configuration bundle are not shipped. Missing prerequisites leave generation unavailable; the default setup launches the GUI and supports model-free tests. There is no automatic dependency or model acquisition. Missing resources leave generation unavailable with a local error. OS isolation is not a prerequisite or guarantee.

Convenience scripts are also included:

```powershell
.\scripts\setup.ps1
.\scripts\launch.ps1
```

If your PowerShell policy blocks local scripts, use the direct Python commands above. Virtual-environment activation is optional. The installed `.\.venv\Scripts\stoneglass.exe` entry point launches the app without a console; `python -m stoneglass` keeps console logs visible.

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m pip check
```

Tests use standard-library `unittest` and Qt's bundled test utilities. They isolate storage, use Qt's offscreen platform by default, and mock inference for routine UI tests. Coverage includes settings, hardware, navigation, readiness and button gating, actual-step progress delivery, cancellation/recovery, cleanup failures, output integrity, PNG export, and closing during work. The suite requires no GPU, model weights, or inference dependencies; static PNG fixtures are test data only.

For a native Windows UI test run:

```powershell
$env:QT_QPA_PLATFORM = 'windows'
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
Remove-Item Env:\QT_QPA_PLATFORM
```

This briefly displays test windows. For manual review, launch the app, visit each page, resize the window, edit generation preferences, restart to verify persistence, and refresh hardware in Settings. On smaller windows the editor and Settings content scroll; Generate remains visible. The suite does not require a GPU, models, or any inference dependency.

## Storage, privacy, and errors

By default, data lives in `%LOCALAPPDATA%\Stoneglass`:

```text
Stoneglass/
  settings.json
  logs/
    stoneglass.log
    stoneglass.log.1    # created when rotation is needed, up to .3
```

Settings include window size/maximized state, sidebar collapse state, generation dimensions/steps/guidance/seed, and selected local model/manifest paths. Preferences autosave after a short debounce; window size saves at close. Prompts stay in memory for the session and are never written to settings or application logs. Generated PNGs remain under `generated/` in the application-data directory; export creates an additional user-selected copy. There are no accounts, telemetry, subscriptions, cloud calls, or runtime downloads. Windows hardware inventory runs locally at startup and can be refreshed. Explicit model validation probes the supported runtime in an owned child process; PyTorch never initializes in the UI process. Each generation uses a fresh worker and closes it before reporting completion.

To choose another data directory for a session:

```powershell
$env:STONEGLASS_DATA_DIR = Join-Path $PWD '.local-data'
.\.venv\Scripts\python.exe -m stoneglass
Remove-Item Env:\STONEGLASS_DATA_DIR
```

Settings are validated and written using a same-directory temporary file and atomic replacement. An unreadable, damaged, or unsupported-version settings file is preserved; defaults are used and saving is blocked with a readable explanation. Close the app and rename that settings file to recover. A failed save appears in Settings/status and is reported on close. Startup storage errors and unexpected GUI exceptions have readable dialogs. Background failures are delivered to the UI. Generic task errors retain tracebacks; inference adapter errors use safe codes and exception classes without adapter messages or chained tracebacks. Logs rotate at 2,000,000 bytes with three backups. They contain local diagnostics, without prompt contents.

## Project structure

```text
Stoneglass/
  pyproject.toml
  README.md
  LICENSE
  CONTRIBUTING.md
  THIRD_PARTY_NOTICES.md
  .gitignore
  .gitattributes
  docs/
    INFERENCE_ARCHITECTURE.md  # Phase 2A boundaries, lifecycle, runtime selection
    UI_REFINEMENT.md           # refinement behavior, changed files, checks
    PUBLICATION_HYGIENE.md     # tracked files, ignore rules, and publication review
  licenses/
    README.md                 # origin and hashes of retained license texts
    LGPL-3.0-only.txt          # official GNU text for dependency reference
  scripts/
    setup.ps1
    launch.ps1
  src/stoneglass/
    __init__.py
    __main__.py
    app.py                    # composition root, theme, startup/error handling
    domain/
      __init__.py
      settings.py             # immutable settings and validation
      dimensions.py           # resolution/aspect choices and exact ratio sizing
      hardware.py             # typed adapter inventory/report
    services/
      __init__.py
      application.py          # service dependencies
      paths.py                # local storage locations
      settings.py             # versioned JSON and atomic persistence
      logging_setup.py        # console and rotating file diagnostics
      hardware.py             # Windows CIM inventory and vendor detection
      inference.py            # serialized model ownership and cleanup
      generation.py           # one generation transaction followed by worker cleanup
      images.py               # bounded PNG validation and lossless export
    infrastructure/
      __init__.py
      workers.py              # owned Qt threads, signals, cancellation
      inference_tasks.py      # background service calls through TaskManager
    inference/
      __init__.py
      contracts.py            # typed requests, models, runtimes, progress, protocols
      errors.py               # prompt-safe typed errors
      validation.py           # strict requests and local model references
      runtime.py              # isolated detection and explicit device selection
      _torch_probe.py         # optional child-process tensor validation
      reviewed_profile.py     # explicit first UI checkpoint/resource fingerprints
    ui/
      __init__.py
      main_window.py          # navigation and service/task coordination
      generate_page.py        # prompts, preferences, generation/cancel/progress
      generation_controller.py # GUI coordination over existing task/service contracts
      models_page.py          # explicit local checkpoint and manifest selection
      dimension_controls.py   # synchronized presets and manual dimensions
      image_preview.py        # fitted validated image and full-resolution PNG export
      sidebar.py              # branding, collapse preference, accessible navigation
      navigation_icons.py     # code-drawn navigation glyphs, separate from branding
      placeholder_page.py     # Gallery empty state
      settings_page.py        # hardware and local settings/status
      components.py           # shared view helpers
      theme.qss
      assets/
        README.md             # source and placement of the supplied branding
        stoneglass-logomark.jpg
  tests/
    qt_support.py
    test_settings.py
    test_hardware.py
    test_application.py
    test_workers.py
    test_dimensions.py
    test_sidebar.py
    inference_support.py      # mock-only fixtures; never generates images
    test_inference_runtime.py
    test_inference_service.py
    test_inference_tasks.py
```

## Architecture

`app.py` composes services and the Qt window. UI views consume plain domain types and application services. Domain types, storage, hardware detection, and inference contracts do not import Qt. The `infrastructure` package supplies the Qt task adapter; production inference implementations live under `inference`, with no UI imports. No existing image-generation application is used as a backend.

`TaskManager` owns a thread and handle for each operation. A `QThread.run()` override executes a plain callable; explicit queued signals deliver results, progress, cancellation, and readable failures to GUI-thread receivers. No worker updates widgets. An event-based context provides cooperative cancellation. Handles finish only after the thread stops, and the window defers closing asynchronously until all active tasks and required model cleanup finish. Operations use bounded I/O and check cancellation between stages. Windows inventory has a 15-second subprocess timeout. The Qt-free `InferenceService` rejects overlapping operations and coordinates ownership/cleanup. `InferenceTasks` reuses the existing manager. The application registers the reviewed local SDXL provider but does not probe or load at startup. Generation runs in an owned process and closes it after each request.

Hardware detection runs `Get-CimInstance Win32_VideoController` through built-in Windows PowerShell, without a shell command assembled from user data. PCI vendor IDs identify AMD, NVIDIA, and Intel, with name/manufacturer fallback. It supports multiple display adapters and treats unknown/basic drivers honestly. It does not import or probe CUDA, and adapter presence does not imply compute support. VRAM is intentionally left unreported: the inventory's 32-bit `AdapterRAM` field cannot reliably describe modern 16/24 GB GPUs. Detection failure remains nonfatal. See Microsoft's [Win32_VideoController reference](https://learn.microsoft.com/en-us/windows/win32/cimwin32prov/win32-videocontroller) and Qt's [QThread reference](https://doc.qt.io/qtforpython-6/PySide6/QtCore/QThread.html).

The RX 9060 XT and future RTX 3090 can be inventoried with the same hardware service. Runtime probing checks the actual installed PyTorch build and per-device tensor operations. HIP is reported as ROCm even though PyTorch uses its CUDA API. The initial UI additionally requires the separately validated RX 9060 XT runtime/model profile. Generic contracts retain CUDA and opt-in CPU support for future adapters; NVIDIA, CPU and LCM generation are not enabled in this UI. No runtime, inference library or model is installed automatically. See [architecture history](docs/INFERENCE_ARCHITECTURE.md) and [current UI integration](docs/STAGE3_UI.md).
