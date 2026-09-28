#!/usr/bin/env python3
"""Dialogs: connect flow, confirmations, prompts."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, QThreadPool, QRunnable, QObject, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.transport import list_available_ports, normalize_port, test_open_port
from ui import icons, theme
from ui.widgets import Card, CheckBox, HLine, SectionLabel


def _dialog_shell(parent: Optional[QWidget], title: str, width: int = 460) -> tuple[QDialog, QVBoxLayout]:
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setMinimumWidth(width)
    outer = QVBoxLayout(dlg)
    outer.setContentsMargins(20, 18, 20, 16)
    outer.setSpacing(14)
    heading = QLabel(title)
    heading.setObjectName("H1")
    outer.addWidget(heading)
    return dlg, outer


def confirm(
    parent: Optional[QWidget],
    title: str,
    message: str,
    accept_text: str = "Confirm",
    destructive: bool = False,
    detail: str = "",
) -> bool:
    dlg, lay = _dialog_shell(parent, title)
    body = QLabel(message)
    body.setWordWrap(True)
    lay.addWidget(body)
    if detail:
        note = QLabel(detail)
        note.setObjectName("Faint")
        note.setWordWrap(True)
        lay.addWidget(note)
    lay.addStretch(1)
    row = QHBoxLayout()
    row.addStretch(1)
    cancel = QPushButton("Cancel")
    cancel.clicked.connect(dlg.reject)
    ok = QPushButton(accept_text)
    ok.setProperty("variant", "danger" if destructive else "primary")
    ok.setDefault(True)
    ok.clicked.connect(dlg.accept)
    row.addWidget(cancel)
    row.addWidget(ok)
    lay.addLayout(row)
    return dlg.exec() == QDialog.DialogCode.Accepted


def confirm_changes(
    parent: Optional[QWidget],
    title: str,
    rows: list[tuple[str, str, str]],
    footer: str = "",
    accept_text: str = "Apply to board",
) -> bool:
    """Show a parameter / current / new table before touching the radio."""
    dlg, lay = _dialog_shell(parent, title, width = 520)
    intro = QLabel("These parameters will be written to the board:")
    intro.setObjectName("Muted")
    lay.addWidget(intro)

    card = Card(margins=12, spacing=8)
    grid = QGridLayout()
    grid.setHorizontalSpacing(18)
    grid.setVerticalSpacing(7)
    for col, head in enumerate(("Parameter", "Current", "New")):
        label = QLabel(head.upper())
        label.setObjectName("StatLabel")
        grid.addWidget(label, 0, col)
    for r, (name, old, new) in enumerate(rows, start=1):
        grid.addWidget(QLabel(name), r, 0)
        current = QLabel(old)
        current.setObjectName("Muted")
        grid.addWidget(current, r, 1)
        target = QLabel(new)
        target.setStyleSheet(f"color: {theme.palette().primary}; font-weight: 600;")
        grid.addWidget(target, r, 2)
    grid.setColumnStretch(0, 1)
    card.body.addLayout(grid)
    lay.addWidget(card)

    if footer:
        note = QLabel(footer)
        note.setObjectName("Faint")
        note.setWordWrap(True)
        lay.addWidget(note)

    row = QHBoxLayout()
    row.addStretch(1)
    cancel = QPushButton("Cancel")
    cancel.clicked.connect(dlg.reject)
    ok = QPushButton(accept_text)
    ok.setProperty("variant", "primary")
    ok.setDefault(True)
    ok.clicked.connect(dlg.accept)
    row.addWidget(cancel)
    row.addWidget(ok)
    lay.addLayout(row)
    return dlg.exec() == QDialog.DialogCode.Accepted


def prompt_text(
    parent: Optional[QWidget],
    title: str,
    label: str,
    default: str = "",
    placeholder: str = "",
    hint: str = "",
) -> Optional[str]:
    dlg, lay = _dialog_shell(parent, title)
    cap = QLabel(label)
    cap.setObjectName("StatLabel")
    edit = QLineEdit(default)
    edit.setPlaceholderText(placeholder)
    edit.selectAll()
    lay.addWidget(cap)
    lay.addWidget(edit)
    if hint:
        note = QLabel(hint)
        note.setObjectName("Faint")
        note.setWordWrap(True)
        lay.addWidget(note)
    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    buttons.button(QDialogButtonBox.StandardButton.Ok).setProperty("variant", "primary")
    buttons.accepted.connect(dlg.accept)
    buttons.rejected.connect(dlg.reject)
    lay.addWidget(buttons)
    edit.returnPressed.connect(dlg.accept)
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return None
    return edit.text().strip() or None


def prompt_capture_session(
    parent: Optional[QWidget],
    title: str = "Start capture",
    default: str = "",
    placeholder: str = "",
    hint: str = "",
    default_reset: bool = True,
) -> Optional[tuple[str, bool]]:
    """Prompt for session name with a default-checked option to reset metrics."""
    dlg, lay = _dialog_shell(parent, title)
    cap = QLabel("Session folder name")
    cap.setObjectName("StatLabel")
    edit = QLineEdit(default)
    edit.setPlaceholderText(placeholder)
    edit.selectAll()
    lay.addWidget(cap)
    lay.addWidget(edit)

    chk_reset = CheckBox("Reset live metrics & session counters (PDR, delivery, drops)")
    chk_reset.setChecked(default_reset)
    chk_reset.setToolTip(
        "Clear session PDR, packet delivery counts, and route timings to start fresh for this capture session."
    )
    lay.addWidget(chk_reset)

    if hint:
        note = QLabel(hint)
        note.setObjectName("Faint")
        note.setWordWrap(True)
        lay.addWidget(note)
    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    buttons.button(QDialogButtonBox.StandardButton.Ok).setProperty("variant", "primary")
    buttons.accepted.connect(dlg.accept)
    buttons.rejected.connect(dlg.reject)
    lay.addWidget(buttons)
    edit.returnPressed.connect(dlg.accept)
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return None
    name = edit.text().strip()
    if not name:
        return None
    return name, chk_reset.isChecked()


def confirm_unsaved(
    parent: Optional[QWidget],
    node_label: str,
    rows: list[tuple[str, str, str]],
    what: str = "this node",
) -> str:
    """Unsaved editor changes before a run. Returns 'cancel', 'apply' or 'start'."""
    dlg, lay = _dialog_shell(parent, "Unsaved settings", width=520)
    head = QHBoxLayout()
    glyph = QLabel()
    glyph.setPixmap(icons.pixmap("warning", theme.color("warning"), 22, 2.0))
    text = QLabel(
        f"<b>{node_label}</b> has edits in the Settings tab that were never applied "
        f"to the board. Starting {what} now would run with the values currently "
        f"stored on the board."
    )
    text.setWordWrap(True)
    head.addWidget(glyph, 0, Qt.AlignmentFlag.AlignTop)
    head.addWidget(text, 1)
    lay.addLayout(head)

    if rows:
        card = Card(margins=12, spacing=8)
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(7)
        for col, name in enumerate(("Parameter", "On board", "In editor")):
            cap = QLabel(name.upper())
            cap.setObjectName("StatLabel")
            grid.addWidget(cap, 0, col)
        for r, (name, old, new) in enumerate(rows, start=1):
            grid.addWidget(QLabel(name), r, 0)
            current = QLabel(old)
            current.setObjectName("Muted")
            grid.addWidget(current, r, 1)
            edited = QLabel(new)
            edited.setStyleSheet(f"color: {theme.palette().warning}; font-weight: 600;")
            grid.addWidget(edited, r, 2)
        grid.setColumnStretch(0, 1)
        card.body.addLayout(grid)
        lay.addWidget(card)

    result = {"value": "cancel"}
    buttons = QHBoxLayout()
    cancel = QPushButton("Cancel")
    cancel.clicked.connect(dlg.reject)
    start = QPushButton("Start anyway")
    apply_first = QPushButton("Apply, then start")
    apply_first.setProperty("variant", "primary")
    apply_first.setDefault(True)
    buttons.addWidget(cancel)
    buttons.addStretch(1)
    buttons.addWidget(start)
    buttons.addWidget(apply_first)
    lay.addLayout(buttons)

    def _pick(value: str) -> None:
        result["value"] = value
        dlg.accept()

    start.clicked.connect(lambda: _pick("start"))
    apply_first.clicked.connect(lambda: _pick("apply"))
    dlg.exec()
    return result["value"]


def warn_disconnect(parent: Optional[QWidget], port: str, reason: str) -> str:
    """Returns 'keep' or 'remove'."""
    dlg, lay = _dialog_shell(parent, "Link lost")
    row = QHBoxLayout()
    glyph = QLabel()
    glyph.setPixmap(icons.pixmap("warning", theme.color("warning"), 22, 2.0))
    text = QLabel(
        f"<b>{port}</b> stopped responding.<br>"
        f"<span style='color:{theme.palette().text_muted}'>{reason or 'the link closed unexpectedly'}</span>"
    )
    text.setWordWrap(True)
    row.addWidget(glyph, 0, Qt.AlignmentFlag.AlignTop)
    row.addWidget(text, 1)
    lay.addLayout(row)
    note = QLabel(
        "Keeping the node preserves its position, name and counters so you can reopen "
        "the link later."
    )
    note.setObjectName("Faint")
    note.setWordWrap(True)
    lay.addWidget(note)
    buttons = QHBoxLayout()
    remove = QPushButton("Remove node")
    remove.setProperty("variant", "danger")
    keep = QPushButton("Keep node (offline)")
    keep.setProperty("variant", "primary")
    keep.setDefault(True)
    buttons.addStretch(1)
    buttons.addWidget(remove)
    buttons.addWidget(keep)
    lay.addLayout(buttons)
    result = {"value": "keep"}

    def _remove() -> None:
        result["value"] = "remove"
        dlg.accept()

    remove.clicked.connect(_remove)
    keep.clicked.connect(dlg.accept)
    dlg.exec()
    return result["value"]


class _ProbeSignals(QObject):
    done = Signal(str, bool, str)


class _Probe(QRunnable):
    def __init__(self, port: str, signals: _ProbeSignals) -> None:
        super().__init__()
        self.port = port
        self.signals = signals

    def run(self) -> None:
        ok, msg = test_open_port(self.port)
        self.signals.done.emit(self.port, ok, msg)


class PortRow(QFrame):
    """One selectable transport with an inline verification result."""

    HEIGHT = 54

    def __init__(self, port: str, description: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.port = port
        self.setObjectName("PortRow")
        self.setFixedHeight(self.HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 0, 12, 0)
        lay.setSpacing(12)

        self.check = CheckBox()
        self.check.setFixedWidth(20)

        title_col = QVBoxLayout()
        title_col.setContentsMargins(0, 0, 0, 0)
        title_col.setSpacing(0)
        name = QLabel(port)
        name.setObjectName("H2")
        self.desc = QLabel(description or "serial device")
        self.desc.setObjectName("Faint")
        title_col.addWidget(name)
        title_col.addWidget(self.desc)

        self.result = QLabel("")
        self.result.setObjectName("Faint")

        middle = Qt.AlignmentFlag.AlignVCenter
        lay.addWidget(self.check, 0, middle)
        lay.addLayout(title_col, 1)
        lay.addWidget(self.result, 0, middle)

    def mousePressEvent(self, event) -> None:  # noqa: N802, ANN001
        """Clicking anywhere on the row toggles it, like a native list."""
        if event.button() == Qt.MouseButton.LeftButton and self.check.isEnabled():
            self.check.toggle()
            event.accept()
            return
        super().mousePressEvent(event)

    def set_result(self, ok: Optional[bool], message: str) -> None:
        if ok is None:
            self.result.setText("checking…")
            self.result.setStyleSheet(f"color:{theme.palette().text_faint};")
            return
        self.result.setText("reachable" if ok else "unavailable")
        color = theme.palette().success if ok else theme.palette().danger
        self.result.setStyleSheet(f"color:{color}; font-weight:600;")
        self.result.setToolTip(message)
        if not ok:
            self.check.setChecked(False)


class ConnectDialog(QDialog):
    """Startup / add-device flow: pick transports, verify, then connect."""

    def __init__(self, parent: Optional[QWidget] = None, preselect: Optional[list[str]] = None):
        super().__init__(parent)
        self.setWindowTitle("Connect boards")
        self.setMinimumSize(560, 520)
        self.selected_ports: list[str] = []
        self._rows: dict[str, PortRow] = {}
        self._signals = _ProbeSignals()
        self._signals.done.connect(self._on_probe)
        self._pool = QThreadPool()
        self._verified: dict[str, bool] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 20, 22, 18)
        outer.setSpacing(14)

        head = QVBoxLayout()
        head.setSpacing(3)
        title = QLabel("Connect boards")
        title.setObjectName("H1")
        sub = QLabel(
            "Select the Stratus Pro boards to monitor. Serial ports are detected "
            "automatically; TCP bridges can be added by URL."
        )
        sub.setObjectName("Muted")
        sub.setWordWrap(True)
        head.addWidget(title)
        head.addWidget(sub)
        outer.addLayout(head)

        outer.addWidget(SectionLabel("Detected serial ports"))
        self.list_holder = QWidget()
        self.list_lay = QVBoxLayout(self.list_holder)
        self.list_lay.setContentsMargins(0, 0, 0, 0)
        self.list_lay.setSpacing(4)
        # Rows keep their natural height instead of being stretched apart.
        self.list_lay.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(self.list_holder)
        scroll.setMinimumHeight(150)
        outer.addWidget(scroll, 1)

        refresh_row = QHBoxLayout()
        rescan = QPushButton("Rescan ports")
        rescan.setIcon(icons.icon("refresh", "text_muted", 16))
        rescan.clicked.connect(self._scan)
        self.verify_btn = QPushButton("Verify selected")
        self.verify_btn.setIcon(icons.icon("check", "text_muted", 16))
        self.verify_btn.clicked.connect(self._verify_selected)
        refresh_row.addWidget(rescan)
        refresh_row.addWidget(self.verify_btn)
        refresh_row.addStretch(1)
        outer.addLayout(refresh_row)

        outer.addWidget(HLine())
        outer.addWidget(SectionLabel("Add a TCP bridge or custom URL"))
        manual_row = QHBoxLayout()
        self.manual = QLineEdit()
        self.manual.setPlaceholderText("socket://10.0.0.139:7777  or  COM9")
        add = QPushButton("Add")
        add.setIcon(icons.icon("plus", "text_muted", 16))
        add.clicked.connect(self._add_manual)
        self.manual.returnPressed.connect(self._add_manual)
        manual_row.addWidget(self.manual, 1)
        manual_row.addWidget(add)
        outer.addLayout(manual_row)

        self.status = QLabel("")
        self.status.setObjectName("Faint")
        self.status.setWordWrap(True)
        outer.addWidget(self.status)

        footer = QHBoxLayout()
        skip = QPushButton("Skip for now")
        skip.clicked.connect(self.reject)
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.setProperty("variant", "primary")
        self.connect_btn.setDefault(True)
        self.connect_btn.clicked.connect(self._accept)
        footer.addWidget(skip)
        footer.addStretch(1)
        footer.addWidget(self.connect_btn)
        outer.addLayout(footer)

        self._scan()
        for port in preselect or []:
            self._add_port(normalize_port(port), "requested on the command line", checked=True)
        self._update_status_count()

    # ------------------------------------------------------------------ rows
    def _scan(self) -> None:
        found = list_available_ports()
        self._detected = len(found)
        for port, desc in found:
            self._add_port(normalize_port(port), desc)
        self._update_status_count()

    def _update_status_count(self) -> None:
        detected = getattr(self, "_detected", 0)
        if not self._rows:
            self.status.setText(
                "No serial ports detected. Add a TCP bridge below, or skip and connect later."
            )
            return
        extra = len(self._rows) - detected
        text = f"{detected} serial port(s) detected"
        if extra > 0:
            text += f", {extra} added manually"
        self.status.setText(text + ".")

    def _add_port(self, port: str, desc: str = "", checked: bool = False) -> None:
        if port in self._rows:
            if checked:
                self._rows[port].check.setChecked(True)
            return
        row = PortRow(port, desc)
        row.check.setChecked(checked)
        self._rows[port] = row
        self.list_lay.insertWidget(self.list_lay.count() - 1, row)

    def _add_manual(self) -> None:
        text = normalize_port(self.manual.text())
        if not text:
            return
        self._add_port(text, "manually added", checked=True)
        self.manual.clear()
        self.status.setText(f"Added {text}. Use \u201cVerify selected\u201d to test it before connecting.")

    # -------------------------------------------------------------- verify
    def _checked_ports(self) -> list[str]:
        return [p for p, row in self._rows.items() if row.check.isChecked()]

    def _verify_selected(self) -> None:
        ports = self._checked_ports()
        if not ports:
            self.status.setText("Select at least one transport to verify.")
            return
        self.status.setText("Verifying…")
        for port in ports:
            self._rows[port].set_result(None, "")
            self._pool.start(_Probe(port, self._signals))

    def _on_probe(self, port: str, ok: bool, message: str) -> None:
        row = self._rows.get(port)
        self._verified[port] = ok
        if row:
            row.set_result(ok, message)
        bad = [p for p, good in self._verified.items() if not good]
        if bad:
            self.status.setText(f"Unavailable: {', '.join(bad)}")
        else:
            self.status.setText("All verified transports are reachable.")

    # -------------------------------------------------------------- accept
    def _accept(self) -> None:
        ports = self._checked_ports()
        if not ports:
            self.status.setText("Select at least one transport, or choose “Skip for now”.")
            return
        unverified = [p for p in ports if p not in self._verified]
        failed = [p for p in ports if self._verified.get(p) is False]
        if failed and not confirm(
            self,
            "Connect anyway?",
            f"{', '.join(failed)} did not respond during verification.",
            accept_text="Connect anyway",
            detail="Nodes that fail to open are shown offline and can be reopened later.",
        ):
            return
        if unverified:
            self.status.setText("Verifying before connect…")
            for port in unverified:
                ok, _ = test_open_port(port)
                self._verified[port] = ok
                self._rows[port].set_result(ok, "")
            failed = [p for p in ports if not self._verified.get(p)]
            if failed and not confirm(
                self,
                "Connect anyway?",
                f"{', '.join(failed)} could not be opened.",
                accept_text="Connect anyway",
            ):
                return
        self.selected_ports = ports
        self.accept()
