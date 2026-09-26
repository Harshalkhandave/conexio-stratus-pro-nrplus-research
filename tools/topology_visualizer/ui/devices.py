#!/usr/bin/env python3
"""Device rail: the roster of boards in the session."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.model import ConnState, NodeState, SessionModel
from ui import icons, theme
from ui.widgets import Badge, SectionLabel, StatusDot


class DeviceRow(QWidget):
    def __init__(self, port: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.port = port
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(10)
        self.dot = StatusDot(diameter=9)
        text = QVBoxLayout()
        text.setSpacing(1)
        self.name = QLabel(port)
        self.name.setFont(theme.ui_font(10, QFont.Weight.DemiBold))
        self.sub = QLabel("")
        self.sub.setObjectName("Faint")
        text.addWidget(self.name)
        text.addWidget(self.sub)
        self.badge = Badge("—")
        lay.addWidget(self.dot, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addLayout(text, 1)
        lay.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignVCenter)

    def update_from(self, node: NodeState) -> None:
        if self.name.text() != node.label:
            self.name.setText(node.label)
        transport = node.port.split("://", 1)[-1]
        rssi = node.live_rssi()
        parts = [] if transport == node.label else [transport]
        if node.device_id is not None:
            parts.append(f"id {node.device_id}")
        if rssi is not None:
            parts.append(f"{rssi:.0f} dBm")
        sub = "  ·  ".join(parts) or "no status yet"
        if self.sub.text() != sub:
            self.sub.setText(sub)

        if node.conn == ConnState.ERROR:
            self.dot.set_state(theme.color("danger"))
            self.badge.set_value("ERROR", theme.palette().danger)
        elif node.conn == ConnState.RECONNECTING:
            self.dot.set_state(theme.color("warning"), pulse=True)
            self.badge.set_value("RECONN", theme.palette().warning)
        elif node.conn == ConnState.DISCONNECTED:
            self.dot.set_state(theme.color("text_faint"))
            self.badge.set_value("OFFLINE", theme.palette().text_faint)
        elif node.running:
            self.dot.set_state(theme.color("success"), pulse=True)
            self.badge.set_value("RUN", theme.palette().success)
        else:
            self.dot.set_state(theme.color("info"))
            self.badge.set_value("IDLE", theme.palette().info)
        role = node.role
        if role:
            self.badge.setToolTip(f"{node.friendly_role} ({role})")


class DeviceRail(QFrame):
    selected = Signal(str)
    add_requested = Signal()
    start_all_requested = Signal()
    stop_all_requested = Signal()
    refresh_all_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("Rail")
        self.setFixedWidth(268)
        self._rows: dict[str, DeviceRow] = {}
        self._items: dict[str, QListWidgetItem] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 12, 12)
        root.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(6)
        title = QLabel("Devices")
        title.setObjectName("H1")
        self.count = QLabel("0")
        self.count.setObjectName("Faint")
        add = QPushButton()
        add.setIcon(icons.icon("plus", "primary", 17))
        add.setToolTip("Connect another board (Ctrl+N)")
        add.setProperty("variant", "tool")
        add.setFixedSize(30, 28)
        add.clicked.connect(self.add_requested.emit)
        header.addWidget(title)
        header.addWidget(self.count)
        header.addStretch(1)
        header.addWidget(add)
        root.addLayout(header)

        self.list = QListWidget()
        self.list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.list.currentItemChanged.connect(self._on_current)
        root.addWidget(self.list, 1)

        self.empty = QLabel(
            "No boards connected yet.\nUse + to add a serial port or TCP bridge."
        )
        self.empty.setObjectName("Faint")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setWordWrap(True)
        root.addWidget(self.empty)

        root.addWidget(SectionLabel("Session actions"))
        self.btn_start_all = QPushButton("Start network")
        self.btn_start_all.setIcon(icons.icon("play", "success", 16))
        self.btn_start_all.setToolTip("Start sink, then relay, then source")
        self.btn_start_all.clicked.connect(self.start_all_requested.emit)
        self.btn_stop_all = QPushButton("Stop all")
        self.btn_stop_all.setIcon(icons.icon("stop", "danger", 16))
        self.btn_stop_all.clicked.connect(self.stop_all_requested.emit)
        self.btn_refresh_all = QPushButton("Refresh all")
        self.btn_refresh_all.setIcon(icons.icon("refresh", "text_muted", 16))
        self.btn_refresh_all.clicked.connect(self.refresh_all_requested.emit)
        for btn in (self.btn_start_all, self.btn_stop_all, self.btn_refresh_all):
            btn.setMinimumHeight(32)
            root.addWidget(btn)

    # ------------------------------------------------------------------ sync
    def sync(self, model: SessionModel, selected: Optional[str]) -> None:
        ports = model.ordered_ports()
        for port in list(self._rows.keys()):
            if port not in model.nodes:
                item = self._items.pop(port)
                self.list.takeItem(self.list.row(item))
                self._rows.pop(port, None)

        for index, port in enumerate(ports):
            row = self._rows.get(port)
            if row is None:
                row = DeviceRow(port)
                item = QListWidgetItem()
                item.setSizeHint(QSize(0, 52))
                item.setData(Qt.ItemDataRole.UserRole, port)
                self.list.addItem(item)
                self.list.setItemWidget(item, row)
                self._rows[port] = row
                self._items[port] = item
            row.update_from(model.nodes[port])

        self.count.setText(f"{len(ports)}")
        self.empty.setVisible(not ports)
        self.list.setVisible(bool(ports))

        if selected and selected in self._items:
            item = self._items[selected]
            if self.list.currentItem() is not item:
                self.list.blockSignals(True)
                self.list.setCurrentItem(item)
                self.list.blockSignals(False)

        any_online = any(n.online for n in model.nodes.values())
        any_running = any(n.running for n in model.nodes.values())
        self.btn_start_all.setEnabled(any_online and not any_running)
        self.btn_stop_all.setEnabled(any_running)
        self.btn_refresh_all.setEnabled(any_online)

    def _on_current(self, current: QListWidgetItem, _previous: QListWidgetItem) -> None:
        if current is None:
            return
        port = current.data(Qt.ItemDataRole.UserRole)
        if port:
            self.selected.emit(port)
