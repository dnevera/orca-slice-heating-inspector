# Changelog

## 0.3.2 — 2026-07-27

### Fixed
- Manifest `type` now declares both `script` and `slicing_pipeline` (was missing `slicing_pipeline`)

## 0.3.1 — 2026-07-27

### Added
- **File numbering in compare mode** — all panels (exhaust, extruder, Vortek nozzle) prefixed with `1.` / `2.` to distinguish current vs base
- **Colored dot indicator** for exhaust fan panels — cyan (current) vs pink (base)
- **Scrollable canvas** — vertical scroll when panels exceed viewport height (compare mode with many nozzles)

### Changed
- Exhaust fan line color now per-panel (cyan/pink) instead of hardcoded cyan
- Main extruder panel minimum height raised to 120px (was 70px)
- `build_wheel.py` reads version from `plugin_manifest.json` (single source of truth)

### Fixed
- Wheel event only captures inside chart area — allows native vertical scrolling in margins

## 0.3.0 — 2026-07-26

### Added
- **Exhaust Fan Track** — dedicated timeline panel showing `M106 P3` exhaust fan activity
  - Step-function visualization with phase-colored zones (startup, ramp, heating, printing, TC recovery, post-print)
  - Parses both `[exhaust-enforcer]`-tagged and native firmware fan commands
  - Interactive tooltip: fan % and current phase on hover
- `_build_exhaust_track()` — converts line-based exhaust events to time-based track
- `exhaust_track` field in parsed file data output

## 0.2.1 — 2026-07-22

### Fixed
- Dynamic Y-axis scaling — adapts to actual temperature data instead of hardcoded 250°C max (fixes ASA 275°C+ clipping)
- Temperature grid levels generated dynamically with appropriate step sizes

### Changed
- README updated: hero-style screenshots, OrcaSlicer Cloud badge, accurate file list, simplified author

## 0.2.0 — 2026-07-21

### Added
- Separate time column in header: `1:13:00 total · 1:06:42 print` with print time highlighted
- Legend highlighting: active filament row highlighted on cursor hover (bold text + subtle background)
- Pin/unpin in-place without window reload (preserves zoom/pan state)
- Both rows in comparison mode always show pin button

### Fixed
- Pin button moved to bottom-right of panel to avoid overlap with TC labels and End G-code text
- Header layout redesigned: unified slice rows with compact meta + dynamic info

## 0.1.0 — 2026-07-20

### Added
- Interactive Canvas-based temperature timeline with zoom/pan/hover
- Preheat, precool, standby, and cooldown zone visualization
- Toolchange and wipe tower markers on timeline
- Vortek nozzle track mini panels per filament
- Side-by-side comparison mode (Compare button)
- Slicer detection from G-code comments (OrcaSlicer / BambuStudio)
- Truncated filenames with tooltip showing full name
- File picker with `.gcode` and `.3mf` support
- Legend with filament colors and slicer info panel
- Synchronized tooltip across all extruder tracks

### Technical
- Script capability plugin (manual run from Plugins dialog)
- Base64 file transfer bridge (wxWebView has no file path access)
- Background thread for parsing (non-blocking UI)
- Separate `template.html` for HTML/JS canvas rendering
