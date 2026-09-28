#!/usr/bin/env python3
"""Serial / TCP transport for multiple boards.

`SerialHub` owns one reader thread per link and publishes complete lines through
both a Qt signal (for the UI) and plain callbacks (for the command engine, which
must see responses without waiting on the UI event loop).
"""

from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import Callable, Optional

from PySide6.QtCore import QObject, Signal

try:
    import serial
    from serial.tools import list_ports
except ImportError:  # pragma: no cover - dependency is declared in requirements
    serial = None  # type: ignore
    list_ports = None  # type: ignore

BAUD_DEFAULT = 115200
URL_SCHEMES = ("socket://", "rfc2217://", "spy://", "loop://")


def normalize_port(port: str) -> str:
    """Normalize a user-entered port or pyserial URL."""
    p = port.strip()
    if not p:
        return p
    lower = p.lower()
    for scheme in URL_SCHEMES:
        if lower.startswith(scheme):
            head, _, rest = p.partition("://")
            return f"{head.lower()}://{rest}"
    if p.upper().startswith("COM") and p[3:].isdigit():
        return p.upper()
    return p


def is_url(port: str) -> bool:
    return "://" in port


def short_port_label(port: str) -> str:
    """Compact label for canvas cards, log filenames and status text."""
    p = normalize_port(port)
    if "://" in p:
        return p.split("://", 1)[1]
    return p


def safe_filename(name: str) -> str:
    out = "".join(c if c.isalnum() or c in "-_." else "_" for c in name).strip("._")
    return out or "node"


def list_available_ports() -> list[tuple[str, str]]:
    if list_ports is None:
        return []
    return [(p.device, p.description or "") for p in list_ports.comports()]


def test_open_port(port: str, baud: int = BAUD_DEFAULT) -> tuple[bool, str]:
    """Open + close a link to prove it is usable. Returns (ok, message)."""
    if serial is None:
        return False, "pyserial is not installed"
    port = normalize_port(port)
    try:
        ser = serial.serial_for_url(url=port, baudrate=baud, timeout=0.2)
        ser.close()
        return True, "OK"
    except Exception as exc:  # noqa: BLE001 - surfaced verbatim to the operator
        return False, str(exc)


def host_ts() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


class SerialHub(QObject):
    line_received = Signal(str, str, str)  # port, host_ts, raw line
    disconnected = Signal(str, str)  # port, reason
    opened = Signal(str)
    write_failed = Signal(str, str)

    def __init__(self, baud: int = BAUD_DEFAULT, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.baud = baud
        self._lock = threading.Lock()
        self._sers: dict[str, object] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._stop: dict[str, threading.Event] = {}
        self._listeners: list[Callable[[str, str, str], None]] = []

    def add_line_listener(self, cb: Callable[[str, str, str], None]) -> None:
        """Register a reader-thread callback: cb(port, host_ts, raw_line)."""
        self._listeners.append(cb)

    def open_port(self, port: str) -> tuple[bool, str]:
        if serial is None:
            return False, "pyserial is not installed"
        port = normalize_port(port)
        with self._lock:
            if port in self._sers:
                return True, "already open"
            try:
                ser = serial.serial_for_url(url=port, baudrate=self.baud, timeout=0.2)
            except Exception as exc:  # noqa: BLE001
                return False, str(exc)
            time.sleep(0.1)
            if hasattr(ser, "_socket") and ser._socket is not None:
                try:
                    import socket as _socket

                    ser._socket.setsockopt(_socket.IPPROTO_TCP, _socket.TCP_NODELAY, 1)
                except Exception:  # noqa: BLE001
                    pass
            if not is_url(port):
                try:
                    ser.reset_input_buffer()
                except Exception:  # noqa: BLE001
                    pass
            try:
                ser.write(b"\r\n")
                ser.flush()
            except Exception:  # noqa: BLE001
                pass
            self._sers[port] = ser
            stop = threading.Event()
            self._stop[port] = stop
            th = threading.Thread(
                target=self._reader, args=(port, ser, stop), daemon=True, name=f"rx-{port}"
            )
            self._threads[port] = th
            th.start()
        self.opened.emit(port)
        return True, "OK"

    def close_port(self, port: str) -> None:
        with self._lock:
            stop = self._stop.pop(port, None)
            ser = self._sers.pop(port, None)
            self._threads.pop(port, None)
        if stop:
            stop.set()
        if ser is not None:
            try:
                ser.close()
            except Exception:  # noqa: BLE001
                pass

    def close_all(self) -> None:
        for port in list(self._sers.keys()):
            self.close_port(port)

    def is_open(self, port: str) -> bool:
        return port in self._sers

    def open_ports(self) -> list[str]:
        return list(self._sers.keys())

    def write_line(self, port: str, text: str) -> bool:
        data = (text.rstrip("\r\n") + "\r\n").encode("utf-8", errors="replace")
        with self._lock:
            ser = self._sers.get(port)
        if ser is None:
            self.write_failed.emit(port, "port is not open")
            return False
        try:
            ser.write(data)
            ser.flush()
            return True
        except Exception as exc:  # noqa: BLE001
            self.write_failed.emit(port, str(exc))
            return False

    def _publish(self, port: str, ts: str, line: str) -> None:
        for cb in list(self._listeners):
            try:
                cb(port, ts, line)
            except Exception:  # noqa: BLE001 - a bad listener must not kill the reader
                pass
        self.line_received.emit(port, ts, line)

    def _reader(self, port: str, ser, stop: threading.Event) -> None:  # noqa: ANN001
        buf = b""
        while not stop.is_set():
            try:
                chunk = ser.read(256)
                if not chunk:
                    if not ser.is_open:
                        break
                    continue
                buf += chunk
                while b"\n" in buf:
                    raw, buf = buf.split(b"\n", 1)
                    line = raw.decode("utf-8", errors="replace").rstrip("\r")
                    if line:
                        self._publish(port, host_ts(), line)
            except Exception as exc:  # noqa: BLE001
                if not stop.is_set():
                    self.disconnected.emit(port, str(exc))
                break
        with self._lock:
            owns = self._sers.get(port) is ser
            if owns:
                self._sers.pop(port, None)
                self._stop.pop(port, None)
                self._threads.pop(port, None)
        if owns:
            try:
                ser.close()
            except Exception:  # noqa: BLE001
                pass
            if not stop.is_set():
                self.disconnected.emit(port, "link closed")
