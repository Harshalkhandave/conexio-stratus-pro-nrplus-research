#!/usr/bin/env python3
"""Design tokens and application stylesheet.

One palette drives both the widget stylesheet and everything the canvas paints,
so light and dark stay consistent.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QColor, QFont, QFontDatabase

UI_FONT_CANDIDATES = ("Segoe UI Variable Text", "Segoe UI", "Inter", "Noto Sans")
MONO_FONT_CANDIDATES = ("Cascadia Mono", "Consolas", "JetBrains Mono", "Menlo", "Monospace")


@dataclass(frozen=True)
class Palette:
    name: str
    bg: str
    surface: str
    surface_alt: str
    surface_hover: str
    border: str
    border_strong: str
    text: str
    text_muted: str
    text_faint: str
    primary: str
    primary_hover: str
    primary_pressed: str
    on_primary: str
    success: str
    warning: str
    danger: str
    info: str
    role_source: str
    role_relay: str
    role_sink: str
    role_none: str
    canvas_bg: str
    canvas_grid: str
    link: str
    link_strong: str
    packet_direct: str
    packet_relay: str
    shadow: str
    chip_bg: str


LIGHT = Palette(
    name="light",
    bg="#F4F6F9",
    surface="#FFFFFF",
    surface_alt="#EEF1F6",
    surface_hover="#E7ECF4",
    border="#DDE3EC",
    border_strong="#C3CCDA",
    text="#111826",
    text_muted="#5A6675",
    text_faint="#8A94A6",
    primary="#2563EB",
    primary_hover="#1D4ED8",
    primary_pressed="#1A44BE",
    on_primary="#FFFFFF",
    success="#15803D",
    warning="#B45309",
    danger="#B91C1C",
    info="#0E7490",
    role_source="#2563EB",
    role_relay="#7C3AED",
    role_sink="#0F766E",
    role_none="#64748B",
    canvas_bg="#F7F9FC",
    canvas_grid="#E3E9F2",
    link="#94A3B8",
    link_strong="#334155",
    packet_direct="#16A34A",
    packet_relay="#D97706",
    shadow="#22314D",
    chip_bg="#EDF1F8",
)

DARK = Palette(
    name="dark",
    bg="#0F1420",
    surface="#161C28",
    surface_alt="#1C2432",
    surface_hover="#232D3E",
    border="#28323F",
    border_strong="#3A465A",
    text="#E8ECF4",
    text_muted="#9AA6B8",
    text_faint="#6F7C90",
    primary="#3B82F6",
    primary_hover="#2E74E8",
    primary_pressed="#2563EB",
    on_primary="#FFFFFF",
    success="#34D399",
    warning="#FBBF24",
    danger="#F87171",
    info="#22D3EE",
    role_source="#60A5FA",
    role_relay="#A78BFA",
    role_sink="#2DD4BF",
    role_none="#8494AB",
    canvas_bg="#0B111B",
    canvas_grid="#19212E",
    link="#465469",
    link_strong="#93A3B8",
    packet_direct="#34D399",
    packet_relay="#FBBF24",
    shadow="#000000",
    chip_bg="#1E2735",
)

_PALETTES = {"light": LIGHT, "dark": DARK}
_current = LIGHT


def palette() -> Palette:
    return _current


def color(token: str, alpha: int | None = None) -> QColor:
    c = QColor(getattr(_current, token))
    if alpha is not None:
        c.setAlpha(alpha)
    return c


def role_color(role: str | None) -> QColor:
    return QColor(
        {
            "source": _current.role_source,
            "relay": _current.role_relay,
            "sink": _current.role_sink,
        }.get(role or "", _current.role_none)
    )


def quality_color(quality: str) -> QColor:
    return QColor(
        {
            "excellent": _current.success,
            "good": _current.success,
            "fair": _current.warning,
            "weak": _current.danger,
        }.get(quality, _current.text_faint)
    )


def _pick(candidates: tuple[str, ...]) -> str:
    families = set(QFontDatabase.families())
    for name in candidates:
        if name in families:
            return name
    return candidates[-1]


def ui_font(size: int = 10, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    f = QFont(_pick(UI_FONT_CANDIDATES), size)
    f.setWeight(weight)
    return f


def mono_font(size: int = 9) -> QFont:
    return QFont(_pick(MONO_FONT_CANDIDATES), size)


def set_theme(app, name: str) -> Palette:  # noqa: ANN001
    """Apply a palette to the whole application."""
    global _current
    _current = _PALETTES.get(name, LIGHT)
    app.setFont(ui_font(10))
    app.setStyleSheet(stylesheet())
    return _current


def stylesheet() -> str:
    p = _current
    ui = _pick(UI_FONT_CANDIDATES)
    mono = _pick(MONO_FONT_CANDIDATES)
    return f"""
* {{ outline: none; }}

QWidget {{
    color: {p.text};
    font-family: "{ui}";
    font-size: 13px;
}}

/* Only containers own a background. Labels and tab pages stay transparent so
   they never paint a grey box on top of a card, rail or canvas. */
QMainWindow, QDialog {{ background: {p.bg}; }}
QLabel, QCheckBox, QRadioButton, QTabWidget, QTabWidget > QWidget, QTabBar,
QSplitter, QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; }}

QMainWindow::separator {{ width: 0px; height: 0px; }}

QToolTip {{
    background: {p.surface};
    color: {p.text};
    border: 1px solid {p.border_strong};
    padding: 5px 8px;
    border-radius: 6px;
}}

/* ---------------------------------------------------------------- surfaces */
QFrame#Card, QFrame#Panel {{
    background: {p.surface};
    border: 1px solid {p.border};
    border-radius: 10px;
}}
QFrame#Rail {{
    background: {p.surface};
    border: none;
    border-right: 1px solid {p.border};
}}
QFrame#TopBar {{
    background: {p.surface};
    border: none;
    border-bottom: 1px solid {p.border};
}}
QFrame#Separator {{ background: {p.border}; max-height: 1px; border: none; }}
QFrame#PortRow {{
    background: {p.surface};
    border: 1px solid {p.border};
    border-radius: 8px;
}}
QFrame#PortRow:hover {{ background: {p.surface_alt}; border-color: {p.border_strong}; }}
QFrame#Chip {{
    background: {p.chip_bg};
    border: 1px solid {p.border};
    border-radius: 999px;
}}

QLabel#H1 {{ font-size: 16px; font-weight: 600; }}
QLabel#H2 {{ font-size: 13px; font-weight: 600; }}
QLabel#SectionLabel {{
    font-size: 11px;
    font-weight: 600;
    color: {p.text_faint};
    letter-spacing: 0.8px;
}}
QLabel#Muted {{ color: {p.text_muted}; }}
QLabel#Faint {{ color: {p.text_faint}; font-size: 12px; }}
QLabel#StatValue {{ font-size: 17px; font-weight: 600; }}
QLabel#StatLabel {{ font-size: 11px; color: {p.text_faint}; letter-spacing: 0.4px; }}
QLabel#Mono {{ font-family: "{mono}"; font-size: 12px; color: {p.text_muted}; }}

/* ----------------------------------------------------------------- buttons */
QPushButton {{
    background: {p.surface};
    color: {p.text};
    border: 1px solid {p.border_strong};
    border-radius: 7px;
    padding: 6px 12px;
    font-size: 13px;
}}
QPushButton:hover {{ background: {p.surface_hover}; }}
QPushButton:pressed {{ background: {p.surface_alt}; }}
QPushButton:disabled {{
    color: {p.text_faint};
    background: {p.surface_alt};
    border-color: {p.border};
}}
QPushButton[variant="primary"] {{
    background: {p.primary};
    color: {p.on_primary};
    border: 1px solid {p.primary};
    font-weight: 600;
}}
QPushButton[variant="primary"]:hover {{ background: {p.primary_hover}; border-color: {p.primary_hover}; }}
QPushButton[variant="primary"]:pressed {{ background: {p.primary_pressed}; }}
QPushButton[variant="primary"]:disabled {{
    background: {p.surface_alt}; color: {p.text_faint}; border-color: {p.border};
}}
QPushButton[variant="danger"] {{ color: {p.danger}; border-color: {p.border_strong}; }}
QPushButton[variant="danger"]:hover {{ background: {p.surface_hover}; border-color: {p.danger}; }}
QPushButton[variant="ghost"] {{ background: transparent; border: 1px solid transparent; }}
QPushButton[variant="ghost"]:hover {{ background: {p.surface_hover}; }}
QPushButton[variant="tool"] {{
    background: transparent; border: 1px solid transparent; padding: 5px 9px;
}}
QPushButton[variant="tool"]:hover {{ background: {p.surface_hover}; border-color: {p.border}; }}
QPushButton[variant="tool"]:checked {{
    background: {p.surface_alt}; border-color: {p.border_strong};
}}

/* ------------------------------------------------------------------ inputs */
QLineEdit, QSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{
    background: {p.surface};
    border: 1px solid {p.border_strong};
    border-radius: 7px;
    padding: 5px 8px;
    selection-background-color: {p.primary};
    selection-color: {p.on_primary};
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus {{
    border-color: {p.primary};
}}
QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled {{
    background: {p.surface_alt}; color: {p.text_faint};
}}
QSpinBox::up-button, QSpinBox::down-button {{
    width: 16px; background: transparent; border: none;
}}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{
    background: {p.surface};
    border: 1px solid {p.border_strong};
    selection-background-color: {p.primary};
    selection-color: {p.on_primary};
    outline: none;
}}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{
    width: 16px; height: 16px; border-radius: 4px;
    border: 1px solid {p.border_strong}; background: {p.surface};
}}
QCheckBox::indicator:hover {{ border-color: {p.primary}; }}
QCheckBox::indicator:checked {{ background: {p.primary}; border-color: {p.primary}; }}
QCheckBox::indicator:disabled {{ background: {p.surface_alt}; border-color: {p.border}; }}

/* -------------------------------------------------------------------- tabs */
QTabWidget::pane {{ border: none; background: transparent; }}
QTabBar {{ qproperty-drawBase: 0; }}
QTabBar::tab {{
    background: transparent;
    color: {p.text_muted};
    padding: 7px 12px;
    margin-right: 2px;
    border: none;
    border-bottom: 2px solid transparent;
    font-size: 12px;
    font-weight: 600;
}}
QTabBar::tab:selected {{ color: {p.text}; border-bottom: 2px solid {p.primary}; }}
QTabBar::tab:hover:!selected {{ color: {p.text}; }}

/* ------------------------------------------------------------------- lists */
QListWidget {{
    background: transparent;
    border: none;
    outline: none;
}}
QListWidget::item {{ border-radius: 8px; margin: 2px 0px; padding: 0px; }}
QListWidget::item:selected {{ background: {p.surface_alt}; }}
QListWidget::item:hover:!selected {{ background: {p.surface_hover}; }}

/* ------------------------------------------------------------- scroll bars */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{
    background: {p.border_strong}; border-radius: 5px; min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{ background: {p.text_faint}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{
    background: {p.border_strong}; border-radius: 5px; min-width: 28px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0px; height: 0px; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QScrollArea {{ border: none; background: transparent; }}
QAbstractScrollArea::corner {{ background: transparent; border: none; }}

/* ---------------------------------------------------------------- splitter */
QSplitter::handle {{ background: {p.border}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}

/* --------------------------------------------------------------- statusbar */
QStatusBar {{
    background: {p.surface};
    border-top: 1px solid {p.border};
    color: {p.text_muted};
    font-size: 12px;
}}
QStatusBar::item {{ border: none; }}

/* ------------------------------------------------------------------- menus */
QMenu {{
    background: {p.surface};
    border: 1px solid {p.border_strong};
    border-radius: 8px;
    padding: 5px;
}}
QMenu::item {{ padding: 6px 22px 6px 12px; border-radius: 6px; }}
QMenu::item:selected {{ background: {p.surface_hover}; }}
QMenu::separator {{ height: 1px; background: {p.border}; margin: 4px 8px; }}

/* --------------------------------------------------------------- progress */
QProgressBar {{
    background: {p.surface_alt};
    border: none;
    border-radius: 3px;
    height: 6px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{ background: {p.primary}; border-radius: 3px; }}

QPlainTextEdit#Console {{
    background: {p.surface};
    border: 1px solid {p.border};
    border-radius: 10px;
    font-family: "{mono}";
    font-size: 12px;
}}

QDialog {{ background: {p.bg}; }}
"""
