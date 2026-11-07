# Third-party attribution and license inventory

This document records dependencies for the **Phase 1 source repository**. Review baseline: **2026-11-06**, Windows 11, CPython 3.13.12, PySide6-Essentials 6.12.0, Shiboken6 6.12.0, pip 25.3. The application requirement permits `PySide6-Essentials>=6.8,<7`; this inventory does not certify every version allowed by that range. Setuptools is resolved in an isolated build environment and is not an application runtime dependency.

Original Stoneglass code and documentation propose `GPL-3.0-or-later`. That declaration does **not** relicense dependencies, upstream notices, system components, the supplied branding, or the GNU license texts themselves. This checkout does not vendor third-party implementation code, Qt/Python binaries, fonts, or models. It includes the project-supplied logomark documented below. Package installation downloads dependencies separately into the ignored virtual environment.

## Project-supplied branding

The project owner has approved these Stoneglass branding assets for inclusion in this repository:

- `Stoneglass_Banner.png` — banner reference asset.
- `Stoneglass_Logo.png` — wordmark reference asset.
- `stoneglass_logomark.jpg` — root logomark.
- `src/stoneglass/ui/assets/stoneglass-logomark.jpg` — packaged logomark.

The two JPEG copies are byte-for-byte identical. Nonessential metadata has been removed without recompressing the image or changing its pixels, dimensions, orientation, or color information. Both PNG reference assets have also received metadata-only cleanup, preserving image pixels, dimensions, transparency, and color information. The sidebar uses the packaged logomark; the PNG references are not bundled in the application. Attribution is to the Stoneglass project. Inclusion approval does not imply an additional trademark grant. See the [asset notes](src/stoneglass/ui/assets/README.md).

## Runtime dependencies

| Component | Purpose and attribution | Upstream licensing and sources |
| --- | --- | --- |
| CPython / Python standard library | Interpreter and standard library; Python Software Foundation and Python contributors, with historical and incorporated-software rights holders | PSF License Version 2, with historical and component-specific notices. [Python 3.13 license and acknowledgements](https://docs.python.org/3.13/license.html), [CPython source](https://github.com/python/cpython/tree/v3.13.12). The interpreter is supplied by the developer, not bundled here. |
| PySide6-Essentials 6.12.0 | Direct dependency providing Python Qt bindings and Qt binaries; Qt for Python Team, The Qt Company Ltd., and upstream contributors/rights holders | Installed `License` metadata: `LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only`. Qt also offers commercial licensing. Stoneglass intends to use the open-source licensing route; no commercial Qt license is assumed. [Qt for Python](https://doc.qt.io/qtforpython-6/), [source repository](https://code.qt.io/cgit/pyside/pyside-setup.git/), [package details](https://doc.qt.io/qtforpython-6/package_details.html). See the notice discrepancy below. |
| Shiboken6 6.12.0 | Transitive dependency pinned by PySide6-Essentials; Python/C++ binding runtime from the Qt for Python project and upstream contributors/rights holders | Installed `License` metadata: `LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only`; commercial alternative also exists. [Shiboken documentation](https://doc.qt.io/qtforpython-6/shiboken6/), [source repository](https://code.qt.io/cgit/pyside/pyside-setup.git/). See the same notice discrepancy below. |
| Qt libraries and embedded third-party code carried by the Essentials wheel | Qt Core, GUI, and Widgets support the app; QtTest supports tests. Attribution belongs to The Qt Company Ltd. and the respective Qt and embedded-component rights holders | Qt module/file terms vary; applicable open-source options include LGPL v3 and GPL v3. Embedded components retain additional licenses and notices. [Qt licensing](https://doc.qt.io/qt-6/licensing.html), [Qt third-party inventory](https://doc.qt.io/qt-6/licenses-used-in-qt.html), [Qt for Python third-party notices](https://doc.qt.io/qtforpython-6/licenses.html), [Qt source repositories](https://code.qt.io/cgit/). Package-level metadata alone is not a full inventory of the bundled binaries. |

The selected open-source route for the PySide/Shiboken library portions is LGPL v3, subject to confirming the exact artifacts and component terms. A reference copy of [LGPL v3](licenses/LGPL-3.0-only.txt) is retained alongside the [GPL v3 text](LICENSE), which LGPL v3 incorporates. The presence of these texts is not evidence that all dependency distribution obligations have been fulfilled.

### Qt wheel notice review — dependency redistribution

This source-only repository contains Stoneglass source, dependency declarations, documentation, and approved assets. It does not distribute Qt/PySide/Shiboken implementation code, wheels, or binaries. The installed-package notice discrepancy below is not identified as a blocker to publishing this project-only source repository under its proposed GPL-3.0-or-later terms. It remains a review item before dependency artifacts are redistributed or a packaged application is released. Vendoring third-party source would also require its applicable licenses and notices.

The installed 6.12.0 packages declare the open-source alternatives above in their `License` metadata. However, each package declares only `LicenseRef-Qt-Commercial.txt` in `License-File`, and its installed `dist-info/licenses/` directory contains only that commercial notice. No standalone GPL/LGPL license text or component notice inventory was found in the installed PySide6 tree during this review.

Observed relative paths:

```text
.venv/Lib/site-packages/pyside6_essentials-6.12.0.dist-info/licenses/LicenseRef-Qt-Commercial.txt
.venv/Lib/site-packages/shiboken6-6.12.0.dist-info/licenses/LicenseRef-Qt-Commercial.txt
```

This is a discrepancy between metadata and packaged notices, not a determination that a commercial license is required or that these artifacts are approved for redistribution. **Before distributing binaries**, verify the provenance and open-source terms of the exact wheels, obtain the corresponding source and complete notices for everything included, and resolve the mismatch. If necessary, use a verified community build/version or build from upstream source after review. Copying generic GPL/LGPL texts alone does not resolve this issue. No runtime dependency version or backend has been changed during repository preparation.

To inspect a contributor's actual installed package metadata:

```powershell
@'
from importlib.metadata import distribution
for name in ("PySide6-Essentials", "shiboken6"):
    package = distribution(name)
    print(name, package.version)
    for field in ("License", "License-Expression", "License-File", "Requires-Dist"):
        print(field, package.metadata.get_all(field, []))
    for path in package.files or ():
        if "licenses" in path.parts:
            print(package.locate_file(path))
'@ | .\.venv\Scripts\python.exe -
```

## Build and development tools

| Tool | Role and attribution | License and upstream source |
| --- | --- | --- |
| setuptools >=77.0.3 | Isolated packaging/build backend; setuptools contributors / Python Packaging Authority | MIT; [upstream license](https://github.com/pypa/setuptools/blob/main/LICENSE), [source](https://github.com/pypa/setuptools). A version supporting SPDX metadata is required. Its own bundled components retain their licenses. It is not shipped as Stoneglass runtime code. |
| pip 25.3 in the reviewed environment | Installer used during setup; The pip developers | MIT; [versioned license](https://github.com/pypa/pip/blob/25.3/LICENSE.txt), [source](https://github.com/pypa/pip/tree/25.3). Vendored tools retain their separate licenses in pip's installed `dist-info/licenses/` tree. pip is tooling, not an application dependency. |
| unittest and QtTest | Tests use Python's standard library and the existing Qt Essentials package | Covered by the corresponding Python and Qt inventories above; no additional test framework is required. |

Windows 11, built-in Windows PowerShell/CIM, and Segoe UI are host-provided platform components. Their software/font rights remain with their owners. Stoneglass invokes local hardware inventory and refers to an installed font by family name; it does not redistribute those components. Source-control and editor tools are not bundled with the application.

## Future dependencies and distribution review

PyTorch, Hugging Face Diffusers, GPU runtimes, model weights, and model licenses are **not part of Phase 1**. No license for future models or generated output is granted or implied by the project license. ComfyUI, Automatic1111, Forge, and other image-generation applications are neither dependencies nor backends.

Before a public release, maintainers will review the exact source/artifact contents and versioned dependency notices. A source-only Stoneglass distribution and a Windows bundle containing Python/Qt have different contents: any bundled dependency must retain its required notices and license texts, and applicable source, modification, replacement/relinking, and other distribution requirements must be addressed under the chosen terms. Record upstream source locations and changes for the exact versions shipped; a documentation link alone is not a substitute for required corresponding source. Qt's [software bill of materials documentation](https://doc.qt.io/qt-6/sbom.html) can help identify embedded components.

No public repository, binary bundle, release upload, or completed legal/compliance sign-off is created by this inventory. The dependency-artifact review above remains open for future redistribution; it does not by itself block this source-only repository.
