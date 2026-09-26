#!/usr/bin/env python3
"""Single parsing pipeline for every incoming serial line.

The router runs on the transport reader threads. It turns raw lines into
`StatusSnapshot` / `Neighbor` / `TopoEvent` objects, hands them to plain
callbacks (used by the command engine for response matching) and re-publishes
them as Qt signals for the UI thread.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from PySide6.QtCore import QObject, Signal

from core.parse_topo import (
    Neighbor,
    NeighborAccumulator,
    StatusAccumulator,
    StatusSnapshot,
    TopoEvent,
    app_payload,
    clean_line,
    parse_line,
    severity,
)


@dataclass
class Response:
    """One decoded line, plus any block that completed on it."""

    port: str
    host_ts: str
    body: str
    event: Optional[TopoEvent] = None
    status: Optional[StatusSnapshot] = None
    neighbors: Optional[list[Neighbor]] = None


class LineRouter(QObject):
    status_ready = Signal(str, object)  # port, StatusSnapshot
    neighbors_ready = Signal(str, object)  # port, list[Neighbor]
    event_ready = Signal(str, object)  # port, TopoEvent
    line_ready = Signal(str, str, str, str)  # port, host_ts, body, severity

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._status: dict[str, StatusAccumulator] = {}
        self._neigh: dict[str, NeighborAccumulator] = {}
        self._listeners: list[Callable[[Response], None]] = []

    def add_listener(self, cb: Callable[[Response], None]) -> None:
        """Register a reader-thread callback that sees every decoded line."""
        self._listeners.append(cb)

    def reset(self, port: str) -> None:
        self._status.pop(port, None)
        self._neigh.pop(port, None)

    def feed(self, port: str, host_ts: str, raw: str) -> None:
        body = app_payload(clean_line(raw))
        if not body:
            return

        status_acc = self._status.setdefault(port, StatusAccumulator())
        neigh_acc = self._neigh.setdefault(port, NeighborAccumulator())

        resp = Response(port=port, host_ts=host_ts, body=body)

        in_status = status_acc.consumes(body)
        if in_status or status_acc.active:
            snap = status_acc.feed(body)
            if snap is not None:
                resp.status = snap
        in_neigh = neigh_acc.consumes(body)
        if in_neigh or neigh_acc.active:
            rows = neigh_acc.feed(body)
            if rows is not None:
                resp.neighbors = rows

        if not in_status and not in_neigh:
            ev = parse_line(f"[{host_ts}] {raw}")
            if ev is not None and ev.kind not in ("status_begin",):
                resp.event = ev

        for cb in list(self._listeners):
            try:
                cb(resp)
            except Exception:  # noqa: BLE001 - never break the reader thread
                pass

        self.line_ready.emit(port, host_ts, body, severity(body))
        if resp.status is not None:
            self.status_ready.emit(port, resp.status)
        if resp.neighbors is not None:
            self.neighbors_ready.emit(port, resp.neighbors)
        if resp.event is not None:
            self.event_ready.emit(port, resp.event)
