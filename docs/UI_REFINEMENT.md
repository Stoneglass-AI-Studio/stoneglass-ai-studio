# Phase 1 UI refinement

PySide6, the dark theme, the two-column Generate layout, and the UI/service/inference boundaries are retained. No inference code, GPU runtime, new runtime dependency, runtime network service, or publication is introduced by this refinement.

## Behavior

- The sidebar has one application name and the supplied logomark. It is 192 logical pixels expanded and 68 collapsed. The control supports Tab/Space; Ctrl+B toggles from elsewhere in the window. Navigation retains keyboard selection, tooltips, and accessible names in both states. Collapse state autosaves and restores with existing version 1 settings; older settings default to expanded.
- Resolution choices are 512×512, 768×1024, 1024×768, and 1024×1024. Exact aspect choices are 1:1, 3:2, 2:3, 16:9, and 9:16. Ratio sizing selects the nearest pixel area on a 64 px grid within a maximum automatic area of 1,048,576 pixels (1024×1024). For example, changing 1024×1024 to 16:9 selects 1024×576, and 3:2 selects 1152×768. Very small sizes may increase to meet the exact grid ratio. It does not silently round an approximate ratio or claim a model-specific VRAM guarantee.
- Both dimension fields update together before preferences notify/autosave. Preset selections never change prompts, steps, guidance, seed, or unrelated preferences. Manual input retains the existing validation and rounds down to a multiple of 64 when committed. Preset labels derive from dimensions; no redundant preset identity is persisted. A 768×1024 resolution has a Custom aspect because 3:4 is not one of the listed aspect choices. Valid dimensions, including larger manually chosen sizes, survive all page/sidebar transitions and restart. Only explicit preset selection applies the automatic area budget; reselecting a matching aspect also applies it.
- `ImagePreview` owns an empty-state viewport stack, a hidden empty toolbar, and status text. Future real zoom/fit/save/edit actions can use these extension points. No images are synthesized or loaded, and no nonfunctional actions are shown as active.
- Hardware fields separate OS, compute backend status, VRAM status, GPU name, vendor, and driver, including multiple adapters. Refresh replaces old adapter fields. The original detection service is unchanged; VRAM remains unreported. Storage paths wrap and can be selected/copied, and privacy statements are separate rows. Save preferences remains visible outside the scroll area.
- Models and Gallery retain unavailable placeholders with consistent card spacing. Generate remains disabled. Small windows use vertical scrolling for settings/editors while preserving both columns and visible primary actions.

## Files changed or added

Paths below are relative to the repository root.

| Area | Files |
| --- | --- |
| Settings and dimension rules | `src/stoneglass/domain/settings.py`, `src/stoneglass/domain/dimensions.py` |
| Window and navigation | `src/stoneglass/ui/main_window.py`, `src/stoneglass/ui/sidebar.py`, `src/stoneglass/ui/navigation_icons.py` |
| Generation and preview | `src/stoneglass/ui/generate_page.py`, `src/stoneglass/ui/dimension_controls.py`, `src/stoneglass/ui/image_preview.py` |
| Shared visuals, Settings, placeholders | `src/stoneglass/ui/components.py`, `src/stoneglass/ui/settings_page.py`, `src/stoneglass/ui/placeholder_page.py`, `src/stoneglass/ui/theme.qss` |
| Supplied mark and package data | `src/stoneglass/ui/assets/stoneglass-logomark.jpg`, `src/stoneglass/ui/assets/README.md`, `pyproject.toml` |
| Tests | `tests/test_application.py`, `tests/test_settings.py`, `tests/test_dimensions.py`, `tests/test_sidebar.py` |
| Documentation | `README.md`, `THIRD_PARTY_NOTICES.md`, `docs/UI_REFINEMENT.md` |

The PNG reference assets and both logomark JPEGs have received metadata-only publication cleanup. Image pixels, dimensions, transparency, and color information are preserved; the JPEG copies remain identical. No inference backend or hardware detection implementation was modified.

## Verification

Run from the repository root:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m pip check
```

Validation on 2026-11-06: **50 tests passed offscreen, four branding tests passed with native Windows Qt**, and `pip check` reported no broken requirements. The full suite includes sidebar keyboard/collapse behavior and persistence, approved artwork integrity and fitted aspect, missing-logo fallback, resolution choices, capped exact aspect sizing, committed manual edits, atomic dimension notifications, preset/custom restoration, unrelated-setting and prompt preservation, large manual sizes across page transitions/restart, separate/multiple GPU fields, long storage paths, caption/value non-overlap, and minimum-window horizontal-scroll checks in both sidebar states. Existing initialization, privacy, settings, hardware, cancellation, and shutdown checks remain included.

Native Windows visual review covers all four pages, expanded/collapsed sidebars, and 1280×820 and 960×640 logical-pixel windows. Generate's editor and Settings use vertical scrolling when necessary. A local wheel check verifies that the existing mark is packaged unchanged and can be loaded independently of the repository's working directory. Test data, captures, and built wheels stay under ignored `.test-artifacts/`.

On the reviewed Windows/Qt 6.12 build, `QWidget.grab()` sometimes omitted pixmaps after sidebar transitions. Native-window captures through `QScreen.grabWindow()` confirmed that the displayed mark and navigation glyphs remain visible. This capture-path discrepancy did not require an application change.

## Current limits

This is Phase 1 only. Model discovery/loading/downloads, real image generation, gallery indexing/browsing, and preview image actions remain unavailable. The minimum supported window is still 960×640 logical pixels. Width/height validation still uses the existing bounds and 64 px increments; ratios outside the listed choices display Custom. The project owner has approved branding inclusion, and the JPEG and PNG metadata cleanup is complete. The remaining dependency-artifact notice review in `THIRD_PARTY_NOTICES.md` applies to future redistribution of those dependencies and packaged applications. Source publication remains a separate maintainer approval. Nothing is published by this change.
