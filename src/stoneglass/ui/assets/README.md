# Stoneglass branding assets

The project owner has approved the Stoneglass logomark, wordmark, and banner for inclusion in this repository.

`stoneglass-logomark.jpg` is the packaged logomark, identical to the root `stoneglass_logomark.jpg`. Nonessential metadata has been removed from both copies. Image pixels, dimensions, orientation, color information, and sidebar appearance are preserved. The approved file hash is checked in `tests/test_sidebar.py`.

The sidebar displays the mark alongside the application name and retains it when collapsed. It loads `assets/stoneglass-logomark.jpg` relative to the `stoneglass.ui` package, including in a built wheel. If the mark is missing or unreadable, the expanded sidebar uses the text “Stoneglass” and the collapsed sidebar uses “SG”. Keep approved replacement assets at this packaged path and preserve their aspect ratio.

The root `Stoneglass_Logo.png` and `Stoneglass_Banner.png` are reference assets and are not loaded or bundled by the application. Both have received metadata-only cleanup without changing image pixels, dimensions, transparency, or color information. Their approved file hashes and dimensions are checked in `tests/test_sidebar.py`.

Attribution: Stoneglass project. See [THIRD_PARTY_NOTICES.md](../../../../THIRD_PARTY_NOTICES.md) for approval and dependency licensing scope. No additional trademark rights are granted by repository inclusion.
