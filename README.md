# Slice Heating Inspector — OrcaSlicer Plugin

Interactive temperature timeline visualization for multi-nozzle G-code.

Analyzes preheat/cooldown events, toolchanges, nozzle assignments, and thermal profiles.
Canvas-based zoom/pan/hover inspector with side-by-side comparison support.

## Features

- **Temperature Timeline** — Interactive Canvas graph with per-heater temperature curves
- **Preheat/Cooldown Detection** — Highlights pre-heating and standby cooldown zones
- **Toolchange Markers** — Nozzle change / wipe tower / carousel zones visualized
- **Comparison Mode** — Compare current OrcaSlicer slice with an external 3MF (e.g., BambuStudio)
- **Vortek Nozzle Tracks** — Mini panels showing individual nozzle thermal activity
- **Zoom/Pan/Hover** — Scroll to zoom, drag to pan, hover for synchronized tooltip

## Plugin Type

**Script** — manual-run via the **"Run"** button in the Plugins dialog.

Click "Run" → file picker opens → select `.gcode` or `.3mf` → interactive temperature timeline is displayed in a webview window.

---

## Installation

### Method 1: Install from Local File

1. Download or clone this repository:
   ```bash
   git clone https://github.com/dnevera/orca-slice-heating-inspector.git
   ```
2. Open **OrcaSlicer** (v2.5+)
3. Go to **File → Plugins** (or click the **Plugins** button in the toolbar)
4. Click **"Install Local Plugin"** (the ⊕ / plus button)
5. In the file dialog, select the `.whl` file:
   ```
   dist/orca_slice_heating_inspector-0.1.0-py3-none-any.whl
   ```
   Build it first with `python3 build_wheel.py`
6. OrcaSlicer copies the plugin into its internal `orca_plugins/` directory and loads it
7. Enable the plugin toggle in the Plugins dialog

### Method 2: Install from OrcaSlicer Cloud Store

1. Open **OrcaSlicer** (v2.5+)
2. Go to **File → Plugins**
3. Switch to the **"Explore"** tab
4. Search for **"Slice Heating Inspector"**
5. Click **"Install"**
6. Enable the plugin toggle

> **Note:** Cloud installation requires being logged into your OrcaSlicer account.

---

## Uninstallation

### Local Plugin

1. Open **File → Plugins**
2. Right-click **"Slice Heating Inspector"** in the plugin list
3. Select **"Delete"** from the context menu
4. Confirm deletion

The plugin files are removed from:
```
<OrcaSlicer data dir>/orca_plugins/orca_slice_heating_inspector-0.1.0-py3-none-any.whl/
```

Platform-specific data directories:
| OS | Path |
|----|------|
| macOS | `~/Library/Application Support/OrcaSlicer/orca_plugins/` |
| Windows | `%APPDATA%\OrcaSlicer\orca_plugins\` |
| Linux | `~/.config/OrcaSlicer/orca_plugins/` |

### Cloud Plugin

1. Open **File → Plugins**
2. Find **"Slice Heating Inspector"**
3. Click **"Unsubscribe"** (removes cloud subscription + local files)

---

## Usage

1. Open **File → Plugins**
2. Expand **"Slice Heating Inspector"** and check the capability checkbox
3. Click the **▶ Run** button
4. In the file picker, select a `.gcode` or `.3mf` file
5. Interactive temperature timeline opens
6. Click **"Compare"** in the timeline to load a second file for side-by-side analysis

---

## Files

| File | Lines | Description |
|------|-------|-------------|
| `orca_slice_heating_inspector.py` | 134 | Plugin entry point — PEP 723 manifest, capability class, UI bridge |
| `thermal_plotter.py` | 1747 | Timeline builder, data parsers (3MF + raw gcode), HTML template |
| `gcode_parser.py` | 452 | G-code parser — M104/M109/M620/M73/T-commands extraction |

## Requirements

- OrcaSlicer **v2.5+** (with Plugin support)
- Python ≥ 3.12 (bundled with OrcaSlicer)

## Author

Denis Sibilev ([@dnevera](https://github.com/dnevera))
