# /// script
# requires-python = ">=3.12"
#
# [tool.orcaslicer.plugin]
# name = "Slice Heating Inspector"
# description = "Interactive temperature timeline visualization for H2C multi-nozzle G-code. Analyzes preheat/cooldown events, toolchanges, and nozzle assignments. Compare current slice with external 3MF."
# author = "dnevera"
# version = "0.1.0"
# type = "script"
# ///
"""Slice Heating Inspector — OrcaSlicer Plugin (Script type).

Manual-run plugin: user clicks "Run" in the Plugins dialog.
Opens a file picker for .gcode or .3mf, analyzes the temperature
profile, and displays an interactive Canvas-based timeline.
A "Compare" button lets the user pick a second file for side-by-side analysis.

Communication between HTML window and Python uses the orca bridge:
  JS → Python: window.orca.postMessage({command: "compare", path: "..."})
  Python → JS: window_handle.post({command: "comparison_data", data: {...}})
"""
import os

import orca

from .thermal_plotter import (
    parse_file_data,             # 3MF parser
    parse_file_data_from_gcode,  # raw .gcode parser
    generate_html,
)


def _build_file_picker_html():
    """HTML page with a file input for selecting .gcode or .3mf files."""
    return """<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #1e1e2e; color: #cdd6f4;
    display: flex; align-items: center; justify-content: center;
    min-height: 100vh;
  }
  .container {
    text-align: center; padding: 40px;
    background: #313244; border-radius: 16px;
    box-shadow: 0 8px 32px rgba(0,0,0,0.3);
    max-width: 520px; width: 90%;
  }
  h1 { font-size: 1.4em; margin-bottom: 8px; color: #f5c2e7; }
  p { font-size: 0.9em; color: #a6adc8; margin-bottom: 24px; }
  .pick-btn {
    border: 2px solid #585b70; border-radius: 12px;
    padding: 40px 20px; margin-bottom: 16px;
    transition: all 0.2s ease; cursor: pointer;
    background: transparent;
  }
  .pick-btn:hover {
    border-color: #89b4fa; background: rgba(137,180,250,0.08);
  }
  .pick-btn .icon { font-size: 2.5em; margin-bottom: 12px; }
  .pick-btn .label { font-size: 0.95em; color: #bac2de; }
  input[type=file] { display: none; }
  .status { font-size: 0.85em; color: #a6adc8; min-height: 1.5em; }
  .status.error { color: #f38ba8; }
</style>
</head><body>
<div class="container">
  <h1>🌡 Slice Heating Inspector</h1>
  <p>Select a G-code or 3MF file to analyze temperature profiles</p>
  <div class="pick-btn" onclick="fileInput.click()">
    <div class="icon">📂</div>
    <div class="label">Click to select file<br>
    <small>.gcode &nbsp;|&nbsp; .3mf</small></div>
  </div>
  <input type="file" id="fileInput" accept=".gcode,.3mf">
  <div class="status" id="status"></div>
</div>
<script>
const fileInput = document.getElementById('fileInput');
const status = document.getElementById('status');

fileInput.addEventListener('change', e => {
  const file = e.target.files[0];
  if (file) handleFile(file);
});

function handleFile(file) {
  const name = file.name.toLowerCase();
  if (!name.endsWith('.gcode') && !name.endsWith('.3mf')) {
    status.textContent = 'Unsupported file type. Use .gcode or .3mf';
    status.className = 'status error';
    return;
  }
  status.textContent = 'Reading: ' + file.name + '...';
  status.className = 'status';

  // wxWebView doesn't expose file paths — read content via FileReader
  const reader = new FileReader();
  reader.onload = function(e) {
    // Convert ArrayBuffer to base64
    const bytes = new Uint8Array(e.target.result);
    let binary = '';
    const chunkSize = 8192;
    for (let i = 0; i < bytes.length; i += chunkSize) {
      binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunkSize));
    }
    const b64 = btoa(binary);
    status.textContent = 'Analyzing: ' + file.name + '...';
    window.orca.postMessage({
      command: 'analyze',
      name: file.name,
      data_b64: b64
    });
  };
  reader.onerror = function() {
    status.textContent = 'Failed to read file';
    status.className = 'status error';
  };
  reader.readAsArrayBuffer(file);
}

// Listen for messages from Python
if (window.orca) {
  window.orca.onMessage = function(data) {
    if (data.command === 'error') {
      status.textContent = data.message;
      status.className = 'status error';
    } else if (data.command === 'status') {
      status.textContent = data.message;
      status.className = 'status';
    }
  };
}
</script>
</body></html>"""



class SliceHeatingInspector(orca.script.ScriptPluginCapabilityBase):
    """Script capability: manual-run temperature timeline inspector."""

    def __init__(self):
        super().__init__()
        self._window = None
        self._f1_data = None

    def get_name(self):
        return "Slice Heating Inspector"

    def execute(self):
        """Called when user clicks 'Run' in the Plugins dialog."""
        picker_html = _build_file_picker_html()

        def on_message(data):
            if not isinstance(data, dict):
                return
            command = data.get("command")

            if command == "analyze":
                name = data.get("name", "unknown")
                data_b64 = data.get("data_b64", "")
                if not data_b64:
                    if self._window and self._window.is_open():
                        self._window.post({"command": "error",
                                           "message": "No file data received"})
                    return
                import threading
                threading.Thread(
                    target=self._analyze_from_b64,
                    args=(name, data_b64),
                    daemon=True
                ).start()

            elif command == "compare":
                name = data.get("name", "unknown")
                data_b64 = data.get("data_b64", "")
                if data_b64:
                    import threading
                    threading.Thread(
                        target=self._do_compare_from_b64,
                        args=(name, data_b64),
                        daemon=True
                    ).start()

        self._window = orca.host.ui.create_window(
            html=picker_html,
            title="Slice Heating Inspector",
            width=520,
            height=420,
            on_message=on_message,
        )

        return orca.ExecutionResult.success("File picker opened")

    def _analyze_from_b64(self, filename, data_b64):
        """Decode base64 file content, save to temp, parse, and show timeline."""
        import base64
        import tempfile

        raw = base64.b64decode(data_b64)
        ext = os.path.splitext(filename)[1].lower()

        # Save to a temp file for the parsers (they expect file paths)
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(raw)
            tmp_path = tmp.name

        try:
            if ext == ".3mf":
                f1_data = parse_file_data(tmp_path)
            elif ext == ".gcode":
                f1_data = parse_file_data_from_gcode(tmp_path, {})
            else:
                if self._window and self._window.is_open():
                    self._window.post({"command": "error",
                                       "message": f"Unsupported format: {ext}"})
                return

            if not f1_data:
                if self._window and self._window.is_open():
                    self._window.post({"command": "error",
                                       "message": "Failed to parse file"})
                return

            # Override temp filename with the original user-selected filename
            f1_data["filename"] = filename

            self._f1_data = f1_data
            html = generate_html(f1_data)

            # Close picker, open timeline
            if self._window and self._window.is_open():
                self._window.close()

            def on_compare_message(msg):
                if not isinstance(msg, dict):
                    return
                if msg.get("command") == "compare":
                    name = msg.get("name", "unknown")
                    b64 = msg.get("data_b64", "")
                    if b64:
                        # Offload heavy parsing to background thread
                        import threading
                        threading.Thread(
                            target=self._do_compare_from_b64,
                            args=(name, b64, filename),
                            daemon=True
                        ).start()

            self._window = orca.host.ui.create_window(
                html=html,
                title=f"Slice Heating Inspector — {filename}",
                width=1200,
                height=800,
                on_message=on_compare_message,
            )
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


    def _do_compare_from_b64(self, filename, data_b64, original_filename=""):
        """Decode base64 comparison file, parse, and open new comparison window.

        Runs in a background thread — must NOT call UI directly.
        Uses orca.host.ui which marshals calls to the UI thread.
        """
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

            if not f2_data or not self._f1_data:
                return

            # Override temp filename with the original user-selected filename
            f2_data["filename"] = filename

            html = generate_html(self._f1_data, f2_data)

            # Close old window and open new one with comparison
            if self._window and self._window.is_open():
                self._window.close()

            title = f"Slice Heating Inspector — {original_filename} vs {filename}"

            def on_compare_message(msg):
                if not isinstance(msg, dict):
                    return
                if msg.get("command") == "compare":
                    name = msg.get("name", "unknown")
                    b64 = msg.get("data_b64", "")
                    if b64:
                        import threading
                        threading.Thread(
                            target=self._do_compare_from_b64,
                            args=(name, b64, original_filename),
                            daemon=True
                        ).start()

            self._window = orca.host.ui.create_window(
                html=html,
                title=title,
                width=1400,
                height=900,
                on_message=on_compare_message,
            )
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


@orca.plugin
class SliceHeatingInspectorPackage(orca.base):
    def register_capabilities(self):
        orca.register_capability(SliceHeatingInspector)
