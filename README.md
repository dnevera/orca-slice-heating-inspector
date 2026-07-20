# Orca Slice Heating Inspector

OrcaSlicer plugin for interactive visualization of temperature profiles, toolchange events, and flush analysis from sliced G-code.

## Features

- 📊 Interactive temperature timeline (Plotly.js)
- 🔄 Toolchange event detection and analysis
- 🎨 Per-nozzle heating/cooling visualization
- ⏱️ Flush volume and timing analysis
- 📈 Side-by-side comparison of two slices

## Installation

### From Orca Cloud
1. Open OrcaSlicer → File → Plugins
2. Switch to "Explore" tab
3. Find "Slice Heating Inspector" → Subscribe → Install

### Local Install
1. Open OrcaSlicer → File → Plugins
2. Click "Install local plugin"
3. Select `orca_slice_heating_inspector.py`

## Usage

### As Slicing Pipeline Plugin (auto)
1. Go to Process Settings → Others → Slicing Pipeline Plugin
2. Select "Slice Heating Inspector"
3. Slice your model — the inspector window opens automatically

### As Script Plugin (manual)
1. Open Plugins dialog
2. Click ▶ Run on "Slice Heating Inspector"

## License

MIT
