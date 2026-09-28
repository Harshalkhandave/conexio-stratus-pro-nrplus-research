#!/usr/bin/env python3
"""Application shell: header, KPI strip, canvas, inspector, console."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QFont, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from core import APP_NAME, APP_VERSION
from core.commands import CommandEngine
from core.logging_session import LoggingSession
from core.model import ConnState, SessionModel
from core.router import LineRouter
from core.store import Store
from core.transport import SerialHub, normalize_port, short_port_label
from ui import icons, theme
from ui.canvas import TopologyCanvas
from ui.console import EventConsole
from ui.devices import DeviceRail
from ui.dialogs import (
    ConnectDialog,
    confirm,
    confirm_changes,
    confirm_unsaved,
    prompt_capture_session,
    prompt_text,
    warn_disconnect,
)
from ui.inspector import NodeInspector
from ui.widgets import BusyOverlay, HLine, StatTile, ToastManager

DATA_ROOT = Path(__file__).resolve().parents[1] / "data"
UI_INTERVAL_MS = 50
SLOW_EVERY = 3
START_STAGGER_MS = 700

PATH_LABEL = {
    "none": ("No path", "text_faint"),
    "direct": ("Direct", "success"),
    "via_relay": ("Via relay", "role_relay"),
    "both": ("Direct + relay", "info"),
}


class MainWindow(QMainWindow):
    def __init__(self, initial_ports: Optional[list[str]] = None) -> None:
        super().__init__()
        self.store = Store()
        self.model = SessionModel()
        self.hub = SerialHub()
        self.router = LineRouter(self)
        self.engine = CommandEngine(self.hub, self.router, self)
        self.capture = LoggingSession(DATA_ROOT)

        self._selected: Optional[str] = None
        self._tick = 0
        self._blocking: dict[int, str] = {}  # request id -> description
        self._expected: dict[int, dict] = {}  # apply request id -> expected settings
        self._quiet: set[int] = set()
        self._announce: dict[int, bool] = {}
        self._req_port: dict[int, str] = {}
        self._after_ok: dict[int, Callable[[], None]] = {}  # run when a request succeeds

        self.setWindowTitle(f"{APP_NAME} {APP_VERSION}")
        self.resize(1440, 900)
        self.setMinimumSize(1180, 720)

        self._build_ui()
        self._build_shortcuts()
        self._connect_signals()

        geometry = self.store.window_geometry()
        if geometry:
            self.restoreGeometry(geometry)

        self._ui_timer = QTimer(self)
        self._ui_timer.setInterval(UI_INTERVAL_MS)
        self._ui_timer.timeout.connect(self._refresh_ui)
        self._ui_timer.start()

        self._reconnect_timer = QTimer(self)
        self._reconnect_timer.timeout.connect(self._on_reconnect_tick)
        self._reconnecting_ports: set[str] = set()
        self._reconnect_attempts: dict[str, int] = {}

        if initial_ports:
            QTimer.singleShot(0, lambda: self.connect_ports(initial_ports))
        self._refresh_ui()

    # ------------------------------------------------------------------- UI
    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_header())
        root.addWidget(self._build_kpi_strip())

        body = QSplitter(Qt.Orientation.Horizontal)
        body.setChildrenCollapsible(False)
        self.rail = DeviceRail()
        body.addWidget(self.rail)

        workspace = QWidget()
        ws = QVBoxLayout(workspace)
        ws.setContentsMargins(14, 12, 14, 12)
        ws.setSpacing(10)

        stack = QSplitter(Qt.Orientation.Vertical)
        stack.setChildrenCollapsible(False)

        canvas_panel = QFrame()
        canvas_panel.setObjectName("Panel")
        cp = QVBoxLayout(canvas_panel)
        cp.setContentsMargins(1, 1, 1, 1)
        cp.setSpacing(0)
        self.canvas = TopologyCanvas()
        cp.addWidget(self._build_canvas_bar())
        cp.addWidget(HLine())
        cp.addWidget(self.canvas, 1)
        stack.addWidget(canvas_panel)

        self.console = EventConsole()
        stack.addWidget(self.console)
        stack.setSizes([560, 220])
        ws.addWidget(stack, 1)
        body.addWidget(workspace)

        self.inspector = NodeInspector()
        body.addWidget(self.inspector)
        body.setStretchFactor(1, 1)
        root.addWidget(body, 1)

        self.overlay = BusyOverlay(central)
        self.overlay.setGeometry(central.rect())
        # Toasts live over the workspace so they never cover the rail or inspector.
        self.toasts = ToastManager(workspace)

        status = self.statusBar()
        self.status_link = QLabel("No boards connected")
        self.status_capture = QLabel("Capture off")
        self.status_hint = QLabel("Ctrl+N add board  ·  F5 refresh  ·  Ctrl+F fit")
        self.status_hint.setObjectName("Faint")
        status.addWidget(self.status_link)
        status.addWidget(QLabel("  "))
        status.addWidget(self.status_capture)
        status.addPermanentWidget(self.status_hint)

    def _build_header(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("TopBar")
        bar.setFixedHeight(56)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(16, 8, 14, 8)
        lay.setSpacing(10)

        mark = QLabel()
        mark.setPixmap(icons.pixmap("topology", theme.color("primary"), 26, 2.0))
        title = QLabel(APP_NAME)
        title.setFont(theme.ui_font(12, QFont.Weight.DemiBold))
        version = QLabel(APP_VERSION)
        version.setObjectName("Faint")
        subtitle = QLabel("DECT NR+ · three-node topology")
        subtitle.setObjectName("Faint")
        lay.addWidget(mark)
        lay.addWidget(title)
        lay.addWidget(version)
        lay.addSpacing(8)
        lay.addWidget(subtitle)
        lay.addStretch(1)

        self.btn_add = QPushButton("Add board")
        self.btn_add.setIcon(icons.icon("plus", "on_primary", 16))
        self.btn_add.setProperty("variant", "primary")
        self.btn_add.clicked.connect(self.add_board)

        self.btn_capture = QPushButton("Start capture")
        self.btn_capture.setIcon(icons.icon("record", "danger", 15))
        self.btn_capture.clicked.connect(self.toggle_capture)

        self.btn_snapshot = QPushButton("Snapshot")
        self.btn_snapshot.setIcon(icons.icon("camera", "text_muted", 16))
        self.btn_snapshot.setToolTip("Export the current topology and counters as JSON (Ctrl+E)")
        self.btn_snapshot.clicked.connect(self.export_snapshot)

        self.btn_menu = QPushButton()
        self.btn_menu.setIcon(icons.icon("gear", "text_muted", 18))
        self.btn_menu.setToolTip("View and preferences")
        self.btn_menu.setFixedWidth(38)
        self.btn_menu.setMenu(self._build_menu())

        for btn in (self.btn_add, self.btn_capture, self.btn_snapshot, self.btn_menu):
            btn.setMinimumHeight(32)
            lay.addWidget(btn)
        return bar

    def _build_kpi_strip(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("TopBar")
        bar.setFixedHeight(62)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(18, 8, 16, 8)
        lay.setSpacing(0)
        self.tiles: dict[str, StatTile] = {}
        specs = (
            ("devices", "Boards online"),
            ("running", "Running"),
            ("path", "Data path"),
            ("hops", "Hops"),
            ("pdr", "Delivery ratio"),
            ("rssi", "Mean RSSI"),
            ("estab", "Route setup"),
            ("routes", "Route changes"),
        )
        for index, (key, label) in enumerate(specs):
            tile = StatTile(label)
            self.tiles[key] = tile
            lay.addWidget(tile)
            if index < len(specs) - 1:
                sep = QFrame()
                sep.setFixedWidth(1)
                sep.setStyleSheet(f"background:{theme.palette().border};")
                lay.addWidget(sep)
                lay.addSpacing(16)
                lay.addSpacing(0)
        lay.addStretch(1)
        return bar

    def _build_canvas_bar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(40)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(12, 6, 10, 6)
        lay.setSpacing(6)
        title = QLabel("Topology")
        title.setObjectName("H2")
        self.path_chip = QLabel("No path")
        self.path_chip.setObjectName("Faint")
        lay.addWidget(title)
        lay.addSpacing(6)
        lay.addWidget(self.path_chip)
        lay.addStretch(1)

        self.legend = QLabel()
        self.legend.setObjectName("Faint")
        lay.addWidget(self.legend)
        lay.addSpacing(10)

        for name, tip, slot in (
            ("topology", "Arrange nodes by role (Ctrl+Shift+A)", self.auto_layout),
            ("fit", "Fit all nodes in view (Ctrl+F)", self.canvas.fit),
        ):
            btn = QPushButton()
            btn.setIcon(icons.icon(name, "text_muted", 17))
            btn.setToolTip(tip)
            btn.setProperty("variant", "tool")
            btn.setFixedSize(32, 28)
            btn.clicked.connect(slot)
            lay.addWidget(btn)
        return bar

    def _build_menu(self) -> QMenu:
        menu = QMenu(self)
        self.act_theme = QAction("Dark theme", self, checkable=True)
        self.act_theme.setChecked(self.store.get("theme") == "dark")
        self.act_theme.triggered.connect(self.toggle_theme)
        menu.addAction(self.act_theme)
        menu.addSeparator()

        self.act_labels = QAction("Show RSSI on links", self, checkable=True)
        self.act_labels.setChecked(bool(self.store.get("show_rssi_labels")))
        self.act_labels.triggered.connect(self._sync_canvas_options)
        menu.addAction(self.act_labels)

        self.act_anim = QAction("Animate packets", self, checkable=True)
        self.act_anim.setChecked(bool(self.store.get("animate_packets")))
        self.act_anim.triggered.connect(self._sync_canvas_options)
        menu.addAction(self.act_anim)
        menu.addSeparator()

        self.act_auto_reconnect = QAction("Auto-reconnect offline nodes", self, checkable=True)
        self.act_auto_reconnect.setChecked(bool(self.store.get("auto_reconnect")))
        self.act_auto_reconnect.triggered.connect(self._toggle_auto_reconnect)
        menu.addAction(self.act_auto_reconnect)
        menu.addSeparator()

        self.act_confirm_apply = QAction("Confirm before applying settings", self, checkable=True)
        self.act_confirm_apply.setChecked(bool(self.store.get("confirm_apply")))
        self.act_confirm_apply.triggered.connect(
            lambda on: self.store.set("confirm_apply", bool(on))
        )
        menu.addAction(self.act_confirm_apply)

        self.act_confirm_run = QAction("Confirm before starting a run", self, checkable=True)
        self.act_confirm_run.setChecked(bool(self.store.get("confirm_run")))
        self.act_confirm_run.triggered.connect(lambda on: self.store.set("confirm_run", bool(on)))
        menu.addAction(self.act_confirm_run)
        menu.addSeparator()

        act_folder = QAction("Open capture folder", self)
        act_folder.triggered.connect(self._open_data_folder)
        menu.addAction(act_folder)

        act_about = QAction(f"About {APP_NAME}", self)
        act_about.triggered.connect(self._about)
        menu.addAction(act_about)
        return menu

    def _toggle_auto_reconnect(self, on: bool) -> None:
        self.store.set("auto_reconnect", bool(on))
        if not on:
            for port in list(self._reconnecting_ports):
                self.stop_reconnect(port, notify=False)

    def _build_shortcuts(self) -> None:
        def add(seq: str, slot) -> None:  # noqa: ANN001
            act = QAction(self)
            act.setShortcut(QKeySequence(seq))
            act.triggered.connect(slot)
            self.addAction(act)

        add("Ctrl+N", self.add_board)
        add("F5", lambda: self._selected and self.refresh_node(self._selected))
        add("F2", lambda: self._selected and self.rename_node(self._selected))
        add("Ctrl+F", self.canvas.fit)
        add("Ctrl+Shift+A", self.auto_layout)
        add("Ctrl+L", self.toggle_capture)
        add("Ctrl+E", self.export_snapshot)
        add("Ctrl+D", lambda: self.toggle_theme(not self.act_theme.isChecked()))
        add("Ctrl++", lambda: self.canvas.zoom_by(1.15))
        add("Ctrl+-", lambda: self.canvas.zoom_by(1 / 1.15))
        add("Ctrl+0", self.canvas.reset_zoom)
        add("Esc", self._clear_selection)

    def _connect_signals(self) -> None:
        self.hub.add_line_listener(self.router.feed)
        self.hub.line_received.connect(self._on_raw_line)
        self.hub.disconnected.connect(self._on_disconnected)
        self.hub.write_failed.connect(
            lambda port, why: self.toasts.show(f"{short_port_label(port)}: {why}", "error")
        )

        self.router.line_ready.connect(self.console.append)
        self.router.status_ready.connect(self._on_status)
        self.router.event_ready.connect(self._on_event)
        self.router.neighbors_ready.connect(self._on_neighbors)

        self.engine.started.connect(self._on_cmd_started)
        self.engine.progress.connect(self._on_cmd_progress)
        self.engine.finished.connect(self._on_cmd_finished)
        self.engine.sent.connect(lambda port, text: self.console.append(port, "", f">>> {text}", "cmd"))

        self.rail.selected.connect(self.select_node)
        self.rail.add_requested.connect(self.add_board)
        self.rail.start_all_requested.connect(self.start_network)
        self.rail.stop_all_requested.connect(self.stop_all)
        self.rail.refresh_all_requested.connect(self.refresh_all)

        self.canvas.node_selected.connect(self.select_node)
        self.canvas.node_moved.connect(self._on_node_moved)
        self.canvas.node_refresh.connect(self.refresh_node)
        self.canvas.node_run.connect(self.run_node)
        self.canvas.node_stop.connect(self.stop_node)
        self.canvas.node_renamed.connect(self.rename_node)
        self.canvas.selection_cleared.connect(self._clear_selection)

        self.inspector.refresh_requested.connect(self.refresh_node)
        self.inspector.apply_requested.connect(self.apply_settings)
        self.inspector.run_requested.connect(self.run_node)
        self.inspector.stop_requested.connect(self.stop_node)
        self.inspector.rename_requested.connect(self.rename_node)
        self.inspector.port_toggle_requested.connect(self.toggle_port)
        self.inspector.remove_requested.connect(self.remove_node)
        self.inspector.neighbors_requested.connect(self.read_neighbors)
        self.inspector.autostart_staged.connect(self.set_autostart)
        self.inspector.save_profile_requested.connect(self.save_profile)
        self.inspector.load_profile_requested.connect(self.load_profile)
        self.inspector.factory_reset_requested.connect(self.factory_reset)

        self.overlay.cancelled.connect(self._cancel_blocking)
        self._sync_canvas_options()

    # -------------------------------------------------------------- transport
    def connect_ports(self, ports: list[str]) -> None:
        opened: list[str] = []
        for raw in ports:
            port = normalize_port(raw)
            if not port:
                continue
            ok, message = self.hub.open_port(port)
            if not ok:
                self.toasts.show(f"{short_port_label(port)} could not be opened: {message}", "error")
                # Keep it visible as an offline node so it can be retried later.
                self.model.add_node(port, **self._layout_for(port))
                self.model.mark_disconnected(port, message)
                continue
            self.router.reset(port)
            self.model.add_node(port, **self._layout_for(port))
            self.capture.add_port(port, self.model.nodes[port].display_name)
            opened.append(port)
            self._quiet.add(self.engine.status(port))
        if opened:
            self.toasts.show(
                f"Connected {', '.join(short_port_label(p) for p in opened)}", "success"
            )
            self.store.set("last_ports", list(self.model.nodes.keys()))
            if self._selected is None:
                self.select_node(opened[0])
            QTimer.singleShot(350, self.canvas.fit)
        self._refresh_ui()

    def _layout_for(self, port: str) -> dict:
        saved = self.store.node_layout(port)
        if not saved:
            return {}
        out: dict = {}
        if saved.get("name"):
            out["name"] = saved["name"]
        if "x" in saved and "y" in saved:
            out["pos"] = (float(saved["x"]), float(saved["y"]))
        return out

    def add_board(self) -> None:
        dialog = ConnectDialog(self)
        if dialog.exec() == ConnectDialog.DialogCode.Accepted:
            self.connect_ports(dialog.selected_ports)

    def toggle_port(self, port: str) -> None:
        node = self.model.nodes.get(port)
        if node is None:
            return
        if port in self._reconnecting_ports or node.conn == ConnState.RECONNECTING:
            self.stop_reconnect(port)
            return
        if self.hub.is_open(port):
            if node.running and not confirm(
                self,
                "Close the link?",
                f"{node.label} is still running. Closing the link stops monitoring but the "
                "board keeps transmitting.",
                accept_text="Close link",
                destructive=True,
            ):
                return
            self.hub.close_port(port)
            self.model.mark_disconnected(port, "closed by user")
            self.toasts.show(f"{node.label}: link closed", "info")
        else:
            ok, message = self.hub.open_port(port)
            if not ok:
                if self.store.get("auto_reconnect", True):
                    self.start_reconnect(port, message)
                else:
                    self.toasts.show(f"{node.label}: {message}", "error")
                return
            self.router.reset(port)
            self.capture.add_port(port, node.display_name)
            node.conn = ConnState.CONNECTED
            node.error_msg = ""
            self.refresh_node(port)
            self.toasts.show(f"{node.label}: link open", "success")
        self._refresh_ui()

    def remove_node(self, port: str) -> None:
        node = self.model.nodes.get(port)
        if node is None:
            return
        if not confirm(
            self,
            "Remove this node?",
            f"{node.label} will be closed and removed from the session.",
            accept_text="Remove node",
            destructive=True,
            detail="Captured log files are kept on disk.",
        ):
            return
        if port in self._reconnecting_ports:
            self.stop_reconnect(port, notify=False)
        self.hub.close_port(port)
        self.router.reset(port)
        self.model.remove_node(port)
        if self._selected == port:
            self._clear_selection()
        self.store.set("last_ports", list(self.model.nodes.keys()))
        self._refresh_ui()

    def _on_disconnected(self, port: str, reason: str) -> None:
        if port not in self.model.nodes:
            return
        self.hub.close_port(port)

        auto_reconnect = bool(self.store.get("auto_reconnect", True))
        if auto_reconnect and reason != "closed by user":
            self.start_reconnect(port, reason)
            return

        self.model.mark_disconnected(port, reason)
        self._refresh_ui()
        if warn_disconnect(self, short_port_label(port), reason) == "remove":
            self.hub.close_port(port)
            self.model.remove_node(port)
            if self._selected == port:
                self._clear_selection()
        self._refresh_ui()

    def start_reconnect(self, port: str, reason: str = "") -> None:
        node = self.model.nodes.get(port)
        if node is None:
            return
        self._reconnecting_ports.add(port)
        self._reconnect_attempts[port] = 0
        self.model.mark_reconnecting(port, reason)
        interval = int(self.store.get("auto_reconnect_interval_ms", 200))
        if not self._reconnect_timer.isActive():
            self._reconnect_timer.start(interval)
        self.toasts.show(
            f"{node.label} disconnected ({reason or 'link lost'}). Auto-reconnecting...",
            kind="warning",
            action_label="Stop",
            on_action=lambda p=port: self.stop_reconnect(p),
        )
        self._refresh_ui(force=True)

    def stop_reconnect(self, port: str, notify: bool = True) -> None:
        self._reconnecting_ports.discard(port)
        self._reconnect_attempts.pop(port, None)
        if not self._reconnecting_ports:
            self._reconnect_timer.stop()
        node = self.model.nodes.get(port)
        if node:
            node.conn = ConnState.DISCONNECTED
            node.busy_label = ""
            node.error_msg = ""
            if notify:
                self.toasts.show(f"{node.label}: auto-reconnect stopped (offline)", "info")
        self._refresh_ui(force=True)

    def _on_reconnect_tick(self) -> None:
        for port in list(self._reconnecting_ports):
            node = self.model.nodes.get(port)
            if node is None:
                self._reconnecting_ports.discard(port)
                self._reconnect_attempts.pop(port, None)
                continue
            self._reconnect_attempts[port] = self._reconnect_attempts.get(port, 0) + 1
            ok, message = self.hub.open_port(port)
            if not ok:
                continue

            # Connection re-established!
            self._reconnecting_ports.discard(port)
            self._reconnect_attempts.pop(port, None)
            if not self._reconnecting_ports:
                self._reconnect_timer.stop()

            self.router.reset(port)
            self.engine.drain(port)
            self.capture.add_port(port, node.display_name)
            node.conn = ConnState.CONNECTED
            node.error_msg = ""
            node.busy_label = ""
            self.toasts.show(f"{node.label} reconnected! Reading status...", "success")
            self._quiet.add(self.engine.status(port))
            self._refresh_ui(force=True)

    # ------------------------------------------------------------- selection
    def select_node(self, port: str) -> None:
        if port not in self.model.nodes:
            return
        first = self._selected != port
        self._selected = port
        self.canvas.select(port)
        self.inspector.show_node(self.model.nodes[port])
        if first and self.model.nodes[port].online and not self.engine.busy(port):
            self._quiet.add(self.engine.status(port))

    def _clear_selection(self) -> None:
        self._selected = None
        self.canvas.select(None)
        self.inspector.clear()

    def _on_node_moved(self, port: str, x: float, y: float) -> None:
        node = self.model.nodes.get(port)
        if node is None:
            return
        node.x, node.y = x, y
        self.store.save_node_layout(port, node.display_name, x, y)

    def rename_node(self, port: str) -> None:
        node = self.model.nodes.get(port)
        if node is None:
            return
        name = prompt_text(
            self,
            "Rename node",
            "Display name",
            default=node.display_name,
            hint=f"Transport: {node.port}. Log files use this name.",
        )
        if not name:
            return
        node.display_name = name
        self.store.save_node_layout(port, name, node.x, node.y)
        self._refresh_ui(force=True)

    # -------------------------------------------------------------- commands
    def refresh_node(self, port: str) -> None:
        node = self.model.nodes.get(port)
        if node is None or not self.hub.is_open(port):
            self.toasts.show("The link is closed — open it before reading status.", "warning")
            return
        req = self.engine.status(port)
        self._block(req, f"Reading status from {node.label}")

    def refresh_all(self) -> None:
        targets = [p for p, n in self.model.nodes.items() if n.online]
        if not targets:
            return
        for port in targets:
            self._block(self.engine.status(port), "Reading status from all boards")

    def read_neighbors(self, port: str) -> None:
        node = self.model.nodes.get(port)
        if node is None or not node.online:
            return
        self._block(self.engine.neighbors(port), f"Reading neighbours of {node.label}")

    def apply_settings(
        self, port: str, changed: dict, then: Optional[Callable[[], None]] = None
    ) -> Optional[int]:
        node = self.model.nodes.get(port)
        if node is None or not node.online:
            return None
        if not changed:
            self.toasts.show("Nothing to apply — the form matches the board.", "info")
            return None
        rows = self.inspector.diff_rows()
        if self.store.get("confirm_apply") and rows:
            footer = "The run will be stopped first." if node.running else ""
            if not confirm_changes(self, f"Apply settings to {node.label}", rows, footer):
                return None
        req = self.engine.apply_settings(port, changed, stop_first=node.running)
        self._expected[req] = dict(changed)
        if then is not None:
            self._after_ok[req] = then
        self._block(req, f"Applying settings to {node.label}")
        self.capture.note(f"apply {node.label}: {changed}")
        return req

    def _guard_unsaved(self, ports: list[str], then: Callable[[], None]) -> bool:
        """Block a run while the Settings form still holds unapplied edits.

        Returns True when it is safe to continue now. When the operator asks to
        apply first, `then` runs once the board has verified the new values.
        """
        port = self.inspector.current_port()
        if port is None or port not in ports or not self.inspector.is_dirty():
            return True
        node = self.model.nodes.get(port)
        label = node.label if node else short_port_label(port)
        choice = confirm_unsaved(
            self,
            label,
            self.inspector.diff_rows(),
            what="the network" if len(ports) > 1 else "this node",
        )
        if choice == "start":
            return True
        if choice == "apply":
            self.apply_settings(port, self.inspector.changed_settings(), then=then)
        return False

    def run_node(self, port: str) -> None:
        node = self.model.nodes.get(port)
        if node is None or not node.online:
            return
        if not self._guard_unsaved([port], lambda: self.run_node(port)):
            return
        if node.role == "source" and not node.dest_id:
            self.toasts.show(
                "This source has no destination id. Set one in Settings before running.",
                "warning",
            )
            return
        if self.store.get("confirm_run"):
            count = node.count or 0
            detail_rows = [
                ("Role", node.role or "unassigned"),
                ("Destination id", str(node.dest_id or "—")),
                ("TX interval", f"{node.interval_ms or '—'} ms"),
                ("Packets", "continuous" if count == 0 else str(count)),
                ("Capture", "recording" if self.capture.active else "not recording"),
            ]
            body = "<br>".join(f"<b>{k}</b>: {v}" for k, v in detail_rows)
            if not confirm(
                self,
                f"Start run on {node.label}?",
                body,
                accept_text="Start run",
                detail=(
                    "Capture is off — start a capture first if this run must be logged."
                    if not self.capture.active
                    else ""
                ),
            ):
                return
        self.model.note_run_started()
        req = self.engine.start(port, node.count or None)
        self._block(req, f"Starting run on {node.label}")
        self.capture.note(f"start {node.label} role={node.role} count={node.count}")

    def stop_node(self, port: str) -> None:
        node = self.model.nodes.get(port)
        if node is None or not node.online:
            return
        self._block(self.engine.stop(port), f"Stopping {node.label}")
        self.capture.note(f"stop {node.label}")

    def start_network(self) -> None:
        """Bring the mesh up in the order sink → relay → source."""
        ports = [p for p in self.model.ordered_ports() if self.model.nodes[p].online]
        if not ports:
            return
        if not self._guard_unsaved(ports, self.start_network):
            return
        missing = [
            self.model.nodes[p].label for p in ports if not self.model.nodes[p].role
        ]
        if missing:
            self.toasts.show(
                f"Assign a role to {', '.join(missing)} before starting the network.", "warning"
            )
            return
        sources = [p for p in ports if self.model.nodes[p].role == "source"]
        bad = [self.model.nodes[p].label for p in sources if not self.model.nodes[p].dest_id]
        if bad:
            self.toasts.show(f"{', '.join(bad)} needs a destination id.", "warning")
            return
        order = ", ".join(
            f"{self.model.nodes[p].label} ({self.model.nodes[p].role})" for p in ports
        )
        if self.store.get("confirm_run") and not confirm(
            self,
            "Start the network?",
            f"Nodes are started in this order:<br><b>{order}</b>",
            accept_text="Start network",
            detail=(
                "Capture is off — start a capture first if this run must be logged."
                if not self.capture.active
                else "Capture is recording."
            ),
        ):
            return
        self.model.note_run_started()
        for index, port in enumerate(ports):
            node = self.model.nodes[port]
            QTimer.singleShot(
                index * START_STAGGER_MS,
                lambda p=port, n=node: self._block(
                    self.engine.start(p, n.count or None), f"Starting {n.label}"
                ),
            )
        self.capture.note(f"start network order={order}")

    def stop_all(self) -> None:
        for port, node in self.model.nodes.items():
            if node.online and node.running:
                self._block(self.engine.stop(port), "Stopping all nodes")
        self.capture.note("stop all")

    def set_autostart(self, port: str, on: bool) -> None:
        """Stage the autostart flag; nothing is sent until Save to flash."""
        node = self.model.nodes.get(port)
        if node is None:
            return
        if self.inspector.pending_autostart(port) is None:
            self.statusBar().showMessage("Autostart matches the board again.", 2500)
            return
        self.toasts.show(
            f"Autostart {'on' if on else 'off'} is staged — press “Save to flash” to write it "
            f"to {node.label}.",
            "info",
        )

    def save_profile(self, port: str) -> None:
        node = self.model.nodes.get(port)
        if node is None:
            return
        pending = self.inspector.pending_autostart(port)
        flash_warn = (
            "⚠️ HARDWARE WARNING: Flash writes physically consume NOR erase cycles. "
            "Only write to flash if you need these settings to persist across power resets."
        )
        if pending is not None:
            detail = (
                f"Autostart will also be turned {'on' if pending else 'off'} as part of this save.\n\n"
                + flash_warn
            )
        else:
            detail = flash_warn
        if not confirm(
            self,
            f"Save profile on {node.label}?",
            "Role, destination, RF parameters and the autostart flag are written to flash and "
            "restored on the next boot.",
            accept_text="Save to flash",
            detail=detail,
        ):
            return
        req = self.engine.save_profile(port, pending)
        if pending is not None:
            self._after_ok[req] = lambda p=port: self.inspector.clear_pending_autostart(p)
        self._block(req, f"Saving profile on {node.label}", announce=True)
        self.capture.note(f"save profile {node.label} autostart={pending}")

    def load_profile(self, port: str) -> None:
        node = self.model.nodes.get(port)
        if node is None:
            return
        self._block(
            self.engine.load_profile(port), f"Loading profile on {node.label}", announce=True
        )

    def factory_reset(self, port: str) -> None:
        node = self.model.nodes.get(port)
        if node is None:
            return
        if not confirm(
            self,
            f"Clear the saved profile on {node.label}?",
            "The flash profile is erased and RAM values return to the firmware defaults.",
            accept_text="Clear profile",
            destructive=True,
            detail="⚠️ HARDWARE WARNING: Erasing flash sectors consumes write endurance cycles. Only do this if necessary to restore default firmware configuration.",
        ):
            return
        self._block(
            self.engine.factory_reset(port), f"Clearing profile on {node.label}", announce=True
        )
        self.capture.note(f"factory reset {node.label}")

    # ---------------------------------------------------------- command flow
    def _block(self, req: int, description: str, announce: bool = False) -> None:
        self._blocking[req] = description
        if announce:
            self._announce[req] = True
        self.overlay.show_busy(description, "waiting for the board to acknowledge…")
        self.overlay.setGeometry(self.centralWidget().rect())
        self.overlay.raise_()

    def _cancel_blocking(self) -> None:
        self._blocking.clear()
        self.overlay.hide_busy()
        self.toasts.show("Still finishing in the background — the UI is unlocked.", "info")

    def _release(self, req: int) -> None:
        self._blocking.pop(req, None)
        if not self._blocking:
            self.overlay.hide_busy()
        else:
            self.overlay.show_busy(next(iter(self._blocking.values())), "")

    def _on_cmd_started(self, port: str, req: int, label: str) -> None:
        self._req_port[req] = port
        node = self.model.nodes.get(port)
        if node is not None:
            node.busy_label = label

    def _on_cmd_progress(self, port: str, req: int, index: int, total: int) -> None:
        if req in self._blocking and total > 1:
            self.overlay.update_detail(f"step {index + 1} of {total}")

    def _on_cmd_finished(self, port: str, req: int, ok: bool, detail: str) -> None:
        node = self.model.nodes.get(port)
        if node is not None and not self.engine.busy(port):
            node.busy_label = ""
        blocking = req in self._blocking
        description = self._blocking.get(req, "")
        self._release(req)
        expected = self._expected.pop(req, None)
        quiet = req in self._quiet
        self._quiet.discard(req)
        self._req_port.pop(req, None)
        after_ok = self._after_ok.pop(req, None)

        if not ok:
            if node is not None and "timeout" in detail:
                node.error_msg = "no reply from board"
            if quiet and not blocking:
                self.console.note(f"{short_port_label(port)}: {detail}")
                return
            label = node.label if node else short_port_label(port)
            self.toasts.show(f"{label}: {detail}", "error")
            return

        if expected is not None:
            matched, mismatches = self.model.settings_match(port, expected)
            if matched:
                self.inspector.mark_applied()
                self.toasts.show(f"{node.label if node else port}: settings verified", "success")
                if after_ok is not None:
                    # e.g. "Apply, then start" — continue once the board agrees.
                    QTimer.singleShot(0, after_ok)
            else:
                self.toasts.show(
                    f"{node.label if node else port}: settings not verified", "warning"
                )
                confirm(
                    self,
                    "Settings could not be verified",
                    "The board reported different values than requested:<br>"
                    + "<br>".join(mismatches),
                    accept_text="Close",
                    detail="Nothing else was changed. Try again, or check the board state.",
                )
            return

        # Successful routine commands are visible in the node state already; only
        # report the ones with a lasting effect so the corner stays quiet.
        if blocking and not quiet and self._announce.pop(req, False):
            self.toasts.show(f"{description} — done", "success")
        elif blocking and description:
            self.statusBar().showMessage(f"{description} — done", 2500)
        if after_ok is not None:
            QTimer.singleShot(0, after_ok)

    # ------------------------------------------------------------- telemetry
    def _on_raw_line(self, port: str, host_ts: str, raw: str) -> None:
        self.capture.write(port, host_ts, raw)

    def _on_status(self, port: str, snap) -> None:  # noqa: ANN001
        self.model.apply_status(port, snap)
        node = self.model.nodes.get(port)
        if node is not None and self._selected == port:
            self.inspector.show_node(node)

    def _on_event(self, port: str, event) -> None:  # noqa: ANN001
        self.model.apply_event(port, event)

    def _on_neighbors(self, port: str, rows) -> None:  # noqa: ANN001
        self.model.apply_neighbors(port, rows)

    # ---------------------------------------------------------------- capture
    def toggle_capture(self) -> None:
        if self.capture.active:
            folder = self.capture.folder
            self.capture.export_snapshot(self.model.to_dict(), "final_snapshot")
            self.capture.stop()
            self.toasts.show(f"Capture saved to {folder}", "success")
        else:
            if not self.model.nodes:
                self.toasts.show("Connect at least one board before capturing.", "warning")
                return
            res = prompt_capture_session(
                self,
                title="Start capture",
                placeholder="exp1_pairwise",
                hint=f"Logs are written to {DATA_ROOT}\\<name>\\ — one file per node, plus "
                "session.json.",
            )
            if not res:
                return
            name, do_reset = res
            if do_reset:
                self.model.reset_metrics()
                self._refresh_ui(force=True)
                self.toasts.show("Session metrics & PDR reset for new capture", "info")
            folder = self.capture.start(
                name,
                list(self.model.nodes.keys()),
                {p: n.display_name for p, n in self.model.nodes.items()},
            )
            self.toasts.show(f"Capturing to {folder}", "success")
        self._update_capture_ui()

    def _update_capture_ui(self) -> None:
        active = self.capture.active
        self.btn_capture.setText("Stop capture" if active else "Start capture")
        self.btn_capture.setIcon(
            icons.icon("stop" if active else "record", "danger", 15)
        )
        self.btn_capture.setProperty("variant", "danger" if active else "")
        self.btn_capture.style().unpolish(self.btn_capture)
        self.btn_capture.style().polish(self.btn_capture)
        if active and self.capture.folder is not None:
            self.status_capture.setText(
                f"● Recording → {self.capture.folder.name}  ({self.capture.line_count} lines)"
            )
            self.status_capture.setStyleSheet(f"color:{theme.palette().danger};")
        else:
            self.status_capture.setText("Capture off")
            self.status_capture.setStyleSheet(f"color:{theme.palette().text_muted};")

    def export_snapshot(self) -> None:
        if not self.model.nodes:
            self.toasts.show("Nothing to export yet.", "warning")
            return
        default = str(
            (self.capture.folder or DATA_ROOT) / "topology_snapshot.json"
        )
        path, _ = QFileDialog.getSaveFileName(
            self, "Export snapshot", default, "JSON (*.json)"
        )
        if not path:
            return
        import json

        Path(path).write_text(json.dumps(self.model.to_dict(), indent=2), encoding="utf-8")
        self.toasts.show(f"Snapshot written to {Path(path).name}", "success")

    # ------------------------------------------------------------------ view
    def toggle_theme(self, dark: bool) -> None:
        name = "dark" if dark else "light"
        self.store.set("theme", name)
        self.act_theme.setChecked(dark)
        app = QApplication.instance()
        theme.set_theme(app, name)
        icons.clear_cache()
        self._restyle()

    def _restyle(self) -> None:
        """Re-apply themed pixmaps and inline colours after a palette change."""
        self.btn_add.setIcon(icons.icon("plus", "on_primary", 16))
        self.btn_snapshot.setIcon(icons.icon("camera", "text_muted", 16))
        self.btn_menu.setIcon(icons.icon("gear", "text_muted", 18))
        self.inspector.btn_refresh.setIcon(icons.icon("refresh", "text_muted", 16))
        self.inspector.btn_run.setIcon(icons.icon("play", "on_primary", 15))
        self.inspector.btn_stop.setIcon(icons.icon("stop", "danger", 15))
        self.rail.btn_start_all.setIcon(icons.icon("play", "success", 16))
        self.rail.btn_stop_all.setIcon(icons.icon("stop", "danger", 16))
        self.rail.btn_refresh_all.setIcon(icons.icon("refresh", "text_muted", 16))
        for card in self.canvas._scene.cards.values():  # noqa: SLF001 - internal by design
            for button in (card.btn_refresh, card.btn_run, card.btn_stop):
                button._pix = None  # noqa: SLF001
            card.update()
        self.canvas._scene.update()  # noqa: SLF001
        self.canvas.viewport().update()
        self.console.retheme()
        self.rail.sync(self.model, self._selected)
        self._update_capture_ui()
        self._refresh_ui(force=True)

    def auto_layout(self) -> None:
        self.canvas.auto_layout(self.model)
        for port, node in self.model.nodes.items():
            self.store.save_node_layout(port, node.display_name, node.x, node.y)

    def _sync_canvas_options(self, *_args) -> None:
        labels = self.act_labels.isChecked()
        animate = self.act_anim.isChecked()
        self.store.set("show_rssi_labels", labels)
        self.store.set("animate_packets", animate)
        self.canvas.set_options(labels, animate)

    def _open_data_folder(self) -> None:
        target = self.capture.folder or DATA_ROOT
        target.mkdir(parents=True, exist_ok=True)
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl

        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    def _about(self) -> None:
        confirm(
            self,
            f"{APP_NAME} {APP_VERSION}",
            "Operator console for the DECT NR+ three-node topology experiments on "
            "Conexio Stratus Pro (nRF9151).<br><br>"
            "Every action is issued as a verified <code>exp</code> shell command; nothing is "
            "typed by hand.",
            accept_text="Close",
            detail="Conexio Technologies · research tooling",
        )

    # --------------------------------------------------------------- refresh
    def _refresh_ui(self, force: bool = False) -> None:
        self.model.prune_stale()
        self.canvas.sync(self.model)
        self._tick += 1
        if not force and self._tick % SLOW_EVERY:
            return

        self.rail.sync(self.model, self._selected)
        if self._selected and self._selected in self.model.nodes:
            self.inspector.update_live(self.model.nodes[self._selected])
        elif self._selected is None and self.inspector.current_port() is not None:
            self.inspector.clear()

        kpi = self.model.kpis()
        self.tiles["devices"].set_value(f"{kpi['online']}/{kpi['total']}")
        self.tiles["running"].set_value(
            str(kpi["running"]), "success" if kpi["running"] else "text"
        )
        label, token = PATH_LABEL.get(str(kpi["path"]), ("—", "text"))
        self.tiles["path"].set_value(label, token)
        self.tiles["hops"].set_value("—" if kpi["hops"] is None else str(kpi["hops"]))
        pdr = kpi["pdr"]
        self.tiles["pdr"].set_value(
            "—" if pdr is None else f"{pdr:.0f}%",
            "text" if pdr is None else ("success" if pdr >= 95 else "warning"),
        )
        rssi = kpi["rssi"]
        self.tiles["rssi"].set_value("—" if rssi is None else f"{rssi:.0f}")
        estab = kpi["establishment_s"]
        self.tiles["estab"].set_value("—" if estab is None else f"{estab:.1f}s")
        self.tiles["routes"].set_value(str(kpi["route_changes"]))

        path_text, _ = PATH_LABEL.get(str(kpi["path"]), ("—", "text"))
        detail = f"Data path: {path_text}"
        if kpi["hops"] is not None:
            detail += f"  ·  {kpi['hops']} hop(s)"
        if self.path_chip.text() != detail:
            self.path_chip.setText(detail)
        legend = (
            f"<span style='color:{theme.palette().packet_direct}'>●</span> direct   "
            f"<span style='color:{theme.palette().packet_relay}'>●</span> relayed"
        )
        if self.legend.text() != legend:
            self.legend.setText(legend)

        online = [n for n in self.model.nodes.values() if n.online]
        if not self.model.nodes:
            summary = "No boards connected"
        else:
            summary = (
                f"{len(online)} of {len(self.model.nodes)} link(s) open  ·  "
                f"{sum(1 for n in online if n.running)} running"
            )
        if self.status_link.text() != summary:
            self.status_link.setText(summary)
        self._update_capture_ui()

    # ---------------------------------------------------------------- events
    def resizeEvent(self, event) -> None:  # noqa: N802, ANN001
        super().resizeEvent(event)
        if self.centralWidget() is not None:
            self.overlay.setGeometry(self.centralWidget().rect())
        self.toasts.relayout()

    def closeEvent(self, event) -> None:  # noqa: N802, ANN001
        self._reconnect_timer.stop()
        self._reconnecting_ports.clear()
        self.store.save_window(self.saveGeometry(), self.saveState())
        for port, node in self.model.nodes.items():
            self.store.save_node_layout(port, node.display_name, node.x, node.y)
        self.store.sync()
        self.capture.stop()
        self.engine.shutdown()
        self.hub.close_all()
        super().closeEvent(event)


def run_app(preselect: Optional[list[str]] = None, skip_connect: bool = False) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    store = Store()
    theme.set_theme(app, str(store.get("theme")))
    app.setWindowIcon(icons.icon("topology", "primary", 32))

    ports: list[str] = list(preselect or [])
    if not skip_connect:
        dialog = ConnectDialog(preselect=preselect)
        if dialog.exec() == ConnectDialog.DialogCode.Accepted:
            ports = dialog.selected_ports

    window = MainWindow(initial_ports=ports)
    window.show()
    return app.exec()
