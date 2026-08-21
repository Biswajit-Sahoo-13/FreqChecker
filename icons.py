"""
icons.py - Vector SVG icon renderer for FreqChecker.

All icon geometry is original artwork drawn for this project, styled to
resemble the general visual language of FxSound (circular power glyph,
hamburger menu, flip arrows, thin window controls). No assets are copied.
Icons are rendered to QIcon/QPixmap at any size and DPI via QSvgRenderer.
"""

from typing import Dict, Optional
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor
from PySide6.QtCore import QByteArray, QSize


def _stroke(paths: str, width: float = 2.0) -> str:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        f'stroke="currentColor" stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round">'
        f"{paths}</svg>"
    )


def _fill(paths: str) -> str:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
        f'fill="currentColor" stroke="none">{paths}</svg>'
    )


SVG_ICONS: Dict[str, str] = {
    # Brand mark: three rounded playback bars of differing height (original)
    "logo-bars": _fill(
        '<rect x="3.5" y="9" width="3.4" height="6" rx="1.7"/>'
        '<rect x="10.3" y="4.5" width="3.4" height="15" rx="1.7"/>'
        '<rect x="17.1" y="8" width="3.4" height="8" rx="1.7"/>'
    ),

    # Power glyph: arc + vertical line inside a circle (original geometry)
    "power": _stroke(
        '<circle cx="12" cy="12" r="9.2"/>'
        '<line x1="12" y1="6.5" x2="12" y2="12"/>'
        '<path d="M 8.2 8.6 A 5.4 5.4 0 1 0 15.8 8.6"/>',
        1.9,
    ),
    "power-off": _stroke(
        '<circle cx="12" cy="12" r="9.2"/>'
        '<line x1="12" y1="7" x2="12" y2="11.4"/>'
        '<path d="M 8.2 8.6 A 5.4 5.4 0 1 0 15.8 8.6"/>',
        1.9,
    ),

    # Window controls (thin line style)
    "minimize": _stroke('<line x1="6" y1="12" x2="18" y2="12"/>', 2.0),
    "close": _stroke(
        '<line x1="7" y1="7" x2="17" y2="17"/><line x1="17" y1="7" x2="7" y2="17"/>', 2.0
    ),
    "maximize": _stroke('<rect x="6.5" y="6.5" width="11" height="11" rx="1.5"/>', 2.0),
    "fullscreen": _stroke(
        '<polyline points="15 3 21 3 21 9"/><polyline points="9 21 3 21 3 15"/>'
        '<line x1="21" y1="3" x2="14" y2="10"/><line x1="3" y1="21" x2="10" y2="14"/>',
        2.0,
    ),
    "fullscreen-exit": _stroke(
        '<polyline points="4 14 4 21 11 21"/><polyline points="20 10 20 3 13 3"/>'
        '<line x1="4" y1="21" x2="11" y2="14"/><line x1="20" y1="3" x2="13" y2="10"/>',
        2.0,
    ),

    # Hamburger menu
    "menu": _stroke(
        '<line x1="4.5" y1="7" x2="19.5" y2="7"/>'
        '<line x1="4.5" y1="12" x2="19.5" y2="12"/>'
        '<line x1="4.5" y1="17" x2="19.5" y2="17"/>',
        2.0,
    ),

    # Flip / swap views: two opposing arrows (original)
    "flip": _stroke(
        '<polyline points="8 5 5 8 8 11"/>'
        '<line x1="5" y1="8" x2="14" y2="8"/>'
        '<polyline points="16 13 19 16 16 19"/>'
        '<line x1="19" y1="16" x2="10" y2="16"/>',
        2.0,
    ),

    # Theme
    "moon": _stroke('<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>'),
    "sun": _stroke(
        '<circle cx="12" cy="12" r="5"/>'
        '<line x1="12" y1="1.5" x2="12" y2="3.5"/><line x1="12" y1="20.5" x2="12" y2="22.5"/>'
        '<line x1="4.05" y1="4.05" x2="5.46" y2="5.46"/><line x1="18.54" y1="18.54" x2="19.95" y2="19.95"/>'
        '<line x1="1.5" y1="12" x2="3.5" y2="12"/><line x1="20.5" y1="12" x2="22.5" y2="12"/>'
        '<line x1="4.05" y1="19.95" x2="5.46" y2="18.54"/><line x1="18.54" y1="5.46" x2="19.95" y2="4.05"/>'
    ),

    # Playback controls
    "play": _fill('<polygon points="7 4.5 20 12 7 19.5 7 4.5"/>'),
    "pause": _fill(
        '<rect x="6.5" y="4.5" width="3.8" height="15" rx="1.2"/>'
        '<rect x="13.7" y="4.5" width="3.8" height="15" rx="1.2"/>'
    ),
    "stop": _fill('<rect x="6" y="6" width="12" height="12" rx="2"/>'),
    "rotate-ccw": _stroke(
        '<polyline points="2.5 4.5 2.5 10 8 10"/>'
        '<path d="M4.08 15a8.5 8.5 0 1 0 1.9-8.83L2.5 10"/>'
    ),
    "volume-2": _stroke(
        '<polygon points="11 5 6.5 9 3 9 3 15 6.5 15 11 19 11 5"/>'
        '<path d="M18.5 5.5a9.2 9.2 0 0 1 0 13M15.2 8.8a4.6 4.6 0 0 1 0 6.4"/>'
    ),

    # Actions & status
    "zap": _fill('<polygon points="13 2 4 14 11.5 14 10.8 22 20 10 12.5 10 13 2"/>'),
    "check": _stroke('<polyline points="20 6.5 9.5 17 4 12"/>', 2.6),
    "x": _stroke(
        '<line x1="6.5" y1="6.5" x2="17.5" y2="17.5"/>'
        '<line x1="17.5" y1="6.5" x2="6.5" y2="17.5"/>',
        2.6,
    ),

    # Files & navigation
    "folder": _stroke(
        '<path d="M22 18.5a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h4.5l2 3H20a2 2 0 0 1 2 2z"/>'
    ),
    "download": _stroke(
        '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>'
        '<polyline points="7 10.5 12 15.5 17 10.5"/><line x1="12" y1="15" x2="12" y2="3.5"/>'
    ),
    "file-text": _stroke(
        '<path d="M14 2.5H6.5a2 2 0 0 0-2 2v15a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2V8z"/>'
        '<polyline points="14 2.5 14 8 19.5 8"/>'
        '<line x1="8.5" y1="13" x2="15.5" y2="13"/><line x1="8.5" y1="17" x2="15.5" y2="17"/>'
    ),
    "arrow-left": _stroke(
        '<line x1="19" y1="12" x2="5" y2="12"/><polyline points="11.5 5.5 5 12 11.5 18.5"/>'
    ),
    "arrow-right": _stroke(
        '<line x1="5" y1="12" x2="19" y2="12"/><polyline points="12.5 5.5 19 12 12.5 18.5"/>'
    ),
    "activity": _stroke('<polyline points="22 12 17.5 12 14.5 20.5 9.5 3.5 6.5 12 2 12"/>'),

    # Speaker / device glyph for Lite home selectors
    "speaker": _stroke(
        '<rect x="6" y="2.5" width="12" height="19" rx="2.5"/>'
        '<circle cx="12" cy="14.5" r="3.6"/>'
        '<circle cx="12" cy="7.2" r="1.5"/>',
        1.8,
    ),
}


def get_svg_icon(name: str, color: str = "#FFFFFF", size: QSize = QSize(20, 20)) -> QIcon:
    """Render a named vector icon tinted with `color`."""
    template = SVG_ICONS.get(name)
    if not template:
        return QIcon()

    svg_content = template.replace("currentColor", color)
    renderer = QSvgRenderer(QByteArray(svg_content.encode("utf-8")))
    pixmap = QPixmap(size.width(), size.height())
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return QIcon(pixmap)


def get_svg_pixmap(name: str, color: str = "#FFFFFF", size: QSize = QSize(20, 20)) -> QPixmap:
    """Render a named vector icon directly to a QPixmap."""
    template = SVG_ICONS.get(name)
    pixmap = QPixmap(size.width(), size.height())
    pixmap.fill(QColor(0, 0, 0, 0))
    if not template:
        return pixmap

    svg_content = template.replace("currentColor", color)
    renderer = QSvgRenderer(QByteArray(svg_content.encode("utf-8")))
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return pixmap
