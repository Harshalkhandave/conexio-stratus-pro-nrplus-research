#!/usr/bin/env python3
"""Reusable presentation widgets: cards, stat tiles, chips, spinner, toasts."""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    QRect,
    QRectF,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QWheelEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QStyle,
    QStyleOptionButton,
    QVBoxLayout,
    QWidget,
)

from ui import icons, theme


# --------------------------------------------------------------------- basics
class Card(QFrame):
    def __init__(self, parent: Optional[QWidget] = None, margins: int = 14, spacing: int = 10):
        super().__init__(parent)
        self.setObjectName("Card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(margins, margins, margins, margins)
        self.body.setSpacing(spacing)


class SectionLabel(QLabel):
    def __init__(self, text: str, parent: Optional[QWidget] = None):
        super().__init__(text.upper(), parent)
        self.setObjectName("SectionLabel")


class HLine(QFrame):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("Separator")
        self.setFixedHeight(1)


class IconButton(QPushButton):
    def __init__(
        self,
        name: str,
        tooltip: str = "",
        token: str = "text_muted",
        size: int = 18,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._name = name
        self._token = token
        self._size = size
        self.setProperty("variant", "tool")
        self.setIcon(icons.icon(name, token, size))
        self.setToolTip(tooltip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(30)

    def restyle(self, token: Optional[str] = None) -> None:
        if token:
            self._token = token
        self.setIcon(icons.icon(self._name, self._token, self._size))


class StatusDot(QWidget):
    """Small state dot with an optional soft halo when live."""

    def __init__(self, parent: Optional[QWidget] = None, diameter: int = 10):
        super().__init__(parent)
        self._d = diameter
        self._color = QColor(theme.palette().text_faint)
        self._pulse = False
        self.setFixedSize(diameter + 6, diameter + 6)

    def set_state(self, color: QColor, pulse: bool = False) -> None:
        if color != self._color or pulse != self._pulse:
            self._color = color
            self._pulse = pulse
            self.update()

    def paintEvent(self, event) -> None:  # noqa: N802, ANN001
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = self.rect().center()
        if self._pulse:
            halo = QColor(self._color)
            halo.setAlpha(60)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(halo)
            p.drawEllipse(c, (self._d + 5) / 2, (self._d + 5) / 2)
        p.setBrush(self._color)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(c, self._d / 2, self._d / 2)


class Badge(QLabel):
    """Pill label used for roles and states."""

    def __init__(self, text: str = "", parent: Optional[QWidget] = None):
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._fg = QColor(theme.palette().text_muted)
        self.setFont(theme.ui_font(8, QFont.Weight.DemiBold))
        self.setFixedHeight(20)
        self.set_tone(theme.palette().text_muted)

    def set_tone(self, color: str | QColor) -> None:
        c = QColor(color)
        self._fg = c
        bg = QColor(c)
        bg.setAlpha(38)
        self.setStyleSheet(
            f"background: rgba({bg.red()},{bg.green()},{bg.blue()},{bg.alpha()});"
            f"color: {c.name()}; border-radius: 10px; padding: 1px 9px;"
            f"font-size: 11px; font-weight: 600;"
        )

    def set_value(self, text: str, color: str | QColor) -> None:
        if self.text() != text:
            self.setText(text)
        self.set_tone(color)


class StatTile(QFrame):
    """Compact KPI readout for the header strip."""

    def __init__(self, label: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(1)
        self.value = QLabel("—")
        self.value.setObjectName("StatValue")
        self.caption = QLabel(label.upper())
        self.caption.setObjectName("StatLabel")
        lay.addWidget(self.value)
        lay.addWidget(self.caption)
        self.setMinimumWidth(96)

    def set_value(self, text: str, token: str = "text") -> None:
        if self.value.text() != text:
            self.value.setText(text)
        col = theme.color(token).name()
        style = f"color: {col};"
        if self.value.styleSheet() != style:
            self.value.setStyleSheet(style)


class Spinner(QWidget):
    """Indeterminate activity ring."""

    def __init__(self, parent: Optional[QWidget] = None, diameter: int = 26, width: float = 3.0):
        super().__init__(parent)
        self._angle = 0
        self._w = width
        self.setFixedSize(diameter, diameter)
        self._timer = QTimer(self)
        self._timer.setInterval(28)
        self._timer.timeout.connect(self._tick)

    def start(self) -> None:
        if not self._timer.isActive():
            self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def _tick(self) -> None:
        self._angle = (self._angle + 9) % 360
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802, ANN001
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self._w, self._w, self.width() - 2 * self._w, self.height() - 2 * self._w)
        track = QColor(theme.palette().border_strong)
        p.setPen(QPen(track, self._w))
        p.drawEllipse(rect)
        pen = QPen(theme.color("primary"), self._w)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawArc(rect, -self._angle * 16, 110 * 16)


class BusyOverlay(QWidget):
    """Blocks interaction while a verified board operation is in flight."""

    cancelled = Signal()

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.hide()
        self._card = QFrame(self)
        self._card.setObjectName("Card")
        lay = QHBoxLayout(self._card)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(14)
        self.spinner = Spinner(self._card)
        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        self.title = QLabel("Working…")
        self.title.setObjectName("H2")
        self.detail = QLabel("")
        self.detail.setObjectName("Faint")
        text_col.addWidget(self.title)
        text_col.addWidget(self.detail)
        self.cancel = QPushButton("Cancel")
        self.cancel.clicked.connect(self.cancelled.emit)
        lay.addWidget(self.spinner)
        lay.addLayout(text_col)
        lay.addSpacing(6)
        lay.addWidget(self.cancel)

    def show_busy(self, title: str, detail: str = "", cancellable: bool = True) -> None:
        self.title.setText(title)
        self.detail.setText(detail)
        self.cancel.setVisible(cancellable)
        self._card.adjustSize()
        self._reposition()
        self.spinner.start()
        self.raise_()
        self.show()

    def update_detail(self, detail: str) -> None:
        self.detail.setText(detail)
        self._card.adjustSize()
        self._reposition()

    def hide_busy(self) -> None:
        self.spinner.stop()
        self.hide()

    def resizeEvent(self, event) -> None:  # noqa: N802, ANN001
        self._reposition()
        super().resizeEvent(event)

    def _reposition(self) -> None:
        cw, ch = self._card.width(), self._card.height()
        self._card.move((self.width() - cw) // 2, (self.height() - ch) // 2)

    def paintEvent(self, event) -> None:  # noqa: N802, ANN001
        p = QPainter(self)
        veil = QColor(theme.palette().bg)
        veil.setAlpha(190)
        p.fillRect(self.rect(), veil)


class Toast(QFrame):
    ICONS = {"success": "check", "info": "info", "warning": "warning", "error": "warning"}
    TOKENS = {"success": "success", "info": "primary", "warning": "warning", "error": "danger"}

    def __init__(
        self,
        parent: QWidget,
        text: str,
        kind: str = "info",
        timeout: int = 4200,
        action_label: str = "",
        on_action: Optional[Callable[[], None]] = None,
    ):
        super().__init__(parent)
        self.setObjectName("Card")
        token = self.TOKENS.get(kind, "primary")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 10, 14, 10)
        lay.setSpacing(10)
        glyph = QLabel()
        glyph.setPixmap(icons.pixmap(self.ICONS.get(kind, "info"), theme.color(token), 18, 2.0))
        label = QLabel(text)
        label.setWordWrap(True)
        label.setMaximumWidth(340)
        lay.addWidget(glyph, 0, Qt.AlignmentFlag.AlignTop)
        lay.addWidget(label, 1)
        if action_label and on_action is not None:
            btn = QPushButton(action_label)
            btn.setProperty("variant", "tool")
            btn.setFixedHeight(26)

            def _act() -> None:
                on_action()
                self.close()

            btn.clicked.connect(_act)
            lay.addWidget(btn)
        accent = theme.color(token).name()
        self.setStyleSheet(
            f"QFrame#Card {{ border-left: 3px solid {accent}; }}"
        )
        self._effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._effect)
        self._effect.setOpacity(0.0)
        self._in = QPropertyAnimation(self._effect, b"opacity", self)
        self._in.setDuration(140)
        self._in.setEndValue(1.0)
        self._out = QPropertyAnimation(self._effect, b"opacity", self)
        self._out.setDuration(220)
        self._out.setEndValue(0.0)
        self._out.setEasingCurve(QEasingCurve.Type.InQuad)
        self._out.finished.connect(self.close)
        self.adjustSize()
        self._in.start()
        QTimer.singleShot(timeout, self._out.start)


class ToastManager:
    """Stacks non-blocking notifications in the bottom-right of a host widget."""

    MAX_VISIBLE = 3

    def __init__(self, host: QWidget):
        self.host = host
        self._toasts: list[Toast] = []
        self._alive = True
        host.destroyed.connect(self._on_host_gone)

    def _on_host_gone(self) -> None:
        self._alive = False
        self._toasts.clear()

    def show(
        self,
        text: str,
        kind: str = "info",
        timeout: int = 4200,
        action_label: str = "",
        on_action: Optional[Callable[[], None]] = None,
    ) -> None:
        if not self._alive:
            return
        while len(self._toasts) >= self.MAX_VISIBLE:
            oldest = self._toasts.pop(0)
            oldest.close()
        toast = Toast(
            self.host,
            text,
            kind,
            timeout,
            action_label=action_label,
            on_action=on_action,
        )
        toast.destroyed.connect(lambda: self._forget(toast))
        self._toasts.append(toast)
        self._layout()
        toast.show()
        toast.raise_()

    def _forget(self, toast: Toast) -> None:
        if toast in self._toasts:
            self._toasts.remove(toast)
        self._layout()

    def _layout(self) -> None:
        if not self._alive:
            return
        margin = 18
        try:
            y = self.host.height() - margin
            width = self.host.width()
            for toast in reversed(self._toasts):
                y -= toast.height()
                toast.move(width - toast.width() - margin, y)
                y -= 8
        except RuntimeError:  # host or toast destroyed mid-teardown
            self._alive = False
            self._toasts.clear()

    def relayout(self) -> None:
        self._layout()


# ------------------------------------------------------- input safety wrappers
class NoWheelSpinBox(QSpinBox):
    """Scrolling a form must never change a radio parameter by accident."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setKeyboardTracking(False)

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        event.ignore()


class NoWheelComboBox(QComboBox):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        event.ignore()

    def paintEvent(self, event) -> None:  # noqa: N802, ANN001
        super().paintEvent(event)
        # The stylesheet hides the platform arrow; draw a themed chevron instead.
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        glyph = icons.pixmap("chevron", theme.color("text_faint"), 14, 2.0)
        x = self.width() - 20
        y = (self.height() - 14) / 2
        painter.drawPixmap(
            QRectF(x, y, 14, 14), glyph, QRectF(0, 0, glyph.width(), glyph.height())
        )


class CheckBox(QCheckBox):
    """Check box that shows an actual tick, not just a filled square."""

    INDICATOR = 16

    def __init__(self, text: str = "", parent: Optional[QWidget] = None):
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, event) -> None:  # noqa: N802, ANN001
        super().paintEvent(event)
        if self.checkState() == Qt.CheckState.Unchecked:
            return
        opt = QStyleOptionButton()
        self.initStyleOption(opt)
        box = self.style().subElementRect(
            QStyle.SubElement.SE_CheckBoxIndicator, opt, self
        )
        if box.isEmpty():
            box = QRect(0, (self.height() - self.INDICATOR) // 2, self.INDICATOR, self.INDICATOR)
        glyph = icons.pixmap("check", theme.color("on_primary"), 11, 2.4)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        target = QRectF(0, 0, 11, 11)
        target.moveCenter(QRectF(box).center())
        painter.drawPixmap(target, glyph, QRectF(0, 0, glyph.width(), glyph.height()))


def field_row(label: str, widget: QWidget) -> QWidget:
    """Label above control; keeps narrow panels readable."""
    holder = QWidget()
    lay = QVBoxLayout(holder)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(3)
    cap = QLabel(label)
    cap.setObjectName("StatLabel")
    lay.addWidget(cap)
    lay.addWidget(widget)
    holder.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
    return holder


class KeyValueGrid(QWidget):
    """Read-only two-column metric list with stable row widgets."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._rows: dict[str, tuple[QLabel, QLabel]] = {}
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(6)

    def add(self, key: str, label: str) -> None:
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        cap = QLabel(label)
        cap.setObjectName("Muted")
        val = QLabel("—")
        val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        val.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(cap, 1)
        lay.addWidget(val, 0)
        self._lay.addWidget(row)
        self._rows[key] = (cap, val)

    def set(self, key: str, text: str, token: str = "text") -> None:
        pair = self._rows.get(key)
        if not pair:
            return
        _, val = pair
        if val.text() != text:
            val.setText(text)
        style = f"color: {theme.color(token).name()}; font-weight: 600;"
        if val.styleSheet() != style:
            val.setStyleSheet(style)
