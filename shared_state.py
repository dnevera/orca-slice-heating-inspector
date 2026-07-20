"""Thread-safe state for Slice Heating Inspector.

Stores baseline and current slice data across plugin invocations
(lives in OrcaSlicer process memory as a module-level singleton).
"""
from __future__ import annotations

import copy
import threading
from typing import Any


class PluginState:
    """Holds baseline and current slice state."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._baseline_data: dict[str, Any] | None = None
        self._baseline_name: str | None = None
        self._current_data: dict[str, Any] | None = None
        self._current_name: str | None = None

    # ── Baseline ──────────────────────────────────────────────────────

    def set_baseline(self, data: dict[str, Any], name: str) -> None:
        with self._lock:
            self._baseline_data = copy.deepcopy(data)
            self._baseline_name = name

    def get_baseline(self) -> tuple[dict[str, Any] | None, str | None]:
        with self._lock:
            return (
                copy.deepcopy(self._baseline_data),
                self._baseline_name,
            )

    def clear_baseline(self) -> None:
        with self._lock:
            self._baseline_data = None
            self._baseline_name = None

    @property
    def has_baseline(self) -> bool:
        with self._lock:
            return self._baseline_data is not None

    @property
    def baseline_name(self) -> str | None:
        with self._lock:
            return self._baseline_name

    # ── Current slice ─────────────────────────────────────────────────

    def set_current(self, data: dict[str, Any], name: str) -> None:
        with self._lock:
            self._current_data = copy.deepcopy(data)
            self._current_name = name

    def get_current(self) -> tuple[dict[str, Any] | None, str | None]:
        with self._lock:
            return (
                copy.deepcopy(self._current_data),
                self._current_name,
            )

    @property
    def has_current(self) -> bool:
        with self._lock:
            return self._current_data is not None

    @property
    def current_name(self) -> str | None:
        with self._lock:
            return self._current_name

    # ── Inspector window ref (for auto-navigate on re-slice) ──────────

    def set_inspector_window(self, window) -> None:
        with self._lock:
            self._inspector_window = window

    def get_inspector_window(self):
        with self._lock:
            return getattr(self, '_inspector_window', None)


state = PluginState()
