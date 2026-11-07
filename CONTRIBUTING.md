# Contributing to Stoneglass

Stoneglass is a free and open-source, local-first image studio for Windows 11. The proposed project license is **GPL-3.0-or-later**. The repository is being prepared for public GitHub development and has not been approved for publication or a first release. Until then, share changes through the project's existing private review process. Do not create a public mirror, push this checkout to a public remote, or upload release artifacts on the project's behalf.

## Current scope

Work is limited to **Phase 1: Application Foundation**. Improvements to the desktop shell, accessibility, preferences, logging, hardware inventory, worker lifecycle, tests, documentation, and licensing fit this phase. Phase 2 needs explicit project approval before implementation.

Keep these project constraints:

- Use Stoneglass's own future Python inference engine. Do not add ComfyUI, Automatic1111, Forge, or another image-generation application as a backend.
- Do not install or configure PyTorch/Diffusers, choose a GPU compute backend, download models, load models, or implement image generation in Phase 1.
- Keep unavailable functionality visibly labeled. Do not simulate successful generation or populate the gallery with pretend output.
- Preserve local storage and privacy-first defaults. Do not add telemetry, accounts, subscriptions, cloud APIs, or runtime downloads.
- Prefer free and open-source dependencies and the Python standard library. Explain the need, attribution, license, and effect on installation size for any dependency change.

## Development setup

Use Windows 11, 64-bit Python 3.11 or newer, and PowerShell. From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m stoneglass
```

Activation is optional. `scripts/setup.ps1` and `scripts/launch.ps1` provide equivalent convenience commands. See [README.md](README.md) for storage paths, troubleshooting, and native UI test instructions. No GPU or model is required for tests.

Keep test/manual-session data inside an ignored directory when useful:

```powershell
$env:STONEGLASS_DATA_DIR = Join-Path $PWD '.local-data'
.\.venv\Scripts\python.exe -m stoneglass
Remove-Item Env:\STONEGLASS_DATA_DIR
```

## Code and review guidelines

Use typed Python, descriptive names, small modules, and clear errors. Follow the existing style. Keep domain types and application services independent of Qt. Keep Qt views in `ui`, threading adapters in `infrastructure`, and future inference code in `inference`. New original source files should carry `SPDX-License-Identifier: GPL-3.0-or-later` in a language-appropriate comment. Preserve upstream notices on imported material instead of replacing them with the project identifier.

Only the GUI thread may update widgets. Route blocking work through the worker architecture, use bounded I/O and cooperative cancellation, and retain workers until they finish. Never terminate a running thread forcibly. Identify adapters without assuming CUDA exists; distinguish hardware inventory from compute support.

Keep patches focused. Describe the problem, resulting behavior, how you verified it, and any remaining limitation. For UI changes, review the default and minimum window sizes and keyboard navigation. Screenshots must use synthetic or nonprivate text. For behavior changes, add meaningful focused tests; documentation-only changes do not need new unit tests.

Before submitting a change, run:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m pip check
```

Review the diff for private paths, prompts, settings, logs, credentials, generated images, virtual environments, and model weights. These do not belong in source control. Image extensions are not globally ignored: approved branding, documentation images, UI assets, and fixtures remain trackable, including root assets. Include their origin and redistribution license. Keep generated images under `outputs/`, `generated/`, `gallery/`, `runs/`, or `.local-data/`; keep private datasets under `data/`, `datasets/`, or `private-datasets/`. These ignored root directories are for local data, not source or approved assets. Qt Designer `.ui` files and `.qrc` resource manifests remain trackable. Do not bundle system fonts.

Model/checkpoint extensions are ignored everywhere, including inside fixture and asset directories. Any exception needs explicit review and approval; do not use `git add -f` to bypass that rule. Only `.env.example` is exempted as an environment template, and it must contain placeholders, never actual secrets. Ignore patterns cannot recognize every secret by content.

`.gitignore` does not affect already tracked files, old commits, tool snapshot refs, or existing Git objects. Check `git ls-files`, `git status --short --untracked-files=all`, the staged diff, and `git for-each-ref` before a release. Do not share the entire `.git` directory, create an all-ref bundle, or perform a mirror push from a private working repository without an explicit review of all refs and objects. Removing tracked files, deleting snapshots, or rewriting history requires separate approval. See [publication hygiene](docs/PUBLICATION_HYGIENE.md).

When reporting bugs through the currently approved review channel, include reproduction steps, expected/actual behavior, Windows/Python/Qt versions, and redacted diagnostics. Include GPU vendor/model if relevant; omit device serial numbers, private prompts, credentials, and unnecessary machine identifiers. Do not post secrets or unredacted logs to a future public issue tracker.

## Contribution licensing and dependency attribution

Submit only work you have the right to contribute. Contributions intended for inclusion in original Stoneglass code and documentation are offered under GPL-3.0-or-later. Contributors retain their copyright; no copyright assignment or separate contributor agreement is introduced here. Preserve existing attribution and identify any third-party material, its source, copyright holders, license, and modifications.

Update [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) when adding or changing dependencies or bundled assets. Check the actual version's metadata and shipped notices, including transitive and embedded components. Do not assume every Qt component, model weight, example, or image uses the same license. Review compatibility with the proposed project license before accepting third-party code. Preserve required license texts and notices in any distribution that includes those components.

Before redistributing dependency artifacts, vendored implementations, or a packaged application, resolve the Qt notice review documented in the third-party inventory and review the exact components to be distributed. The current source-only repository does not include Qt/PySide/Shiboken implementations or binaries, so that artifact review does not itself block source publication. Publishing, release uploads, and repository visibility changes remain separate maintainer decisions. These contribution guidelines describe the project's current private workflow; they do not add restrictions to rights granted by the GPL for licensed copies.
