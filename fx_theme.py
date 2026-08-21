"""
fx_theme.py - Authentic FxSound Design Tokens & Complete Theme Engine for FreqChecker.
Ported from FxSound (FxTheme.cpp/.h) with dual Dark (Crimson #d51535) and Light (Cyan #1ac1ff) palettes.
"""

import os
from typing import Dict, Any


# ══════════════════════════════════════════════════════════════════════════════
# VISUALIZER & FONT METRICS CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════
VIS_PANEL_RADIUS: int = 8
VIS_BAR_WIDTH: float = 4.0
VIS_BAR_PITCH: float = 9.1
VIS_FPS: int = 30
SPECTRUM_BANDS = [63, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]
FONT_FAMILY_STACK: str = "'Manrope', 'Segoe UI', 'Inter', -apple-system, sans-serif"
_BUNDLED_FONTS = ("Manrope.ttf",)

_ACTIVE_THEME: str = "dark"


# ══════════════════════════════════════════════════════════════════════════════
# AUTHENTIC FXSOUND 27-TOKEN COLOR TABLES
# ══════════════════════════════════════════════════════════════════════════════
FX_COLORS_DARK: Dict[str, str] = {
    "window_bg": "#181818",
    "control_bg": "#0f0f0f",
    "card_bg": "#1e1e1e",
    "card_border": "#2b2b2b",
    "outline": "#2b2b2b",
    "primary_accent": "#d51535",       # Crimson Red
    "accent_hover": "#e63462",
    "accent_pressed": "#b7102b",
    "slider_track": "#e33250",
    "slider_hl": "#f7546f",
    "graph_high": "#d51535",
    "graph_low": "#fe566a",
    "cyan_secondary": "#00e5ff",      # Cyan accent for Right channel / controls
    "cyan_hover": "#33ebff",
    "text_primary": "#ffffff",
    "text_body": "#b1b1b1",
    "text_muted": "#7f7f7f",
    "text_disabled": "#555555",
    "menu_bg": "#383838",
    "menu_hl": "#414141",
    "badge_bg": "#252525",
    "danger": "#ff4d4f",
    "danger_hover": "#ff7875",
    "warning": "#faad14",
    "success": "#52c41a",
    "info": "#1890ff",
}

FX_COLORS_LIGHT: Dict[str, str] = {
    "window_bg": "#f5f5f5",
    "control_bg": "#e6e6e6",
    "card_bg": "#ffffff",
    "card_border": "#d9d9d9",
    "outline": "#d9d9d9",
    "primary_accent": "#1ac1ff",       # Electric Cyan / Blue
    "accent_hover": "#23b6eb",
    "accent_pressed": "#0090cc",
    "slider_track": "#0a4d66",
    "slider_hl": "#53ccff",
    "graph_high": "#1ac1ff",
    "graph_low": "#72d8ff",
    "cyan_secondary": "#0091ea",
    "cyan_hover": "#00b0ff",
    "text_primary": "#1f1f1f",
    "text_body": "#4e4e4e",
    "text_muted": "#7f7f7f",
    "text_disabled": "#aaaaaa",
    "menu_bg": "#c7c7c7",
    "menu_hl": "#b9b9b9",
    "badge_bg": "#f0f0f0",
    "danger": "#f5222d",
    "danger_hover": "#ff4d4f",
    "warning": "#d48806",
    "success": "#389e0d",
    "info": "#096dd9",
}


def is_dark() -> bool:
    """Check if current active theme is dark."""
    return _ACTIVE_THEME == "dark"


def set_theme(theme_name: str):
    """Set global active theme ('dark' or 'light')."""
    global _ACTIVE_THEME
    _ACTIVE_THEME = "dark" if theme_name.lower() == "dark" else "light"


def get_fx_color(token: str, is_dark_theme: bool = True) -> str:
    """Retrieve color hex string by token name for the given theme."""
    table = FX_COLORS_DARK if is_dark_theme else FX_COLORS_LIGHT
    return table.get(token, "#d51535" if is_dark_theme else "#1ac1ff")


def painter_palette() -> Dict[str, Any]:
    """Retrieve painter color tokens for custom drawing widgets."""
    dark = is_dark()
    if dark:
        return {
            "vis_panel": "#0f0f0f",
            "vis_high": "#d51535",
            "vis_low": "#fe566a",
            "bg_outer": "#181818",
            "bg_plot": "#0f0f0f",
            "grid_maj": "#2b2b2b",
            "grid_min": "#202020",
            "axis": "#3a3a3a",
            "text_hint": "#7f7f7f",
            "left": "#d51535",
            "right": "#00e5ff",
            "control_pt": "#00e5ff",
            "retest_pt": "#b388ff",
            "good": "#52c41a",
            "borderline": "#faad14",
            "bad": "#ff4d4f",
            "anom_fill": "#33ff4d4f",
            "anom_top": "#ff4d4f",
            "roll_fill": "#26323232",
        }
    else:
        return {
            "vis_panel": "#e6e6e6",
            "vis_high": "#1ac1ff",
            "vis_low": "#72d8ff",
            "bg_outer": "#f5f5f5",
            "bg_plot": "#ffffff",
            "grid_maj": "#d9d9d9",
            "grid_min": "#e8e8e8",
            "axis": "#bfbfbf",
            "text_hint": "#7f7f7f",
            "left": "#1ac1ff",
            "right": "#0091ea",
            "control_pt": "#0091ea",
            "retest_pt": "#722ed1",
            "good": "#389e0d",
            "borderline": "#d48806",
            "bad": "#f5222d",
            "anom_fill": "#33f5222d",
            "anom_top": "#f5222d",
            "roll_fill": "#26c8c8c8",
        }


# ══════════════════════════════════════════════════════════════════════════════
# COMPREHENSIVE QSS STYLESHEET GENERATOR
# ══════════════════════════════════════════════════════════════════════════════
def build_qss(c: Dict[str, str]) -> str:
    """Generate complete unified QSS stylesheet from token dictionary."""
    return f"""
/* ── Global Reset & Base Typography ── */
QWidget {{
    background-color: {c["window_bg"]};
    color: {c["text_body"]};
    font-family: {FONT_FAMILY_STACK};
    font-size: 13px;
}}

QMainWindow {{
    background-color: {c["window_bg"]};
}}

/* ── Container Cards & Panels ── */
QFrame.card {{
    background-color: {c["card_bg"]};
    border: 1px solid {c["card_border"]};
    border-radius: 12px;
}}

QFrame.panel {{
    background-color: {c["control_bg"]};
    border: 1px solid {c["outline"]};
    border-radius: 8px;
}}

/* ── Typography & Headers ── */
QLabel {{
    background: transparent;
    color: {c["text_body"]};
}}

QLabel.brand-title {{
    font-size: 16px;
    font-weight: 800;
    color: {c["text_primary"]};
    letter-spacing: 1.5px;
}}

QLabel.title {{
    font-size: 17px;
    font-weight: 700;
    color: {c["text_primary"]};
}}

QLabel.section-title {{
    font-size: 14px;
    font-weight: 700;
    color: {c["text_primary"]};
    letter-spacing: 0.5px;
}}

QLabel.subtitle {{
    font-size: 12px;
    color: {c["text_body"]};
    line-height: 1.4;
}}

QLabel.hint {{
    font-size: 11px;
    color: {c["text_muted"]};
}}

QLabel.freq-display {{
    font-size: 38px;
    font-weight: 800;
    color: {c["primary_accent"]};
    letter-spacing: -0.5px;
}}

/* ── Status Badges ── */
QLabel.badge-info {{
    background-color: {c["control_bg"]};
    color: {c["text_body"]};
    border: 1px solid {c["card_border"]};
    border-radius: 6px;
    padding: 4px 8px;
    font-size: 11px;
}}

QLabel.badge-warning {{
    background-color: {c["control_bg"]};
    color: {c["warning"]};
    border: 1px solid {c["warning"]};
    border-radius: 6px;
    padding: 4px 8px;
    font-size: 11px;
    font-weight: 600;
}}

QLabel.badge-success {{
    background-color: {c["control_bg"]};
    color: {c["success"]};
    border: 1px solid {c["success"]};
    border-radius: 6px;
    padding: 4px 8px;
    font-size: 11px;
    font-weight: 600;
}}

/* ── Primary Action Buttons ── */
QPushButton {{
    background-color: {c["primary_accent"]};
    color: #ffffff;
    border: none;
    border-radius: 8px;
    padding: 8px 18px;
    font-weight: 700;
    font-size: 13px;
}}

QPushButton:hover {{
    background-color: {c["accent_hover"]};
}}

QPushButton:pressed {{
    background-color: {c["accent_pressed"]};
}}

QPushButton:disabled {{
    background-color: {c["control_bg"]};
    color: {c["text_disabled"]};
    border: 1px solid {c["card_border"]};
}}

/* ── Secondary Outlined Buttons ── */
QPushButton.secondary {{
    background-color: {c["control_bg"]};
    color: {c["text_primary"]};
    border: 1px solid {c["card_border"]};
    border-radius: 8px;
    padding: 7px 14px;
    font-weight: 600;
}}

QPushButton.secondary:hover {{
    background-color: {c["card_bg"]};
    border-color: {c["primary_accent"]};
    color: {c["primary_accent"]};
}}

QPushButton.secondary:pressed {{
    background-color: {c["control_bg"]};
}}

/* ── Danger Buttons ── */
QPushButton.danger {{
    background-color: {c["control_bg"]};
    color: {c["danger"]};
    border: 1px solid {c["danger"]};
    border-radius: 8px;
    padding: 6px 12px;
    font-weight: 700;
}}

QPushButton.danger:hover {{
    background-color: {c["danger"]};
    color: #ffffff;
}}

QPushButton.danger:pressed {{
    background-color: {c["danger_hover"]};
}}

/* ── Diagnostic Choice & Pill Buttons ── */
QPushButton.toggle-choice {{
    background-color: {c["control_bg"]};
    color: {c["text_primary"]};
    border: 1.5px solid {c["card_border"]};
    border-radius: 10px;
    font-size: 14px;
    font-weight: 700;
}}

QPushButton.toggle-choice:hover {{
    border-color: {c["primary_accent"]};
    color: {c["primary_accent"]};
}}

QPushButton.toggle-yes-active {{
    background-color: {c["primary_accent"]};
    color: #ffffff;
    border: 1.5px solid {c["primary_accent"]};
    border-radius: 8px;
    font-weight: 700;
}}

QPushButton.toggle-no-active {{
    background-color: {c["danger"]};
    color: #ffffff;
    border: 1.5px solid {c["danger"]};
    border-radius: 8px;
    font-weight: 700;
}}

QPushButton.num-pill {{
    background-color: {c["control_bg"]};
    color: {c["text_body"]};
    border: 1px solid {c["card_border"]};
    border-radius: 6px;
    font-weight: 700;
    font-size: 12px;
    min-width: 28px;
    min-height: 28px;
    padding: 0;
}}

QPushButton.num-pill:hover {{
    background-color: {c["card_bg"]};
    border-color: {c["primary_accent"]};
    color: {c["primary_accent"]};
}}

QPushButton.num-pill-active {{
    background-color: {c["primary_accent"]};
    color: #ffffff;
    border: 1px solid {c["primary_accent"]};
    border-radius: 6px;
    font-weight: 800;
    font-size: 12px;
    min-width: 28px;
    min-height: 28px;
    padding: 0;
}}

/* ── Sliders ── */
QSlider::groove:horizontal {{
    height: 4px;
    background: {c["card_border"]};
    border-radius: 2px;
}}

QSlider::sub-page:horizontal {{
    background: {c["primary_accent"]};
    border-radius: 2px;
}}

QSlider::handle:horizontal {{
    background: {c["primary_accent"]};
    border: 2px solid #ffffff;
    width: 14px;
    margin-top: -5px;
    margin-bottom: -5px;
    border-radius: 7px;
}}

QSlider::handle:horizontal:hover {{
    background: {c["accent_hover"]};
    border: 2px solid #ffffff;
}}

/* ── Combo Boxes (FxSound pill dropdowns) ── */
QComboBox {{
    background-color: {c["control_bg"]};
    color: {c["text_primary"]};
    border: 1px solid {c["card_border"]};
    border-radius: 10px;
    padding: 9px 14px;
    min-height: 20px;
    font-size: 13px;
    font-weight: 600;
}}

QComboBox:hover {{
    border-color: {c["primary_accent"]};
}}

QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 28px;
    border-left: none;
}}

QComboBox QAbstractItemView {{
    background-color: {c["menu_bg"]};
    color: {c["text_primary"]};
    border: 1px solid {c["card_border"]};
    border-radius: 6px;
    selection-background-color: {c["primary_accent"]};
    selection-color: #ffffff;
    padding: 4px;
}}

/* ── SpinBoxes ── */
QSpinBox, QDoubleSpinBox {{
    background-color: {c["control_bg"]};
    color: {c["text_primary"]};
    border: 1px solid {c["card_border"]};
    border-radius: 8px;
    padding: 6px 10px;
    font-size: 13px;
    font-weight: 600;
}}

QSpinBox:hover, QDoubleSpinBox:hover {{
    border-color: {c["primary_accent"]};
}}

/* ── CheckBoxes ── */
QCheckBox {{
    color: {c["text_body"]};
    font-size: 13px;
    spacing: 8px;
    background: transparent;
}}

QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border-radius: 4px;
    border: 1.5px solid {c["card_border"]};
    background-color: {c["control_bg"]};
}}

QCheckBox::indicator:hover {{
    border-color: {c["primary_accent"]};
}}

QCheckBox::indicator:checked {{
    background-color: {c["primary_accent"]};
    border-color: {c["primary_accent"]};
}}

/* ── Progress Bar ── */
QProgressBar {{
    background-color: {c["control_bg"]};
    border: 1px solid {c["card_border"]};
    border-radius: 5px;
    height: 8px;
    text-align: center;
}}

QProgressBar::chunk {{
    background-color: {c["primary_accent"]};
    border-radius: 4px;
}}

/* ── Text Edits & Reports ── */
QTextEdit {{
    background-color: {c["control_bg"]};
    color: {c["text_primary"]};
    border: 1px solid {c["card_border"]};
    border-radius: 8px;
    padding: 10px;
    font-family: 'Cascadia Code', 'Consolas', 'Courier New', monospace;
    font-size: 12px;
    line-height: 1.4;
}}

/* ── Splitters & Scrollbars ── */
QSplitter::handle {{
    background-color: {c["card_border"]};
    width: 2px;
    height: 2px;
}}

QScrollBar:vertical {{
    background: {c["control_bg"]};
    width: 8px;
    border-radius: 4px;
}}

QScrollBar::handle:vertical {{
    background: {c["card_border"]};
    min-height: 20px;
    border-radius: 4px;
}}

QScrollBar::handle:vertical:hover {{
    background: {c["primary_accent"]};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}

/* ── Tooltips ── */
QToolTip {{
    background-color: {c["card_bg"]};
    color: {c["text_primary"]};
    border: 1px solid {c["card_border"]};
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 12px;
}}
"""


DARK_THEME_QSS: str = build_qss(FX_COLORS_DARK)
LIGHT_THEME_QSS: str = build_qss(FX_COLORS_LIGHT)


def load_app_fonts() -> bool:
    """
    Register bundled FxSound-style fonts (Manrope) with QFontDatabase and
    rebuild both theme stylesheets so QSS picks up the new family stack.
    Must be called AFTER QApplication is constructed. Safe to call twice.
    Returns True when at least one bundled font family was registered.
    """
    global FONT_FAMILY_STACK, DARK_THEME_QSS, LIGHT_THEME_QSS
    loaded_any = False
    try:
        from PySide6.QtGui import QFontDatabase
        base_dir = os.path.dirname(os.path.abspath(__file__))
        for font_file in _BUNDLED_FONTS:
            font_path = os.path.join(base_dir, "fonts", font_file)
            if not os.path.exists(font_path):
                continue
            font_id = QFontDatabase.addApplicationFont(font_path)
            if font_id < 0:
                continue
            families = QFontDatabase.applicationFontFamilies(font_id)
            if not families:
                continue
            family = families[0]
            if family not in FONT_FAMILY_STACK:
                FONT_FAMILY_STACK = f"'{family}', {FONT_FAMILY_STACK}"
            loaded_any = True
    except Exception:
        loaded_any = False
    DARK_THEME_QSS = build_qss(FX_COLORS_DARK)
    LIGHT_THEME_QSS = build_qss(FX_COLORS_LIGHT)
    return loaded_any


def get_qss(is_dark_theme: bool = True) -> str:
    """Retrieve full application stylesheet for given theme mode."""
    return DARK_THEME_QSS if is_dark_theme else LIGHT_THEME_QSS
