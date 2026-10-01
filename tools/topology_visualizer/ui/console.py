#!/usr/bin/env python3
"""Event console: filtered, colour-coded live serial feed."""

from __future__ import annotations

from collections import deque
from html import escape
from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.parse_topo import SEV_CMD, SEV_DELIVER, SEV_ERROR, SEV_RELAY, SEV_RX, SEV_TX, SEV_WARN
from core.transport import short_port_label
from ui import icons, theme
from ui.widgets import SectionLabel

MAX_LINES = 4000

FILTERS = {
    "all": "All",
    "traffic": "Traffic",
    "control": "Control",
    "alerts": "Alerts",
}

TRAFFIC_SEV = {SEV_TX, SEV_RX, SEV_RELAY, SEV_DELIVER}
ALERT_SEV = {SEV_WARN, SEV_ERROR}


class EventConsole(QFrame):
    cleared = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("Panel")
        self._lines: deque[tuple[str, str, str, str]] = deque(maxlen=MAX_LINES)
        self._filter = "all"
        self._query = ""
        self._paused = False
        self._autoscroll = True
        self._port_filter: Optional[str] = None

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 12)
        root.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(6)
        head.addWidget(SectionLabel("Event console"))
        head.addSpacing(6)

        self._filter_buttons: dict[str, QPushButton] = {}
        for key, label in FILTERS.items():
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setProperty("variant", "tool")
            btn.setChecked(key == "all")
            btn.setFixedHeight(26)
            btn.clicked.connect(lambda _=False, k=key: self.set_filter(k))
            head.addWidget(btn)
            self._filter_buttons[key] = btn

        head.addStretch(1)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter text…")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(180)
        self.search.textChanged.connect(self._on_query)
        head.addWidget(self.search)

        self.btn_pause = QPushButton()
        self.btn_pause.setIcon(icons.icon("pause", "text_muted", 16))
        self.btn_pause.setToolTip("Pause the feed (buffer keeps filling)")
        self.btn_pause.setCheckable(True)
        self.btn_pause.setProperty("variant", "tool")
        self.btn_pause.toggled.connect(self._on_pause)

        self.btn_scroll = QPushButton()
        self.btn_scroll.setIcon(icons.icon("chevron", "text_muted", 16))
        self.btn_scroll.setToolTip("Follow newest lines")
        self.btn_scroll.setCheckable(True)
        self.btn_scroll.setChecked(True)
        self.btn_scroll.setProperty("variant", "tool")
        self.btn_scroll.toggled.connect(self._on_autoscroll)

        self.btn_copy = QPushButton()
        self.btn_copy.setIcon(icons.icon("copy", "text_muted", 16))
        self.btn_copy.setToolTip("Copy visible lines")
        self.btn_copy.setProperty("variant", "tool")
        self.btn_copy.clicked.connect(self._copy)

        self.btn_clear = QPushButton()
        self.btn_clear.setIcon(icons.icon("trash", "text_muted", 16))
        self.btn_clear.setToolTip("Clear the console")
        self.btn_clear.setProperty("variant", "tool")
        self.btn_clear.clicked.connect(self.clear)

        for btn in (self.btn_pause, self.btn_scroll, self.btn_copy, self.btn_clear):
            btn.setFixedSize(30, 26)
            head.addWidget(btn)
        root.addLayout(head)

        self.view = QPlainTextEdit()
        self.view.setObjectName("Console")
        self.view.setReadOnly(True)
        self.view.setMaximumBlockCount(MAX_LINES)
        self.view.setPlaceholderText("Serial traffic from every connected board appears here.")
        self.view.setFont(theme.mono_font(9))
        root.addWidget(self.view, 1)

        self.footer = QLabel("0 lines")
        self.footer.setObjectName("Faint")
        root.addWidget(self.footer)

    # ---------------------------------------------------------------- filters
    def set_filter(self, key: str) -> None:
        self._filter = key
        for name, btn in self._filter_buttons.items():
            btn.setChecked(name == key)
        self._rerender()

    def set_port_filter(self, port: Optional[str]) -> None:
        if self._port_filter == port:
            return
        self._port_filter = port
        self._rerender()

    def _on_query(self, text: str) -> None:
        self._query = text.strip().lower()
        self._rerender()

    def _on_pause(self, paused: bool) -> None:
        self._paused = paused
        self.btn_pause.setIcon(icons.icon("play" if paused else "pause", "text_muted", 16))
        if not paused:
            self._rerender()

    def _on_autoscroll(self, on: bool) -> None:
        self._autoscroll = on
        if on:
            self._scroll_to_end()

    def _visible(self, entry: tuple[str, str, str, str]) -> bool:
        port, _ts, body, sev = entry
        if self._port_filter and port != self._port_filter:
            return False
        if self._filter == "traffic" and sev not in TRAFFIC_SEV:
            return False
        if self._filter == "control" and sev in TRAFFIC_SEV:
            return False
        if self._filter == "alerts" and sev not in ALERT_SEV:
            return False
        if self._query and self._query not in body.lower():
            return False
        return True

    # ----------------------------------------------------------------- feed
    def append(self, port: str, host_ts: str, body: str, sev: str) -> None:
        entry = (port, host_ts, body, sev)
        self._lines.append(entry)
        if not self._paused and self._visible(entry):
            self.view.appendHtml(self._html(entry))
            if self._autoscroll:
                self._scroll_to_end()
        self._update_footer()

    def note(self, text: str) -> None:
        self.append("host", "", text, SEV_CMD)

    def _html(self, entry: tuple[str, str, str, str]) -> str:
        port, ts, body, sev = entry
        p = theme.palette()
        colors = {
            SEV_TX: p.role_source,
            SEV_RX: p.info,
            SEV_RELAY: p.role_relay,
            SEV_DELIVER: p.success,
            SEV_WARN: p.warning,
            SEV_ERROR: p.danger,
            SEV_CMD: p.primary,
        }
        col = colors.get(sev, p.text)
        label = short_port_label(port)
        return (
            f"<span style='color:{p.text_faint}'>{escape(ts)}</span> "
            f"<span style='color:{p.text_muted}'>{escape(label):>8}</span> "
            f"<span style='color:{col}'>{escape(body)}</span>"
        )

    def _rerender(self) -> None:
        self.view.clear()
        html = [self._html(e) for e in self._lines if self._visible(e)]
        if html:
            self.view.appendHtml("<br>".join(html))
        if self._autoscroll:
            self._scroll_to_end()
        self._update_footer()

    def _update_footer(self) -> None:
        shown = sum(1 for e in self._lines if self._visible(e))
        text = f"{shown} of {len(self._lines)} lines"
        if self._port_filter:
            text += f"  ·  {short_port_label(self._port_filter)} only"
        if self._paused:
            text += "  ·  paused"
        if self.footer.text() != text:
            self.footer.setText(text)

    def _scroll_to_end(self) -> None:
        bar = self.view.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _copy(self) -> None:
        text = "\n".join(
            f"{ts} {short_port_label(port)} {body}"
            for port, ts, body, _sev in self._lines
            if self._visible((port, ts, body, _sev))
        )
        self.view.copyAvailable.emit(False)
        from PySide6.QtGui import QGuiApplication

        QGuiApplication.clipboard().setText(text)

    def retheme(self) -> None:
        """Re-colour the buffered feed after a palette change."""
        self.view.setFont(theme.mono_font(9))
        for name, glyph in (
            ("btn_pause", "play" if self._paused else "pause"),
            ("btn_scroll", "chevron"),
            ("btn_copy", "copy"),
            ("btn_clear", "trash"),
        ):
            getattr(self, name).setIcon(icons.icon(glyph, "text_muted", 16))
        self._rerender()

    def clear(self) -> None:
        self._lines.clear()
        self.view.clear()
        self._update_footer()
        self.cleared.emit()

    def visible_text(self) -> str:
        return "\n".join(
            f"{ts} {short_port_label(port)} {body}"
            for port, ts, body, sev in self._lines
            if self._visible((port, ts, body, sev))
        )
