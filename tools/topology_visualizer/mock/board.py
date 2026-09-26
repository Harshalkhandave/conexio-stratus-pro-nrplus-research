#!/usr/bin/env python3
"""Simulated 03_topology boards served over TCP.

Speaks the same shell dialect and emits the same log lines as the firmware, so
the visualizer can be demonstrated and regression-tested without hardware:

    net = MockNetwork()
    net.start()
    print(net.urls)   # ['socket://127.0.0.1:53401', ...]
"""

from __future__ import annotations

import random
import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

BOOT_BANNER = "*** Booting Zephyr OS build v3.7.99 ***"


def _stamp(t0: float) -> str:
    ms = int((time.monotonic() - t0) * 1000)
    return f"[{ms // 3600000:02d}:{(ms // 60000) % 60:02d}:{(ms // 1000) % 60:02d}.{ms % 1000:03d},000]"


@dataclass
class Packet:
    seq: int
    src: int
    dst: int
    prev: int
    hop: int


@dataclass
class BoardConfig:
    device_id: int
    role: str = "source"
    dest_id: int = 0
    max_hops: int = 4
    interval_ms: int = 1000
    hello_ms: int = 2000
    count: int = 0
    power: int = 11
    mcs: int = 1
    size: int = 32
    dedup: bool = True
    carrier: int = 1
    net: str = "0x1a2b"
    autostart: bool = False


@dataclass
class Counters:
    seq_next: int = 1
    data_sent: int = 0
    hello_sent: int = 0
    fwd_sent: int = 0
    rx_ok: int = 0
    rx_fail: int = 0
    deliver: int = 0
    fwd_dup: int = 0
    fwd_ttl: int = 0
    fwd_qfull: int = 0


@dataclass
class MockBoard:
    cfg: BoardConfig
    radio: "MockRadio"
    counters: Counters = field(default_factory=Counters)
    running: bool = False
    saved: Optional[dict] = None
    _clients: list[socket.socket] = field(default_factory=list)
    _seen: set = field(default_factory=set)
    _t0: float = field(default_factory=time.monotonic)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    # ------------------------------------------------------------------ output
    def attach(self, conn: socket.socket) -> None:
        with self._lock:
            self._clients.append(conn)
        self.raw(BOOT_BANNER)
        self.log(f"topology experiment ready role={self.cfg.role} device_id={self.cfg.device_id}")

    def detach(self, conn: socket.socket) -> None:
        with self._lock:
            if conn in self._clients:
                self._clients.remove(conn)

    def raw(self, text: str) -> None:
        data = (text + "\r\n").encode()
        with self._lock:
            targets = list(self._clients)
        for conn in targets:
            try:
                conn.sendall(data)
            except OSError:
                self.detach(conn)

    def log(self, text: str) -> None:
        self.raw(f"{_stamp(self._t0)} <inf> app: {text}")

    def shell(self, text: str) -> None:
        self.raw(text)

    # ----------------------------------------------------------------- shell
    def handle(self, line: str) -> None:
        line = line.strip()
        if not line:
            return
        if not line.startswith("exp"):
            self.shell(f"{line}: command not found")
            return
        parts = line.split()
        cmd = parts[1] if len(parts) > 1 else ""
        args = parts[2:]
        handler = {
            "status": self._cmd_status,
            "neigh": self._cmd_neigh,
            "start": self._cmd_start,
            "stop": self._cmd_stop,
            "role": self._cmd_role,
            "sett": self._cmd_sett,
            "save": self._cmd_save,
            "load": self._cmd_load,
            "factory": self._cmd_factory,
            "autostart": self._cmd_autostart,
        }.get(cmd)
        if handler is None:
            self.shell(f"unknown command: exp {cmd}")
            return
        handler(args)

    def _cmd_status(self, _args: list[str]) -> None:
        c, k = self.cfg, self.counters
        self.shell("exp status:")
        self.shell(
            f"  role={c.role} running={1 if self.running else 0} device_id={c.device_id} "
            f"dest_id={c.dest_id} max_hops={c.max_hops}"
        )
        self.shell(f"  carrier={c.carrier} net={c.net}")
        self.shell(
            f"  interval_ms={c.interval_ms} hello_ms={c.hello_ms} count={c.count} (0=forever)"
        )
        self.shell(f"  power={c.power} mcs={c.mcs} size={c.size} dedup={1 if c.dedup else 0}")
        self.shell(
            f"  autostart={1 if c.autostart else 0} persist={1 if self.saved else 0}"
        )
        self.shell(
            f"  seq_next={k.seq_next} data_sent={k.data_sent} hello_sent={k.hello_sent} "
            f"fwd_sent={k.fwd_sent}"
        )
        self.shell(
            f"  rx_ok={k.rx_ok} rx_fail={k.rx_fail} deliver={k.deliver} fwd_dup={k.fwd_dup} "
            f"fwd_ttl={k.fwd_ttl} fwd_qfull={k.fwd_qfull}"
        )

    def _cmd_neigh(self, _args: list[str]) -> None:
        self.shell("exp neigh:")
        peers = [b for b in self.radio.boards if b is not self and self.radio.linked(self, b)]
        if not peers:
            self.shell("  (none)")
            return
        for peer in peers:
            rssi = -63 - random.random() * 6
            self.shell(
                f"  id={peer.cfg.device_id} rssi={int(rssi)}.{abs(int(rssi * 10)) % 10} "
                f"last_ms={int((time.monotonic() - self._t0) * 1000)} "
                f"hello={self.counters.rx_ok} data={self.counters.deliver}"
            )

    def _cmd_start(self, args: list[str]) -> None:
        if self.running:
            self.shell("already running; stop first")
            return
        if self.cfg.role == "source" and not self.cfg.dest_id:
            self.shell("source needs dest_id; set: exp sett dest <id>")
            return
        if args:
            try:
                self.cfg.count = int(args[0])
            except ValueError:
                pass
        self.running = True
        self.shell(
            f"started role={self.cfg.role} dest={self.cfg.dest_id} count={self.cfg.count} "
            "(0=forever)"
        )
        self.log(f"started role={self.cfg.role} device_id={self.cfg.device_id} running=1")

    def _cmd_stop(self, _args: list[str]) -> None:
        if not self.running:
            self.shell("not running")
            return
        self.running = False
        self.shell("stop requested")
        k = self.counters
        self.log(
            f"SUMMARY: role={self.cfg.role} reason=user device_id={self.cfg.device_id} "
            f"dest={self.cfg.dest_id} data_sent={k.data_sent} hello_sent={k.hello_sent} "
            f"fwd_sent={k.fwd_sent} rx_ok={k.rx_ok} deliver={k.deliver}"
        )

    def _cmd_role(self, args: list[str]) -> None:
        if not args:
            self.shell("usage: exp role <source|relay|sink>")
            return
        if self.running:
            self.shell("stop the run before changing role")
            return
        if args[0] not in ("source", "relay", "sink"):
            self.shell(f"unknown role '{args[0]}' (source|relay|sink)")
            return
        self.cfg.role = args[0]
        self.shell(f"role={self.cfg.role} (RAM only -> exp save to persist)")

    def _cmd_sett(self, args: list[str]) -> None:
        if len(args) < 2:
            self.shell("usage: exp sett <key> <value>")
            return
        if self.running:
            self.shell("stop the run before changing settings")
            return
        key, value = args[0], args[1]
        if key == "role":
            return self._cmd_role([value])
        if key == "autostart":
            return self._cmd_autostart([value])
        if key == "dedup":
            val = value.lower()
            if val not in ("on", "off", "1", "0", "true", "false"):
                self.shell("dedup must be on|off (or 1|0)")
                return
            self.cfg.dedup = val in ("on", "1", "true")
            self.shell(f"dedup={1 if self.cfg.dedup else 0} (RAM — exp save to persist)")
            return
        try:
            number = int(value, 0)
        except ValueError:
            self.shell(f"unknown key '{key}'")
            return
        limits = {
            "dest": (0, 65535),
            "interval": (10, 600000),
            "hello": (0, 600000),
            "count": (0, 1000000),
            "power": (0, 13),
            "mcs": (0, 7),
            "size": (8, 32),
            "max_hops": (1, 16),
        }
        if key not in limits:
            self.shell(f"unknown key '{key}'")
            return
        lo, hi = limits[key]
        if not lo <= number <= hi:
            self.shell(f"{key} must be {lo}..{hi}")
            return
        attr = {
            "dest": "dest_id",
            "interval": "interval_ms",
            "hello": "hello_ms",
            "count": "count",
            "power": "power",
            "mcs": "mcs",
            "size": "size",
            "max_hops": "max_hops",
        }[key]
        setattr(self.cfg, attr, number)
        self.shell("ok (RAM -> exp save to persist)")

    def _cmd_save(self, _args: list[str]) -> None:
        self.saved = dict(self.cfg.__dict__)
        self.shell(
            f"saved role={self.cfg.role} dest={self.cfg.dest_id} "
            f"autostart={1 if self.cfg.autostart else 0}"
        )

    def _cmd_load(self, _args: list[str]) -> None:
        if self.running:
            self.shell("stop the run before load")
            return
        if not self.saved:
            self.shell("no saved profile (or load failed)")
            return
        self.cfg = BoardConfig(**self.saved)
        self.shell(
            f"loaded role={self.cfg.role} dest={self.cfg.dest_id} "
            f"autostart={1 if self.cfg.autostart else 0}"
        )

    def _cmd_factory(self, _args: list[str]) -> None:
        if self.running:
            self.shell("stop the run before factory reset of profile")
            return
        self.saved = None
        self.cfg.autostart = False
        self.cfg.dedup = True
        self.shell("cleared flash profile; RAM restored to Kconfig defaults")
        self.shell(f"role={self.cfg.role} dest={self.cfg.dest_id} autostart=0")

    def _cmd_autostart(self, args: list[str]) -> None:
        if not args:
            self.shell(
                f"autostart={1 if self.cfg.autostart else 0} persist={1 if self.saved else 0}"
            )
            return
        value = args[0].lower()
        if value not in ("on", "off", "1", "0"):
            self.shell("autostart must be on|off (or 1|0)")
            return
        self.cfg.autostart = value in ("on", "1")
        self.shell(
            f"autostart={1 if self.cfg.autostart else 0} "
            "(RAM -> exp save to persist across reset)"
        )

    # ----------------------------------------------------------------- radio
    def tick(self, now: float, last_tx: dict, last_hello: dict) -> None:
        if not self.running:
            return
        cfg = self.cfg
        if cfg.hello_ms and now - last_hello.get(self.cfg.device_id, 0) >= cfg.hello_ms / 1000:
            last_hello[cfg.device_id] = now
            self.counters.hello_sent += 1
            self.log(f"TX: node={cfg.device_id} type=HELLO size=24 time={int(now * 1000) % 100000}")
            self.radio.hello(self)
        if cfg.role != "source":
            return
        if now - last_tx.get(cfg.device_id, 0) < cfg.interval_ms / 1000:
            return
        if cfg.count and self.counters.data_sent >= cfg.count:
            self.running = False
            self.shell("run complete")
            return
        last_tx[cfg.device_id] = now
        pkt = Packet(seq=self.counters.seq_next, src=cfg.device_id, dst=cfg.dest_id, prev=cfg.device_id, hop=0)
        self.counters.seq_next += 1
        self.counters.data_sent += 1
        self.log(
            f"TX: node={cfg.device_id} type=DATA seq={pkt.seq} src={pkt.src} dst={pkt.dst} "
            f"hop=0 size={cfg.size} time={int(now * 1000) % 100000}"
        )
        self.radio.send(self, pkt)

    def on_hello(self, sender: "MockBoard") -> None:
        rssi = -60 - random.random() * 8
        self.counters.rx_ok += 1
        self.log(
            f"RX: node={self.cfg.device_id} type=HELLO src={sender.cfg.device_id} "
            f"rssi={int(rssi)}.{random.randint(0, 9)} time={int(time.monotonic() * 1000) % 100000}"
        )

    def on_rx(self, pkt: Packet) -> None:
        me = self.cfg.device_id
        rssi = -62 - pkt.hop * 9 - random.random() * 5
        rssi_i, rssi_f = int(rssi), random.randint(0, 9)
        self.counters.rx_ok += 1
        self.log(
            f"RX: node={me} type=DATA seq={pkt.seq} src={pkt.src} dst={pkt.dst} prev={pkt.prev} "
            f"hop={pkt.hop} rssi={rssi_i}.{rssi_f} time={int(time.monotonic() * 1000) % 100000}"
        )
        if pkt.dst == me:
            key = (pkt.src, pkt.seq)
            if key in self._seen:
                self.counters.fwd_dup += 1
                return
            self._seen.add(key)
            self.counters.deliver += 1
            self.log(
                f"DELIVER: node={me} seq={pkt.seq} src={pkt.src} prev={pkt.prev} "
                f"hops={pkt.hop} rssi={rssi_i}.{rssi_f} time={int(time.monotonic() * 1000)}"
            )
            return
        if self.cfg.role != "relay":
            return
        if pkt.hop >= self.cfg.max_hops:
            self.counters.fwd_ttl += 1
            self.log(
                f"FORWARD_DROP: node={me} seq={pkt.seq} src={pkt.src} reason=ttl "
                f"hop={pkt.hop} max={self.cfg.max_hops}"
            )
            return
        forwarded = Packet(pkt.seq, pkt.src, pkt.dst, me, pkt.hop + 1)
        self.counters.fwd_sent += 1
        self.log(
            f"FORWARD: node={me} seq={forwarded.seq} src={forwarded.src} dst={forwarded.dst} "
            f"prev={forwarded.prev} hop={forwarded.hop} size={self.cfg.size}"
        )
        self.radio.send(self, forwarded, delay=0.05)


class MockRadio:
    """Shared airtime with an optional reachability matrix."""

    def __init__(self) -> None:
        self.boards: list[MockBoard] = []
        self.blocked: set[tuple[int, int]] = set()

    def block(self, a: int, b: int) -> None:
        self.blocked.add((min(a, b), max(a, b)))

    def linked(self, a: MockBoard, b: MockBoard) -> bool:
        key = (min(a.cfg.device_id, b.cfg.device_id), max(a.cfg.device_id, b.cfg.device_id))
        return key not in self.blocked

    def hello(self, sender: MockBoard) -> None:
        for board in self.boards:
            if board is not sender and self.linked(sender, board):
                board.on_hello(sender)

    def send(self, sender: MockBoard, pkt: Packet, delay: float = 0.0) -> None:
        def deliver() -> None:
            for board in self.boards:
                if board is sender or not self.linked(sender, board):
                    continue
                board.on_rx(pkt)

        if delay:
            timer = threading.Timer(delay, deliver)
            timer.daemon = True
            timer.start()
        else:
            deliver()


class MockNetwork:
    """Three simulated boards, each reachable on its own TCP port."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        direct_source_to_sink: bool = False,
        autostart: bool = False,
    ) -> None:
        self.host = host
        self.radio = MockRadio()
        self.boards = [
            MockBoard(BoardConfig(device_id=11, role="source", dest_id=33), self.radio),
            MockBoard(BoardConfig(device_id=22, role="relay"), self.radio),
            MockBoard(BoardConfig(device_id=33, role="sink"), self.radio),
        ]
        self.radio.boards = self.boards
        if not direct_source_to_sink:
            self.radio.block(11, 33)
        if autostart:
            for board in self.boards:
                board.running = True
        self._servers: list[socket.socket] = []
        self._threads: list[threading.Thread] = []
        self._stop = threading.Event()
        self.urls: list[str] = []

    def start(self) -> list[str]:
        for board in self.boards:
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind((self.host, 0))
            srv.listen(1)
            srv.settimeout(0.3)
            self._servers.append(srv)
            port = srv.getsockname()[1]
            self.urls.append(f"socket://{self.host}:{port}")
            th = threading.Thread(target=self._serve, args=(srv, board), daemon=True)
            th.start()
            self._threads.append(th)
        ticker = threading.Thread(target=self._tick_loop, daemon=True)
        ticker.start()
        self._threads.append(ticker)
        return self.urls

    def _serve(self, srv: socket.socket, board: MockBoard) -> None:
        while not self._stop.is_set():
            try:
                conn, _addr = srv.accept()
            except (TimeoutError, OSError):
                continue
            conn.settimeout(0.3)
            board.attach(conn)
            threading.Thread(
                target=self._read_loop, args=(conn, board), daemon=True
            ).start()

    def _read_loop(self, conn: socket.socket, board: MockBoard) -> None:
        buf = b""
        while not self._stop.is_set():
            try:
                chunk = conn.recv(256)
            except TimeoutError:
                continue
            except OSError:
                break
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                board.handle(raw.decode(errors="replace").strip())
        board.detach(conn)
        try:
            conn.close()
        except OSError:
            pass

    def _tick_loop(self) -> None:
        last_tx: dict[int, float] = {}
        last_hello: dict[int, float] = {}
        while not self._stop.is_set():
            now = time.monotonic()
            for board in self.boards:
                try:
                    board.tick(now, last_tx, last_hello)
                except Exception:  # noqa: BLE001 - a simulation glitch must not stop the demo
                    pass
            time.sleep(0.05)

    def stop(self) -> None:
        self._stop.set()
        for srv in self._servers:
            try:
                srv.close()
            except OSError:
                pass
        self._servers.clear()
