#!/usr/bin/env python3
"""Local test runner for Slice Heating Inspector.

Generates HTML from a 3MF or .gcode file and opens it in the default browser.
No OrcaSlicer required — runs the full pipeline standalone.

Usage:
    python3 test_local.py /path/to/file.3mf
    python3 test_local.py /path/to/file.gcode
    python3 test_local.py file1.3mf file2.3mf          # comparison mode
"""
import sys
import os
import webbrowser
import tempfile

# Add current dir to path so we can import the modules directly
sys.path.insert(0, os.path.dirname(__file__))

from thermal_plotter import (
    parse_file_data,
    parse_file_data_from_gcode,
    generate_html,
)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    files = sys.argv[1:]

    def load(path):
        path = os.path.expanduser(path)
        if not os.path.exists(path):
            print(f"❌ File not found: {path}")
            sys.exit(1)
        print(f"📂 Parsing: {os.path.basename(path)}")
        if path.endswith('.3mf'):
            return parse_file_data(path)
        elif path.endswith('.gcode'):
            return parse_file_data_from_gcode(path)
        else:
            print(f"❌ Unsupported format: {path} (need .3mf or .gcode)")
            sys.exit(1)

    f1_data = load(files[0])
    if f1_data is None:
        print("❌ Failed to parse file 1")
        sys.exit(1)

    f2_data = None
    if len(files) > 1:
        f2_data = load(files[1])
        if f2_data is None:
            print("❌ Failed to parse file 2")
            sys.exit(1)

    # Print summary
    et = f1_data.get('exhaust_track', [])
    print(f"✅ File 1: {f1_data['filename']}")
    print(f"   Duration: {f1_data['total_duration']:.0f}s | Track points: {len(f1_data['track'])}")
    print(f"   Exhaust events: {len(et)}")
    if et:
        phases = {}
        for p in et:
            phases[p['phase']] = phases.get(p['phase'], 0) + 1
        print(f"   Exhaust phases: {phases}")

    if f2_data:
        et2 = f2_data.get('exhaust_track', [])
        print(f"✅ File 2: {f2_data['filename']}")
        print(f"   Duration: {f2_data['total_duration']:.0f}s | Exhaust events: {len(et2)}")

    # Generate HTML
    html = generate_html(f1_data, f2_data, f1_source="file", f2_source="file")

    # Write to temp file and open
    out_path = os.path.join(tempfile.gettempdir(), "heating_inspector_test.html")
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f"\n🌐 Opening: {out_path}")
    webbrowser.open(f"file://{out_path}")


if __name__ == "__main__":
    main()
