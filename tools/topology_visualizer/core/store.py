#!/usr/bin/env python3
"""Persistent preferences and per-port layout, backed by QSettings."""

from __future__ import annotations

import json
from typing import Optional

from PySide6.QtCore import QByteArray, QSettings

from core import APP_NAME, APP_ORG

DEFAULTS = {
    "theme": "light",
    "confirm_apply": True,
    "confirm_run": True,
    "autoscroll": True,
    "show_rssi_labels": True,
    "animate_packets": True,
    "auto_reconnect": True,
    "auto_reconnect_interval_ms": 200,
    "last_ports": [],
    "log_root": "",
}


class Store:
    def __init__(self) -> None:
        self._s = QSettings(APP_ORG, APP_NAME)

    # ------------------------------------------------------------ preferences
    def get(self, key: str, default=None):
        fallback = DEFAULTS.get(key, default)
        value = self._s.value(f"prefs/{key}", None)
        if value is None:
            return fallback
        if isinstance(fallback, bool):
            if isinstance(value, str):
                return value.lower() in ("1", "true", "yes")
            return bool(value)
        if isinstance(fallback, int) and not isinstance(fallback, bool):
            try:
                return int(value)
            except (ValueError, TypeError):
                return fallback
        if isinstance(fallback, list):
            if isinstance(value, str):
                return [p for p in value.split(",") if p]
            return list(value) if value else []
        return value

    def set(self, key: str, value) -> None:
        if isinstance(value, list):
            value = ",".join(value)
        self._s.setValue(f"prefs/{key}", value)

    # ---------------------------------------------------------- window state
    def save_window(self, geometry: QByteArray, state: QByteArray) -> None:
        self._s.setValue("window/geometry", geometry)
        self._s.setValue("window/state", state)

    def window_geometry(self) -> Optional[QByteArray]:
        return self._s.value("window/geometry")

    def window_state(self) -> Optional[QByteArray]:
        return self._s.value("window/state")

    # ----------------------------------------------------------- node layout
    def node_layout(self, port: str) -> dict:
        raw = self._s.value(f"layout/{port}")
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return {}

    def save_node_layout(self, port: str, name: str, x: float, y: float) -> None:
        self._s.setValue(
            f"layout/{port}", json.dumps({"name": name, "x": round(x, 1), "y": round(y, 1)})
        )

    def sync(self) -> None:
        self._s.sync()
