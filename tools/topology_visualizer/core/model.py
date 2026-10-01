#!/usr/bin/env python3
"""Session model: the live picture of the three-node network.

Holds one `NodeState` per link, derived `LinkState` edges, packet animations and
session KPIs. All time-sensitive values expire so the canvas never shows stale
radio data.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

from core.parse_topo import Neighbor, StatusSnapshot, TopoEvent
from core.transport import short_port_label

# Lifetime of live radio values before they are cleared from the UI (ms).
RSSI_STALE_MS = 2500
LINK_STALE_MS = 3000
PATH_STALE_MS = 4000
ANIM_DURATION_S = 0.55
RSSI_HISTORY = 40

ROLE_ORDER = ("sink", "relay", "source")
ROLE_FRIENDLY = {"source": "Sensor", "relay": "Router", "sink": "Gateway"}


class ConnState(str, Enum):
    CONNECTED = "connected"
    RUNNING = "running"
    DISCONNECTED = "disconnected"
    ERROR = "error"
    RECONNECTING = "reconnecting"


def _now() -> float:
    return time.monotonic()


def link_quality(rssi: Optional[float]) -> str:
    """Coarse label used for edge colour and the inspector."""
    if rssi is None:
        return "unknown"
    if rssi >= -60:
        return "excellent"
    if rssi >= -75:
        return "good"
    if rssi >= -90:
        return "fair"
    return "weak"


@dataclass
class PacketAnim:
    """A packet in flight: device-id waypoints the canvas maps to positions."""

    waypoints: list[int]
    t0: float
    duration: float = ANIM_DURATION_S
    hops: Optional[int] = None


@dataclass
class NodeState:
    port: str
    display_name: str = ""
    device_id: Optional[int] = None
    role: Optional[str] = None
    dest_id: Optional[int] = None
    max_hops: Optional[int] = None
    interval_ms: Optional[int] = None
    hello_ms: Optional[int] = None
    count: Optional[int] = None
    power: Optional[int] = None
    mcs: Optional[int] = None
    size: Optional[int] = None
    dedup: Optional[bool] = None
    source_rx: Optional[bool] = None
    carrier: Optional[int] = None
    net: Optional[str] = None
    autostart: Optional[bool] = None
    persist: Optional[bool] = None
    running: bool = False
    conn: ConnState = ConnState.DISCONNECTED
    error_msg: str = ""
    busy_label: str = ""

    parent_id: Optional[int] = None
    last_rssi: Optional[float] = None
    rssi_mono: float = 0.0
    rssi_history: deque = field(default_factory=lambda: deque(maxlen=RSSI_HISTORY))
    last_seen: Optional[str] = None
    hop_count: Optional[int] = None
    seq_next: Optional[int] = None
    tx_count: int = 0
    fwd_count: int = 0
    deliver_count: int = 0
    rx_ok: int = 0
    rx_fail: int = 0
    data_sent: int = 0
    hello_sent: int = 0
    fwd_dup: int = 0
    fwd_ttl: int = 0
    fwd_qfull: int = 0
    q_peak: Optional[int] = None
    neighbors: list[Neighbor] = field(default_factory=list)
    packet_loss_pct: Optional[float] = None
    last_route_change: Optional[str] = None
    status_age_mono: float = 0.0

    x: float = 0.0
    y: float = 0.0

    def __post_init__(self) -> None:
        if not self.display_name:
            self.display_name = short_port_label(self.port)

    @property
    def friendly_role(self) -> str:
        if not self.role:
            return "unassigned"
        return ROLE_FRIENDLY.get(self.role, self.role)

    @property
    def label(self) -> str:
        return self.display_name or short_port_label(self.port)

    @property
    def online(self) -> bool:
        return self.conn in (ConnState.CONNECTED, ConnState.RUNNING)

    @property
    def identified(self) -> bool:
        return self.device_id is not None

    def live_rssi(self, now: Optional[float] = None) -> Optional[float]:
        now = now or _now()
        if self.last_rssi is None:
            return None
        if (now - self.rssi_mono) * 1000 > RSSI_STALE_MS:
            return None
        return self.last_rssi

    def state_text(self) -> str:
        if self.conn == ConnState.ERROR:
            return "Link error"
        if self.conn == ConnState.RECONNECTING:
            return "Reconnecting..."
        if self.conn == ConnState.DISCONNECTED:
            return "Offline"
        if self.running:
            return "Running"
        return "Idle"


@dataclass
class LinkState:
    a_id: int
    b_id: int
    rssi: Optional[float] = None
    last_seen: Optional[str] = None
    mono: float = 0.0
    packets: int = 0
    relayed: bool = False

    @property
    def quality(self) -> str:
        return link_quality(self.rssi)


@dataclass
class SessionModel:
    nodes: dict[str, NodeState] = field(default_factory=dict)
    links: dict[tuple[int, int], LinkState] = field(default_factory=dict)
    path_class: str = "none"
    seen_direct: bool = False
    seen_via: bool = False
    path_mono: float = 0.0
    route_changes: int = 0
    run_started_host: Optional[datetime] = None
    first_deliver_host: Optional[datetime] = None
    establishment_s: Optional[float] = None
    id_to_port: dict[int, str] = field(default_factory=dict)
    anims: list[PacketAnim] = field(default_factory=list)

    # ------------------------------------------------------------ node table
    def add_node(self, port: str, name: str = "", pos: Optional[tuple[float, float]] = None):
        if port in self.nodes:
            n = self.nodes[port]
            n.conn = ConnState.CONNECTED
            n.error_msg = ""
            return n
        idx = len(self.nodes)
        default = (60.0 + (idx % 3) * 300.0, 60.0 + (idx // 3) * 260.0)
        x, y = pos or default
        n = NodeState(
            port=port,
            display_name=name or short_port_label(port),
            x=x,
            y=y,
            conn=ConnState.CONNECTED,
        )
        self.nodes[port] = n
        return n

    def mark_disconnected(self, port: str, reason: str = "") -> None:
        n = self.nodes.get(port)
        if not n:
            return
        n.conn = ConnState.DISCONNECTED if reason == "closed by user" else ConnState.ERROR
        n.running = False
        n.error_msg = "" if reason == "closed by user" else reason
        n.busy_label = ""
        n.last_rssi = None

    def mark_reconnecting(self, port: str, reason: str = "") -> None:
        n = self.nodes.get(port)
        if not n:
            return
        n.conn = ConnState.RECONNECTING
        n.running = False
        n.error_msg = reason
        n.busy_label = ""
        n.last_rssi = None

    def remove_node(self, port: str) -> None:
        n = self.nodes.pop(port, None)
        if n and n.device_id is not None:
            self.id_to_port.pop(n.device_id, None)
            self.links = {
                k: v for k, v in self.links.items() if n.device_id not in (v.a_id, v.b_id)
            }

    def node_by_id(self, device_id: int) -> Optional[NodeState]:
        port = self.id_to_port.get(device_id)
        return self.nodes.get(port) if port else None

    def ordered_ports(self) -> list[str]:
        def key(port: str) -> tuple[int, str]:
            role = self.nodes[port].role
            rank = ROLE_ORDER.index(role) if role in ROLE_ORDER else len(ROLE_ORDER)
            return rank, port
        return sorted(self.nodes.keys(), key=key)

    # ----------------------------------------------------------- staleness
    def prune_stale(self) -> None:
        now = _now()
        for n in self.nodes.values():
            if n.last_rssi is not None and (now - n.rssi_mono) * 1000 > RSSI_STALE_MS:
                n.last_rssi = None
            if not n.online:
                n.hop_count = None
        for key in [k for k, l in self.links.items() if (now - l.mono) * 1000 > LINK_STALE_MS]:
            self.links.pop(key, None)
        if self.path_class != "none" and (now - self.path_mono) * 1000 > PATH_STALE_MS:
            self.path_class = "none"
            self.seen_direct = False
            self.seen_via = False
            for n in self.nodes.values():
                n.hop_count = None
        self.anims = [a for a in self.anims if (now - a.t0) < a.duration + 0.05]

    # ------------------------------------------------------------- ingestion
    def apply_status(self, port: str, snap: StatusSnapshot) -> None:
        n = self.nodes.get(port)
        if not n:
            return
        n.error_msg = ""
        n.status_age_mono = _now()
        if snap.device_id is not None:
            if n.device_id is not None and n.device_id != snap.device_id:
                self.id_to_port.pop(n.device_id, None)
            n.device_id = snap.device_id
            self.id_to_port[snap.device_id] = port
        for attr, value in (
            ("role", snap.role),
            ("dest_id", snap.dest_id),
            ("max_hops", snap.max_hops),
            ("interval_ms", snap.interval_ms),
            ("hello_ms", snap.hello_ms),
            ("count", snap.count),
            ("power", snap.power),
            ("mcs", snap.mcs),
            ("size", snap.size),
            ("dedup", snap.dedup),
            ("source_rx", snap.source_rx),
            ("carrier", snap.carrier),
            ("net", snap.net),
            ("autostart", snap.autostart),
            ("persist", snap.persist),
            ("seq_next", snap.seq_next),
        ):
            if value is not None:
                setattr(n, attr, value)
        if snap.running is not None:
            n.running = snap.running
            if n.online:
                n.conn = ConnState.RUNNING if snap.running else ConnState.CONNECTED
        if snap.role == "source" and snap.dest_id is not None:
            n.parent_id = snap.dest_id or None
        for attr, value in (
            ("data_sent", snap.data_sent),
            ("hello_sent", snap.hello_sent),
            ("fwd_count", snap.fwd_sent),
            ("deliver_count", snap.deliver),
            ("rx_ok", snap.rx_ok),
            ("rx_fail", snap.rx_fail),
            ("fwd_dup", snap.fwd_dup),
            ("fwd_ttl", snap.fwd_ttl),
            ("fwd_qfull", snap.fwd_qfull),
            ("q_peak", snap.q_peak),
        ):
            if value is not None:
                setattr(n, attr, value)
        if snap.data_sent is not None:
            n.tx_count = snap.data_sent
        self._recompute_loss()

    def apply_neighbors(self, port: str, rows: list[Neighbor]) -> None:
        n = self.nodes.get(port)
        if not n:
            return
        n.neighbors = list(rows)
        now = _now()
        if n.device_id is None:
            return
        for row in rows:
            self._touch_link(row.id, n.device_id, row.rssi, n.last_seen, now)

    def apply_event(self, port: str, ev: TopoEvent, host_now: Optional[str] = None) -> None:
        n = self.nodes.get(port)
        if n is None:
            return
        ts = ev.host_ts or host_now
        now = _now()
        if ts:
            n.last_seen = ts

        if ev.kind == "role":
            if ev.role:
                n.role = ev.role
            if ev.device_id is not None:
                n.device_id = ev.device_id
                self.id_to_port[ev.device_id] = port
            if ev.running is not None:
                n.running = ev.running
                if n.online:
                    n.conn = ConnState.RUNNING if ev.running else ConnState.CONNECTED

        elif ev.kind in ("persist", "autostart"):
            if ev.autostart is not None:
                n.autostart = ev.autostart
            if ev.persist is not None:
                n.persist = ev.persist
            if ev.role:
                n.role = ev.role

        elif ev.kind == "tx":
            self._bind_id(n, port, ev.node)
            if (ev.msg_type or "").upper() == "HELLO":
                n.hello_sent += 1
            else:
                n.tx_count += 1
                n.data_sent += 1

        elif ev.kind in ("forward", "forward_q"):
            # The onward transmission itself; the next receiver draws the hop.
            if ev.kind == "forward":
                n.fwd_count += 1
            n.q_peak = max(n.q_peak or 0, 1)
            if ev.hops is not None:
                n.hop_count = ev.hops
            self._bind_id(n, port, ev.node)

        elif ev.kind == "rx":
            n.rx_ok += 1
            self._bind_id(n, port, ev.node)
            self._note_rssi(n, ev.rssi, now)
            self._note_air_hop(n, ev, ts, now, animate=True)

        elif ev.kind == "deliver":
            n.deliver_count += 1
            self._bind_id(n, port, ev.node)
            self._note_rssi(n, ev.rssi, now)
            if ev.hops is not None:
                n.hop_count = ev.hops
            if ev.prev is not None:
                n.parent_id = ev.prev
            # The matching RX line already animated the hop that carried this packet.
            self._note_air_hop(n, ev, ts, now, animate=False)
            self._update_path(ev.hops, ts, now)
            if self.run_started_host and self.first_deliver_host is None:
                self.first_deliver_host = datetime.now()
                self.establishment_s = (
                    self.first_deliver_host - self.run_started_host
                ).total_seconds()

        elif ev.kind in ("summary", "stopped"):
            n.running = False
            if n.conn == ConnState.RUNNING:
                n.conn = ConnState.CONNECTED

        self._recompute_loss()

    def _bind_id(self, n: NodeState, port: str, device_id: Optional[int]) -> None:
        if device_id is None:
            return
        n.device_id = device_id
        self.id_to_port[device_id] = port

    def _note_air_hop(
        self,
        n: NodeState,
        ev: TopoEvent,
        ts: Optional[str],
        now: float,
        animate: bool,
    ) -> None:
        """Credit the radio link that actually carried this frame.

        Only `prev` transmitted it. Using `src` here would invent a direct
        source-to-sink link (and paint its RSSI) for relayed traffic.
        """
        if n.device_id is None:
            return
        sender = ev.prev if ev.prev else ev.src
        if sender is None or sender == n.device_id:
            return
        relayed = bool(ev.hops and ev.hops >= 1)
        self._touch_link(sender, n.device_id, ev.rssi, ts, now, relayed=relayed)
        if animate and (ev.msg_type or "DATA").upper() != "HELLO":
            self.anims.append(PacketAnim([sender, n.device_id], now, hops=ev.hops))

    def _note_rssi(self, n: NodeState, rssi: Optional[float], now: float) -> None:
        if rssi is None:
            return
        n.last_rssi = rssi
        n.rssi_mono = now
        n.rssi_history.append(rssi)

    # ------------------------------------------------------------ run state
    def note_run_started(self) -> None:
        self.run_started_host = datetime.now()
        self.first_deliver_host = None
        self.establishment_s = None
        self.seen_direct = False
        self.seen_via = False
        self.path_class = "none"
        self.path_mono = _now()
        self.route_changes = 0

    def _update_path(self, hops: Optional[int], ts: Optional[str], now: float) -> None:
        previous = self.path_class
        if hops == 0:
            self.seen_direct = True
        elif hops is not None and hops >= 1:
            self.seen_via = True
        if self.seen_direct and self.seen_via:
            self.path_class = "both"
        elif self.seen_via:
            self.path_class = "via_relay"
        elif self.seen_direct:
            self.path_class = "direct"
        else:
            self.path_class = "none"
        self.path_mono = now
        if self.path_class != previous:
            if previous != "none":
                self.route_changes += 1
            if ts:
                for n in self.nodes.values():
                    n.last_route_change = ts

    def _touch_link(
        self,
        a: int,
        b: int,
        rssi: Optional[float],
        ts: Optional[str],
        now: float,
        relayed: bool = False,
    ) -> None:
        if a == b:
            return
        key = (min(a, b), max(a, b))
        link = self.links.get(key)
        if link is None:
            link = LinkState(a_id=key[0], b_id=key[1])
            self.links[key] = link
        if rssi is not None:
            link.rssi = rssi
        if ts:
            link.last_seen = ts
        link.mono = now
        link.packets += 1
        if relayed:
            link.relayed = True

    def _recompute_loss(self) -> None:
        sources = [n for n in self.nodes.values() if n.role == "source"]
        sinks = [n for n in self.nodes.values() if n.role == "sink"]
        if not sources or not sinks:
            return
        sent = max((s.data_sent for s in sources), default=0)
        delivered = max((s.deliver_count for s in sinks), default=0)
        if sent <= 0:
            return
        success = min(delivered, sent)
        loss = max(0.0, 100.0 * (1.0 - success / sent))
        for n in sinks:
            n.packet_loss_pct = round(loss, 1)

    # ------------------------------------------------------------------ KPIs
    def kpis(self) -> dict[str, object]:
        sources = [n for n in self.nodes.values() if n.role == "source"]
        sinks = [n for n in self.nodes.values() if n.role == "sink"]
        sent = max((n.data_sent for n in sources), default=0)
        delivered = max((n.deliver_count for n in sinks), default=0)
        pdr = (100.0 * min(delivered, sent) / sent) if sent else None
        hops = [n.hop_count for n in sinks if n.hop_count is not None]
        rssis = [n.live_rssi() for n in self.nodes.values()]
        rssis = [r for r in rssis if r is not None]
        run_s = None
        if self.run_started_host:
            run_s = (datetime.now() - self.run_started_host).total_seconds()
        return {
            "online": sum(1 for n in self.nodes.values() if n.online),
            "total": len(self.nodes),
            "running": sum(1 for n in self.nodes.values() if n.running),
            "sent": sent,
            "delivered": delivered,
            "pdr": pdr,
            "hops": hops[0] if hops else None,
            "rssi": (sum(rssis) / len(rssis)) if rssis else None,
            "path": self.path_class,
            "establishment_s": self.establishment_s,
            "route_changes": self.route_changes,
            "run_s": run_s,
        }

    def settings_match(self, port: str, expected: dict) -> tuple[bool, list[str]]:
        n = self.nodes.get(port)
        if not n:
            return False, ["node is no longer in the session"]
        mismatches: list[str] = []
        checks = (
            ("role", n.role, expected.get("role")),
            ("dest", n.dest_id, expected.get("dest")),
            ("interval", n.interval_ms, expected.get("interval")),
            ("hello", n.hello_ms, expected.get("hello")),
            ("count", n.count, expected.get("count")),
            ("power", n.power, expected.get("power")),
            ("mcs", n.mcs, expected.get("mcs")),
            ("size", n.size, expected.get("size")),
            ("max_hops", n.max_hops, expected.get("max_hops")),
            ("dedup", n.dedup, expected.get("dedup")),
        )
        for key, actual, want in checks:
            if want is None:
                continue
            if actual != want:
                mismatches.append(f"{key}: expected {want}, board reports {actual}")
        return (not mismatches), mismatches

    # ------------------------------------------------------------- snapshot
    def to_dict(self) -> dict:
        return {
            "captured": datetime.now().isoformat(timespec="seconds"),
            "kpis": self.kpis(),
            "nodes": [
                {
                    "port": n.port,
                    "name": n.display_name,
                    "device_id": n.device_id,
                    "role": n.role,
                    "state": n.state_text(),
                    "dest_id": n.dest_id,
                    "max_hops": n.max_hops,
                    "interval_ms": n.interval_ms,
                    "hello_ms": n.hello_ms,
                    "count": n.count,
                    "power": n.power,
                    "mcs": n.mcs,
                    "size": n.size,
                    "dedup": n.dedup,
                    "carrier": n.carrier,
                    "net": n.net,
                    "autostart": n.autostart,
                    "persist": n.persist,
                    "data_sent": n.data_sent,
                    "hello_sent": n.hello_sent,
                    "fwd_sent": n.fwd_count,
                    "deliver": n.deliver_count,
                    "rx_ok": n.rx_ok,
                    "rx_fail": n.rx_fail,
                    "last_rssi": n.last_rssi,
                    "hop_count": n.hop_count,
                }
                for n in self.nodes.values()
            ],
            "links": [
                {
                    "a": l.a_id,
                    "b": l.b_id,
                    "rssi": l.rssi,
                    "quality": l.quality,
                    "packets": l.packets,
                    "relayed": l.relayed,
                }
                for l in self.links.values()
            ],
        }
