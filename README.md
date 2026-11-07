# Stoneglass

Stoneglass is a free and open-source, standalone, local-first Windows 11 desktop image studio. **Phase 1 provides the application foundation only.** Its future inference engine will be Python code within this project, using a GPU-specific strategy established before installing PyTorch or Diffusers.

The dark PySide6 interface includes Generate, Models, Gallery, and Settings. You can edit prompts and generation preferences, inspect local hardware, and save preferences. **Generation, model loading, and gallery browsing are unavailable and labeled accordingly.** The Generate button is disabled; the preview is an empty state. There is no simulated image generation.

Stoneglass is independent of ComfyUI, Automatic1111, Forge, and other image-generation applications. It does not use them as backends. Inference will run through Stoneglass's own engine, on your machine, without accounts or a cloud service.

## Phase 1 interface

The sidebar uses the existing project-supplied logomark beside one application name. Its expanded width is 192 logical pixels; collapse it to 68 with the **Collapse** control or **Ctrl+B**. The choice saves locally. Collapsed navigation keeps tooltips and accessible names, and arrow-key navigation continues to work. If the mark is unavailable, text branding remains. See the [branding asset notes](src/stoneglass/ui/assets/README.md) for the packaged asset path and fallback.

Generate retains a two-column editor/preview layout. Resolution presets include **512×512, 768×1024, 1024×768, and 1024×1024**. Aspect choices are **1:1, 3:2, 2:3, 16:9, and 9:16**. Both selectors change only width and height; prompts, steps, guidance, seed, and other preferences remain unchanged. Aspect choices keep an exact ratio on the existing 64 px grid and choose the closest pixel count **up to 1,048,576 pixels (the area of 1024×1024)**. They do not automatically select a large size just because manual dimensions were large. The largest automatic choices are 1024×1024, 1152×768, 768×1152, 1024×576, and 576×1024 respectively. Very small inputs may need to grow to fit an exact ratio on the grid.

Manual dimensions still support 256–2048 px per side and round down to the grid when committed. The automatic aspect budget is applied only when a preset is selected: valid manual dimensions are preserved across page/sidebar changes and application restarts, including larger manual sizes that match a listed aspect. Each selector shows **Custom** when the dimensions do not match its choices; a named resolution may still have a Custom aspect if that ratio is not listed. The saved dimensions determine preset labels after restart. This UI budget does not establish a future model's VRAM requirements.

The preview is an honest empty state, with separate viewport, toolbar, and status extension points for later work. Zoom, fit, save, and editing actions are not exposed as active controls. Generate stays disabled. Models and Gallery remain placeholders. Settings separates operating system, compute status, GPU name/vendor/driver, and unreported VRAM, with selectable, wrapping storage paths. **Save preferences** remains outside the scrolling content.

See [UI refinement notes](docs/UI_REFINEMENT.md) for changed files, validation, and current limits.

## Project status and license

This is an unreleased Phase 1 foundation being prepared for future public GitHub development. **The repository is not being published as part of this work.** Code and dependency licensing must be reviewed before its first public release. Phase 2 requires explicit project approval.

The proposed project license is **GNU GPL version 3 or, at your option, any later version** (`GPL-3.0-or-later`). Original Stoneglass code, scripts, and documentation use these terms, except files explicitly carrying other terms and unmodified third-party license texts. Copyright remains with the respective contributors. See [LICENSE](LICENSE) for the official, unmodified GPL v3 text; the “or later” choice is declared here and in package metadata. Stoneglass is provided without warranty under that license.

Dependencies retain their own licenses. Stoneglass branding is approved by the project owner for inclusion. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for attribution and licensing scope. The Qt wheel-notice review concerns redistribution of dependency artifacts and packaged applications; this source-only repository does not include those implementations or binaries. That inventory is not a completed binary-distribution audit.

Contributor setup, change guidelines, and contribution licensing are in [CONTRIBUTING.md](CONTRIBUTING.md). No public repository URL or issue tracker is advertised before publication is approved.

## Setup and launch in PowerShell

Use 64-bit Python 3.11 or newer on Windows 11. This phase was verified with Python 3.13.12 and PySide6 Essentials 6.12.0. Python must be available as `python` on PATH. Run the following commands from your checkout's root directory.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m stoneglass
```

The dependency installation requires network access to the Python package index. Once installed, the application runs offline. `PySide6-Essentials` supplies the `PySide6` Qt Core, GUI, Widgets, and QtTest modules without the additional WebEngine and multimedia bundles. Its only transitive runtime dependency is Shiboken. No PyTorch, Diffusers, compute runtimes, AI models, or other image-generation applications are installed or required.

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

Tests use the standard-library `unittest` runner and Qt's bundled test utilities. They isolate storage in temporary directories, use Qt's offscreen platform by default, and mock hardware inventory. They cover settings round trips, validation, corruption/version handling, atomic-write failures, AMD/NVIDIA/Intel identification, multiple adapters, detection failures/timeouts, application initialization, navigation, disabled generation, autosave/privacy, button interactions, worker progress/errors/cancellation, GUI thread delivery, and closing while work is running.

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

Settings include window size/maximized state, sidebar collapse state, and generation dimensions, steps, guidance, and seed. Generation and sidebar preferences autosave after a short debounce; window size is saved at close. Prompts stay in memory for the current session and are never written to settings or application logs. No images or models are saved in Phase 1. There are no accounts, telemetry, subscriptions, cloud calls, or runtime downloads. The application performs one local Windows hardware inventory at startup, with a manual refresh available.

To choose another data directory for a session:

```powershell
$env:STONEGLASS_DATA_DIR = Join-Path $PWD '.local-data'
.\.venv\Scripts\python.exe -m stoneglass
Remove-Item Env:\STONEGLASS_DATA_DIR
```

Settings are validated and written using a same-directory temporary file and atomic replacement. An unreadable, damaged, or unsupported-version settings file is preserved; defaults are used and saving is blocked with a readable explanation. Close the app and rename that settings file to recover. A failed save appears in Settings/status and is reported on close. Startup storage errors and unexpected GUI exceptions have readable dialogs. Background failures are logged with tracebacks and delivered to the UI. Logs rotate at 2,000,000 bytes with three backups. They contain local diagnostics, without prompt contents.

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
    infrastructure/
      __init__.py
      workers.py              # owned Qt threads, signals, cancellation
    inference/
      __init__.py
      contracts.py            # future backend protocol; no implementation
    ui/
      __init__.py
      main_window.py          # navigation and service/task coordination
      generate_page.py        # prompts, preferences, unavailable preview
      dimension_controls.py   # synchronized presets and manual dimensions
      image_preview.py        # empty viewport and future action integration points
      sidebar.py              # branding, collapse preference, accessible navigation
      navigation_icons.py     # code-drawn navigation glyphs, separate from branding
      placeholder_page.py     # Models and Gallery empty states
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
```

## Architecture

`app.py` composes services and the Qt window. UI views consume plain domain types and application services. Domain types, storage, hardware detection, and the inference contract do not import Qt. The `infrastructure` package supplies the Qt task adapter; inference implementations will live only under `inference`, with no UI imports. No existing image-generation application is used as a backend.

`TaskManager` owns a thread and handle for each operation. A `QThread.run()` override executes a plain callable; explicit queued signals deliver results, progress, cancellation, and readable failures to GUI-thread receivers. No worker updates widgets. An event-based context provides cooperative cancellation. Handles finish only after the thread stops, and the window defers closing asynchronously until all active tasks finish. Operations must use bounded I/O and check cancellation between stages. Windows inventory has a 15-second subprocess timeout. Future pipeline serialization and model lifecycle policy belong to the inference service, once that phase is approved.

Hardware detection runs `Get-CimInstance Win32_VideoController` through built-in Windows PowerShell, without a shell command assembled from user data. PCI vendor IDs identify AMD, NVIDIA, and Intel, with name/manufacturer fallback. It supports multiple display adapters and treats unknown/basic drivers honestly. It does not import or probe CUDA, and adapter presence does not imply compute support. VRAM is intentionally left unreported: the inventory's 32-bit `AdapterRAM` field cannot reliably describe modern 16/24 GB GPUs. Detection failure remains nonfatal. See Microsoft's [Win32_VideoController reference](https://learn.microsoft.com/en-us/windows/win32/cimwin32prov/win32-videocontroller) and Qt's [QThread reference](https://doc.qt.io/qtforpython-6/PySide6/QtCore/QThread.html).

The RX 9060 XT and future RTX 3090 can be inventoried with the same service. Choosing and validating their Windows compute runtimes, installing PyTorch/Diffusers, adding model loading, and implementing real generation are **deferred until Phase 2 is approved**. Phase 1 does not select a GPU backend or claim inference compatibility.
