#!/usr/bin/env python3
"""Vector icons painted at runtime.

Keeping icons in code avoids shipping binary assets and lets every glyph follow
the active theme colour.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

from ui import theme

_CACHE: dict[tuple, QIcon] = {}
BOX = 24.0


def _stroke(painter: QPainter, col: QColor, width: float = 2.0) -> None:
    pen = QPen(col, width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)


def _arrow_arc(p: QPainter, c: QColor, start: float, sweep: float, radius: float = 7.4) -> None:
    """Circular arrow: arc plus a head tangent to its starting point."""
    _stroke(p, c)
    rect = QRectF(12 - radius, 12 - radius, 2 * radius, 2 * radius)
    path = QPainterPath()
    path.arcMoveTo(rect, start)
    path.arcTo(rect, start, sweep)
    p.drawPath(path)

    a = math.radians(start)
    sx, sy = 12 + radius * math.cos(a), 12 - radius * math.sin(a)
    direction = 1.0 if sweep < 0 else -1.0
    tx, ty = math.sin(a) * direction, math.cos(a) * direction
    px, py = -ty, tx
    head = QPainterPath(QPointF(sx + tx * 5.2, sy + ty * 5.2))
    head.lineTo(QPointF(sx + px * 3.5, sy + py * 3.5))
    head.lineTo(QPointF(sx - px * 3.5, sy - py * 3.5))
    head.closeSubpath()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    p.drawPath(head)


def _refresh(p: QPainter, c: QColor) -> None:
    _arrow_arc(p, c, start=70.0, sweep=-285.0)


def _play(p: QPainter, c: QColor) -> None:
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    path = QPainterPath()
    path.moveTo(8.5, 5.5)
    path.lineTo(19.0, 12.0)
    path.lineTo(8.5, 18.5)
    path.closeSubpath()
    p.drawPath(path)


def _stop(p: QPainter, c: QColor) -> None:
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    p.drawRoundedRect(QRectF(7, 7, 10, 10), 2, 2)


def _plus(p: QPainter, c: QColor) -> None:
    _stroke(p, c, 2.2)
    p.drawLine(QPointF(12, 5.5), QPointF(12, 18.5))
    p.drawLine(QPointF(5.5, 12), QPointF(18.5, 12))


def _close(p: QPainter, c: QColor) -> None:
    _stroke(p, c, 2.2)
    p.drawLine(QPointF(6.5, 6.5), QPointF(17.5, 17.5))
    p.drawLine(QPointF(17.5, 6.5), QPointF(6.5, 17.5))


def _check(p: QPainter, c: QColor) -> None:
    _stroke(p, c, 2.4)
    p.drawPolyline([QPointF(5, 12.8), QPointF(9.8, 17.5), QPointF(19, 6.8)])


def _power(p: QPainter, c: QColor) -> None:
    _stroke(p, c)
    rect = QRectF(4.5, 4.5, 15, 15)
    path = QPainterPath()
    path.arcMoveTo(rect, 118)
    path.arcTo(rect, 118, 304)
    p.drawPath(path)
    p.drawLine(QPointF(12, 3.2), QPointF(12, 10.5))


def _plug(p: QPainter, c: QColor) -> None:
    _stroke(p, c)
    p.drawRoundedRect(QRectF(8, 9, 8, 8), 2, 2)
    p.drawLine(QPointF(10, 9), QPointF(10, 4.5))
    p.drawLine(QPointF(14, 9), QPointF(14, 4.5))
    p.drawLine(QPointF(12, 17), QPointF(12, 20))


def _trash(p: QPainter, c: QColor) -> None:
    _stroke(p, c)
    p.drawLine(QPointF(4.5, 7), QPointF(19.5, 7))
    p.drawLine(QPointF(9.5, 7), QPointF(10.2, 4.6))
    p.drawLine(QPointF(14.5, 7), QPointF(13.8, 4.6))
    path = QPainterPath()
    path.moveTo(6.6, 7)
    path.lineTo(7.7, 19.4)
    path.lineTo(16.3, 19.4)
    path.lineTo(17.4, 7)
    p.drawPath(path)
    p.drawLine(QPointF(10.4, 10), QPointF(10.8, 16.6))
    p.drawLine(QPointF(13.6, 10), QPointF(13.2, 16.6))


def _save(p: QPainter, c: QColor) -> None:
    _stroke(p, c)
    p.drawLine(QPointF(12, 3.6), QPointF(12, 13.6))
    p.drawPolyline([QPointF(8, 10), QPointF(12, 14.2), QPointF(16, 10)])
    p.drawPolyline([QPointF(4.6, 17), QPointF(4.6, 20), QPointF(19.4, 20), QPointF(19.4, 17)])


def _load(p: QPainter, c: QColor) -> None:
    _stroke(p, c)
    p.drawLine(QPointF(12, 20.4), QPointF(12, 10.4))
    p.drawPolyline([QPointF(8, 14), QPointF(12, 9.8), QPointF(16, 14)])
    p.drawPolyline([QPointF(4.6, 7), QPointF(4.6, 4), QPointF(19.4, 4), QPointF(19.4, 7)])


def _factory(p: QPainter, c: QColor) -> None:
    _arrow_arc(p, c, start=110.0, sweep=285.0)


def _record(p: QPainter, c: QColor) -> None:
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    p.drawEllipse(QRectF(6.5, 6.5, 11, 11))


def _camera(p: QPainter, c: QColor) -> None:
    _stroke(p, c)
    p.drawRoundedRect(QRectF(3.5, 7, 17, 12.5), 3, 3)
    p.drawLine(QPointF(9, 7), QPointF(10.4, 4.6))
    p.drawLine(QPointF(15, 7), QPointF(13.6, 4.6))
    p.drawEllipse(QRectF(9.2, 9.6, 5.6, 5.6))


def _gear(p: QPainter, c: QColor) -> None:
    _stroke(p, c, 1.8)
    p.drawEllipse(QRectF(9, 9, 6, 6))
    p.drawEllipse(QRectF(4.6, 4.6, 14.8, 14.8))
    for angle in range(0, 360, 45):
        path = QPainterPath()
        path.moveTo(12, 12)
        p.save()
        p.translate(12, 12)
        p.rotate(angle)
        p.drawLine(QPointF(7.4, 0), QPointF(9.6, 0))
        p.restore()


def _sun(p: QPainter, c: QColor) -> None:
    _stroke(p, c)
    p.drawEllipse(QRectF(8.4, 8.4, 7.2, 7.2))
    for angle in range(0, 360, 45):
        p.save()
        p.translate(12, 12)
        p.rotate(angle)
        p.drawLine(QPointF(8.6, 0), QPointF(10.6, 0))
        p.restore()


def _moon(p: QPainter, c: QColor) -> None:
    _stroke(p, c)
    path = QPainterPath()
    path.moveTo(17.4, 15.6)
    path.arcTo(QRectF(4, 3.4, 17, 17), 25, 200)
    path.arcTo(QRectF(8.6, 3.4, 15, 15), 205, -160)
    p.drawPath(path)


def _fit(p: QPainter, c: QColor) -> None:
    _stroke(p, c)
    for sx, sy in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
        cx = 12 + sx * 7.5
        cy = 12 + sy * 7.5
        p.drawLine(QPointF(cx, cy), QPointF(cx - sx * 4, cy))
        p.drawLine(QPointF(cx, cy), QPointF(cx, cy - sy * 4))


def _topology(p: QPainter, c: QColor) -> None:
    _stroke(p, c, 1.8)
    p.drawLine(QPointF(6.5, 8), QPointF(17.5, 8))
    p.drawLine(QPointF(6.5, 8), QPointF(12, 17.5))
    p.drawLine(QPointF(17.5, 8), QPointF(12, 17.5))
    p.setBrush(theme.color("surface"))
    for pt in (QPointF(6.5, 8), QPointF(17.5, 8), QPointF(12, 17.5)):
        p.drawEllipse(pt, 3.0, 3.0)


def _warning(p: QPainter, c: QColor) -> None:
    _stroke(p, c)
    path = QPainterPath()
    path.moveTo(12, 4)
    path.lineTo(20.5, 19.4)
    path.lineTo(3.5, 19.4)
    path.closeSubpath()
    p.drawPath(path)
    p.drawLine(QPointF(12, 9.6), QPointF(12, 14.2))
    p.setBrush(c)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(QPointF(12, 16.8), 1.1, 1.1)


def _info(p: QPainter, c: QColor) -> None:
    _stroke(p, c)
    p.drawEllipse(QRectF(4.2, 4.2, 15.6, 15.6))
    p.drawLine(QPointF(12, 11), QPointF(12, 16.6))
    p.setBrush(c)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(QPointF(12, 7.9), 1.1, 1.1)


def _search(p: QPainter, c: QColor) -> None:
    _stroke(p, c)
    p.drawEllipse(QRectF(4.6, 4.6, 11.2, 11.2))
    p.drawLine(QPointF(15.4, 15.4), QPointF(19.6, 19.6))


def _copy(p: QPainter, c: QColor) -> None:
    _stroke(p, c)
    p.drawRoundedRect(QRectF(8.4, 8.4, 11, 11), 2.5, 2.5)
    path = QPainterPath()
    path.moveTo(6, 15.4)
    path.lineTo(4.6, 15.4)
    path.lineTo(4.6, 4.6)
    path.lineTo(15.4, 4.6)
    path.lineTo(15.4, 6)
    p.drawPath(path)


def _chevron(p: QPainter, c: QColor) -> None:
    _stroke(p, c, 2.2)
    p.drawPolyline([QPointF(7, 10), QPointF(12, 15), QPointF(17, 10)])


def _pause(p: QPainter, c: QColor) -> None:
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    p.drawRoundedRect(QRectF(7.5, 6.5, 3.4, 11), 1.4, 1.4)
    p.drawRoundedRect(QRectF(13.1, 6.5, 3.4, 11), 1.4, 1.4)


_PAINTERS = {
    "refresh": _refresh,
    "play": _play,
    "stop": _stop,
    "plus": _plus,
    "close": _close,
    "check": _check,
    "power": _power,
    "plug": _plug,
    "trash": _trash,
    "save": _save,
    "load": _load,
    "factory": _factory,
    "record": _record,
    "camera": _camera,
    "gear": _gear,
    "sun": _sun,
    "moon": _moon,
    "fit": _fit,
    "topology": _topology,
    "warning": _warning,
    "info": _info,
    "search": _search,
    "copy": _copy,
    "chevron": _chevron,
    "pause": _pause,
}


def pixmap(name: str, col: QColor, size: int = 20, ratio: float = 1.0) -> QPixmap:
    px = QPixmap(int(size * ratio), int(size * ratio))
    px.setDevicePixelRatio(ratio)
    px.fill(Qt.GlobalColor.transparent)
    painter = QPainter(px)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(size / BOX, size / BOX)
    fn = _PAINTERS.get(name)
    if fn is not None:
        fn(painter, col)
    painter.end()
    return px


def icon(name: str, token: str = "text", size: int = 20) -> QIcon:
    """Themed icon; `token` is a palette field name or a #rrggbb string."""
    col = QColor(token) if token.startswith("#") else theme.color(token)
    key = (name, col.name(), size, theme.palette().name)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached
    ic = QIcon()
    ic.addPixmap(pixmap(name, col, size, 2.0))
    disabled = QColor(theme.palette().text_faint)
    ic.addPixmap(pixmap(name, disabled, size, 2.0), QIcon.Mode.Disabled)
    _CACHE[key] = ic
    return ic


def clear_cache() -> None:
    _CACHE.clear()
