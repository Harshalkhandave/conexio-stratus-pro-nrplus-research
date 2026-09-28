#!/usr/bin/env python3
r"""Headless regression run for the visualizer.

Starts three simulated boards, drives the real UI against them and checks the
whole chain: parsing, verified commands, live model, capture files, snapshot
export and both themes.

    .\.venv\Scripts\python.exe tests\test_smoke.py
    .\.venv\Scripts\python.exe tests\test_smoke.py --shots artifacts --show
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FAILURES: list[str] = []
CHECKS = 0


def check(label: str, condition: bool, detail: str = "") -> bool:
    global CHECKS
    CHECKS += 1
    if condition:
        print(f"  PASS  {label}")
    else:
        FAILURES.append(label)
        print(f"  FAIL  {label}" + (f" — {detail}" if detail else ""))
    return bool(condition)


# --------------------------------------------------------------------- parsing
def test_parsing() -> None:
    from core.parse_topo import (
        NeighborAccumulator,
        StatusAccumulator,
        app_payload,
        clean_line,
        parse_line,
    )

    print("parsing")
    status_block = [
        "exp status:",
        "  role=relay running=1 device_id=22 dest_id=0 max_hops=4",
        "  carrier=1 net=0x1a2b",
        "  interval_ms=1000 hello_ms=2000 count=0 (0=forever)",
        "  power=11 mcs=1 size=32 dedup=1 source_rx=1 rx_win=2000 fwd=cut_through",
        "  autostart=1 persist=1",
        "  seq_next=5 data_sent=4 hello_sent=2 fwd_sent=3",
        "  rx_ok=9 rx_fail=1 deliver=0 fwd_dup=1 fwd_ttl=0 fwd_qfull=0 q_peak=2",
    ]
    acc = StatusAccumulator()
    snap = None
    for line in status_block:
        snap = acc.feed(line) or snap
    check("status block parsed", snap is not None)
    if snap:
        check("status role/id", snap.role == "relay" and snap.device_id == 22)
        check("status running flag", snap.running is True)
        check("status dedup flag", snap.dedup is True)
        check("status source_rx flag", snap.source_rx is True)
        check("status rx_win", snap.rx_window_ms == 2000)
        check("status fwd_mode", snap.fwd_mode == "cut_through")
        check("status autostart + persist", snap.autostart is True and snap.persist is True)
        check("status counters", snap.rx_ok == 9 and snap.fwd_sent == 3)
        check("status q_peak", snap.q_peak == 2)

    # Test status block with interleaved asynchronous logs
    interleaved_block = [
        "exp status:",
        "  role=source running=1 device_id=14402 dest_id=56992 max_hops=1",
        "TX: node=14402 type=DATA seq=58 src=14402 dst=56992 hop=0 size=64 time=1518359 time_us=1518359772",
        "--- 3 messages dropped ---",
        "  carrier=0 net=0x1234",
        "  interval_ms=10 hello_ms=1000 count=0 (0=forever)",
        "RX: node=44720 type=DATA seq=58 src=14402 dst=56992 prev=14402 hop=0 rssi=-68.0 time=7968600 time_us=7968600739",
        "FORWARD_Q: node=44720 seq=58 src=14402 dst=56992 prev=44720 hop=1",
        "  power=0 mcs=0 size=64 dedup=0 source_rx=0 rx_win=0 fwd=FLOOD",
        "  autostart=0 persist=1",
        "  seq_next=59 data_sent=58 hello_sent=1 fwd_sent=0",
        "  rx_ok=0 rx_fail=0 deliver=0 fwd_dup=0 fwd_ttl=0 fwd_qfull=0 q_peak=0",
    ]
    acc_intl = StatusAccumulator()
    snap_intl = None
    for line in interleaved_block:
        res = acc_intl.feed(line)
        if res:
            snap_intl = res
    check("interleaved status parsed", snap_intl is not None and snap_intl.seq_next == 59 and snap_intl.device_id == 14402)

    deliver = parse_line(
        "[10:11:12.130] <inf> app: DELIVER: node=33 seq=7 src=11 prev=22 hops=1 rssi=-71.2 time=99 time_us=99000123"
    )
    check("deliver parsed", deliver is not None and deliver.kind == "deliver")
    if deliver:
        check("deliver fields", deliver.src == 11 and deliver.prev == 22 and deliver.hops == 1)
        check("deliver rssi", abs((deliver.rssi or 0) + 71.2) < 0.01)
        check("deliver time_us", deliver.time_us == 99000123)

    tx = parse_line("<inf> app: TX: node=11 type=DATA seq=3 src=11 dst=33 hop=0 size=32 time=12 time_us=12000456")
    check("tx parsed", tx is not None and tx.kind == "tx" and tx.dst == 33 and tx.time_us == 12000456)

    dedup = parse_line("dedup=1 (RAM — exp save to persist)")
    check("dedup ack parsed", dedup is not None and dedup.kind == "ack")

    source_rx = parse_line("source_rx=0 (RAM — exp save to persist)")
    check("source_rx ack parsed", source_rx is not None and source_rx.kind == "ack")

    rx_win_ack = parse_line("rx_window=500 ms (source_rx=1) (RAM — exp save to persist)")
    check("rx_window ack parsed", rx_win_ack is not None and rx_win_ack.kind == "ack")

    fwd_mode_ack = parse_line("fwd_mode=cut_through (RAM — exp save to persist)")
    check("fwd_mode ack parsed", fwd_mode_ack is not None and fwd_mode_ack.kind == "ack")

    autostart = parse_line("autostart=1 (RAM -> exp save to persist across reset)")
    check("autostart ack parsed", autostart is not None and autostart.autostart is True)

    saved = parse_line("saved role=sink dest=0 autostart=1")
    check("save ack parsed", saved is not None and saved.kind == "persist")

    neigh = NeighborAccumulator()
    neigh.feed("exp neigh:")
    neigh.feed("  id=22 rssi=-64.3 last_ms=120 hello=4 data=2")
    rows = neigh.feed("uart:~$")
    check("neighbour rows parsed", bool(rows) and rows[0].id == 22)

    check("ansi + prompt stripped", clean_line("\x1b[1;32muart:~$ exp status") == "exp status")
    check("log prefix stripped", app_payload("<inf> app: TX: node=1") == "TX: node=1")

    queued = parse_line("<inf> app: FORWARD_Q: node=22 seq=3 src=11 dst=33 prev=22 hop=1")
    check("forward enqueue kept separate", queued is not None and queued.kind == "forward_q")
    sent = parse_line("<inf> app: FORWARD: node=22 seq=3 src=11 dst=33 prev=22 hop=1 size=18")
    check("forward transmit parsed", sent is not None and sent.kind == "forward")

    drop_ttl = parse_line("<inf> app: FORWARD_DROP: node=22 seq=3 src=11 reason=ttl hop=5 max=4")
    check("forward_drop ttl parsed", drop_ttl is not None and drop_ttl.kind == "forward_drop" and drop_ttl.msg_type == "ttl" and drop_ttl.hops == 5)
    drop_qfull = parse_line("<inf> app: FORWARD_DROP: node=22 seq=3 reason=queue_full")
    check("forward_drop qfull parsed", drop_qfull is not None and drop_qfull.kind == "forward_drop" and drop_qfull.msg_type == "queue_full")
    from core.parse_topo import severity
    check("forward drop severity is warn", severity("FORWARD_DROP: node=22 reason=ttl") == "warn")

    deliv_hop = parse_line("<inf> app: DELIVER: node=33 seq=7 src=11 prev=22 hop=2 rssi=-70.0")
    check("deliver hop singular parsed", deliv_hop is not None and deliv_hop.hops == 2)
    tx_hops = parse_line("<inf> app: TX: node=11 type=DATA seq=3 src=11 dst=33 hops=0 size=32")
    check("tx hops plural parsed", tx_hops is not None and tx_hops.hops == 0)


def test_model_reset_and_events() -> None:
    from core.model import SessionModel
    from core.parse_topo import parse_line

    print("model metrics reset and drop/summary events")
    m = SessionModel()
    m.add_node("COM1")
    m.add_node("COM2")
    m.nodes["COM1"].role = "source"
    m.nodes["COM2"].role = "sink"

    m.apply_event("COM1", parse_line("<inf> app: TX: node=11 type=DATA seq=1 src=11 dst=33 hop=0 size=32"))
    m.apply_event("COM1", parse_line("<inf> app: TX: node=11 type=DATA seq=2 src=11 dst=33 hop=0 size=32"))
    m.apply_event("COM2", parse_line("<inf> app: RX: node=33 type=DATA seq=1 src=11 dst=33 prev=11 hop=0 rssi=-65.0"))
    m.apply_event("COM2", parse_line("<inf> app: DELIVER: node=33 seq=1 src=11 prev=11 hops=0 rssi=-65.0"))

    check("traffic recorded in model", m.nodes["COM1"].tx_count == 2 and m.nodes["COM2"].deliver_count == 1)
    k = m.kpis()
    check("kpis show pdr", k["pdr"] == 50.0 and k["sent"] == 2 and k["delivered"] == 1)

    m.apply_event("COM1", parse_line("<inf> app: FORWARD_DROP: node=11 seq=3 reason=ttl hop=5 max=4"))
    check("forward_drop ttl incremented", m.nodes["COM1"].fwd_ttl == 1)
    m.apply_event("COM1", parse_line("<inf> app: FORWARD_DROP: node=11 seq=4 reason=queue_full"))
    check("forward_drop qfull incremented", m.nodes["COM1"].fwd_qfull == 1)
    m.apply_event("COM1", parse_line("<inf> app: FORWARD_DROP: duplicate from 11 seq 1"))
    check("forward_drop dup incremented", m.nodes["COM1"].fwd_dup == 1)

    m.reset_metrics()
    check("counters zeroed after reset", m.nodes["COM1"].tx_count == 0 and m.nodes["COM2"].deliver_count == 0)
    check("drop counters zeroed", m.nodes["COM1"].fwd_ttl == 0 and m.nodes["COM1"].fwd_qfull == 0 and m.nodes["COM1"].fwd_dup == 0)
    check("pdr cleared after reset", m.kpis()["pdr"] is None and m.kpis()["sent"] == 0 and m.kpis()["delivered"] == 0)
    check("anims cleared", len(m.anims) == 0)

    sum_ev = parse_line("SUMMARY: role=source reason=completed device_id=11 dest=33 data_sent=50 hello_sent=10 fwd_sent=0 rx_ok=5 rx_fail=0 deliver=0 q_peak=1")
    m.apply_event("COM1", sum_ev)
    check("summary counters synced to model", m.nodes["COM1"].data_sent == 50 and m.nodes["COM1"].tx_count == 50 and m.nodes["COM1"].hello_sent == 10)


# ------------------------------------------------------------- relayed traffic
def test_relay_paths() -> None:
    """A relayed packet must never draw a direct source-to-sink link."""
    from core.model import SessionModel
    from core.parse_topo import parse_line

    print("relayed path model")
    m = SessionModel()
    for port in ("relay", "sink"):
        m.add_node(port)
    lines = [
        ("relay", "RX: node=22 type=DATA seq=1 src=11 dst=33 prev=11 hop=0 rssi=-70.0 time=1"),
        ("relay", "FORWARD_Q: node=22 seq=1 src=11 dst=33 prev=22 hop=1"),
        ("relay", "FORWARD: node=22 seq=1 src=11 dst=33 prev=22 hop=1 size=18"),
        ("sink", "RX: node=33 type=DATA seq=1 src=11 dst=33 prev=22 hop=1 rssi=-80.0 time=2"),
        ("sink", "DELIVER: node=33 seq=1 src=11 prev=22 hops=1 rssi=-80.0 time=2"),
    ]
    for port, body in lines:
        event = parse_line(f"<inf> app: {body}")
        if event:
            m.apply_event(port, event)

    keys = sorted(m.links)
    check("only the two real hops exist", keys == [(11, 22), (22, 33)], str(keys))
    check("no phantom source-to-sink link", (11, 33) not in m.links)
    check("sink rssi belongs to the relay hop", m.links[(22, 33)].rssi == -80.0)
    check("source hop keeps its own rssi", m.links[(11, 22)].rssi == -70.0)
    hops = [a.waypoints for a in m.anims]
    check("one animation per air hop", hops == [[11, 22], [22, 33]], str(hops))
    check("forward counted once, not per queue entry", m.nodes["relay"].fwd_count == 1)

    hello = parse_line("<inf> app: RX: node=33 type=HELLO src=11 rssi=-88.0 time=3")
    if hello:
        m.apply_event("sink", hello)
    check("hello discovers a link without animating", (11, 33) in m.links and len(m.anims) == 2)


# ------------------------------------------------------------------ capture io
def test_capture_files() -> None:
    from core.logging_session import LoggingSession

    print("capture files")
    tmp = Path(tempfile.mkdtemp(prefix="nrplus-log-"))
    try:
        session = LoggingSession(tmp)
        folder = session.start("exp1", ["COM9"], {"COM9": "COM9"})
        prompt = "\x1b[1;32muart:~$ \x1b[m\x1b[8D\x1b[J"
        session.write(
            "COM9",
            "17:57:45.223",
            f"{prompt}{prompt}[00:10:36.162,658] \x1b[0m<inf> app: RX: node=44720 seq=3\x1b[0m",
        )
        session.write("COM9", "17:57:45.224", prompt)
        session.stop()

        path = folder / "COM9_log.txt"
        check("log file carries the _log suffix", path.exists(), str(list(folder.iterdir())))
        lines = path.read_text(encoding="utf-8").splitlines()
        payload = [ln for ln in lines if not ln.startswith("=====")]
        check("no escape codes survive", all("\x1b" not in ln for ln in lines))
        check("prompt-only line dropped", len(payload) == 1, str(payload))
        check(
            "payload kept verbatim",
            bool(payload)
            and payload[0] == "[17:57:45.223] [00:10:36.162,658] <inf> app: RX: node=44720 seq=3",
            str(payload[:1]),
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ------------------------------------------------------------------------ app
class Harness:
    def __init__(self, shots: Path | None, show: bool) -> None:
        self.shots = shots
        self.tmp = Path(tempfile.mkdtemp(prefix="nrplus-vis-"))
        if not show:
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        os.environ["QT_SCALE_FACTOR"] = "1"

        from PySide6.QtCore import QSettings
        from PySide6.QtWidgets import QApplication

        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(
            QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(self.tmp / "settings")
        )
        self.app = QApplication.instance() or QApplication([])
        self.app.setStyle("Fusion")

        from ui import theme

        theme.set_theme(self.app, "light")

        from mock.board import MockNetwork

        self.network = MockNetwork()
        self.ports = self.network.start()

        import ui.main_window as mw

        mw.DATA_ROOT = self.tmp / "capture"
        self.mw = mw
        self.window = mw.MainWindow(initial_ports=None)
        self.window.resize(1560, 940)
        self.window.show()
        self.pump(0.3)
        self.window.connect_ports(self.ports)

    def pump(self, seconds: float) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.008)

    def wait_for(self, predicate, timeout: float = 8.0) -> bool:  # noqa: ANN001
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if predicate():
                return True
            self.pump(0.05)
        return predicate()

    def shot(self, name: str) -> None:
        if self.shots is None:
            return
        self.shots.mkdir(parents=True, exist_ok=True)
        self.pump(0.35)
        path = self.shots / f"{name}.png"
        self.window.grab().save(str(path))
        print(f"        screenshot: {path}")

    def close(self) -> None:
        self.window.close()
        self.pump(0.2)
        self.network.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)


def test_source_rx_and_flash_lifecycle() -> None:
    from mock.board import BoardConfig, MockBoard, MockRadio

    print("source_rx lifecycle and flash persistence")
    radio = MockRadio()
    board = MockBoard(cfg=BoardConfig(device_id=11, role="source", dest_id=33), radio=radio)
    radio.boards.append(board)

    # 1. Default is source_rx = True
    check("initial source_rx is true", board.cfg.source_rx is True)

    # 2. Turn off source_rx
    board.handle("exp sett source_rx off")
    check("source_rx turned off", board.cfg.source_rx is False)

    # 3. Changing role resets source_rx back to True (does not remember off)
    board.handle("exp role relay")
    check("role change to relay resets source_rx to true", board.cfg.role == "relay" and board.cfg.source_rx is True)

    # 4. Changing back to source still has source_rx as True (must turn off again)
    board.handle("exp role source")
    check("role change back to source keeps source_rx as true", board.cfg.role == "source" and board.cfg.source_rx is True)

    # 5. User turns source_rx off again and saves to flash
    board.handle("exp sett source_rx off")
    board.handle("exp save")
    check("saved profile has source_rx false", board.saved is not None and board.saved.get("source_rx") is False)

    # 6. Role changed in RAM without saving
    board.handle("exp role relay")
    check("RAM role is relay with source_rx true", board.cfg.role == "relay" and board.cfg.source_rx is True)

    # 7. Loading from flash restores role=source and source_rx=False
    board.handle("exp load")
    check("loaded profile restores source_rx false", board.cfg.role == "source" and board.cfg.source_rx is False)

    # 8. Factory reset clears profile and restores source_rx=True
    board.handle("exp reset")
    check("reset alias restores source_rx true", board.cfg.source_rx is True and board.saved is None)

    # 9. Test rx_window and fwd_mode shell commands and aliases
    board.handle("exp set rx_window 350")
    check("exp set rx_window updates rx_window_ms", board.cfg.rx_window_ms == 350 and board.cfg.source_rx is True)
    board.handle("exp sett rx_window 0")
    check("rx_window 0 turns source_rx off", board.cfg.rx_window_ms == 0 and board.cfg.source_rx is False)
    board.handle("exp set fwd_mode batch")
    check("exp set fwd_mode updates fwd_mode", board.cfg.fwd_mode == "batch")
    board.handle("exp factory")


def test_app(shots: Path | None, show: bool) -> None:
    h = Harness(shots, show)
    model = h.window.model
    try:
        print("connect + status discovery")
        ok = h.wait_for(lambda: sum(1 for n in model.nodes.values() if n.identified) == 3)
        check("three boards connected and identified", ok,
              f"ids={[n.device_id for n in model.nodes.values()]}")
        roles = sorted(n.role or "" for n in model.nodes.values())
        check("roles read from boards", roles == ["relay", "sink", "source"], str(roles))
        check("no node reported an error", all(not n.error_msg for n in model.nodes.values()))

        source = next(p for p, n in model.nodes.items() if n.role == "source")
        sink = next(p for p, n in model.nodes.items() if n.role == "sink")

        print("selection + inspector")
        h.window.select_node(source)
        h.pump(0.25)
        check("inspector follows selection", h.window.inspector.current_port() == source)
        check("form is clean after load", not h.window.inspector.is_dirty())
        check("source_rx is enabled for source role", h.window.inspector.chk_source_rx.isEnabled())
        h.window.select_node(sink)
        h.wait_for(lambda: not h.window.engine.busy(sink))
        check("source_rx is frozen for sink role", not h.window.inspector.chk_source_rx.isEnabled() and h.window.inspector.chk_source_rx.isChecked())
        h.window.select_node(source)
        h.wait_for(lambda: not h.window.engine.busy(source) and h.window.inspector.chk_source_rx.isEnabled())
        check("source_rx is enabled again when switching back to source", h.window.inspector.chk_source_rx.isEnabled())
        h.window.inspector.cmb_role.setCurrentText("relay")
        h.pump(0.1)
        check("source_rx freezes when role changed to relay", not h.window.inspector.chk_source_rx.isEnabled() and h.window.inspector.chk_source_rx.isChecked())
        h.window.inspector.cmb_role.setCurrentText("source")
        h.pump(0.1)
        check("source_rx auto-enabled when role changed back to source", h.window.inspector.chk_source_rx.isEnabled() and h.window.inspector.chk_source_rx.isChecked())
        # Verify that toggling through roles without applying preserves custom source_rx=False:
        h.window.inspector.chk_source_rx.setChecked(False)
        h.window.inspector._on_source_rx_clicked(False)
        h.window.inspector.cmb_role.setCurrentText("sink")
        h.pump(0.1)
        check("source_rx frozen on sink", not h.window.inspector.chk_source_rx.isEnabled() and h.window.inspector.chk_source_rx.isChecked())
        h.window.inspector.cmb_role.setCurrentText("source")
        h.pump(0.1)
        check("source_rx preserved as False when cycling back to source without applying", h.window.inspector.chk_source_rx.isEnabled() and not h.window.inspector.chk_source_rx.isChecked())
        h.window.inspector._revert()  # noqa: SLF001
        h.pump(0.1)
        h.window.auto_layout()
        h.pump(0.2)
        h.shot("01_connected_light")

        print("verified apply")
        h.window.store.set("confirm_apply", False)
        h.window.store.set("confirm_run", False)
        h.window.inspector.spins["interval"].setValue(500)
        h.window.inspector.spins["power"].setValue(9)
        h.window.inspector.spins["size"].setValue(128)
        h.window.inspector.chk_source_rx.setChecked(False)
        check("form marked dirty", h.window.inspector.is_dirty())
        h.window.inspector._apply()  # noqa: SLF001 - same path as the Apply button
        applied = h.wait_for(
            lambda: model.nodes[source].interval_ms == 500
            and model.nodes[source].power == 9
            and model.nodes[source].size == 128
            and model.nodes[source].source_rx is False
        )
        check("settings applied and verified", applied,
              f"interval={model.nodes[source].interval_ms} power={model.nodes[source].power} size={model.nodes[source].size} source_rx={model.nodes[source].source_rx}")
        released = h.wait_for(lambda: not h.window.overlay.isVisible(), timeout=6)
        check("busy overlay released", released)
        check("form clean after apply", not h.window.inspector.is_dirty())

        print("rejected apply")
        h.window.inspector.spins["mcs"].setValue(7)
        h.window.inspector._revert()  # noqa: SLF001
        h.pump(0.2)

        print("start network")
        h.window.start_network()
        running = h.wait_for(lambda: all(n.running for n in model.nodes.values()), timeout=10)
        check("all three nodes running", running,
              str({n.label: n.running for n in model.nodes.values()}))
        delivered = h.wait_for(lambda: model.nodes[sink].deliver_count >= 2, timeout=12)
        check("sink delivers packets", delivered, f"deliver={model.nodes[sink].deliver_count}")
        check("relay forwards traffic",
              any(n.fwd_count > 0 for n in model.nodes.values() if n.role == "relay"))
        check("relay recorded queue peak",
              any((n.q_peak or 0) >= 1 for n in model.nodes.values() if n.role == "relay"))
        check("path classified via relay", model.path_class == "via_relay", model.path_class)
        check("links discovered", len(model.links) >= 2, str(list(model.links)))
        src_id = model.nodes[source].device_id
        sink_id = model.nodes[sink].device_id
        blocked = (min(src_id, sink_id), max(src_id, sink_id))
        check("blocked source-sink pair stays unlinked", blocked not in model.links,
              str(list(model.links)))
        check("hop count reported", model.nodes[sink].hop_count == 1)
        check("rssi is live", model.nodes[sink].live_rssi() is not None)
        check("links carry RSSI",
              all(l.rssi is not None for l in model.links.values()),
              str({k: l.rssi for k, l in model.links.items()}))
        check("links saw packet traffic", any(l.packets > 0 for l in model.links.values()))
        kpi = model.kpis()
        check("kpi delivery ratio computed", kpi["pdr"] is not None, str(kpi))
        check("route establishment measured", model.establishment_s is not None)
        h.window.select_node(sink)
        h.pump(0.4)
        h.shot("02_running_light")

        print("console")
        check("console received traffic", len(h.window.console._lines) > 20)  # noqa: SLF001
        h.window.console.set_filter("traffic")
        h.pump(0.15)
        traffic_only = h.window.console.visible_text()
        check("traffic filter narrows the feed",
              "DELIVER" in traffic_only or "RX:" in traffic_only)
        h.window.console.set_filter("all")

        print("neighbours")
        h.window.read_neighbors(sink)
        got = h.wait_for(lambda: bool(model.nodes[sink].neighbors))
        check("neighbour table read", got)

        print("capture")
        h.window.capture.start(
            "smoke_session",
            list(model.nodes.keys()),
            {p: n.display_name for p, n in model.nodes.items()},
        )
        h.window._update_capture_ui()  # noqa: SLF001
        h.pump(1.2)
        folder = h.window.capture.folder
        files = sorted(p.name for p in folder.glob("*.txt")) if folder else []
        check("one log file per node", len(files) == 3, str(files))
        check("log files use the _log suffix", all(f.endswith("_log.txt") for f in files), str(files))
        expected_prefixes = set()
        for n in model.nodes.values():
            safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in n.display_name)
            expected_prefixes.add(safe)
        check("log filenames derive from display names",
              all(any(f.startswith(pfx) for pfx in expected_prefixes) for f in files),
              f"files={files}")
        if folder and files:
            body = (folder / files[0]).read_text(encoding="utf-8")
            check(
                "captured lines are clean",
                "\x1b" not in body and "uart:~$" not in body,
                repr(body[:120]),
            )
        check("session manifest written", (folder / "session.json").exists() if folder else False)
        check("capture lines recorded", h.window.capture.line_count > 5)
        snap_path = h.window.capture.export_snapshot(model.to_dict(), "snapshot")
        check("snapshot exported", bool(snap_path and snap_path.exists()))
        h.window.toggle_capture()
        check("capture stopped", not h.window.capture.active)

        print("capture toggle with reset prompt")
        orig_prompt = h.mw.prompt_capture_session
        h.mw.prompt_capture_session = lambda *a, **k: ("smoke_reset_run", True)
        model.nodes[source].tx_count = 88
        h.window.toggle_capture()
        check("toggle_capture started and reset metrics", h.window.capture.active and model.nodes[source].tx_count == 0)
        h.window.toggle_capture()
        check("toggle_capture stopped second session", not h.window.capture.active)
        h.mw.prompt_capture_session = orig_prompt

        print("stop")
        h.window.stop_all()
        stopped = h.wait_for(lambda: not any(n.running for n in model.nodes.values()), timeout=10)
        check("all nodes stopped", stopped)
        idle = h.wait_for(lambda: not model.links and model.path_class == "none", timeout=8)
        check("stale links and path cleared", idle,
              f"links={len(model.links)} path={model.path_class}")

        print("unsaved changes guard")
        h.window.select_node(source)
        h.pump(0.25)
        h.window.inspector.spins["interval"].setValue(700)
        check("guard sees the dirty form", h.window.inspector.is_dirty())
        asked: list[str] = []
        original_guard = h.mw.confirm_unsaved

        def _cancel(parent, label, rows, what="this node"):  # noqa: ANN001, ARG001
            asked.append(label)
            return "cancel"

        h.mw.confirm_unsaved = _cancel
        h.window.run_node(source)
        h.pump(0.5)
        check("run warns and stops on unapplied edits",
              bool(asked) and not model.nodes[source].running)
        h.mw.confirm_unsaved = lambda *a, **k: "apply"  # noqa: ARG005
        h.window.run_node(source)
        chained = h.wait_for(
            lambda: model.nodes[source].interval_ms == 700 and model.nodes[source].running,
            timeout=14,
        )
        check("apply-then-start writes the form and starts the run", chained,
              f"interval={model.nodes[source].interval_ms} running={model.nodes[source].running}")
        h.mw.confirm_unsaved = original_guard
        h.window.stop_all()
        h.wait_for(lambda: not any(n.running for n in model.nodes.values()), timeout=10)

        print("unsaved guard — start anyway")
        h.window.select_node(source)
        h.pump(0.25)
        h.window.inspector.spins["power"].setValue(5)
        check("form dirty for start-anyway test", h.window.inspector.is_dirty())
        h.mw.confirm_unsaved = lambda *a, **k: "start"  # noqa: ARG005
        h.window.run_node(source)
        started_anyway = h.wait_for(lambda: model.nodes[source].running, timeout=10)
        check("start-anyway runs without applying",
              started_anyway and model.nodes[source].power == 9,
              f"running={model.nodes[source].running} power={model.nodes[source].power}")
        h.mw.confirm_unsaved = original_guard
        h.window.stop_all()
        h.wait_for(lambda: not any(n.running for n in model.nodes.values()), timeout=10)
        h.window.inspector._revert()  # noqa: SLF001

        print("flash profile")
        h.window.select_node(sink)
        h.pump(0.2)
        h.window.inspector.tabs.setCurrentIndex(1)
        h.pump(0.3)
        h.shot("05_settings")
        h.window.inspector.tabs.setCurrentIndex(2)
        h.pump(0.3)
        h.window.inspector.chk_autostart.click()
        h.pump(0.6)
        check("autostart change is staged, not sent",
              h.window.inspector.pending_autostart(sink) is True
              and not model.nodes[sink].autostart)
        check("pending autostart is announced in the panel",
              h.window.inspector.autostart_hint.isVisible())
        h.shot("06_flash")
        original_confirm = h.mw.confirm
        h.mw.confirm = lambda *a, **k: True  # noqa: ARG005
        h.window.save_profile(sink)
        h.mw.confirm = original_confirm
        stored = h.wait_for(
            lambda: model.nodes[sink].persist is True and model.nodes[sink].autostart is True
        )
        check("save to flash writes profile and staged autostart", stored,
              f"persist={model.nodes[sink].persist} autostart={model.nodes[sink].autostart}")
        cleared_pending = h.wait_for(
            lambda: h.window.inspector.pending_autostart(sink) is None
        )
        check("pending flag cleared after save", cleared_pending)
        h.pump(0.3)
        h.window._block(  # noqa: SLF001
            h.window.engine.factory_reset(sink), "Clearing profile"
        )
        cleared = h.wait_for(
            lambda: model.nodes[sink].persist is False
            and model.nodes[sink].autostart is False
        )
        check("factory reset clears profile and autostart", cleared)
        h.window.inspector.tabs.setCurrentIndex(0)

        print("dark theme")
        h.window.toggle_theme(True)
        h.pump(0.4)
        from ui import theme

        check("dark palette active", theme.palette().name == "dark")
        h.window.select_node(source)
        h.pump(0.3)
        h.shot("03_dark")
        h.window.toggle_theme(False)
        h.pump(0.2)

        print("link loss handling")
        node = model.nodes[source]
        h.window.hub.close_port(source)
        model.mark_disconnected(source, "closed by user")
        h.pump(0.3)
        check("offline node marked", not node.online)
        check("offline node keeps its name", node.display_name == node.label)
        h.window.inspector.show_node(node)
        h.pump(0.1)
        check("run disabled while offline", not h.window.inspector.btn_run.isEnabled())
        check("port button offers reopen", h.window.inspector.btn_port.text() == "Open link")
        h.shot("04_offline")

        print("auto-reconnect handling")
        from core.model import ConnState
        h.window.start_reconnect(source, "unexpected reset")
        check("node in reconnecting state", node.conn == ConnState.RECONNECTING)
        h.window.inspector.show_node(node)
        check("port button offers stop reconnect", h.window.inspector.btn_port.text() == "Stop reconnect")
        h.window.stop_reconnect(source, notify=False)
        check("node reverted to offline", node.conn == ConnState.DISCONNECTED)
        check("port button restored to open link", h.window.inspector.btn_port.text() == "Open link")

        print("layout persistence")
        h.window._on_node_moved(sink, 640.0, 220.0)  # noqa: SLF001
        saved = h.window.store.node_layout(sink)
        check("node position persisted", saved.get("x") == 640.0 and saved.get("y") == 220.0)
    finally:
        h.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Visualizer smoke tests")
    parser.add_argument("--shots", type=Path, help="Directory for UI screenshots")
    parser.add_argument("--show", action="store_true", help="Run with a visible window")
    args = parser.parse_args(argv)

    start = time.monotonic()
    test_parsing()
    test_model_reset_and_events()
    test_relay_paths()
    test_capture_files()
    test_source_rx_and_flash_lifecycle()
    test_app(args.shots, args.show)
    took = time.monotonic() - start

    print()
    if FAILURES:
        print(f"{len(FAILURES)} of {CHECKS} checks failed in {took:.1f}s:")
        for name in FAILURES:
            print(f"  - {name}")
        return 1
    print(f"all {CHECKS} checks passed in {took:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
