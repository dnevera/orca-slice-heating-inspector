# /// script
# requires-python = ">=3.12"
#
# [tool.orcaslicer.plugin]
# name = "Slice Heating Inspector"
# description = "Interactive temperature timeline visualization for H2C multi-nozzle G-code. Analyzes preheat/cooldown events, toolchanges, and nozzle assignments. Compare current slice with external 3MF."
# author = "dnevera"
# version = "0.2.0"
# type = "script"
# ///
"""Slice Heating Inspector — OrcaSlicer Plugin (Script + Pipeline).

Single-window plugin with Dashboard → Plotter navigation.
Dashboard: select base slice source (file or current Orca slice), manage baseline.
Plotter: interactive temperature timeline with Compare and Pin Baseline.

Pipeline hook (SliceAutoCapture) auto-captures G-code on every slice via
psGCodePostProcess, stores parsed data in shared_state, and signals the
inspector window to refresh via a tiny 'slice_ready' postMessage.
The JS handler bounces it back as 'analyze_current' → Python reopens the
window with fresh data on the UI thread (close + create_window = on top).
"""
import os
import threading

import orca

from .thermal_plotter import (
    parse_file_data,
    parse_file_data_from_gcode,
    generate_html,
)
from . import shared_state



def _load_dashboard_template():
    """Load dashboard HTML template from dashboard.html."""
    path = os.path.join(os.path.dirname(__file__), "dashboard.html")
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


class SliceHeatingInspector(orca.script.ScriptPluginCapabilityBase):
    """Script capability: single-window temperature timeline inspector."""

    def __init__(self):
        super().__init__()
        self._window = None
        self._window_gen = 0        # generation counter for on_close safety
        # Row data: what's currently displayed
        self._row1_data = None      # data dict for Row 1
        self._row1_name = None      # filename for Row 1
        self._row2_data = None      # data dict for Row 2
        self._row2_name = None      # filename for Row 2
        # Compare file preserved across re-slices
        self._compare_data = None
        self._compare_name = None

    def get_name(self):
        return "Slice Heating Inspector"

    def execute(self):
        """Called when user clicks 'Run' in the Plugins dialog."""
        if self._window is not None and self._window.is_open():
            self._navigate_to_dashboard()
            return orca.ExecutionResult.success("Dashboard refreshed")

        # If current slice data exists, go straight to plotter
        cur_data, cur_name = shared_state.state.get_current()
        if cur_data:
            self._show_single(cur_data, cur_name, source="current")
        else:
            self._create_window(self._build_dashboard_html())
        return orca.ExecutionResult.success("Inspector opened")

    def _make_on_close(self, gen):
        """Create a generation-scoped on_close callback."""
        def on_close():
            if self._window_gen == gen:
                self._window = None
                shared_state.state.set_inspector_window(None)
        return on_close

    def _on_message(self, data):
        """Central message router for all JS → Python commands."""
        try:
            self._on_message_inner(data)
        except Exception as exc:
            self._post({"command": "error",
                        "message": f"Plugin error: {exc}"})

    def _on_message_inner(self, data):
        if not isinstance(data, dict):
            return
        command = data.get("command")

        if command == "analyze":
            name = data.get("name", "unknown")
            data_b64 = data.get("data_b64", "")
            if data_b64:
                threading.Thread(
                    target=self._analyze_from_b64,
                    args=(name, data_b64),
                    daemon=True,
                ).start()
            else:
                self._post({"command": "error", "message": "No file data received"})

        elif command == "analyze_current":
            self._handle_analyze_current()

        elif command == "go_dashboard":
            self._navigate_to_dashboard()

        elif command == "pin_baseline":
            self._handle_pin(data.get("file_num", 1))

        elif command == "clear_baseline":
            self._handle_unpin()

        elif command == "compare":
            name = data.get("name", "unknown")
            data_b64 = data.get("data_b64", "")
            if data_b64 and self._row1_data:
                threading.Thread(
                    target=self._do_compare_from_b64,
                    args=(name, data_b64),
                    daemon=True,
                ).start()

    # ── Core display methods ──────────────────────────────────────────

    def _show_single(self, f_data, name, source="file"):
        """Show a single file in plotter view."""
        st = shared_state.state
        self._row1_data = f_data
        self._row1_name = name
        self._row2_data = None
        self._row2_name = None

        pin_state = "pinned" if (st.has_baseline and st.baseline_name == name) else "can_pin"
        f1_source = self._source_with_pin(source, name)

        html = generate_html(f_data, f1_source=f1_source,
                             f1_pin_state=pin_state)
        self._open_html(html, title=f"Slice Heating Inspector — {name}")

    def _show_comparison(self, f1_data, f1_name, f1_source,
                         f2_data, f2_name, f2_source,
                         f1_pin="none", f2_pin="none"):
        """Show two files in comparison view."""
        self._row1_data = f1_data
        self._row1_name = f1_name
        self._row2_data = f2_data
        self._row2_name = f2_name

        html = generate_html(f1_data, f2_data,
                             f1_source=f1_source, f2_source=f2_source,
                             f1_pin_state=f1_pin, f2_pin_state=f2_pin)
        title = f"Slice Heating Inspector — {f1_name}"
        self._open_html(html, title=title, width=1400, height=900)

    # ── Handlers ──────────────────────────────────────────────────────

    def _handle_analyze_current(self):
        """Handle new slice from Orca pipeline."""
        cur_data, cur_name = shared_state.state.get_current()
        if not cur_data:
            self._post({"command": "error",
                        "message": "No current slice — slice a project first"})
            return

        st = shared_state.state
        if st.has_baseline:
            # Fixed base mode: pinned base = Row1 (always first), new slice = Row2
            bl_data, bl_name = st.get_baseline()
            self._show_comparison(
                bl_data, bl_name, "pinned",
                cur_data, cur_name, "current",
                f1_pin="pinned", f2_pin="can_pin")
        elif self._row1_data and self._row1_name:
            # Rotation mode: previous → Row2, new → Row1
            prev_data = self._row1_data
            prev_name = self._row1_name
            self._show_comparison(
                cur_data, cur_name, "current",
                prev_data, prev_name, "previous",
                f1_pin="can_pin", f2_pin="can_pin")
        else:
            # First slice — single view
            self._show_single(cur_data, cur_name, source="current")

    def _handle_pin(self, file_num):
        """Pin the specified row as baseline — in-place, no window reload."""
        if file_num == 2 and self._row2_data:
            pin_data, pin_name = self._row2_data, self._row2_name
        else:
            pin_data, pin_name = self._row1_data, self._row1_name

        if not pin_data:
            return

        shared_state.state.set_baseline(pin_data, pin_name)

        # Just update pin states in JS — no window close/reopen
        # Pinned row = "pinned", other row = "can_pin" (switchable)
        if file_num == 1:
            f1_pin = "pinned"
            f2_pin = "can_pin" if self._row2_data else "none"
        else:
            f1_pin = "can_pin" if self._row1_data else "none"
            f2_pin = "pinned"
        self._post({"command": "update_pin_states",
                    "f1_pin_state": f1_pin, "f2_pin_state": f2_pin})

    def _handle_unpin(self):
        """Clear baseline — in-place, no window reload."""
        shared_state.state.clear_baseline()

        # Both rows become can_pin (or can_pin for single)
        f1_pin = "can_pin" if self._row1_data else "none"
        f2_pin = "can_pin" if self._row2_data else "none"
        self._post({"command": "update_pin_states",
                    "f1_pin_state": f1_pin, "f2_pin_state": f2_pin})

    # ── Helpers ───────────────────────────────────────────────────────

    def _source_with_pin(self, base_source, name):
        """Add 'current_pinned' if this file is both current and pinned."""
        st = shared_state.state
        if st.has_baseline and st.baseline_name == name and base_source == "current":
            return "current_pinned"
        return base_source

    def _guess_source(self, name):
        """Guess source label from name."""
        cur_data, cur_name = shared_state.state.get_current()
        if cur_name and cur_name == name:
            return "current"
        return "file"

    def _row2_source_label(self):
        """Determine source label for Row 2 based on context."""
        if self._compare_name and self._row2_name == self._compare_name:
            return "compare"
        cur_data, cur_name = shared_state.state.get_current()
        if cur_name and self._row2_name == cur_name:
            return "current"
        return "previous"

    def _post(self, msg):
        """Post a message to JS (thread-safe via orca runtime)."""
        if self._window and self._window.is_open():
            self._window.post(msg)

    def _create_window(self, html, title="Slice Heating Inspector",
                       width=1200, height=800):
        """Create a new window with generation-scoped on_close."""
        self._window_gen += 1
        self._window = orca.host.ui.create_window(
            html=html,
            title=title,
            width=width,
            height=height,
            on_message=self._on_message,
            on_close=self._make_on_close(self._window_gen),
        )
        shared_state.state.set_inspector_window(self._window)

    def _open_html(self, html, title="Slice Heating Inspector",
                   width=1200, height=800):
        """Close current window, open new one with given HTML."""
        if self._window and self._window.is_open():
            self._window.close()
        self._create_window(html, title, width, height)

    def _navigate_to_dashboard(self):
        self._open_html(self._build_dashboard_html())

    # ── Dashboard builder ─────────────────────────────────────────────

    def _build_dashboard_html(self):
        """Generate Dashboard HTML reflecting current plugin state."""
        st = shared_state.state

        # Baseline section
        if st.has_baseline:
            bl_name = st.baseline_name or "unnamed"
            baseline_section = (
                '<div class="baseline-box">'
                '<span class="bl-label">\U0001f4cc Baseline:</span>'
                f'<span class="bl-name">{bl_name}</span>'
                '<button class="bl-clear" onclick="clearBaseline()">\u2715</button>'
                '</div>'
            )
        else:
            baseline_section = (
                '<div class="baseline-box empty">'
                '<span class="bl-label">No baseline set \u2014 pin from plotter view</span>'
                '</div>'
            )

        # Current OrcaSlicer slice option — no internal paths in UI
        current_option = (
            '<option value="current">'
            '\U0001f4ca Current OrcaSlicer Slice</option>'
        )

        return (_load_dashboard_template()
                .replace("%CURRENT_OPTION%", current_option)
                .replace("%BASELINE_SECTION%", baseline_section))

    # ── Analysis (background threads) ─────────────────────────────────

    def _analyze_from_b64(self, filename, data_b64):
        """Background thread: decode base64 file, parse, open plotter window."""
        import base64
        import tempfile

        raw = base64.b64decode(data_b64)
        ext = os.path.splitext(filename)[1].lower()

        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(raw)
            tmp_path = tmp.name

        try:
            if ext == ".3mf":
                f_data = parse_file_data(tmp_path)
            elif ext == ".gcode":
                f_data = parse_file_data_from_gcode(tmp_path, {})
            else:
                self._post({"command": "error",
                            "message": f"Unsupported format: {ext}"})
                return

            if not f_data:
                self._post({"command": "error",
                            "message": "Failed to parse file"})
                return

            f_data["filename"] = filename

            # Check if baseline exists → show comparison
            st = shared_state.state
            if st.has_baseline:
                bl_data, bl_name = st.get_baseline()
                self._compare_data = f_data
                self._compare_name = filename
                self._show_comparison(
                    bl_data, bl_name, "pinned",
                    f_data, filename, "compare",
                    f1_pin="pinned", f2_pin="can_pin")
            else:
                self._show_single(f_data, filename, source="file")
        except Exception as exc:
            self._post({"command": "error",
                        "message": f"Analysis error: {exc}"})
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    def _do_compare_from_b64(self, filename, data_b64):
        """Background thread: parse comparison file, open comparison window."""
        import base64
        import tempfile

        raw = base64.b64decode(data_b64)
        ext = os.path.splitext(filename)[1].lower()

        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(raw)
            tmp_path = tmp.name

        try:
            if ext == ".3mf":
                f2_data = parse_file_data(tmp_path)
            elif ext == ".gcode":
                f2_data = parse_file_data_from_gcode(tmp_path, {})
            else:
                return

            if not f2_data or not self._row1_data:
                return

            f2_data["filename"] = filename
            self._compare_data = f2_data
            self._compare_name = filename

            st = shared_state.state
            if st.has_baseline:
                # Base vs compare
                bl_data, bl_name = st.get_baseline()
                self._show_comparison(
                    bl_data, bl_name, "pinned",
                    f2_data, filename, "compare",
                    f1_pin="pinned", f2_pin="can_pin")
            else:
                # Current vs compare (no pin, both can be pinned)
                self._show_comparison(
                    self._row1_data, self._row1_name,
                    self._guess_source(self._row1_name),
                    f2_data, filename, "compare",
                    f1_pin="can_pin", f2_pin="can_pin")
        except Exception as exc:
            self._post({"command": "error",
                        "message": f"Analysis error: {exc}"})
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


# ── Pipeline auto-capture (optional — requires orca.slicing support) ──────
_SliceAutoCapture = None
try:
    class SliceAutoCapture(orca.slicing.SlicingPipelineCapabilityBase):
        """Pipeline capability: auto-captures G-code on every Slice."""

        def __init__(self):
            super().__init__()

        def get_name(self):
            return "Slice Heating Inspector \u2014 Auto Capture"

        def execute(self, ctx):
            # Only act at the final G-code post-process step
            if ctx.step != orca.slicing.Step.psGCodePostProcess:
                return orca.ExecutionResult.success("skip")

            gcode_path = ctx.gcode_path
            if not gcode_path or not os.path.isfile(gcode_path):
                return orca.ExecutionResult.success("no gcode file")

            try:
                f_data = parse_file_data_from_gcode(gcode_path, {})
                if not f_data:
                    return orca.ExecutionResult.success("parse empty")

                # Extract clean model name — no internal temp paths in UI
                raw_name = ctx.output_name if ctx.output_name else gcode_path
                name = os.path.basename(raw_name)
                # Strip .gcode extension for cleaner display
                if name.lower().endswith('.gcode'):
                    name = name[:-6]
                f_data["filename"] = name

                # Store parsed data — "Current OrcaSlicer Slice" in shared state
                shared_state.state.set_current(f_data, name)

                # Signal the inspector window (tiny message, no HTML payload).
                window = shared_state.state.get_inspector_window()
                if window is not None and window.is_open():
                    window.post({"command": "slice_ready", "name": name})

            except Exception as exc:
                shared_state.state.set_current(
                    None, f"Pipeline error: {exc}")

            return orca.ExecutionResult.success("captured")

    _SliceAutoCapture = SliceAutoCapture
except AttributeError:
    pass  # orca.slicing not available in this build


@orca.plugin
class SliceHeatingInspectorPackage(orca.base):
    def register_capabilities(self):
        orca.register_capability(SliceHeatingInspector)
        if _SliceAutoCapture is not None:
            orca.register_capability(_SliceAutoCapture)
