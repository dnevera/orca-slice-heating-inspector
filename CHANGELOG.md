# Changelog

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
