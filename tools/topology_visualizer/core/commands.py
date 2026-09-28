#!/usr/bin/env python3
"""Command engine: queued, acknowledged board commands.

Every operator action becomes a `Request` (one or more shell commands executed in
order). A worker thread per port sends each step, waits for the board's
acknowledgement and reports success or the board's own error text. Nothing here
runs on the UI thread, so the interface never sleeps on serial I/O.
"""

from __future__ import annotations

import itertools
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from PySide6.QtCore import QObject, Signal

from core.router import LineRouter, Response
from core.transport import SerialHub

Matcher = Callable[[Response], Optional[bool]]

DEFAULT_STEP_TIMEOUT = 3.0
STATUS_TIMEOUT = 6.0
INTER_STEP_GAP = 0.06


def _is_error_text(body: str) -> bool:
    low = body.lower()
    return any(
        key in low
        for key in (
            "must be",
            "unknown role",
            "unknown key",
            "stop the run",
            "already running",
            "save failed",
            "factory clear failed",
            "no saved profile",
            "needs dest_id",
            "persist disabled",
            "usage:",
        )
    )


def match_ok(resp: Response) -> Optional[bool]:
    body = resp.body
    if body.startswith("ok"):
        return True
    if body.startswith("role=") and "running=" not in body:
        return True
    if body.startswith("autostart="):
        return True
    if body.startswith("dedup="):
        return True
    if body.startswith("source_rx="):
        return True
    if body.startswith("rx_window="):
        return True
    if body.startswith("fwd_mode="):
        return True
    if _is_error_text(body):
        return False
    return None


def match_status(resp: Response) -> Optional[bool]:
    if resp.status is not None:
        return True
    return None


def match_neighbors(resp: Response) -> Optional[bool]:
    if resp.neighbors is not None:
        return True
    return None


def match_started(resp: Response) -> Optional[bool]:
    if resp.body.startswith("started role="):
        return True
    if _is_error_text(resp.body):
        return False
    return None


def match_stopped(resp: Response) -> Optional[bool]:
    body = resp.body
    if body.startswith("stop requested") or body == "not running":
        return True
    if body.startswith("SUMMARY:"):
        return True
    return None


def match_saved(resp: Response) -> Optional[bool]:
    if resp.body.startswith("saved role="):
        return True
    if _is_error_text(resp.body):
        return False
    return None


def match_loaded(resp: Response) -> Optional[bool]:
    if resp.body.startswith("loaded role="):
        return True
    if _is_error_text(resp.body):
        return False
    return None


def match_cleared(resp: Response) -> Optional[bool]:
    if resp.body.startswith("cleared flash profile"):
        return True
    if _is_error_text(resp.body):
        return False
    return None


@dataclass
class Step:
    text: str
    match: Matcher = match_ok
    timeout: float = DEFAULT_STEP_TIMEOUT
    optional: bool = False  # a failed/ignored ack does not fail the request


@dataclass
class Request:
    port: str
    kind: str
    label: str
    steps: list[Step]
    id: int = 0
    responses: list[str] = field(default_factory=list)
    last_status: object = None


class CommandEngine(QObject):
    """Serialized per-port command execution with acknowledgement tracking."""

    started = Signal(str, int, str)  # port, request id, label
    progress = Signal(str, int, int, int)  # port, request id, step index, total
    finished = Signal(str, int, bool, str)  # port, request id, ok, detail
    sent = Signal(str, str)  # port, command text

    def __init__(
        self,
        hub: SerialHub,
        router: LineRouter,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self.hub = hub
        self.router = router
        self._ids = itertools.count(1)
        self._queues: dict[str, queue.Queue[Optional[Request]]] = {}
        self._workers: dict[str, threading.Thread] = {}
        self._inbox: dict[str, queue.Queue[Response]] = {}
        self._active: dict[str, Optional[Request]] = {}
        self._lock = threading.RLock()
        router.add_listener(self._on_response)

    # ---------------------------------------------------------------- plumbing
    def _on_response(self, resp: Response) -> None:
        box = self._inbox.get(resp.port)
        if box is not None:
            box.put(resp)

    def _worker_for(self, port: str) -> queue.Queue:
        with self._lock:
            q = self._queues.get(port)
            if q is None:
                q = queue.Queue()
                self._queues[port] = q
                self._inbox[port] = queue.Queue()
                th = threading.Thread(
                    target=self._run, args=(port, q), daemon=True, name=f"cmd-{port}"
                )
                self._workers[port] = th
                th.start()
            return q

    def submit(self, req: Request) -> int:
        with self._lock:
            # Deduplicate read-only requests (status / neigh) if already active or queued
            if req.kind in ("status", "neigh"):
                active = self._active.get(req.port)
                if active and active.kind == req.kind:
                    return active.id
                q = self._queues.get(req.port)
                if q:
                    for item in list(q.queue):
                        if item and item.kind == req.kind:
                            return item.id
            req.id = next(self._ids)
            self._worker_for(req.port).put(req)
            return req.id

    def shutdown(self) -> None:
        for port, q in list(self._queues.items()):
            q.put(None)
            self._workers.pop(port, None)
        self._queues.clear()

    def pending(self, port: str) -> int:
        with self._lock:
            q = self._queues.get(port)
            depth = q.qsize() if q else 0
            return depth + (1 if self._active.get(port) else 0)

    def busy(self, port: str) -> bool:
        return self.pending(port) > 0

    def drain(self, port: str) -> None:
        self._drain_inbox(port)
        with self._lock:
            q = self._queues.get(port)
            if q:
                while not q.empty():
                    try:
                        q.get_nowait()
                    except queue.Empty:
                        break

    def _drain_inbox(self, port: str) -> None:
        box = self._inbox.get(port)
        if not box:
            return
        while True:
            try:
                box.get_nowait()
            except queue.Empty:
                return

    def _run(self, port: str, q: queue.Queue) -> None:
        while True:
            req = q.get()
            if req is None:
                return
            with self._lock:
                self._active[port] = req
            self.started.emit(port, req.id, req.label)
            ok, detail = self._execute(req)
            with self._lock:
                self._active[port] = None
            self.finished.emit(port, req.id, ok, detail)

    def _execute(self, req: Request) -> tuple[bool, str]:
        port = req.port
        total = len(req.steps)
        for idx, step in enumerate(req.steps):
            if not self.hub.is_open(port):
                return False, "link is not open"
            self._drain_inbox(port)
            self.progress.emit(port, req.id, idx, total)
            if not self.hub.write_line(port, step.text):
                return False, f"could not send '{step.text}'"
            self.sent.emit(port, step.text)
            ok, detail = self._await(req, step)
            if not ok and not step.optional:
                return False, detail or f"no acknowledgement for '{step.text}'"
            time.sleep(INTER_STEP_GAP)
        return True, "verified"

    def _await(self, req: Request, step: Step) -> tuple[bool, str]:
        box = self._inbox[req.port]
        deadline = time.monotonic() + step.timeout
        poked = False
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False, f"timeout waiting for reply to '{step.text}'"
            try:
                resp = box.get(timeout=min(0.25, remaining))
            except queue.Empty:
                if not poked and step.text.startswith("exp status") and (step.timeout - remaining) > 0.6:
                    self.hub.write_line(req.port, "")
                    poked = True
                continue
            if resp.body.strip() == step.text.strip():
                continue  # shell echo of our own command
            if resp.status is not None:
                req.last_status = resp.status
            verdict = step.match(resp)
            if verdict is True:
                req.responses.append(resp.body)
                return True, resp.body
            if verdict is False:
                req.responses.append(resp.body)
                return False, resp.body

    # ------------------------------------------------------------- public API
    def status(self, port: str) -> int:
        return self.submit(
            Request(
                port=port,
                kind="status",
                label="Reading status",
                steps=[Step("exp status", match_status, STATUS_TIMEOUT)],
            )
        )

    def neighbors(self, port: str) -> int:
        return self.submit(
            Request(
                port=port,
                kind="neigh",
                label="Reading neighbours",
                steps=[Step("exp neigh", match_neighbors, STATUS_TIMEOUT)],
            )
        )

    def start(self, port: str, count: Optional[int] = None) -> int:
        text = "exp start" if not count else f"exp start {int(count)}"
        return self.submit(
            Request(
                port=port,
                kind="start",
                label="Starting run",
                steps=[Step(text, match_started, 4.0)],
            )
        )

    def stop(self, port: str) -> int:
        return self.submit(
            Request(
                port=port,
                kind="stop",
                label="Stopping run",
                steps=[Step("exp stop", match_stopped, 3.0)],
            )
        )

    def apply_settings(
        self,
        port: str,
        settings: dict,
        *,
        stop_first: bool,
        verify: bool = True,
    ) -> int:
        steps: list[Step] = []
        if stop_first:
            steps.append(Step("exp stop", match_stopped, 3.0, optional=True))
        role = settings.get("role")
        if role:
            steps.append(Step(f"exp role {role}"))
        for key in ("dest", "interval", "hello", "count", "power", "mcs", "size", "max_hops"):
            val = settings.get(key)
            if val is not None:
                steps.append(Step(f"exp sett {key} {int(val)}"))
        if "dedup" in settings and settings["dedup"] is not None:
            flag = "on" if settings["dedup"] else "off"
            steps.append(Step(f"exp sett dedup {flag}"))
        if "fwd_mode" in settings and settings["fwd_mode"] is not None:
            steps.append(Step(f"exp sett fwd_mode {settings['fwd_mode']}"))
        if "rx_window" in settings and settings["rx_window"] is not None:
            steps.append(Step(f"exp sett rx_window {int(settings['rx_window'])}"))
        elif "source_rx" in settings and settings["source_rx"] is not None:
            flag = "on" if settings["source_rx"] else "off"
            steps.append(Step(f"exp sett source_rx {flag}"))
        if verify:
            steps.append(Step("exp status", match_status, STATUS_TIMEOUT))
        return self.submit(
            Request(port=port, kind="apply", label="Applying settings", steps=steps)
        )

    def set_autostart(self, port: str, on: bool) -> int:
        return self.submit(
            Request(
                port=port,
                kind="autostart",
                label="Setting autostart",
                steps=[Step(f"exp autostart {'on' if on else 'off'}")],
            )
        )

    def save_profile(self, port: str, autostart: Optional[bool] = None) -> int:
        """Write the profile, optionally arming autostart in the same sequence."""
        steps: list[Step] = []
        if autostart is not None:
            steps.append(Step(f"exp autostart {'on' if autostart else 'off'}"))
        steps.append(Step("exp save", match_saved, 4.0))
        steps.append(Step("exp status", match_status, STATUS_TIMEOUT))
        return self.submit(
            Request(
                port=port,
                kind="save",
                label="Saving profile to flash",
                steps=steps,
            )
        )

    def load_profile(self, port: str) -> int:
        return self.submit(
            Request(
                port=port,
                kind="load",
                label="Loading profile from flash",
                steps=[
                    Step("exp load", match_loaded, 4.0),
                    Step("exp status", match_status, STATUS_TIMEOUT),
                ],
            )
        )

    def factory_reset(self, port: str) -> int:
        return self.submit(
            Request(
                port=port,
                kind="factory",
                label="Clearing saved profile",
                steps=[
                    Step("exp factory", match_cleared, 4.0),
                    Step("exp status", match_status, STATUS_TIMEOUT),
                ],
            )
        )
