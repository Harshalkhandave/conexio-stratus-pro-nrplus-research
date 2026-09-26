#!/usr/bin/env python3
"""Topology canvas.

Node cards, links and in-flight packets are persistent scene items that are
updated in place, so a 20 Hz refresh stays smooth and text never flickers.
"""

from __future__ import annotations

import math
import time
from typing import Optional

from PySide6.QtCore import QLineF, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QGraphicsDropShadowEffect,
    QGraphicsItem,
    QGraphicsObject,
    QGraphicsScene,
    QGraphicsView,
    QStyleOptionGraphicsItem,
)

from core.model import ConnState, NodeState, SessionModel
from ui import icons, theme

CARD_W = 248.0
CARD_H = 152.0
GRID = 26


def _elide(text: str, font: QFont, width: float) -> str:
    fm = QFontMetricsF(font)
    return fm.elidedText(text, Qt.TextElideMode.ElideMiddle, width)


class CardButton(QGraphicsItem):
    """Small icon button drawn inside a node card."""

    SIZE = 28.0

    def __init__(self, parent: "NodeCard", name: str, tooltip: str, on_click) -> None:  # noqa: ANN001
        super().__init__(parent)
        self._name = name
        self._on_click = on_click
        self._hover = False
        self._enabled = True
        self._tone = "text_muted"
        self._pix: Optional[QPixmap] = None
        self.setAcceptHoverEvents(True)
        self.setToolTip(tooltip)
        self.setZValue(4)

    def set_enabled(self, enabled: bool, tone: str = "text_muted") -> None:
        if enabled == self._enabled and tone == self._tone:
            return
        self._enabled = enabled
        self._tone = tone
        self._pix = None
        self.update()

    def boundingRect(self) -> QRectF:  # noqa: N802
        return QRectF(0, 0, self.SIZE, self.SIZE)

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget=None) -> None:  # noqa: ANN001
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.boundingRect().adjusted(0.5, 0.5, -0.5, -0.5)
        if self._enabled and self._hover:
            painter.setBrush(theme.color("surface_hover"))
            painter.setPen(QPen(theme.color("border_strong"), 1))
        else:
            painter.setBrush(theme.color("surface_alt"))
            painter.setPen(QPen(theme.color("border"), 1))
        painter.drawRoundedRect(rect, 7, 7)
        if self._pix is None:
            tone = self._tone if self._enabled else "text_faint"
            self._pix = icons.pixmap(self._name, theme.color(tone), 16, 2.0)
        painter.drawPixmap(
            QRectF(
                rect.center().x() - 8,
                rect.center().y() - 8,
                16,
                16,
            ),
            self._pix,
            QRectF(0, 0, self._pix.width(), self._pix.height()),
        )

    def hoverEnterEvent(self, event) -> None:  # noqa: N802, ANN001
        self._hover = True
        self.update()

    def hoverLeaveEvent(self, event) -> None:  # noqa: N802, ANN001
        self._hover = False
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802, ANN001
        if self._enabled:
            event.accept()
        else:
            event.ignore()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802, ANN001
        if self._enabled and self.boundingRect().contains(event.pos()):
            self._on_click()
        event.accept()


class NodeCard(QGraphicsObject):
    """A board rendered as a status card that can be dragged and selected."""

    def __init__(self, port: str, scene_ref: "TopologyScene") -> None:
        super().__init__()
        self.port = port
        self._scene_ref = scene_ref
        self._node: Optional[NodeState] = None
        self._busy_phase = 0.0
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setAcceptHoverEvents(True)
        self.setZValue(3)
        self.setCursor(Qt.CursorShape.OpenHandCursor)

        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(22)
        shadow.setOffset(0, 3)
        shadow_col = QColor(theme.palette().shadow)
        shadow_col.setAlpha(46)
        shadow.setColor(shadow_col)
        self.setGraphicsEffect(shadow)

        self.btn_refresh = CardButton(
            self, "refresh", "Read status from board", lambda: scene_ref.node_refresh.emit(port)
        )
        self.btn_run = CardButton(
            self, "play", "Start run on this node", lambda: scene_ref.node_run.emit(port)
        )
        self.btn_stop = CardButton(
            self, "stop", "Stop run on this node", lambda: scene_ref.node_stop.emit(port)
        )
        y = CARD_H - CardButton.SIZE - 12
        self.btn_refresh.setPos(14, y)
        self.btn_run.setPos(14 + 34, y)
        self.btn_stop.setPos(14 + 68, y)

    # ------------------------------------------------------------- geometry
    def boundingRect(self) -> QRectF:  # noqa: N802
        return QRectF(0, 0, CARD_W, CARD_H)

    def center(self) -> QPointF:
        return self.pos() + QPointF(CARD_W / 2, CARD_H / 2)

    def rect_scene(self) -> QRectF:
        return QRectF(self.pos(), self.boundingRect().size())

    # ---------------------------------------------------------------- state
    def set_node(self, node: NodeState) -> None:
        self._node = node
        online = node.online
        busy = bool(node.busy_label)
        self.btn_refresh.set_enabled(online and not busy, "primary")
        self.btn_run.set_enabled(online and not busy and not node.running, "success")
        self.btn_stop.set_enabled(online and not busy and node.running, "danger")
        self.update()

    def tick(self, dt: float) -> None:
        if self._node is not None and (self._node.busy_label or self._node.conn == ConnState.RECONNECTING):
            self._busy_phase = (self._busy_phase + dt * 300) % 360
            self.update()

    # --------------------------------------------------------------- paint
    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget=None) -> None:  # noqa: ANN001
        node = self._node
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.boundingRect().adjusted(0.5, 0.5, -0.5, -0.5)
        offline = node is None or not node.online
        role_col = theme.role_color(node.role if node else None)

        # Offline cards stay in place but read as inactive: muted fill, dashed edge.
        painter.setBrush(theme.color("surface_alt") if offline else theme.color("surface"))
        border = theme.color("border")
        width = 1.0
        style = Qt.PenStyle.SolidLine
        if self.isSelected():
            border = theme.color("primary")
            width = 2.0
        if offline:
            border = theme.color("border_strong") if not self.isSelected() else border
            style = Qt.PenStyle.DashLine
        pen = QPen(border, width, style)
        painter.setPen(pen)
        painter.drawRoundedRect(rect, 13, 13)

        # Role accent strip on the left edge.
        clip = QPainterPath()
        clip.addRoundedRect(rect, 13, 13)
        painter.save()
        painter.setClipPath(clip)
        painter.setPen(Qt.PenStyle.NoPen)
        accent = QColor(role_col)
        if node and node.conn == ConnState.RECONNECTING:
            accent = theme.color("warning")
        elif offline:
            accent = theme.color("text_faint")
        painter.setBrush(accent)
        painter.drawRect(QRectF(rect.left(), rect.top(), 4.5, rect.height()))
        painter.restore()

        if node is None:
            return

        left = rect.left() + 16
        content_w = rect.width() - 30

        # -------- header: state dot, name, role badge
        dot_col, pulse = self._state_visual(node)
        painter.setPen(Qt.PenStyle.NoPen)
        if pulse:
            halo = QColor(dot_col)
            halo.setAlpha(55)
            painter.setBrush(halo)
            painter.drawEllipse(QPointF(left + 4, rect.top() + 22), 7.5, 7.5)
        painter.setBrush(dot_col)
        painter.drawEllipse(QPointF(left + 4, rect.top() + 22), 4.0, 4.0)

        name_font = theme.ui_font(11, QFont.Weight.DemiBold)
        painter.setFont(name_font)
        painter.setPen(theme.color("text") if not offline else theme.color("text_muted"))
        badge_text = (node.role or "unassigned").upper()
        badge_font = theme.ui_font(8, QFont.Weight.DemiBold)
        badge_w = QFontMetricsF(badge_font).horizontalAdvance(badge_text) + 16
        name_w = content_w - badge_w - 26
        painter.drawText(
            QRectF(left + 16, rect.top() + 12, name_w, 20),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            _elide(node.label, name_font, name_w),
        )

        badge_rect = QRectF(rect.right() - 14 - badge_w, rect.top() + 13, badge_w, 18)
        bg = QColor(role_col if not offline else theme.palette().text_faint)
        bg.setAlpha(40)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bg)
        painter.drawRoundedRect(badge_rect, 9, 9)
        painter.setFont(badge_font)
        painter.setPen(role_col if not offline else theme.color("text_faint"))
        painter.drawText(badge_rect, int(Qt.AlignmentFlag.AlignCenter), badge_text)

        # -------- transport line
        sub_font = theme.ui_font(8)
        painter.setFont(sub_font)
        painter.setPen(theme.color("text_faint"))
        transport = node.port if "://" not in node.port else node.port.split("://", 1)[1]
        parts = [] if transport == node.label else [transport]
        if node.device_id is not None:
            parts.append(f"id {node.device_id}")
        subtitle = "  ·  ".join(parts) or "waiting for status"
        painter.drawText(
            QRectF(left + 16, rect.top() + 30, content_w - 16, 14),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            _elide(subtitle, sub_font, content_w - 16),
        )

        painter.setPen(QPen(theme.color("border"), 1))
        painter.drawLine(QPointF(left, rect.top() + 50), QPointF(rect.right() - 14, rect.top() + 50))

        # -------- metrics: three columns
        rssi = node.live_rssi()
        cells = [
            ("RSSI", f"{rssi:.0f} dBm" if rssi is not None else "—",
             self._rssi_token(rssi)),
            ("HOPS", "—" if node.hop_count is None else str(node.hop_count), "text"),
            ("DEST", "—" if not node.dest_id else str(node.dest_id), "text"),
        ]
        col_w = (rect.width() - 30) / 3
        label_font = theme.ui_font(7, QFont.Weight.DemiBold)
        value_font = theme.ui_font(10, QFont.Weight.DemiBold)
        for i, (label, value, token) in enumerate(cells):
            x = left + i * col_w
            painter.setFont(label_font)
            painter.setPen(theme.color("text_faint"))
            painter.drawText(
                QRectF(x, rect.top() + 56, col_w, 12),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                label,
            )
            painter.setFont(value_font)
            painter.setPen(theme.color(token if not offline else "text_faint"))
            painter.drawText(
                QRectF(x, rect.top() + 68, col_w, 16),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                value,
            )

        # -------- counters
        counters = f"TX {node.tx_count}   FWD {node.fwd_count}   RX {node.rx_ok}   DEL {node.deliver_count}"
        counter_font = theme.ui_font(8)
        painter.setFont(counter_font)
        painter.setPen(theme.color("text_muted"))
        painter.drawText(
            QRectF(left, rect.top() + 90, content_w, 14),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            _elide(counters, counter_font, content_w),
        )

        # -------- footer: status text or busy spinner, right aligned
        status_font = theme.ui_font(8, QFont.Weight.DemiBold)
        painter.setFont(status_font)
        if node.busy_label or node.conn == ConnState.RECONNECTING:
            spinner_token = "warning" if node.conn == ConnState.RECONNECTING else "primary"
            painter.setPen(theme.color(spinner_token))
            text = node.busy_label or "Reconnecting..."
            arc_rect = QRectF(rect.right() - 26, CARD_H - 34, 13, 13)
            pen = QPen(theme.color(spinner_token), 2.0)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawArc(arc_rect, int(-self._busy_phase * 16), 110 * 16)
            painter.setPen(theme.color(spinner_token))
            painter.drawText(
                QRectF(left + 96, CARD_H - 40, content_w - 122, 24),
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                _elide(text, status_font, content_w - 122),
            )
        else:
            text = node.error_msg or node.state_text()
            token = "danger" if node.conn == ConnState.ERROR else (
                "success" if node.running else "text_muted"
            )
            painter.setPen(theme.color(token))
            painter.drawText(
                QRectF(left + 96, CARD_H - 40, content_w - 96, 24),
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                _elide(text, status_font, content_w - 96),
            )

    def _state_visual(self, node: NodeState) -> tuple[QColor, bool]:
        if node.conn == ConnState.ERROR:
            return theme.color("danger"), False
        if node.conn == ConnState.RECONNECTING:
            return theme.color("warning"), True
        if node.conn == ConnState.DISCONNECTED:
            return theme.color("text_faint"), False
        if node.running:
            return theme.color("success"), True
        return theme.color("info"), False

    def _rssi_token(self, rssi: Optional[float]) -> str:
        if rssi is None:
            return "text_faint"
        if rssi >= -75:
            return "success"
        if rssi >= -90:
            return "warning"
        return "danger"

    # --------------------------------------------------------------- events
    def itemChange(self, change, value):  # noqa: N802, ANN001
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            self._scene_ref.node_moved.emit(self.port, self.pos())
        return super().itemChange(change, value)

    def mousePressEvent(self, event) -> None:  # noqa: N802, ANN001
        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        self._scene_ref.node_selected.emit(self.port)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802, ANN001
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802, ANN001
        self._scene_ref.node_renamed.emit(self.port)
        event.accept()


class EdgeItem(QGraphicsItem):
    """A radio link drawn as a soft curve with an RSSI chip at its midpoint."""

    def __init__(self) -> None:
        super().__init__()
        self.setZValue(1)
        self._path = QPainterPath()
        self._label = ""
        self._color = theme.color("link")
        self._width = 2.0
        self._mid = QPointF()
        self._show_label = True
        self._active = False

    def configure(
        self,
        a: QPointF,
        b: QPointF,
        color: QColor,
        width: float,
        label: str,
        show_label: bool,
        active: bool,
    ) -> None:
        line = QLineF(a, b)
        normal = line.normalVector().unitVector()
        bow = min(34.0, line.length() * 0.14)
        ctrl = QPointF(
            (a.x() + b.x()) / 2 + (normal.dx() * bow),
            (a.y() + b.y()) / 2 + (normal.dy() * bow),
        )
        path = QPainterPath(a)
        path.quadTo(ctrl, b)
        self.prepareGeometryChange()
        self._path = path
        self._mid = path.pointAtPercent(0.5)
        self._color = color
        self._width = width
        self._label = label
        self._show_label = show_label
        self._active = active
        self.update()

    def path(self) -> QPainterPath:
        return self._path

    def boundingRect(self) -> QRectF:  # noqa: N802
        return self._path.boundingRect().adjusted(-40, -24, 40, 24)

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget=None) -> None:  # noqa: ANN001
        if self._path.isEmpty():
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._active:
            glow = QColor(self._color)
            glow.setAlpha(52)
            painter.setPen(QPen(glow, self._width + 6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawPath(self._path)
        pen = QPen(self._color, self._width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(self._path)

        if not self._show_label or not self._label:
            return
        font = theme.ui_font(8, QFont.Weight.DemiBold)
        painter.setFont(font)
        fm = QFontMetricsF(font)
        w = fm.horizontalAdvance(self._label) + 14
        chip = QRectF(self._mid.x() - w / 2, self._mid.y() - 10, w, 19)
        painter.setPen(QPen(theme.color("border"), 1))
        painter.setBrush(theme.color("surface"))
        painter.drawRoundedRect(chip, 9, 9)
        painter.setPen(self._color)
        painter.drawText(chip, int(Qt.AlignmentFlag.AlignCenter), self._label)


class PacketItem(QGraphicsItem):
    """A packet in flight; drawn above links but under the node cards."""

    R = 6.0

    def __init__(self) -> None:
        super().__init__()
        self.setZValue(2)
        self._color = theme.color("packet_direct")

    def set_color(self, color: QColor) -> None:
        self._color = color
        self.update()

    def boundingRect(self) -> QRectF:  # noqa: N802
        r = self.R + 6
        return QRectF(-r, -r, 2 * r, 2 * r)

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget=None) -> None:  # noqa: ANN001
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        halo = QColor(self._color)
        halo.setAlpha(70)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(halo)
        painter.drawEllipse(QPointF(0, 0), self.R + 4, self.R + 4)
        painter.setBrush(self._color)
        painter.drawEllipse(QPointF(0, 0), self.R, self.R)
        painter.setPen(QPen(theme.color("surface"), 1.4))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPointF(0, 0), self.R, self.R)


class TopologyScene(QGraphicsScene):
    node_moved = Signal(str, QPointF)
    node_selected = Signal(str)
    node_refresh = Signal(str)
    node_run = Signal(str)
    node_stop = Signal(str)
    node_renamed = Signal(str)
    background_clicked = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setSceneRect(0, 0, 1200, 700)
        self.cards: dict[str, NodeCard] = {}
        self._edges: dict[tuple[int, int], EdgeItem] = {}
        self._packets: list[PacketItem] = []
        self.show_rssi_labels = True
        self.animate = True

    # -------------------------------------------------------------- painting
    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:  # noqa: N802
        painter.fillRect(rect, theme.color("canvas_bg"))
        painter.setPen(QPen(theme.color("canvas_grid"), 1))
        left = int(rect.left()) - (int(rect.left()) % GRID)
        top = int(rect.top()) - (int(rect.top()) % GRID)
        points = []
        y = top
        while y < rect.bottom():
            x = left
            while x < rect.right():
                points.append(QPointF(x, y))
                x += GRID
            y += GRID
        painter.drawPoints(points)

    # ------------------------------------------------------------------ sync
    def sync(self, model: SessionModel, dt: float) -> None:
        for port in list(self.cards.keys()):
            if port not in model.nodes:
                card = self.cards.pop(port)
                self.removeItem(card)

        for port, node in model.nodes.items():
            card = self.cards.get(port)
            if card is None:
                card = NodeCard(port, self)
                card.setPos(node.x, node.y)
                self.addItem(card)
                self.cards[port] = card
            elif not card.isUnderMouse():
                if abs(card.pos().x() - node.x) > 0.5 or abs(card.pos().y() - node.y) > 0.5:
                    card.setPos(node.x, node.y)
            card.set_node(node)
            card.tick(dt)

        self._sync_edges(model)
        self._sync_packets(model)

    def _anchor(self, card: NodeCard, toward: QPointF) -> QPointF:
        """Point on the card border facing `toward`, so lines never run under cards."""
        rect = card.rect_scene()
        c = rect.center()
        dx = toward.x() - c.x()
        dy = toward.y() - c.y()
        if dx == 0 and dy == 0:
            return c
        hw, hh = rect.width() / 2 + 3, rect.height() / 2 + 3
        scale = min(
            hw / abs(dx) if dx else float("inf"),
            hh / abs(dy) if dy else float("inf"),
        )
        return QPointF(c.x() + dx * scale, c.y() + dy * scale)

    def _sync_edges(self, model: SessionModel) -> None:
        live: set[tuple[int, int]] = set()
        for key, link in model.links.items():
            a = model.node_by_id(link.a_id)
            b = model.node_by_id(link.b_id)
            if a is None or b is None:
                continue
            ca, cb = self.cards.get(a.port), self.cards.get(b.port)
            if ca is None or cb is None:
                continue
            edge = self._edges.get(key)
            if edge is None:
                edge = EdgeItem()
                self.addItem(edge)
                self._edges[key] = edge
            pa = self._anchor(ca, cb.center())
            pb = self._anchor(cb, ca.center())
            color = theme.quality_color(link.quality)
            if link.rssi is None:
                color = theme.color("link")
            width = 2.0 if link.rssi is None else (
                3.4 if link.quality in ("excellent", "good") else 2.6
            )
            label = f"{link.rssi:.0f} dBm" if link.rssi is not None else ""
            edge.configure(
                pa, pb, color, width, label, self.show_rssi_labels, link.packets > 0
            )
            live.add(key)

        for key in list(self._edges.keys()):
            if key not in live:
                self.removeItem(self._edges.pop(key))

    def _sync_packets(self, model: SessionModel) -> None:
        if not self.animate:
            for item in self._packets:
                item.setVisible(False)
            return
        now = time.monotonic()
        active: list[tuple[QPointF, QColor]] = []
        for anim in model.anims:
            pts: list[QPointF] = []
            for wid in anim.waypoints:
                node = model.node_by_id(wid)
                card = self.cards.get(node.port) if node else None
                if card is not None:
                    pts.append(card.center())
            if len(pts) < 2:
                continue
            frac = min(1.0, max(0.0, (now - anim.t0) / anim.duration))
            pos = self._along(pts, frac)
            color = theme.color("packet_relay") if (anim.hops or 0) >= 1 else theme.color(
                "packet_direct"
            )
            active.append((pos, color))

        while len(self._packets) < len(active):
            item = PacketItem()
            self.addItem(item)
            self._packets.append(item)
        for idx, item in enumerate(self._packets):
            if idx < len(active):
                pos, color = active[idx]
                item.setPos(pos)
                item.set_color(color)
                item.setVisible(True)
            else:
                item.setVisible(False)

    @staticmethod
    def _along(pts: list[QPointF], frac: float) -> QPointF:
        segs = []
        total = 0.0
        for i in range(len(pts) - 1):
            d = math.hypot(pts[i + 1].x() - pts[i].x(), pts[i + 1].y() - pts[i].y())
            segs.append(d)
            total += d
        if total <= 0:
            return pts[0]
        dist = frac * total
        for i, d in enumerate(segs):
            if dist <= d or i == len(segs) - 1:
                t = 0.0 if d == 0 else min(1.0, dist / d)
                return QPointF(
                    pts[i].x() + (pts[i + 1].x() - pts[i].x()) * t,
                    pts[i].y() + (pts[i + 1].y() - pts[i].y()) * t,
                )
            dist -= d
        return pts[-1]

    def mousePressEvent(self, event) -> None:  # noqa: N802, ANN001
        item = self.itemAt(event.scenePos(), self.views()[0].transform() if self.views() else None)
        if item is None:
            self.background_clicked.emit()
        super().mousePressEvent(event)


class TopologyCanvas(QGraphicsView):
    node_selected = Signal(str)
    node_moved = Signal(str, float, float)
    node_refresh = Signal(str)
    node_run = Signal(str)
    node_stop = Signal(str)
    node_renamed = Signal(str)
    selection_cleared = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._scene = TopologyScene()
        self.setScene(self._scene)
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing
        )
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.SmartViewportUpdate)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setMinimumSize(560, 380)
        self._last_tick = time.monotonic()
        self._zoom = 1.0

        self._scene.node_selected.connect(self.node_selected)
        self._scene.node_moved.connect(
            lambda port, pos: self.node_moved.emit(port, pos.x(), pos.y())
        )
        self._scene.node_refresh.connect(self.node_refresh)
        self._scene.node_run.connect(self.node_run)
        self._scene.node_stop.connect(self.node_stop)
        self._scene.node_renamed.connect(self.node_renamed)
        self._scene.background_clicked.connect(self.selection_cleared)

    # --------------------------------------------------------------- options
    def set_options(self, rssi_labels: bool, animate: bool) -> None:
        self._scene.show_rssi_labels = rssi_labels
        self._scene.animate = animate

    # ------------------------------------------------------------------ sync
    def sync(self, model: SessionModel) -> None:
        now = time.monotonic()
        dt = now - self._last_tick
        self._last_tick = now
        self._scene.sync(model, dt)
        self._update_scene_rect()

    def _update_scene_rect(self) -> None:
        """Keep the scrollable area just big enough: no phantom scrollbars."""
        cards = list(self._scene.cards.values())
        if not cards:
            return
        rect = cards[0].rect_scene()
        for card in cards[1:]:
            rect = rect.united(card.rect_scene())
        rect = rect.adjusted(-90, -70, 90, 70)
        # Derive the view extent in scene coordinates from the viewport pixel
        # size and the current transform — NOT from mapToScene, which depends
        # on the scene rect and creates a feedback loop when scroll-bar
        # visibility toggles the viewport size each frame.
        vp = self.viewport().size()
        sx = self.transform().m11() or 1.0
        sy = self.transform().m22() or 1.0
        view_w = vp.width() / sx
        view_h = vp.height() / sy
        if rect.width() < view_w:
            pad = (view_w - rect.width()) / 2
            rect.adjust(-pad, 0, pad, 0)
        if rect.height() < view_h:
            pad = (view_h - rect.height()) / 2
            rect.adjust(0, -pad, 0, pad)
        old = self._scene.sceneRect()
        # Only update when the change exceeds a small threshold to prevent
        # sub-pixel oscillation between frames.
        if (abs(rect.x() - old.x()) > 2 or abs(rect.y() - old.y()) > 2 or
                abs(rect.width() - old.width()) > 2 or abs(rect.height() - old.height()) > 2):
            self._scene.setSceneRect(rect)

    def select(self, port: Optional[str]) -> None:
        for key, card in self._scene.cards.items():
            card.setSelected(key == port)

    # ---------------------------------------------------------------- layout
    def auto_layout(self, model: SessionModel) -> None:
        """Arrange source → relay → sink so the data path reads left to right."""
        ports = model.ordered_ports()
        by_role: dict[str, list[str]] = {}
        for port in ports:
            by_role.setdefault(model.nodes[port].role or "unassigned", []).append(port)

        slots: list[tuple[str, float, float]] = []
        lanes = ("source", "relay", "sink", "unassigned")
        x = 40.0
        for role in lanes:
            group = by_role.get(role, [])
            for idx, port in enumerate(group):
                y = 60.0 + idx * (CARD_H + 40)
                if role == "relay":
                    y -= 120.0
                slots.append((port, x, max(0.0, y)))
            if group:
                x += CARD_W + 110
        for port, px, py in slots:
            node = model.nodes[port]
            node.x, node.y = px, py
            card = self._scene.cards.get(port)
            if card is not None:
                card.setPos(px, py)
        self.fit()

    def fit(self) -> None:
        items = [c for c in self._scene.cards.values()]
        if not items:
            self.resetTransform()
            self._zoom = 1.0
            return
        rect = items[0].rect_scene()
        for card in items[1:]:
            rect = rect.united(card.rect_scene())
        # Slightly wider than the scene margin so fitting never leaves scrollbars.
        rect = rect.adjusted(-120, -100, 120, 100)
        self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
        self._zoom = self.transform().m11()
        if self._zoom > 1.0:  # never blow cards up beyond 1:1
            self.resetTransform()
            self.centerOn(rect.center())
            self._zoom = 1.0

    def zoom_by(self, factor: float) -> None:
        target = max(0.35, min(2.2, self._zoom * factor))
        factor = target / self._zoom
        self._zoom = target
        self.scale(factor, factor)

    def reset_zoom(self) -> None:
        self.resetTransform()
        self._zoom = 1.0

    # ---------------------------------------------------------------- events
    def wheelEvent(self, event) -> None:  # noqa: N802, ANN001
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.zoom_by(1.15 if event.angleDelta().y() > 0 else 1 / 1.15)
            event.accept()
            return
        super().wheelEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802, ANN001
        if event.button() == Qt.MouseButton.MiddleButton:
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802, ANN001
        super().mouseReleaseEvent(event)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
