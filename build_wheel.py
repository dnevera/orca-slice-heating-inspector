#!/usr/bin/env python3
"""Build .whl package for Slice Heating Inspector OrcaSlicer plugin.

Creates a standard Python wheel (.whl) that OrcaSlicer can install
via the "Install local plugin" dialog.

Usage:
    python3 build_wheel.py          # builds into dist/
    python3 build_wheel.py --clean  # removes dist/ and build artifacts
"""
import argparse
import csv
import hashlib
import io
import os
import sys
import zipfile

# ── Package metadata ──────────────────────────────────────────────────────

DISPLAY_NAME = "Slice Heating Inspector"
IMPORT_NAME = "orca_slice_heating_inspector"
VERSION = "0.2.1"
SUMMARY = (
    "Interactive temperature timeline visualization for H2C multi-nozzle G-code. "
    "Analyzes preheat/cooldown events, toolchanges, and nozzle assignments."
)
AUTHOR = "dnevera"

# Files that form the plugin package (relative to repo root)
PACKAGE_FILES = [
    "orca_slice_heating_inspector.py",  # entry point → __init__.py
    "gcode_parser.py",
    "thermal_plotter.py",
    "shared_state.py",
    "dashboard.html",
    "template.html",
    "CHANGELOG.md",
]


# ── Wheel construction ────────────────────────────────────────────────────

def sha256_digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_metadata() -> str:
    repo_root = os.path.dirname(os.path.abspath(__file__))
    readme_path = os.path.join(repo_root, "README.md")
    long_desc = ""
    if os.path.exists(readme_path):
        with open(readme_path, "r", encoding="utf-8") as f:
            long_desc = f.read()

    header = (
        f"Metadata-Version: 2.4\n"
        f"Name: {DISPLAY_NAME}\n"
        f"Version: {VERSION}\n"
        f"Summary: {SUMMARY}\n"
        f"Author: {AUTHOR}\n"
        f"Import-Name: {IMPORT_NAME}\n"
        f"Requires-Python: >=3.12\n"
        f"Description-Content-Type: text/markdown\n"
    )
    if long_desc:
        header += f"\n{long_desc}\n"
    return header


def build_wheel_info() -> str:
    return (
        "Wheel-Version: 1.0\n"
        "Generator: build_wheel.py\n"
        "Root-Is-Purelib: true\n"
        "Tag: py3-none-any\n"
    )


def build_top_level() -> str:
    return f"{IMPORT_NAME}\n"


def build_wheel(output_dir: str) -> str:
    """Create the .whl file in output_dir. Returns path to the created file."""
    os.makedirs(output_dir, exist_ok=True)

    repo_root = os.path.dirname(os.path.abspath(__file__))
    dist_info = f"{IMPORT_NAME}-{VERSION}.dist-info"
    whl_filename = f"{IMPORT_NAME}-{VERSION}-py3-none-any.whl"
    whl_path = os.path.join(output_dir, whl_filename)

    record_rows = []

    with zipfile.ZipFile(whl_path, "w", compression=zipfile.ZIP_DEFLATED) as whl:

        # ── Package files ──
        for src_file in PACKAGE_FILES:
            src_path = os.path.join(repo_root, src_file)
            if not os.path.exists(src_path):
                print(f"ERROR: missing source file: {src_path}", file=sys.stderr)
                sys.exit(1)

            with open(src_path, "rb") as f:
                data = f.read()

            # Entry point becomes __init__.py inside the package
            if src_file == "orca_slice_heating_inspector.py":
                arc_name = f"{IMPORT_NAME}/__init__.py"
            else:
                arc_name = f"{IMPORT_NAME}/{src_file}"

            whl.writestr(arc_name, data)
            digest = sha256_digest(data)
            record_rows.append((arc_name, f"sha256={digest}", str(len(data))))

        # ── dist-info/METADATA ──
        metadata_content = build_metadata().encode("utf-8")
        metadata_arc = f"{dist_info}/METADATA"
        whl.writestr(metadata_arc, metadata_content)
        record_rows.append((metadata_arc, f"sha256={sha256_digest(metadata_content)}",
                            str(len(metadata_content))))

        # ── dist-info/WHEEL ──
        wheel_content = build_wheel_info().encode("utf-8")
        wheel_arc = f"{dist_info}/WHEEL"
        whl.writestr(wheel_arc, wheel_content)
        record_rows.append((wheel_arc, f"sha256={sha256_digest(wheel_content)}",
                            str(len(wheel_content))))

        # ── dist-info/top_level.txt ──
        top_level_content = build_top_level().encode("utf-8")
        top_level_arc = f"{dist_info}/top_level.txt"
        whl.writestr(top_level_arc, top_level_content)
        record_rows.append((top_level_arc, f"sha256={sha256_digest(top_level_content)}",
                            str(len(top_level_content))))

        # ── dist-info/RECORD (self-referencing, no hash) ──
        record_arc = f"{dist_info}/RECORD"
        record_rows.append((record_arc, "", ""))

        buf = io.StringIO()
        writer = csv.writer(buf)
        for row in record_rows:
            writer.writerow(row)
        record_content = buf.getvalue().encode("utf-8")
        whl.writestr(record_arc, record_content)

    return whl_path


def clean(output_dir: str):
    """Remove build artifacts."""
    import shutil
    if os.path.exists(output_dir):
        shutil.rmtree(output_dir)
        print(f"Removed {output_dir}/")


def main():
    parser = argparse.ArgumentParser(description="Build .whl for Slice Heating Inspector plugin")
    parser.add_argument("--clean", action="store_true", help="Remove dist/ directory")
    parser.add_argument("--output", default="dist", help="Output directory (default: dist/)")
    args = parser.parse_args()

    if args.clean:
        clean(args.output)
        return

    whl_path = build_wheel(args.output)
    size_kb = os.path.getsize(whl_path) / 1024
    print(f"✅ Built: {whl_path} ({size_kb:.0f} KB)")
    print(f"   Install in OrcaSlicer: File → Plugins → Install local plugin → select {os.path.basename(whl_path)}")


if __name__ == "__main__":
    main()
