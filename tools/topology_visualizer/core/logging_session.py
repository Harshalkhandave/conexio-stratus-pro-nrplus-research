#!/usr/bin/env python3
"""Capture session: one text log per node plus a machine-readable manifest."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional, TextIO

from core import APP_VERSION
from core.parse_topo import clean_line
from core.transport import safe_filename, short_port_label

# "COM9.txt" is a reserved Windows device name (OneDrive refuses to sync it),
# so every capture file carries a suffix.
FILE_SUFFIX = "_log"


def log_filename(display_name: str, port: str) -> str:
    return f"{safe_filename(display_name or short_port_label(port))}{FILE_SUFFIX}.txt"


class LoggingSession:
    """Writes `tools/topology_visualizer/data/<name>/<node>_log.txt` in the serial_logger format."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.folder: Optional[Path] = None
        self.started: Optional[datetime] = None
        self.active = False
        self.line_count = 0
        self._files: dict[str, TextIO] = {}
        self._names: dict[str, str] = {}

    def start(self, folder_name: str, ports: list[str], display_names: dict[str, str]) -> Path:
        self.stop()
        safe = safe_filename(folder_name.strip())
        if not safe:
            safe = datetime.now().strftime("run_%Y%m%d_%H%M%S")
        self.folder = self.root / safe
        self.folder.mkdir(parents=True, exist_ok=True)
        self.started = datetime.now()
        self.line_count = 0
        for port in ports:
            self.add_port(port, display_names.get(port, short_port_label(port)), _open=True)
        self.active = True
        self._write_manifest()
        return self.folder

    def add_port(self, port: str, display_name: str, _open: bool = False) -> None:
        if self.folder is None or port in self._files:
            return
        if not self.active and not _open:
            return
        path = self.folder / log_filename(display_name, port)
        # Default newline translation keeps the file readable in Windows editors.
        fh = path.open("a", encoding="utf-8", errors="replace")
        fh.write(
            f"===== visualizer {APP_VERSION} capture start "
            f"{datetime.now().isoformat(timespec='seconds')} port={port} =====\n"
        )
        fh.flush()
        self._files[port] = fh
        self._names[port] = display_name
        if self.active:
            self._write_manifest()

    def write(self, port: str, host_ts: str, line: str) -> None:
        """Append one line, stripped of ANSI colour and shell prompt redraws."""
        if not self.active:
            return
        fh = self._files.get(port)
        if fh is None:
            return
        text = clean_line(line)
        if not text:
            return
        fh.write(f"[{host_ts}] {text}\n")
        fh.flush()
        self.line_count += 1

    def note(self, text: str) -> None:
        """Record an operator action in every open log."""
        if not self.active:
            return
        stamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        for fh in self._files.values():
            fh.write(f"[{stamp}] ##### {text}\n")
            fh.flush()

    def export_snapshot(self, payload: dict, name: str = "snapshot") -> Optional[Path]:
        if self.folder is None:
            return None
        path = self.folder / f"{safe_filename(name)}.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return path

    def _write_manifest(self) -> None:
        if self.folder is None:
            return
        manifest = {
            "tool": "topology_visualizer",
            "version": APP_VERSION,
            "started": self.started.isoformat(timespec="seconds") if self.started else None,
            "nodes": [
                {
                    "port": port,
                    "name": self._names.get(port, ""),
                    "file": log_filename(self._names.get(port, ""), port),
                }
                for port in self._files
            ],
        }
        (self.folder / "session.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    def stop(self) -> None:
        for fh in self._files.values():
            try:
                fh.write(
                    f"===== visualizer capture end "
                    f"{datetime.now().isoformat(timespec='seconds')} =====\n"
                )
                fh.close()
            except Exception:  # noqa: BLE001
                pass
        self._files.clear()
        self._names.clear()
        self.active = False
