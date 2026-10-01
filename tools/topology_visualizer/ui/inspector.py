#!/usr/bin/env python3
"""Node inspector: live telemetry, radio parameters and flash profile."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QPushButton,
)

from core.model import ConnState, NodeState, link_quality
from ui import icons, theme
from ui.widgets import (
    Badge,
    CheckBox,
    HLine,
    KeyValueGrid,
    NoWheelComboBox,
    NoWheelSpinBox,
    SectionLabel,
    field_row,
)

ROLES = ("source", "relay", "sink")
ROLE_HINT = {
    "source": "Sensor — generates data towards the destination id",
    "relay": "Router — forwards traffic it is not addressed to",
    "sink": "Gateway — final destination, reports delivery",
}


class Sparkline(QWidget):
    """Recent RSSI trend for the selected node."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._values: list[float] = []
        self.setFixedHeight(46)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_values(self, values: list[float]) -> None:
        if values == self._values:
            return
        self._values = values
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802, ANN001
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(theme.color("border"), 1))
        p.setBrush(theme.color("surface_alt"))
        p.drawRoundedRect(rect, 8, 8)
        if len(self._values) < 2:
            p.setPen(theme.color("text_faint"))
            p.setFont(theme.ui_font(8))
            p.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), "waiting for RSSI samples")
            return
        lo, hi = -110.0, -40.0
        inner = rect.adjusted(8, 7, -8, -7)
        points = []
        n = len(self._values)
        for i, v in enumerate(self._values):
            t = i / (n - 1)
            clamped = max(lo, min(hi, v))
            y = inner.bottom() - (clamped - lo) / (hi - lo) * inner.height()
            points.append(QPointF(inner.left() + t * inner.width(), y))
        pen = QPen(theme.color("primary"), 1.8)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPolyline(points)
        last = self._values[-1]
        p.setBrush(theme.color("primary"))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(points[-1], 2.6, 2.6)
        p.setPen(theme.color("text_faint"))
        p.setFont(theme.ui_font(7))
        p.drawText(
            QRectF(inner.left(), rect.top() + 3, inner.width(), 12),
            int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
            f"{last:.0f} dBm  ·  {len(self._values)} samples",
        )


class NodeInspector(QFrame):
    apply_requested = Signal(str, dict)
    run_requested = Signal(str)
    stop_requested = Signal(str)
    refresh_requested = Signal(str)
    neighbors_requested = Signal(str)
    rename_requested = Signal(str)
    port_toggle_requested = Signal(str)
    remove_requested = Signal(str)
    autostart_staged = Signal(str, bool)
    save_profile_requested = Signal(str)
    load_profile_requested = Signal(str)
    factory_reset_requested = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("Rail")
        self.setFixedWidth(348)
        self._port: Optional[str] = None
        self._node: Optional[NodeState] = None
        self._baseline: dict[str, object] = {}
        self._loading = False
        # Autostart edits are held here until the operator presses Save to flash.
        self._pending_autostart: dict[str, bool] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 12, 12)
        root.setSpacing(10)

        self._build_header(root)
        root.addWidget(HLine())
        self._build_actions(root)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_overview(), "Overview")
        self.tabs.addTab(self._build_settings(), "Settings")
        self.tabs.addTab(self._build_flash(), "Flash")
        root.addWidget(self.tabs, 1)

        self.placeholder = QLabel(
            "Select a device to inspect its telemetry,\nchange radio parameters or manage its "
            "saved profile."
        )
        self.placeholder.setObjectName("Faint")
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder.setWordWrap(True)
        root.addWidget(self.placeholder, 1)
        self.clear()

    # ---------------------------------------------------------------- header
    def _build_header(self, root: QVBoxLayout) -> None:
        top = QHBoxLayout()
        top.setSpacing(6)
        self.title = QLabel("No device")
        self.title.setObjectName("H1")
        self.btn_rename = QPushButton()
        self.btn_rename.setIcon(icons.icon("gear", "text_faint", 15))
        self.btn_rename.setToolTip("Rename this node (F2)")
        self.btn_rename.setProperty("variant", "tool")
        self.btn_rename.setFixedSize(26, 24)
        self.btn_rename.clicked.connect(lambda: self._emit(self.rename_requested))
        self.state_badge = Badge("—")
        top.addWidget(self.title, 1)
        top.addWidget(self.btn_rename)
        top.addWidget(self.state_badge)
        root.addLayout(top)

        meta = QHBoxLayout()
        meta.setSpacing(8)
        self.transport = QLabel("—")
        self.transport.setObjectName("Mono")
        self.role_badge = Badge("—")
        meta.addWidget(self.transport, 1)
        meta.addWidget(self.role_badge)
        root.addLayout(meta)

        self.alert = QLabel("")
        self.alert.setWordWrap(True)
        self.alert.setVisible(False)
        root.addWidget(self.alert)

    def _build_actions(self, root: QVBoxLayout) -> None:
        row = QHBoxLayout()
        row.setSpacing(6)
        self.btn_run = QPushButton("Run")
        self.btn_run.setIcon(icons.icon("play", "on_primary", 15))
        self.btn_run.setProperty("variant", "primary")
        self.btn_run.clicked.connect(lambda: self._emit(self.run_requested))
        self.btn_stop = QPushButton("Stop")
        self.btn_stop.setIcon(icons.icon("stop", "danger", 15))
        self.btn_stop.setProperty("variant", "danger")
        self.btn_stop.clicked.connect(lambda: self._emit(self.stop_requested))
        self.btn_refresh = QPushButton()
        self.btn_refresh.setIcon(icons.icon("refresh", "text_muted", 16))
        self.btn_refresh.setToolTip("Read status from the board (F5)")
        self.btn_refresh.setFixedWidth(38)
        self.btn_refresh.clicked.connect(lambda: self._emit(self.refresh_requested))
        row.addWidget(self.btn_run, 1)
        row.addWidget(self.btn_stop, 1)
        row.addWidget(self.btn_refresh)
        root.addLayout(row)

        row2 = QHBoxLayout()
        row2.setSpacing(6)
        self.btn_port = QPushButton("Close link")
        self.btn_port.setIcon(icons.icon("power", "text_muted", 15))
        self.btn_port.clicked.connect(lambda: self._emit(self.port_toggle_requested))
        self.btn_remove = QPushButton("Remove")
        self.btn_remove.setIcon(icons.icon("trash", "danger", 15))
        self.btn_remove.setProperty("variant", "danger")
        self.btn_remove.clicked.connect(lambda: self._emit(self.remove_requested))
        row2.addWidget(self.btn_port, 1)
        row2.addWidget(self.btn_remove, 1)
        root.addLayout(row2)

    # -------------------------------------------------------------- overview
    def _build_overview(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 8, 0, 0)
        outer.setSpacing(0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        holder = QWidget()
        lay = QVBoxLayout(holder)
        lay.setContentsMargins(0, 0, 6, 0)
        lay.setSpacing(12)

        lay.addWidget(SectionLabel("Radio link"))
        self.grid_link = KeyValueGrid()
        for key, label in (
            ("device_id", "Device id"),
            ("dest", "Destination id"),
            ("hops", "Hop count"),
            ("rssi", "Last RSSI"),
            ("quality", "Link quality"),
            ("carrier", "Carrier / network"),
            ("dedup", "Relay dedup"),
            ("route", "Last route change"),
            ("seen", "Last line"),
        ):
            self.grid_link.add(key, label)
        lay.addWidget(self.grid_link)

        self.spark = Sparkline()
        lay.addWidget(self.spark)

        lay.addWidget(SectionLabel("Counters"))
        self.grid_counters = KeyValueGrid()
        for key, label in (
            ("data_sent", "Data sent"),
            ("hello_sent", "Hello sent"),
            ("fwd", "Forwarded"),
            ("rx_ok", "Received ok"),
            ("rx_fail", "Receive errors"),
            ("deliver", "Delivered"),
            ("loss", "Packet loss"),
            ("drops", "Dup / TTL / queue"),
            ("q_peak", "Queue peak"),
        ):
            self.grid_counters.add(key, label)
        lay.addWidget(self.grid_counters)

        head = QHBoxLayout()
        head.addWidget(SectionLabel("Neighbours"))
        head.addStretch(1)
        self.btn_neigh = QPushButton("Read")
        self.btn_neigh.setProperty("variant", "tool")
        self.btn_neigh.setFixedHeight(24)
        self.btn_neigh.clicked.connect(lambda: self._emit(self.neighbors_requested))
        head.addWidget(self.btn_neigh)
        lay.addLayout(head)
        self.neigh_label = QLabel("—")
        self.neigh_label.setObjectName("Muted")
        self.neigh_label.setWordWrap(True)
        lay.addWidget(self.neigh_label)

        lay.addStretch(1)
        scroll.setWidget(holder)
        outer.addWidget(scroll)
        return page

    # -------------------------------------------------------------- settings
    def _build_settings(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 8, 0, 0)
        outer.setSpacing(10)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        holder = QWidget()
        lay = QVBoxLayout(holder)
        lay.setContentsMargins(0, 0, 6, 0)
        lay.setSpacing(12)

        self.cmb_role = NoWheelComboBox()
        for role in ROLES:
            self.cmb_role.addItem(role)
        self.cmb_role.currentTextChanged.connect(self._on_role_changed)
        lay.addWidget(field_row("Role", self.cmb_role))
        self.role_hint = QLabel("")
        self.role_hint.setObjectName("Faint")
        self.role_hint.setWordWrap(True)
        lay.addWidget(self.role_hint)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        self.spins: dict[str, NoWheelSpinBox] = {}
        specs = (
            ("dest", "Destination id", 0, 65535, ""),
            ("max_hops", "Max hops", 1, 16, ""),
            ("interval", "TX interval", 10, 600000, " ms"),
            ("hello", "Hello interval", 0, 600000, " ms"),
            ("count", "Packet count", 0, 1000000, ""),
            ("power", "TX power", 0, 13, ""),
            ("mcs", "MCS", 0, 7, ""),
            ("size", "Payload", 8, 128, " B"),
        )
        for index, (key, label, lo, hi, suffix) in enumerate(specs):
            spin = NoWheelSpinBox()
            spin.setRange(lo, hi)
            if suffix:
                spin.setSuffix(suffix)
            spin.setMinimumWidth(120)
            spin.valueChanged.connect(self._on_form_changed)
            self.spins[key] = spin
            grid.addWidget(field_row(label, spin), index // 2, index % 2)
        lay.addLayout(grid)

        self.chk_dedup = CheckBox("Relay duplicate packet filter (dedup)")
        self.chk_dedup.setToolTip(
            "Filter duplicate sequence numbers at relay. Turn off for reboot experiments where source sequence resets."
        )
        self.chk_dedup.clicked.connect(self._on_form_changed)
        lay.addWidget(self.chk_dedup)

        self.chk_source_rx = CheckBox("Source 2s RX listen window (source_rx)")
        self.chk_source_rx.setToolTip(
            "When enabled, source listens for 2s after each transmission (default). "
            "Turn off to allow high-rate stress bursts (sub-second intervals)."
        )
        self.chk_source_rx.clicked.connect(self._on_form_changed)
        lay.addWidget(self.chk_source_rx)

        note = QLabel(
            "Values are written with <code>exp role</code> / <code>exp sett</code> and then "
            "verified by reading <code>exp status</code> back. Use the Flash tab to keep them "
            "across a reset."
        )
        note.setObjectName("Faint")
        note.setWordWrap(True)
        lay.addWidget(note)
        lay.addStretch(1)
        scroll.setWidget(holder)
        outer.addWidget(scroll, 1)

        self.dirty_label = QLabel("")
        self.dirty_label.setObjectName("Faint")
        outer.addWidget(self.dirty_label)

        buttons = QHBoxLayout()
        buttons.setSpacing(6)
        self.btn_revert = QPushButton("Revert")
        self.btn_revert.clicked.connect(self._revert)
        self.btn_apply = QPushButton("Apply settings")
        self.btn_apply.setProperty("variant", "primary")
        self.btn_apply.setIcon(icons.icon("check", "on_primary", 15))
        self.btn_apply.clicked.connect(self._apply)
        buttons.addWidget(self.btn_revert)
        buttons.addWidget(self.btn_apply, 1)
        outer.addLayout(buttons)
        return page

    # ----------------------------------------------------------------- flash
    def _build_flash(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 8, 0, 0)
        lay.setSpacing(12)

        lay.addWidget(SectionLabel("Boot behaviour"))
        self.grid_flash = KeyValueGrid()
        self.grid_flash.add("persist", "Saved profile in flash")
        self.grid_flash.add("autostart", "Autostart after reset")
        lay.addWidget(self.grid_flash)

        self.chk_autostart = CheckBox("Start the run automatically after reset")
        self.chk_autostart.clicked.connect(self._on_autostart_clicked)
        lay.addWidget(self.chk_autostart)

        self.autostart_hint = QLabel("")
        self.autostart_hint.setWordWrap(True)
        self.autostart_hint.setVisible(False)
        lay.addWidget(self.autostart_hint)

        note = QLabel(
            "Autostart lives in the saved profile. Ticking the box changes nothing on the "
            "board until you press <b>Save to flash</b> — that is what Week 4 healing tests "
            "rely on after a power cut."
        )
        note.setObjectName("Faint")
        note.setWordWrap(True)
        lay.addWidget(note)

        lay.addWidget(HLine())
        lay.addWidget(SectionLabel("Profile"))
        self.btn_save = QPushButton("Save to flash")
        self.btn_save.setIcon(icons.icon("save", "text_muted", 16))
        self.btn_save.setToolTip("exp save — store role, RF parameters and autostart in NVS")
        self.btn_save.clicked.connect(lambda: self._emit(self.save_profile_requested))
        self.btn_load = QPushButton("Load from flash")
        self.btn_load.setIcon(icons.icon("load", "text_muted", 16))
        self.btn_load.setToolTip("exp load — restore the saved profile into RAM")
        self.btn_load.clicked.connect(lambda: self._emit(self.load_profile_requested))
        self.btn_factory = QPushButton("Clear saved profile")
        self.btn_factory.setIcon(icons.icon("factory", "danger", 16))
        self.btn_factory.setProperty("variant", "danger")
        self.btn_factory.setToolTip("exp factory — erase NVS profile and restore build defaults")
        self.btn_factory.clicked.connect(lambda: self._emit(self.factory_reset_requested))
        for btn in (self.btn_save, self.btn_load, self.btn_factory):
            btn.setMinimumHeight(32)
            lay.addWidget(btn)

        lay.addStretch(1)
        return page

    # ------------------------------------------------------------------ data
    def clear(self) -> None:
        self._port = None
        self._node = None
        self.title.setText("No device selected")
        self.transport.setText("—")
        self.state_badge.set_value("—", theme.palette().text_faint)
        self.role_badge.set_value("—", theme.palette().text_faint)
        self.tabs.setVisible(False)
        self.alert.setVisible(False)
        self.placeholder.setVisible(True)
        for btn in (
            self.btn_run,
            self.btn_stop,
            self.btn_refresh,
            self.btn_port,
            self.btn_remove,
            self.btn_rename,
        ):
            btn.setEnabled(False)

    def current_port(self) -> Optional[str]:
        return self._port

    def show_node(self, node: NodeState, reload_form: bool = True) -> None:
        switching = node.port != self._port
        self._port = node.port
        self._node = node
        self.tabs.setVisible(True)
        self.placeholder.setVisible(False)
        if switching or (reload_form and not self.is_dirty()):
            self._load_form(node)
        self.update_live(node)

    def update_live(self, node: NodeState) -> None:
        """Refresh read-only values; never disturbs the settings form."""
        if node.port != self._port:
            return
        self._node = node
        p = theme.palette()
        if self.title.text() != node.label:
            self.title.setText(node.label)
        transport = node.port
        if self.transport.text() != transport:
            self.transport.setText(transport)

        if node.conn == ConnState.ERROR:
            self.state_badge.set_value("ERROR", p.danger)
        elif node.conn == ConnState.RECONNECTING:
            self.state_badge.set_value("RECONNECTING", p.warning)
        elif node.conn == ConnState.DISCONNECTED:
            self.state_badge.set_value("OFFLINE", p.text_faint)
        elif node.busy_label:
            self.state_badge.set_value("BUSY", p.primary)
        elif node.running:
            self.state_badge.set_value("RUNNING", p.success)
        else:
            self.state_badge.set_value("IDLE", p.info)
        self.role_badge.set_value(
            (node.role or "unassigned").upper(), theme.role_color(node.role).name()
        )

        message = ""
        tone = p.warning
        if node.conn == ConnState.ERROR:
            message = node.error_msg or "The link dropped unexpectedly."
            tone = p.danger
        elif node.conn == ConnState.RECONNECTING:
            reason = f" ({node.error_msg})" if node.error_msg else ""
            message = f"Link lost{reason}. Auto-reconnecting every 200 ms..."
            tone = p.warning
        elif node.conn == ConnState.DISCONNECTED:
            message = "Link closed. Reopen it to control this board."
            tone = p.text_muted
        elif not node.identified:
            message = "No reply to `exp status` yet — check the board and the bridge."
        self.alert.setVisible(bool(message))
        if message:
            self.alert.setText(message)
            self.alert.setStyleSheet(f"color:{tone}; font-size:12px;")

        rssi = node.live_rssi()
        self.grid_link.set("device_id", "—" if node.device_id is None else str(node.device_id))
        self.grid_link.set("dest", "—" if not node.dest_id else str(node.dest_id))
        self.grid_link.set("hops", "—" if node.hop_count is None else str(node.hop_count))
        self.grid_link.set(
            "rssi",
            "—" if rssi is None else f"{rssi:.1f} dBm",
            "text" if rssi is None else self._rssi_token(rssi),
        )
        quality = link_quality(rssi)
        self.grid_link.set(
            "quality",
            "—" if rssi is None else quality,
            "text" if rssi is None else self._rssi_token(rssi),
        )
        carrier = "—"
        if node.carrier is not None:
            carrier = f"{node.carrier}"
            if node.net:
                carrier += f" / {node.net}"
        self.grid_link.set("carrier", carrier)
        self.grid_link.set(
            "dedup",
            "—" if node.dedup is None else ("on" if node.dedup else "off"),
            "success" if (node.dedup is not False) else "warning",
        )
        self.grid_link.set("route", node.last_route_change or "—")
        self.grid_link.set("seen", node.last_seen or "—")

        self.grid_counters.set("data_sent", str(node.data_sent))
        self.grid_counters.set("hello_sent", str(node.hello_sent))
        self.grid_counters.set("fwd", str(node.fwd_count))
        self.grid_counters.set("rx_ok", str(node.rx_ok))
        self.grid_counters.set(
            "rx_fail", str(node.rx_fail), "warning" if node.rx_fail else "text"
        )
        self.grid_counters.set("deliver", str(node.deliver_count))
        loss = node.packet_loss_pct
        self.grid_counters.set(
            "loss",
            "—" if loss is None else f"{loss:.1f} %",
            "text" if loss is None else ("success" if loss < 5 else "warning"),
        )
        self.grid_counters.set("drops", f"{node.fwd_dup} / {node.fwd_ttl} / {node.fwd_qfull}")
        self.grid_counters.set(
            "q_peak", "—" if node.q_peak is None else f"{node.q_peak} / 8"
        )
        self.spark.set_values(list(node.rssi_history))

        if node.neighbors:
            self.neigh_label.setText(
                "\n".join(
                    f"id {n.id}   {('%.1f dBm' % n.rssi) if n.rssi is not None else '— dBm'}"
                    f"   hello {n.hello or 0}   data {n.data or 0}"
                    for n in node.neighbors
                )
            )
        else:
            self.neigh_label.setText("No neighbour table read yet.")

        self.grid_flash.set(
            "persist",
            "—" if node.persist is None else ("present" if node.persist else "none"),
            "success" if node.persist else "text_muted",
        )
        self.grid_flash.set(
            "autostart",
            "—" if node.autostart is None else ("enabled" if node.autostart else "disabled"),
            "success" if node.autostart else "text_muted",
        )
        pending = self._pending_autostart.get(node.port)
        if pending is not None and pending == bool(node.autostart):
            # The board caught up with the staged value; nothing left to write.
            self._pending_autostart.pop(node.port, None)
            pending = None
        wanted = bool(node.autostart) if pending is None else pending
        if self.chk_autostart.isChecked() != wanted:
            self.chk_autostart.blockSignals(True)
            self.chk_autostart.setChecked(wanted)
            self.chk_autostart.blockSignals(False)
        self.autostart_hint.setVisible(pending is not None)
        if pending is not None:
            self.autostart_hint.setText(
                f"Pending: autostart will be turned <b>{'on' if pending else 'off'}</b> when you "
                f"press Save to flash. The board still has it "
                f"{'on' if node.autostart else 'off'}."
            )
            self.autostart_hint.setStyleSheet(
                f"color:{theme.palette().warning}; font-size:12px;"
            )

        self._apply_enabled_state(node)

    def _rssi_token(self, rssi: float) -> str:
        if rssi >= -75:
            return "success"
        if rssi >= -90:
            return "warning"
        return "danger"

    def _apply_enabled_state(self, node: NodeState) -> None:
        online = node.online
        reconnecting = node.conn == ConnState.RECONNECTING
        busy = bool(node.busy_label) and not reconnecting
        ready = online and not busy
        self.btn_rename.setEnabled(True)
        self.btn_remove.setEnabled(not busy)
        self.btn_run.setEnabled(ready and not node.running)
        self.btn_stop.setEnabled(ready and node.running)
        self.btn_refresh.setEnabled(ready)
        self.btn_neigh.setEnabled(ready)
        self.btn_port.setEnabled(not busy)
        if reconnecting:
            self.btn_port.setText("Stop reconnect")
            self.btn_port.setIcon(icons.icon("stop", "warning", 15))
            self.btn_port.setToolTip("Stop automatic reconnect and keep node offline")
            self.btn_port.setProperty("variant", "warning")
        else:
            self.btn_port.setProperty("variant", "")
            self.btn_port.setText("Close link" if online else "Open link")
            self.btn_port.setIcon(icons.icon("power" if online else "plug", "text_muted", 15))
            self.btn_port.setToolTip("")
        self.btn_port.style().unpolish(self.btn_port)
        self.btn_port.style().polish(self.btn_port)
        dirty = self.is_dirty()
        self.btn_apply.setEnabled(ready and dirty)
        self.btn_revert.setEnabled(dirty)
        for widget in list(self.spins.values()) + [self.cmb_role, self.chk_dedup]:
            widget.setEnabled(ready)
        is_source = self.cmb_role.currentText() == "source"
        self.chk_source_rx.setEnabled(ready and is_source)
        if not is_source:
            if not self.chk_source_rx.isChecked():
                self.chk_source_rx.blockSignals(True)
                self.chk_source_rx.setChecked(True)
                self.chk_source_rx.blockSignals(False)
            self.chk_source_rx.setToolTip(
                "Frozen ON for relay and sink (relays and sinks must always listen for network traffic)."
            )
        else:
            self.chk_source_rx.setToolTip(
                "When enabled, source listens for 2s after each transmission (default). "
                "Turn off to allow high-rate stress bursts (sub-second intervals)."
            )
        self.chk_autostart.setEnabled(ready)
        self.btn_save.setEnabled(ready)
        pending = self._pending_autostart.get(node.port)
        variant = "primary" if pending is not None else ""
        if self.btn_save.property("variant") != variant:
            self.btn_save.setProperty("variant", variant)
            self.btn_save.setIcon(
                icons.icon("save", "on_primary" if variant else "text_muted", 16)
            )
            self.btn_save.style().unpolish(self.btn_save)
            self.btn_save.style().polish(self.btn_save)
        self.btn_load.setEnabled(ready and not node.running)
        self.btn_factory.setEnabled(ready and not node.running)
        if dirty:
            self.dirty_label.setText("Unsaved changes — Apply writes them to the board.")
            self.dirty_label.setStyleSheet(f"color:{theme.palette().warning};")
        else:
            self.dirty_label.setText("Form matches the board.")
            self.dirty_label.setStyleSheet(f"color:{theme.palette().text_faint};")

    # ------------------------------------------------------------------ form
    def _load_form(self, node: NodeState) -> None:
        self._loading = True
        if node.role in ROLES:
            self.cmb_role.setCurrentText(node.role)
        self.role_hint.setText(ROLE_HINT.get(self.cmb_role.currentText(), ""))
        values = {
            "dest": node.dest_id,
            "max_hops": node.max_hops,
            "interval": node.interval_ms,
            "hello": node.hello_ms,
            "count": node.count,
            "power": node.power,
            "mcs": node.mcs,
            "size": node.size,
        }
        for key, spin in self.spins.items():
            value = values.get(key)
            if value is not None:
                spin.setValue(int(value))
        dedup_val = True if node.dedup is None else bool(node.dedup)
        self.chk_dedup.blockSignals(True)
        self.chk_dedup.setChecked(dedup_val)
        self.chk_dedup.blockSignals(False)
        if node.role == "source":
            source_rx_val = True if node.source_rx is None else bool(node.source_rx)
        else:
            source_rx_val = True
        self.chk_source_rx.blockSignals(True)
        self.chk_source_rx.setChecked(source_rx_val)
        self.chk_source_rx.blockSignals(False)
        self._baseline = self._collect()
        self._loading = False
        self.dirty_label.setText("Form matches the board.")

    def _on_role_changed(self, role: str) -> None:
        self.role_hint.setText(ROLE_HINT.get(role, ""))
        if not self._loading:
            # Auto-enable (check) source_rx to True whenever the role changes
            self.chk_source_rx.blockSignals(True)
            self.chk_source_rx.setChecked(True)
            self.chk_source_rx.blockSignals(False)
        self._on_form_changed()

    def _collect(self) -> dict[str, object]:
        data: dict[str, object] = {
            "role": self.cmb_role.currentText(),
            "dedup": self.chk_dedup.isChecked(),
            "source_rx": self.chk_source_rx.isChecked(),
        }
        for key, spin in self.spins.items():
            data[key] = int(spin.value())
        return data

    def is_dirty(self) -> bool:
        if not self._baseline:
            return False
        return self._collect() != self._baseline

    def _on_form_changed(self, *_args) -> None:
        if self._loading or self._node is None:
            return
        self._apply_enabled_state(self._node)

    def _revert(self) -> None:
        if self._node is None:
            return
        self._load_form(self._node)
        self._apply_enabled_state(self._node)

    def diff_rows(self) -> list[tuple[str, str, str]]:
        """(parameter, current, new) for everything the operator changed."""
        current = self._collect()
        rows: list[tuple[str, str, str]] = []
        labels = {
            "role": "Role",
            "dest": "Destination id",
            "max_hops": "Max hops",
            "interval": "TX interval (ms)",
            "hello": "Hello interval (ms)",
            "count": "Packet count",
            "power": "TX power",
            "mcs": "MCS",
            "size": "Payload (B)",
            "dedup": "Relay dedup",
            "source_rx": "Source 2s RX window",
        }
        for key, label in labels.items():
            old = self._baseline.get(key)
            new = current.get(key)
            if old != new:
                def _fmt(val: object) -> str:
                    if isinstance(val, bool):
                        return "on" if val else "off"
                    return "—" if val is None else str(val)
                rows.append((label, _fmt(old), _fmt(new)))
        return rows

    def changed_settings(self) -> dict:
        """Only the fields that differ, so we send the shortest command set."""
        current = self._collect()
        return {k: v for k, v in current.items() if self._baseline.get(k) != v}

    def mark_applied(self) -> None:
        self._baseline = self._collect()
        if self._node is not None:
            self._apply_enabled_state(self._node)

    def _apply(self) -> None:
        if self._port:
            self.apply_requested.emit(self._port, self.changed_settings())

    def _on_autostart_clicked(self, checked: bool) -> None:
        """Stage the change only; flash is untouched until Save to flash."""
        if not self._port or self._node is None:
            return
        if checked == bool(self._node.autostart):
            self._pending_autostart.pop(self._port, None)
        else:
            self._pending_autostart[self._port] = checked
        self.update_live(self._node)
        self.autostart_staged.emit(self._port, checked)

    def pending_autostart(self, port: str) -> Optional[bool]:
        return self._pending_autostart.get(port)

    def clear_pending_autostart(self, port: str) -> None:
        self._pending_autostart.pop(port, None)
        if self._node is not None and self._node.port == port:
            self.update_live(self._node)

    def _emit(self, signal: Signal) -> None:
        if self._port:
            signal.emit(self._port)
