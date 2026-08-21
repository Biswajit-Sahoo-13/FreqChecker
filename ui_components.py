"""
ui_components.py - Premium UI for FreqChecker inspired by FxSound.
Features:
- Dual Dark/Light themes using authentic FxSound color palettes
- 9-band Animated Equalizer Visualizer widget
- Interactive Log-Frequency Response Plot with glow effects and theme awareness
"""

import math
import random
from typing import List, Optional, Tuple, Dict
from PySide6.QtWidgets import (
    QWidget, QToolTip, QFrame, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QSlider, QSizePolicy, QGraphicsOpacityEffect
)
from PySide6.QtCore import (
    Qt, QRectF, QPointF, Signal, QPropertyAnimation, QEasingCurve,
    QTimer, Property, QParallelAnimationGroup, QObject
)
from PySide6.QtGui import (
    QPainter, QColor, QPen, QBrush, QFont, QPainterPath,
    QLinearGradient, QRadialGradient, QFontMetrics
)

from models import Measurement, Region, Classification, Stage, RegionCategory


# ══════════════════════════════════════════════════════════════════════════════
# FXSOUND AUTHENTIC COLOR TOKENS
# Dark:  Bg #14161A, Panel #1E222A, Border #2E3542, Accent #00A2FF/#0090FF, Cyan #00E5FF, Glow #80D8FF
# Light: Bg #F0F4F8, Panel #FFFFFF, Border #D8E2EC, Accent #0084E6/#0099FF, Cyan #00B0FF, Glow #00A2FF
# ══════════════════════════════════════════════════════════════════════════════

DARK_THEME_QSS = """
/* ── Global Dark Theme (FxSound Signature Electric Blue & Cyan) ── */
QMainWindow, QDialog, QWidget#CentralWidget {
    background-color: #14161A;
    color: #E2E8F0;
    font-family: 'Segoe UI Variable Display', 'Segoe UI', system-ui, -apple-system, sans-serif;
    font-size: 13px;
}

/* ── Scrollbars ── */
QScrollArea { background: transparent; border: none; }
QScrollBar:vertical {
    background: #181C22; width: 6px; border-radius: 3px; margin: 0;
}
QScrollBar::handle:vertical {
    background: rgba(0, 162, 255, 0.35); min-height: 28px; border-radius: 3px;
}
QScrollBar::handle:vertical:hover {
    background: rgba(0, 229, 255, 0.7);
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal {
    background: #181C22; height: 6px; border-radius: 3px;
}
QScrollBar::handle:horizontal {
    background: rgba(0, 162, 255, 0.35); min-width: 28px; border-radius: 3px;
}

/* ── Cards / Panels ── */
QFrame[class="card"] {
    background-color: #1E222A;
    border: 1px solid #2E3542;
    border-radius: 12px;
}
QFrame[class="card"]:hover {
    border-color: #3D4657;
}
QFrame[class="card-highlight"] {
    background-color: #142032;
    border: 1px solid rgba(0, 162, 255, 0.45);
    border-radius: 12px;
}

/* ── Typography ── */
QLabel {
    color: #A0AEC0;
    font-size: 13px;
}
QLabel[class="brand-title"] {
    font-size: 20px;
    font-weight: 800;
    color: #00A2FF;
    letter-spacing: -0.5px;
}
QLabel[class="title"] {
    font-size: 22px;
    font-weight: 700;
    color: #FFFFFF;
    letter-spacing: -0.3px;
}
QLabel[class="subtitle"] {
    font-size: 12px;
    color: #8A99AD;
    line-height: 1.4;
}
QLabel[class="section-title"] {
    font-size: 12px;
    font-weight: 700;
    color: #00A2FF;
    letter-spacing: 0.8px;
    text-transform: uppercase;
}
QLabel[class="freq-display"] {
    font-size: 46px;
    font-weight: 800;
    color: #00E5FF;
    letter-spacing: -1.5px;
}

/* ── Primary Buttons ── */
QPushButton {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #0077FF, stop:1 #00A2FF);
    color: #FFFFFF;
    border: none;
    padding: 10px 20px;
    border-radius: 9px;
    font-size: 13px;
    font-weight: 700;
}
QPushButton:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #0090FF, stop:1 #00E5FF);
    color: #121418;
}
QPushButton:pressed {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #0055CC, stop:1 #0077FF);
    color: #FFFFFF;
}
QPushButton:disabled {
    background: #282E38;
    color: #5A6577;
}

/* ── Secondary / Outline Buttons ── */
QPushButton[class="secondary"] {
    background: #242A34;
    color: #00A2FF;
    border: 1px solid #333C4C;
    border-radius: 9px;
    font-weight: 600;
}
QPushButton[class="secondary"]:hover {
    background: #2C3442;
    color: #00E5FF;
    border-color: #00A2FF;
}
QPushButton[class="secondary"]:pressed {
    background: #1B2028;
}

/* ── Action Toggle Buttons ── */
QPushButton[class="toggle-choice"] {
    background: #242A34;
    color: #CBD5E0;
    border: 2px solid #333C4C;
    border-radius: 12px;
    font-size: 14px;
    font-weight: 700;
    padding: 14px 24px;
}
QPushButton[class="toggle-choice"]:hover {
    background: #2C3442;
    border-color: #00A2FF;
    color: #FFFFFF;
}
QPushButton[class="toggle-yes-active"] {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #0077FF, stop:1 #00A2FF);
    color: #FFFFFF;
    border: 2px solid #33C5FF;
    border-radius: 12px;
    font-size: 14px;
    font-weight: 800;
    padding: 14px 24px;
}
QPushButton[class="toggle-no-active"] {
    background: #E53935;
    color: #FFFFFF;
    border: 2px solid #FF5252;
    border-radius: 12px;
    font-size: 14px;
    font-weight: 800;
    padding: 14px 24px;
}

/* ── Pill Buttons for numbers ── */
QPushButton[class="num-pill"] {
    background: #242A34;
    color: #A0AEC0;
    border: 1px solid #333C4C;
    border-radius: 7px;
    font-size: 12px;
    font-weight: 600;
    padding: 4px 8px;
    min-width: 28px;
    min-height: 28px;
}
QPushButton[class="num-pill"]:hover {
    background: #2C3442;
    color: #FFFFFF;
    border-color: #00E5FF;
}
QPushButton[class="num-pill-active"] {
    background: #00A2FF;
    color: #FFFFFF;
    border: 1px solid #80D8FF;
    border-radius: 7px;
    font-size: 12px;
    font-weight: 800;
    padding: 4px 8px;
    min-width: 28px;
    min-height: 28px;
}

/* ── Danger Button ── */
QPushButton[class="danger"] {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #D32F2F, stop:1 #FF5252);
    color: #FFFFFF;
    border: none;
    font-weight: 700;
}
QPushButton[class="danger"]:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #FF5252, stop:1 #FF8A80);
}

/* ── Sliders ── */
QSlider::groove:horizontal {
    height: 5px;
    background: #2A313E;
    border-radius: 2px;
}
QSlider::sub-page:horizontal {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0077FF, stop:1 #00E5FF);
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background: #00E5FF;
    border: 2px solid #14161A;
    width: 18px;
    margin-top: -7px;
    margin-bottom: -7px;
    border-radius: 9px;
}
QSlider::handle:horizontal:hover {
    background: #80D8FF;
}

/* ── ComboBox ── */
QComboBox {
    background-color: #1E222A;
    border: 1px solid #333C4C;
    border-radius: 9px;
    padding: 8px 14px;
    color: #E2E8F0;
    font-size: 13px;
    min-height: 20px;
}
QComboBox:hover {
    border-color: #00A2FF;
}
QComboBox::drop-down {
    border: none;
    width: 24px;
}
QComboBox QAbstractItemView {
    background-color: #1E222A;
    border: 1px solid #3D4657;
    border-radius: 8px;
    selection-background-color: #00A2FF;
    selection-color: #FFFFFF;
    color: #E2E8F0;
    padding: 4px;
    outline: none;
}
QComboBox QAbstractItemView::item {
    padding: 7px 12px;
    border-radius: 5px;
}
QComboBox QAbstractItemView::item:hover {
    background-color: rgba(0, 162, 255, 0.2);
}

/* ── CheckBox ── */
QCheckBox {
    color: #A0AEC0;
    font-size: 13px;
    spacing: 10px;
}
QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border-radius: 5px;
    border: 1px solid #3D4657;
    background-color: #181C22;
}
QCheckBox::indicator:checked {
    background: #00A2FF;
    border-color: #00A2FF;
}

/* ── Progress Bar ── */
QProgressBar {
    background-color: #242A34;
    border: none;
    border-radius: 4px;
    height: 8px;
    color: transparent;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0077FF, stop:1 #00E5FF);
    border-radius: 4px;
}

/* ── Text / Report ── */
QTextEdit, QPlainTextEdit {
    background-color: #16191E;
    border: 1px solid #2E3542;
    border-radius: 10px;
    color: #CBD5E0;
    font-family: 'Cascadia Code', 'Consolas', monospace;
    font-size: 12px;
    padding: 12px;
    selection-background-color: #00A2FF;
    selection-color: #FFFFFF;
}

/* ── SpinBox ── */
QSpinBox, QDoubleSpinBox {
    background-color: #1E222A;
    border: 1px solid #333C4C;
    border-radius: 7px;
    padding: 6px 10px;
    color: #E2E8F0;
}
QSpinBox:hover, QDoubleSpinBox:hover {
    border-color: #00A2FF;
}

/* ── Tooltip ── */
QToolTip {
    background-color: #1E222A;
    border: 1px solid #3D4657;
    border-radius: 8px;
    color: #FFFFFF;
    padding: 8px 12px;
    font-size: 12px;
}

/* ── Splitters (Movable Side Windows) ── */
QSplitter {
    background: transparent;
}
QSplitter::handle:horizontal {
    background-color: #242A34;
    width: 6px;
    margin: 2px 2px;
    border-radius: 3px;
}
QSplitter::handle:horizontal:hover {
    background-color: #00A2FF;
}
QSplitter::handle:horizontal:pressed {
    background-color: #00E5FF;
}
QSplitter::handle:vertical {
    background-color: #242A34;
    height: 6px;
    margin: 2px 2px;
    border-radius: 3px;
}
QSplitter::handle:vertical:hover {
    background-color: #00A2FF;
}

/* ── Status Badges ── */
QLabel[class="badge-success"] {
    background-color: rgba(0, 162, 255, 0.15);
    color: #00E5FF;
    border: 1px solid rgba(0, 162, 255, 0.35);
    border-radius: 6px;
    padding: 4px 8px;
    font-weight: 600;
    font-size: 11px;
}
QLabel[class="badge-warning"] {
    background-color: rgba(255, 179, 0, 0.15);
    color: #FFB300;
    border: 1px solid rgba(255, 179, 0, 0.35);
    border-radius: 6px;
    padding: 4px 8px;
    font-weight: 600;
    font-size: 11px;
}
QLabel[class="badge-info"] {
    background-color: rgba(0, 229, 255, 0.15);
    color: #00E5FF;
    border: 1px solid rgba(0, 229, 255, 0.35);
    border-radius: 6px;
    padding: 4px 8px;
    font-weight: 600;
    font-size: 11px;
}
QLabel[class="badge-danger"] {
    background-color: rgba(255, 82, 82, 0.15);
    color: #FF5252;
    border: 1px solid rgba(255, 82, 82, 0.35);
    border-radius: 6px;
    padding: 4px 8px;
    font-weight: 600;
    font-size: 11px;
}
"""

LIGHT_THEME_QSS = """
/* ── Global Light Theme (FxSound Light) ── */
QMainWindow, QDialog, QWidget#CentralWidget {
    background-color: #F0F4F8;
    color: #1A202C;
    font-family: 'Segoe UI Variable Display', 'Segoe UI', system-ui, -apple-system, sans-serif;
    font-size: 13px;
}

/* ── Scrollbars ── */
QScrollArea { background: transparent; border: none; }
QScrollBar:vertical {
    background: #E2E8F0; width: 6px; border-radius: 3px; margin: 0;
}
QScrollBar::handle:vertical {
    background: rgba(0, 132, 230, 0.4); min-height: 28px; border-radius: 3px;
}
QScrollBar::handle:vertical:hover {
    background: rgba(0, 132, 230, 0.8);
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal {
    background: #E2E8F0; height: 6px; border-radius: 3px;
}
QScrollBar::handle:horizontal {
    background: rgba(0, 132, 230, 0.4); min-width: 28px; border-radius: 3px;
}

/* ── Cards / Panels ── */
QFrame[class="card"] {
    background-color: #FFFFFF;
    border: 1px solid #D8E2EC;
    border-radius: 12px;
}
QFrame[class="card"]:hover {
    border-color: #CBD5E1;
}
QFrame[class="card-highlight"] {
    background-color: #EDF5FD;
    border: 1px solid rgba(0, 132, 230, 0.4);
    border-radius: 12px;
}
    background-color: #F0FDF4;
    border: 1px solid rgba(0, 200, 83, 0.4);
    border-radius: 12px;
}

/* ── Typography ── */
QLabel {
    color: #4A5568;
    font-size: 13px;
}
QLabel[class="brand-title"] {
    font-size: 20px;
    font-weight: 800;
    color: #0084E6;
    letter-spacing: -0.5px;
}
QLabel[class="title"] {
    font-size: 22px;
    font-weight: 700;
    color: #1A202C;
    letter-spacing: -0.3px;
}
QLabel[class="subtitle"] {
    font-size: 12px;
    color: #718096;
    line-height: 1.4;
}
QLabel[class="section-title"] {
    font-size: 12px;
    font-weight: 700;
    color: #0084E6;
    letter-spacing: 0.8px;
    text-transform: uppercase;
}
QLabel[class="freq-display"] {
    font-size: 46px;
    font-weight: 800;
    color: #0084E6;
    letter-spacing: -1.5px;
}

/* ── Primary Buttons ── */
QPushButton {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #0077FF, stop:1 #0099FF);
    color: #FFFFFF;
    border: none;
    padding: 10px 20px;
    border-radius: 9px;
    font-size: 13px;
    font-weight: 700;
}
QPushButton:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #0088FF, stop:1 #00B0FF);
}
QPushButton:pressed {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #0055CC, stop:1 #0077FF);
}
QPushButton:disabled {
    background: #E2E8F0;
    color: #A0AEC0;
}

/* ── Secondary / Outline Buttons ── */
QPushButton[class="secondary"] {
    background: #FFFFFF;
    color: #0084E6;
    border: 1px solid #CBD5E1;
    border-radius: 9px;
    font-weight: 600;
}
QPushButton[class="secondary"]:hover {
    background: #EDF5FD;
    border-color: #0084E6;
}
QPushButton[class="secondary"]:pressed {
    background: #E2EFFD;
}

/* ── Action Toggle Buttons ── */
QPushButton[class="toggle-choice"] {
    background: #F1F5F9;
    color: #334155;
    border: 2px solid #CBD5E1;
    border-radius: 12px;
    font-size: 14px;
    font-weight: 700;
    padding: 14px 24px;
}
QPushButton[class="toggle-choice"]:hover {
    background: #E2E8F0;
    border-color: #0084E6;
    color: #0F172A;
}
QPushButton[class="toggle-yes-active"] {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #0077FF, stop:1 #0099FF);
    color: #FFFFFF;
    border: 2px solid #0084E6;
    border-radius: 12px;
    font-size: 14px;
    font-weight: 800;
    padding: 14px 24px;
}
QPushButton[class="toggle-no-active"] {
    background: #EF5350;
    color: #FFFFFF;
    border: 2px solid #E53935;
    border-radius: 12px;
    font-size: 14px;
    font-weight: 800;
    padding: 14px 24px;
}

/* ── Pill Buttons for numbers ── */
QPushButton[class="num-pill"] {
    background: #F1F5F9;
    color: #475569;
    border: 1px solid #CBD5E1;
    border-radius: 7px;
    font-size: 12px;
    font-weight: 600;
    padding: 4px 8px;
    min-width: 28px;
    min-height: 28px;
}
QPushButton[class="num-pill"]:hover {
    background: #E2E8F0;
    color: #0F172A;
    border-color: #0084E6;
}
QPushButton[class="num-pill-active"] {
    background: #0084E6;
    color: #FFFFFF;
    border: 1px solid #00A2FF;
    border-radius: 7px;
    font-size: 12px;
    font-weight: 800;
    padding: 4px 8px;
    min-width: 28px;
    min-height: 28px;
}

/* ── Danger Button ── */
QPushButton[class="danger"] {
    background: #EF5350;
    color: #FFFFFF;
    border: none;
    font-weight: 700;
}
QPushButton[class="danger"]:hover {
    background: #E53935;
}

/* ── Sliders ── */
QSlider::groove:horizontal {
    height: 5px;
    background: #CBD5E1;
    border-radius: 2px;
}
QSlider::sub-page:horizontal {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0077FF, stop:1 #00A2FF);
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background: #0084E6;
    border: 2px solid #FFFFFF;
    width: 18px;
    margin-top: -7px;
    margin-bottom: -7px;
    border-radius: 9px;
}
QSlider::handle:horizontal:hover {
    background: #0099FF;
}

/* ── ComboBox ── */
QComboBox {
    background-color: #FFFFFF;
    border: 1px solid #CBD5E1;
    border-radius: 9px;
    padding: 8px 14px;
    color: #1A202C;
    font-size: 13px;
    min-height: 20px;
}
QComboBox:hover {
    border-color: #0084E6;
}
QComboBox::drop-down {
    border: none;
    width: 24px;
}
QComboBox QAbstractItemView {
    background-color: #FFFFFF;
    border: 1px solid #CBD5E1;
    border-radius: 8px;
    selection-background-color: #0084E6;
    selection-color: #FFFFFF;
    color: #1A202C;
    padding: 4px;
    outline: none;
}
QComboBox QAbstractItemView::item {
    padding: 7px 12px;
    border-radius: 5px;
}
QComboBox QAbstractItemView::item:hover {
    background-color: rgba(0, 132, 230, 0.15);
}

/* ── CheckBox ── */
QCheckBox {
    color: #4A5568;
    font-size: 13px;
    spacing: 10px;
}
QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border-radius: 5px;
    border: 1px solid #CBD5E1;
    background-color: #FFFFFF;
}
QCheckBox::indicator:checked {
    background: #0084E6;
    border-color: #0084E6;
}

/* ── Progress Bar ── */
QProgressBar {
    background-color: #E2E8F0;
    border: none;
    border-radius: 4px;
    height: 8px;
    color: transparent;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0077FF, stop:1 #00A2FF);
    border-radius: 4px;
}

/* ── Text / Report ── */
QTextEdit, QPlainTextEdit {
    background-color: #F8FAFC;
    border: 1px solid #CBD5E1;
    border-radius: 10px;
    color: #334155;
    font-family: 'Cascadia Code', 'Consolas', monospace;
    font-size: 12px;
    padding: 12px;
    selection-background-color: #0084E6;
    selection-color: #FFFFFF;
}

/* ── SpinBox ── */
QSpinBox, QDoubleSpinBox {
    background-color: #FFFFFF;
    border: 1px solid #CBD5E1;
    border-radius: 7px;
    padding: 6px 10px;
    color: #1A202C;
}
QSpinBox:hover, QDoubleSpinBox:hover {
    border-color: #0084E6;
}

/* ── Tooltip ── */
QToolTip {
    background-color: #FFFFFF;
    border: 1px solid #CBD5E1;
    border-radius: 8px;
    color: #1A202C;
    padding: 8px 12px;
    font-size: 12px;
}

/* ── Splitters (Movable Side Windows) ── */
QSplitter {
    background: transparent;
}
QSplitter::handle:horizontal {
    background-color: #CBD5E1;
    width: 6px;
    margin: 2px 2px;
    border-radius: 3px;
}
QSplitter::handle:horizontal:hover {
    background-color: #0084E6;
}
QSplitter::handle:horizontal:pressed {
    background-color: #0099FF;
}
QSplitter::handle:vertical {
    background-color: #CBD5E1;
    height: 6px;
    margin: 2px 2px;
    border-radius: 3px;
}
QSplitter::handle:vertical:hover {
    background-color: #0084E6;
}

/* ── Status Badges ── */
QLabel[class="badge-success"] {
    background-color: rgba(0, 132, 230, 0.12);
    color: #0066CC;
    border: 1px solid rgba(0, 132, 230, 0.3);
    border-radius: 6px;
    padding: 4px 8px;
    font-weight: 600;
    font-size: 11px;
}
QLabel[class="badge-warning"] {
    background-color: rgba(239, 108, 0, 0.12);
    color: #EF6C00;
    border: 1px solid rgba(239, 108, 0, 0.3);
    border-radius: 6px;
    padding: 4px 8px;
    font-weight: 600;
    font-size: 11px;
}
QLabel[class="badge-info"] {
    background-color: rgba(0, 132, 230, 0.12);
    color: #0084E6;
    border: 1px solid rgba(0, 132, 230, 0.3);
    border-radius: 6px;
    padding: 4px 8px;
    font-weight: 600;
    font-size: 11px;
}
QLabel[class="badge-danger"] {
    background-color: rgba(211, 47, 47, 0.12);
    color: #D32F2F;
    border: 1px solid rgba(211, 47, 47, 0.3);
    border-radius: 6px;
    padding: 4px 8px;
    font-weight: 600;
    font-size: 11px;
}
"""


# ══════════════════════════════════════════════════════════════════════════════
# ANIMATED 9-BAND FXSOUND SPECTRUM EQUALIZER WIDGET
# ══════════════════════════════════════════════════════════════════════════════

class FxSpectrumVisualizerWidget(QWidget):
    """
    Animated 9-band audio equalizer visualizer styled directly after FxSound.
    Animates dynamically when audio is playing, decays smoothly to resting bars.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(40)
        self.setMinimumWidth(180)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(
            "Live 9-Band Spectrum Equalizer Visualizer\n"
            "• Animates in real-time to reflect active audio output across 9 ISO bands (63 Hz – 16 kHz).\n"
            "• Visualizes output energy and harmonic spread during tests, sweeps, and music."
        )

        self._is_dark = True
        self._is_playing = False
        self._target_freq_hz: float = 1000.0

        # 9 center frequency bands matching FxSound EQ
        self.bands = [63, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]
        self._bar_levels = [0.12] * len(self.bands)
        self._bar_targets = [0.12] * len(self.bands)
        self._phase = 0.0

        # Animation timer ~40 FPS
        self._timer = QTimer(self)
        self._timer.setInterval(25)
        self._timer.timeout.connect(self._on_tick)
        self._timer.start()

    def set_theme(self, is_dark: bool):
        self._is_dark = is_dark
        self.update()

    def set_playing_state(self, is_playing: bool, target_freq_hz: float = 1000.0):
        self._is_playing = is_playing
        self._target_freq_hz = max(20.0, float(target_freq_hz))
        self.update()

    def _on_tick(self):
        self._phase += 0.15
        if self._is_playing:
            # Find closest band to target frequency
            log_target = math.log10(self._target_freq_hz)
            for i, band in enumerate(self.bands):
                log_band = math.log10(band)
                dist = abs(log_target - log_band)
                # Gaussian-like spectral spread around active frequency
                proximity = math.exp(-dist * dist * 4.0)
                osc = math.sin(self._phase * 2.0 + i * 0.8) * 0.15
                target = max(0.18, min(0.95, 0.25 + proximity * 0.65 + osc))
                self._bar_targets[i] = target
        else:
            # Idle calm resting level
            for i in range(len(self.bands)):
                idle_wave = math.sin(self._phase * 0.5 + i * 0.5) * 0.04
                self._bar_targets[i] = 0.10 + idle_wave

        # Smooth easing towards targets
        for i in range(len(self.bands)):
            self._bar_levels[i] += (self._bar_targets[i] - self._bar_levels[i]) * 0.22

        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        n = len(self.bands)

        bar_w = max(4.0, (w - (n - 1) * 4.0 - 12.0) / n)
        spacing = 4.0
        start_x = (w - (n * bar_w + (n - 1) * spacing)) / 2.0

        for i, level in enumerate(self._bar_levels):
            bx = start_x + i * (bar_w + spacing)
            bh = max(4.0, level * (h - 8.0))
            by = h - 4.0 - bh

            bar_rect = QRectF(bx, by, bar_w, bh)
            corner_r = min(3.0, bar_w / 2.0)

            # Gradient for bar (FxSound Electric Blue & Cyan)
            grad = QLinearGradient(bx, by, bx, by + bh)
            if self._is_dark:
                grad.setColorAt(0.0, QColor("#80D8FF"))
                grad.setColorAt(0.4, QColor("#00E5FF"))
                grad.setColorAt(0.8, QColor("#00A2FF"))
                grad.setColorAt(1.0, QColor("#0055CC"))
            else:
                grad.setColorAt(0.0, QColor("#00B0FF"))
                grad.setColorAt(0.5, QColor("#0084E6"))
                grad.setColorAt(1.0, QColor("#004DA8"))

            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(grad))
            painter.drawRoundedRect(bar_rect, corner_r, corner_r)

            # Top glow dot when active
            if self._is_playing and level > 0.4:
                glow_c = QColor("#FFFFFF" if self._is_dark else "#0084E6")
                glow_c.setAlpha(int(min(220, level * 250)))
                painter.setBrush(QBrush(glow_c))
                painter.drawEllipse(QPointF(bx + bar_w / 2.0, by + 2.0), 1.5, 1.5)


# ══════════════════════════════════════════════════════════════════════════════
# LOG FREQUENCY RESPONSE PLOT WIDGET
# ══════════════════════════════════════════════════════════════════════════════

class LogFrequencyPlotWidget(QWidget):
    """
    Interactive Log-Frequency Response Plot with theme awareness,
    click-to-replay, multi-channel curves, and shaded anomaly regions.
    """
    point_clicked = Signal(float, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(400, 200)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True)
        self._is_dark = True

        self.f_min = 50.0
        self.f_max = 18000.0
        self.y_min = 0.0
        self.y_max = 10.5

        self.measurements_left: List[Measurement] = []
        self.measurements_right: List[Measurement] = []
        self.regions_left: List[Region] = []
        self.regions_right: List[Region] = []
        self.active_channel_filter = "both"
        self._point_rects: List[Tuple[QRectF, Measurement]] = []

    def set_theme(self, is_dark: bool):
        self._is_dark = is_dark
        self.update()

    def set_data(self, left_measurements, right_measurements, left_regions=None, right_regions=None):
        self.measurements_left = [m for m in left_measurements if not m.input_error]
        self.measurements_right = [m for m in right_measurements if not m.input_error]
        self.regions_left = left_regions or []
        self.regions_right = right_regions or []
        self.update()

    def set_channel_filter(self, channel: str):
        self.active_channel_filter = channel
        self.update()

    def _freq_to_x(self, freq, rect):
        freq = max(self.f_min, min(self.f_max, freq))
        ratio = (math.log10(freq) - math.log10(self.f_min)) / (math.log10(self.f_max) - math.log10(self.f_min))
        return rect.left() + ratio * rect.width()

    def _y_to_pixel(self, val, rect):
        val = max(self.y_min, min(self.y_max, val))
        ratio = (val - self.y_min) / (self.y_max - self.y_min)
        return rect.bottom() - ratio * rect.height()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        ml, mr, mt, mb = 44, 20, 22, 34
        plot_rect = QRectF(ml, mt, max(10, w - ml - mr), max(10, h - mt - mb))

        if self._is_dark:
            bg_outer, bg_plot = QColor("#14161A"), QColor("#1E222A")
            grid_maj, grid_min = QColor(46, 53, 66, 90), QColor(36, 42, 52, 60)
            axis_c, text_c = QColor(60, 70, 86, 120), QColor("#8A99AD")
            clr_left, clr_right = QColor("#00E5FF"), QColor("#0084FF")
            anom_fill, anom_top = QColor(255, 82, 82, 35), QColor("#FF5252")
            roll_fill = QColor(50, 60, 75, 40)
        else:
            bg_outer, bg_plot = QColor("#F0F4F8"), QColor("#FFFFFF")
            grid_maj, grid_min = QColor(216, 226, 236, 90), QColor(230, 238, 246, 60)
            axis_c, text_c = QColor(190, 200, 215, 120), QColor("#64748B")
            clr_left, clr_right = QColor("#0091EA"), QColor("#0066CC")
            anom_fill, anom_top = QColor(239, 83, 80, 35), QColor("#EF5350")
            roll_fill = QColor(200, 210, 225, 40)

        painter.fillRect(self.rect(), bg_outer)
        painter.fillRect(plot_rect, bg_plot)
        font = QFont("Segoe UI", 8)
        painter.setFont(font)

        ticks = [63, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]
        minors = [80, 100, 160, 200, 315, 400, 630, 800, 1250, 1600, 2500, 3150, 5000, 6300, 10000, 12500]

        painter.setPen(QPen(grid_min, 1, Qt.DotLine))
        for mf in minors:
            if self.f_min <= mf <= self.f_max:
                x = self._freq_to_x(mf, plot_rect)
                painter.drawLine(QPointF(x, plot_rect.top()), QPointF(x, plot_rect.bottom()))

        for f in ticks:
            x = self._freq_to_x(f, plot_rect)
            painter.setPen(QPen(grid_maj, 1, Qt.DashLine))
            painter.drawLine(QPointF(x, plot_rect.top()), QPointF(x, plot_rect.bottom()))
            lbl = f"{f//1000}k" if f >= 1000 else str(f)
            painter.setPen(text_c)
            painter.drawText(QRectF(x - 22, plot_rect.bottom() + 4, 44, 18), Qt.AlignHCenter | Qt.AlignTop, lbl)

        for yv in range(0, 11, 2):
            y_px = self._y_to_pixel(yv, plot_rect)
            painter.setPen(QPen(grid_maj, 1, Qt.DashLine))
            painter.drawLine(QPointF(plot_rect.left(), y_px), QPointF(plot_rect.right(), y_px))
            painter.setPen(text_c)
            painter.drawText(QRectF(0, y_px - 8, ml - 6, 16), Qt.AlignRight | Qt.AlignVCenter, str(yv))

        painter.setPen(QPen(axis_c, 1))
        painter.drawRect(plot_rect)

        # Draw Anomaly Shading (Red highlights for defects)
        regs = []
        if self.active_channel_filter in ("both", "left"): regs.extend(self.regions_left)
        if self.active_channel_filter in ("both", "right"): regs.extend(self.regions_right)
        for reg in regs:
            rx_l = self._freq_to_x(reg.f_low, plot_rect)
            rx_r = self._freq_to_x(reg.f_high, plot_rect)
            rw = max(5, rx_r - rx_l)
            rr = QRectF(rx_l, plot_rect.top(), rw, plot_rect.height())
            if reg.category == RegionCategory.EXPECTED_LOW_ROLLOFF:
                painter.fillRect(rr, roll_fill)
            else:
                painter.fillRect(rr, anom_fill)
                painter.setPen(QPen(anom_top, 2))
                painter.drawLine(QPointF(rx_l, plot_rect.top()), QPointF(rx_r, plot_rect.top()))

        self._point_rects.clear()
        if self.active_channel_filter in ("both", "left"):
            self._draw_channel(painter, plot_rect, self.measurements_left, clr_left)
        if self.active_channel_filter in ("both", "right"):
            self._draw_channel(painter, plot_rect, self.measurements_right, clr_right)
        self._draw_legend(painter, plot_rect, clr_left, clr_right)

    def _draw_channel(self, painter, rect, points, color):
        if not points: return
        sorted_pts = sorted(points, key=lambda p: p.frequency_hz)

        # Draw smooth response path
        path = QPainterPath()
        for i, p in enumerate(sorted_pts):
            pt = QPointF(self._freq_to_x(p.frequency_hz, rect), self._y_to_pixel(p.quality, rect))
            if i == 0: path.moveTo(pt)
            else: path.lineTo(pt)
        lc = QColor(color); lc.setAlpha(180)
        painter.setPen(QPen(lc, 2.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.drawPath(path)

        for p in sorted_pts:
            px = self._freq_to_x(p.frequency_hz, rect)
            py = self._y_to_pixel(p.quality, rect)
            eff = p.effective_classification or p.classification
            if p.is_control: dc = QColor("#00E5FF")
            elif p.is_retest: dc = QColor("#B388FF")
            elif eff == Classification.GOOD: dc = QColor("#00A2FF")
            elif eff == Classification.BORDERLINE: dc = QColor("#FFB300")
            else: dc = QColor("#FF5252")

            # Subtle glow halo
            gc = QColor(dc); gc.setAlpha(35)
            gg = QRadialGradient(QPointF(px, py), 10)
            gg.setColorAt(0, gc); gg.setColorAt(1, QColor(0,0,0,0))
            painter.setBrush(QBrush(gg)); painter.setPen(Qt.NoPen)
            painter.drawEllipse(QPointF(px, py), 10, 10)

            # Node circle
            r = 4.5
            pr = QRectF(px-r, py-r, r*2, r*2)
            self._point_rects.append((pr, p))
            painter.setBrush(QBrush(dc))
            painter.setPen(QPen(QColor(255,255,255,160), 1))
            painter.drawEllipse(pr)

    def _draw_legend(self, painter, rect, clr_l, clr_r):
        font = QFont("Segoe UI", 8, QFont.Bold); painter.setFont(font)
        x, y = rect.right() - 230, rect.top() + 8
        for i, (c, t) in enumerate([(clr_l, "Left"), (clr_r, "Right")]):
            painter.setPen(Qt.NoPen); painter.setBrush(c)
            painter.drawEllipse(QPointF(x + i*60, y+6), 4, 4)
            painter.setPen(c)
            painter.drawText(QRectF(x + i*60 + 10, y, 46, 14), Qt.AlignLeft | Qt.AlignVCenter, t)
        painter.fillRect(QRectF(x+124, y+1, 9, 9), QColor(255, 82, 82, 70))
        painter.setPen(QColor("#FF5252") if self._is_dark else QColor("#EF5350"))
        painter.drawText(QRectF(x+138, y, 75, 14), Qt.AlignLeft | Qt.AlignVCenter, "Anomaly")

    def mouseMoveEvent(self, event):
        pos = event.position()
        for pr, m in self._point_rects:
            if pr.adjusted(-5,-5,5,5).contains(pos):
                self.setCursor(Qt.PointingHandCursor)
                eff = m.effective_classification or m.classification
                st = f" [{m.stage}]" if m.stage else ""
                QToolTip.showText(event.globalPosition().toPoint(),
                    f"{m.frequency_hz:.1f} Hz ({m.channel.upper()})\n"
                    f"Clarity: {m.clarity}/10 · Quality: {m.quality:.1f}\n"
                    f"{eff}{st}  ·  Click to replay", self)
                return
        self.setCursor(Qt.ArrowCursor); QToolTip.hideText()
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            pos = event.position()
            for pr, m in self._point_rects:
                if pr.adjusted(-6,-6,6,6).contains(pos):
                    self.point_clicked.emit(m.frequency_hz, m.channel); return
        super().mousePressEvent(event)

