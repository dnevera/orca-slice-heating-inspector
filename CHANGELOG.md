# Changelog

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
