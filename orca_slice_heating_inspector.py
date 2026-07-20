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
        self._current_data = None   # parsed data for currently viewed file
        self._current_name = None   # filename of currently viewed file

    def get_name(self):
        return "Slice Heating Inspector"

    def execute(self):
        """Called when user clicks 'Run' in the Plugins dialog."""
        if self._window is not None and self._window.is_open():
            self._navigate_to_dashboard()
            return orca.ExecutionResult.success("Dashboard refreshed")

        self._create_window(self._build_dashboard_html())
        return orca.ExecutionResult.success("Dashboard opened")

    def _make_on_close(self, gen):
        """Create a generation-scoped on_close callback.

        wxWidgets fires on_close asynchronously (next event loop iteration).
        Without generation check, closing window A would clear the reference
        to the NEWLY created window B — breaking pipeline auto-refresh.
        """
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
            # Orca runtime swallows exceptions — post error to JS for visibility
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
            cur_data, cur_name = shared_state.state.get_current()
            if cur_data:
                self._current_data = cur_data
                self._current_name = cur_name
                html = generate_html(cur_data)
                self._open_html(html, title=f"Slice Heating Inspector — {cur_name}")
            else:
                self._post({"command": "error",
                            "message": "No current slice — slice a project first"})

        elif command == "go_dashboard":
            self._navigate_to_dashboard()

        elif command == "pin_baseline":
            if self._current_data and self._current_name:
                shared_state.state.set_baseline(
                    self._current_data, self._current_name)
                self._post({"command": "baseline_pinned",
                            "name": self._current_name})

        elif command == "clear_baseline":
            shared_state.state.clear_baseline()
            self._navigate_to_dashboard()

        elif command == "compare":
            name = data.get("name", "unknown")
            data_b64 = data.get("data_b64", "")
            if data_b64 and self._current_data:
                threading.Thread(
                    target=self._do_compare_from_b64,
                    args=(name, data_b64),
                    daemon=True,
                ).start()

    # ── Helpers ───────────────────────────────────────────────────────

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
        """Close current window, open new one with given HTML.

        wxWebView's document.write via post is unreliable for large HTML.
        The proven pattern: close + create_window.
        Generation counter prevents async _on_close from clearing the new window.
        """
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
                '<span class="bl-label">📌 Baseline:</span>'
                f'<span class="bl-name">{bl_name}</span>'
                '<button class="bl-clear" onclick="clearBaseline()">✕</button>'
                '</div>'
            )
        else:
            baseline_section = (
                '<div class="baseline-box empty">'
                '<span class="bl-label">No baseline set — pin from plotter view</span>'
                '</div>'
            )

        # Current OrcaSlicer slice option — no internal paths in UI
        current_option = (
            '<option value="current">'
            '📊 Current OrcaSlicer Slice</option>'
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
            self._current_data = f_data
            self._current_name = filename

            html = generate_html(f_data)
            self._open_html(html, title=f"Slice Heating Inspector — {filename}")
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

            if not f2_data or not self._current_data:
                return

            f2_data["filename"] = filename
            html = generate_html(self._current_data, f2_data)
            title = f"Slice Heating Inspector — {self._current_name} vs {filename}"
            self._open_html(html, title=title, width=1400, height=900)
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
        """Pipeline capability: auto-captures G-code on every Slice.

        Hooks into psGCodePostProcess — fired at the end of background
        slicing (for BBL printers this runs inside process_fff).
        Reads ctx.gcode_path, parses temperature events, stores in
        shared_state. If inspector window is open, auto-navigates
        to updated plotter (live reload on re-slice).
        """

        def __init__(self):
            super().__init__()

        def get_name(self):
            return "Slice Heating Inspector — Auto Capture"

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
                # window.post() is safe from slicing thread (CallAfter, non-blocking).
                # JS receives slice_ready → bounces back analyze_current → Python
                # handles it on UI thread via _open_html (close+create_window = on top).
                window = shared_state.state.get_inspector_window()
                if window is not None and window.is_open():
                    window.post({"command": "slice_ready", "name": name})

            except Exception as exc:
                # Store error for debugging — visible when user clicks analyze_current
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
