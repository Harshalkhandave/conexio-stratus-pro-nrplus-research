#!/usr/bin/env python3
"""Parse 03_topology firmware serial output into structured events.

Pure functions + small accumulators only: safe to call from reader threads and
from tests without Qt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

_ANSI_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
_HOST_TS_RE = re.compile(r"^\[(\d{2}:\d{2}:\d{2}\.\d{3})\]\s*(.*)$")
_KV_RE = re.compile(r"(\w+)=([^\s]+)")

SEV_INFO = "info"
SEV_TX = "tx"
SEV_RX = "rx"
SEV_RELAY = "relay"
SEV_DELIVER = "deliver"
SEV_WARN = "warn"
SEV_ERROR = "error"
SEV_CMD = "cmd"


def clean_line(s: str) -> str:
    """Drop ANSI colours and the Zephyr shell prompt prefix."""
    s = _ANSI_RE.sub("", s)
    if "uart:~$" in s:
        s = s.split("uart:~$")[-1]
    return s.strip()


def strip_host_ts(line: str) -> tuple[Optional[str], str]:
    line = clean_line(line)
    m = _HOST_TS_RE.match(line)
    if m:
        return m.group(1), m.group(2).strip()
    return None, line


def app_payload(rest: str) -> str:
    """Strip the Zephyr log prefix so parsing sees the bare payload."""
    if "<inf> app:" in rest:
        rest = rest.split("<inf> app:", 1)[1].strip()
    for tag in ("<dbg> app:", "<wrn> app:", "<err> app:"):
        if tag in rest:
            rest = rest.split(tag, 1)[1].strip()
            break
    return rest


def parse_kv(text: str) -> dict[str, str]:
    return {k: v for k, v in _KV_RE.findall(text)}


def _i(d: dict[str, str], key: str) -> Optional[int]:
    v = d.get(key)
    if v is None:
        return None
    try:
        return int(v, 0)
    except ValueError:
        return None


def _f(d: dict[str, str], key: str) -> Optional[float]:
    v = d.get(key)
    if v is None:
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _b(d: dict[str, str], key: str) -> Optional[bool]:
    v = d.get(key)
    if v is None:
        return None
    return v.strip().lower() in ("1", "on", "true", "yes")


def severity(body: str) -> str:
    """Console colour class for a payload line."""
    if body.startswith(">>>"):
        return SEV_CMD
    if body.startswith("TX:"):
        return SEV_TX
    if body.startswith("RX:"):
        return SEV_RX
    if body.startswith("FORWARD"):
        return SEV_RELAY
    if body.startswith("DELIVER:"):
        return SEV_DELIVER
    low = body.lower()
    if any(k in low for k in ("failed", "error", "err ", "fatal")):
        return SEV_ERROR
    if any(k in low for k in ("warn", "must be", "unknown", "not running", "no saved")):
        return SEV_WARN
    return SEV_INFO


@dataclass
class TopoEvent:
    kind: str
    host_ts: Optional[str] = None
    raw: str = ""
    node: Optional[int] = None
    src: Optional[int] = None
    dst: Optional[int] = None
    prev: Optional[int] = None
    seq: Optional[int] = None
    hops: Optional[int] = None
    rssi: Optional[float] = None
    msg_type: Optional[str] = None
    role: Optional[str] = None
    device_id: Optional[int] = None
    running: Optional[bool] = None
    autostart: Optional[bool] = None
    persist: Optional[bool] = None


@dataclass
class Neighbor:
    id: int
    rssi: Optional[float] = None
    last_ms: Optional[int] = None
    hello: Optional[int] = None
    data: Optional[int] = None


@dataclass
class StatusSnapshot:
    """Parsed `exp status` multiline block."""

    role: Optional[str] = None
    running: Optional[bool] = None
    device_id: Optional[int] = None
    dest_id: Optional[int] = None
    max_hops: Optional[int] = None
    carrier: Optional[int] = None
    net: Optional[str] = None
    interval_ms: Optional[int] = None
    hello_ms: Optional[int] = None
    count: Optional[int] = None
    power: Optional[int] = None
    mcs: Optional[int] = None
    size: Optional[int] = None
    dedup: Optional[bool] = None
    autostart: Optional[bool] = None
    persist: Optional[bool] = None
    seq_next: Optional[int] = None
    data_sent: Optional[int] = None
    hello_sent: Optional[int] = None
    fwd_sent: Optional[int] = None
    rx_ok: Optional[int] = None
    rx_fail: Optional[int] = None
    deliver: Optional[int] = None
    fwd_dup: Optional[int] = None
    fwd_ttl: Optional[int] = None
    fwd_qfull: Optional[int] = None
    raw_lines: list[str] = field(default_factory=list)


# Field markers that belong to an `exp status` block body.
STATUS_FIELD_HINTS = (
    "role=",
    "carrier=",
    "interval_ms=",
    "power=",
    "dedup=",
    "seq_next=",
    "rx_ok=",
    "device_id=",
    "dest_id=",
    "hello_ms=",
    "mcs=",
    "data_sent=",
    "autostart=",
    "persist=",
)


class StatusAccumulator:
    """Collect lines after `exp status:` until the counters line (rx_ok=…)."""

    def __init__(self) -> None:
        self.active = False
        self.lines: list[str] = []

    def reset(self) -> None:
        self.active = False
        self.lines = []

    def feed(self, body: str) -> Optional[StatusSnapshot]:
        body = body.strip()
        if body.startswith("exp status:"):
            self.active = True
            self.lines = [body]
            return None
        if not self.active:
            return None
        if any(h in body for h in STATUS_FIELD_HINTS):
            self.lines.append(body)
            if body.startswith("rx_ok=") or " rx_ok=" in body:
                snap = parse_status_lines(self.lines)
                self.reset()
                return snap
            return None
        return self.flush()

    def consumes(self, body: str) -> bool:
        """True when `body` is part of a status block (already handled here)."""
        body = body.strip()
        if body.startswith("exp status:"):
            return True
        return self.active and any(h in body for h in STATUS_FIELD_HINTS)

    def flush(self) -> Optional[StatusSnapshot]:
        snap = None
        if self.active and len(self.lines) > 1:
            snap = parse_status_lines(self.lines)
        self.reset()
        return snap


class NeighborAccumulator:
    """Collect `exp neigh:` rows until a non-row line arrives."""

    def __init__(self) -> None:
        self.active = False
        self.rows: list[Neighbor] = []

    def feed(self, body: str) -> Optional[list[Neighbor]]:
        body = body.strip()
        if body.startswith("exp neigh:"):
            self.active = True
            self.rows = []
            return None
        if not self.active:
            return None
        if body.startswith("id="):
            kv = parse_kv(body)
            self.rows.append(
                Neighbor(
                    id=_i(kv, "id") or 0,
                    rssi=_f(kv, "rssi"),
                    last_ms=_i(kv, "last_ms"),
                    hello=_i(kv, "hello"),
                    data=_i(kv, "data"),
                )
            )
            return None
        if body.startswith("(none)"):
            self.active = False
            rows, self.rows = self.rows, []
            return rows
        self.active = False
        rows, self.rows = self.rows, []
        return rows

    def consumes(self, body: str) -> bool:
        body = body.strip()
        if body.startswith("exp neigh:"):
            return True
        return self.active and (body.startswith("id=") or body.startswith("(none)"))


def parse_status_lines(lines: list[str]) -> StatusSnapshot:
    text = " ".join(clean_line(x) for x in lines)
    kv = parse_kv(text)
    snap = StatusSnapshot(raw_lines=list(lines))
    snap.role = kv.get("role")
    snap.running = _b(kv, "running")
    snap.device_id = _i(kv, "device_id")
    snap.dest_id = _i(kv, "dest_id")
    snap.max_hops = _i(kv, "max_hops")
    snap.carrier = _i(kv, "carrier")
    snap.net = kv.get("net")
    snap.interval_ms = _i(kv, "interval_ms")
    snap.hello_ms = _i(kv, "hello_ms")
    snap.count = _i(kv, "count")
    snap.power = _i(kv, "power")
    snap.mcs = _i(kv, "mcs")
    snap.size = _i(kv, "size")
    snap.dedup = _b(kv, "dedup")
    snap.autostart = _b(kv, "autostart")
    snap.persist = _b(kv, "persist")
    snap.seq_next = _i(kv, "seq_next")
    snap.data_sent = _i(kv, "data_sent")
    snap.hello_sent = _i(kv, "hello_sent")
    snap.fwd_sent = _i(kv, "fwd_sent")
    snap.rx_ok = _i(kv, "rx_ok")
    snap.rx_fail = _i(kv, "rx_fail")
    snap.deliver = _i(kv, "deliver")
    snap.fwd_dup = _i(kv, "fwd_dup")
    snap.fwd_ttl = _i(kv, "fwd_ttl")
    snap.fwd_qfull = _i(kv, "fwd_qfull")
    return snap


def parse_line(line: str) -> Optional[TopoEvent]:
    """Parse one raw serial line (optionally host-timestamped)."""
    host_ts, rest = strip_host_ts(line)
    if not rest or rest.startswith("====="):
        return None

    if rest.startswith(">>>"):
        return TopoEvent(kind="cmd", host_ts=host_ts, raw=rest)

    body = app_payload(rest)
    kv = parse_kv(body)

    if body.startswith("exp status:"):
        return TopoEvent(kind="status_begin", host_ts=host_ts, raw=body)

    if body.startswith("TX:"):
        return TopoEvent(
            kind="tx",
            host_ts=host_ts,
            raw=body,
            node=_i(kv, "node"),
            src=_i(kv, "src") or _i(kv, "node"),
            dst=_i(kv, "dst"),
            seq=_i(kv, "seq"),
            hops=_i(kv, "hop"),
            msg_type=kv.get("type"),
        )

    if body.startswith("RX:"):
        return TopoEvent(
            kind="rx",
            host_ts=host_ts,
            raw=body,
            node=_i(kv, "node"),
            src=_i(kv, "src"),
            dst=_i(kv, "dst"),
            prev=_i(kv, "prev"),
            seq=_i(kv, "seq"),
            hops=_i(kv, "hop"),
            rssi=_f(kv, "rssi"),
            msg_type=kv.get("type"),
        )

    if body.startswith("FORWARD:") or body.startswith("FORWARD_Q:"):
        # FORWARD_Q is only the enqueue; FORWARD is the transmission that counts.
        return TopoEvent(
            kind="forward_q" if body.startswith("FORWARD_Q:") else "forward",
            host_ts=host_ts,
            raw=body,
            node=_i(kv, "node"),
            src=_i(kv, "src"),
            dst=_i(kv, "dst"),
            prev=_i(kv, "prev"),
            seq=_i(kv, "seq"),
            hops=_i(kv, "hop"),
        )

    if body.startswith("DELIVER:"):
        return TopoEvent(
            kind="deliver",
            host_ts=host_ts,
            raw=body,
            node=_i(kv, "node"),
            src=_i(kv, "src"),
            prev=_i(kv, "prev"),
            seq=_i(kv, "seq"),
            hops=_i(kv, "hops"),
            rssi=_f(kv, "rssi"),
        )

    if body.startswith("SUMMARY:"):
        return TopoEvent(
            kind="summary",
            host_ts=host_ts,
            raw=body,
            role=kv.get("role"),
            device_id=_i(kv, "device_id"),
            node=_i(kv, "device_id"),
        )

    if body.startswith("device_id=") and "role=" not in body:
        did = _i(kv, "device_id")
        if did is not None:
            return TopoEvent(kind="status", host_ts=host_ts, raw=body, device_id=did, node=did)

    # `exp save` / `exp load` / `exp factory` acknowledgements carry role+autostart.
    if body.startswith("saved role=") or body.startswith("loaded role="):
        return TopoEvent(
            kind="persist",
            host_ts=host_ts,
            raw=body,
            role=kv.get("role"),
            autostart=_b(kv, "autostart"),
            persist=True,
        )

    if body.startswith("cleared flash profile"):
        return TopoEvent(kind="persist", host_ts=host_ts, raw=body, persist=False)

    if body.startswith("autostart="):
        return TopoEvent(
            kind="autostart",
            host_ts=host_ts,
            raw=body,
            autostart=_b(kv, "autostart"),
            persist=_b(kv, "persist"),
        )

    if body.startswith("started role=") or (body.startswith("role=") and "running=" in body):
        return TopoEvent(
            kind="role",
            host_ts=host_ts,
            raw=body,
            role=kv.get("role"),
            device_id=_i(kv, "device_id"),
            node=_i(kv, "device_id"),
            running=True if body.startswith("started role=") else _b(kv, "running"),
        )

    if body.startswith("role=") and "SUMMARY" not in body:
        return TopoEvent(kind="role", host_ts=host_ts, raw=body, role=kv.get("role"))

    if "run active role=" in body:
        role = kv.get("role") or body.split("role=")[-1].strip()
        return TopoEvent(kind="role", host_ts=host_ts, raw=body, role=role, running=True)

    if body.startswith("stop requested") or body == "not running":
        return TopoEvent(kind="stopped", host_ts=host_ts, raw=body)

    if body.startswith("ok") or body.startswith("dedup="):
        return TopoEvent(kind="ack", host_ts=host_ts, raw=body)

    return TopoEvent(kind="log", host_ts=host_ts, raw=body)
