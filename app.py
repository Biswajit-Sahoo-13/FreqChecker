"""
app.py - Main desktop application for FreqChecker: Adaptive Speaker Frequency Diagnostic Tool.
Featuring FxSound-inspired dark/light aesthetics, 9-band animated EQ visualizer, streamlined 1-touch
auto-advance testing, log sweep, log-mapped manual tone generator, and real-music A/B speaker comparison.
"""

import os
import sys
import time
import json
import math
import faulthandler
import traceback
import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QStackedWidget, QVBoxLayout,
    QHBoxLayout, QLabel, QPushButton, QSlider, QComboBox, QCheckBox,
    QProgressBar, QTextEdit, QFileDialog, QMessageBox, QFrame,
    QSplitter, QSpinBox, QDoubleSpinBox, QSizePolicy, QScrollArea
)
from PySide6.QtCore import Qt, QTimer, Signal, QObject, Slot, QSize, QPoint
from PySide6.QtGui import QKeySequence, QShortcut, QPainter, QColor, QPainterPath, QIcon

from models import (
    Measurement, Region, ChannelResult, Session,
    Classification, Stage, RegionCategory, practical_round_freq
)
from audio_engine import AudioEngine
from diagnostic_core import DiagnosticController, DiagnosticConfig, TestScheduler
from ui_components import LogFrequencyPlotWidget, FxSpectrumVisualizerWidget
import fx_theme
from fx_theme import DARK_THEME_QSS, LIGHT_THEME_QSS, get_fx_color
from icons import get_svg_icon, get_svg_pixmap


def _setup_crash_logger():
    """Enable faulthandler and top-level excepthook to capture unhandled crashes to disk."""
    if getattr(sys, "frozen", False):
        app_dir = os.path.dirname(sys.executable)
    else:
        app_dir = os.path.dirname(os.path.abspath(__file__))
    log_path = os.path.join(app_dir, "freqchecker_crash.log")

    try:
        if sys.stderr is not None:
            faulthandler.enable()
        else:
            crash_file = open(log_path, "a", encoding="utf-8")
            faulthandler.enable(file=crash_file)
    except Exception:
        pass

    def _handle_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            if sys.__excepthook__:
                sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"\n[{datetime.datetime.now().isoformat()}] UNCAUGHT EXCEPTION:\n")
                traceback.print_exception(exc_type, exc_value, exc_traceback, file=f)
        except Exception:
            pass
        if sys.__excepthook__:
            try:
                sys.__excepthook__(exc_type, exc_value, exc_traceback)
            except Exception:
                pass

    sys.excepthook = _handle_exception

_setup_crash_logger()

try:
    import soundfile  # noqa: F401
    SOUNDFILE_AVAILABLE = True
except ImportError:
    SOUNDFILE_AVAILABLE = False

# Page indices
PAGE_WIZARD = 0
PAGE_TESTING = 1
PAGE_MANUAL = 2
PAGE_SWEEP = 3
PAGE_RESULTS = 4
PAGE_MUSIC = 5


def _fmt_time(seconds: float) -> str:
    s = max(0, int(seconds))
    return f"{s // 60}:{s % 60:02d}"


class AudioSignalBridge(QObject):
    """
    Thread-safe bridge to marshal background audio events to Qt GUI main thread.
    """
    playback_started = Signal(float)  # target frequency
    playback_finished = Signal(bool, str)
    sweep_started = Signal()
    music_started = Signal()
    music_finished = Signal(bool, str)
    preflight_detected = Signal(dict)


class FxTitleBar(QWidget):
    """FxSound-exact custom title bar: 57px, #181818/#f5f5f5, drag + min/close, rounded top."""

    def __init__(self, parent_window: QMainWindow):
        super().__init__(parent_window)
        self._win = parent_window
        self._drag_pos: Optional[QPoint] = None
        self.setFixedHeight(38)
        self.setAttribute(Qt.WA_StyledBackground, True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(18, 0, 10, 0)
        lay.setSpacing(10)
        # Brand — clickable to homepage (Home) + Back button
        self.btn_back = QPushButton()
        self.btn_back.setIcon(get_svg_icon("arrow-left", color="#b1b1b1"))
        self.btn_back.setIconSize(QSize(16, 16))
        self.btn_back.setFixedSize(28, 28)
        self.btn_back.setToolTip("Back")
        self.btn_back.setStyleSheet("QPushButton { background: rgba(255,255,255,0.06); border: 1px solid #2b2b2b; border-radius: 7px; } QPushButton:hover { background: rgba(255,255,255,0.10); border-color:#3a3a3a; } QPushButton:disabled { opacity: 0.35; }")
        self.btn_back.clicked.connect(lambda: self._win._go_back())
        lay.addWidget(self.btn_back)
        lay.addSpacing(4)
        # FxSound-style vector logo bars + title (original artwork) — whole brand is Home button
        self.brand_btn = QPushButton()
        self.brand_btn.setCursor(Qt.PointingHandCursor)
        self.brand_btn.setToolTip("Go to Homepage")
        self.brand_btn.setStyleSheet("QPushButton { background: transparent; border: none; text-align: left; } QPushButton:hover { background: rgba(255,255,255,0.06); border-radius: 8px; }")
        brand_lay = QHBoxLayout(self.brand_btn)
        brand_lay.setContentsMargins(6, 2, 8, 2)
        brand_lay.setSpacing(8)
        self.lbl_icon = QLabel()
        self.lbl_icon.setFixedSize(22, 22)
        self.lbl_icon.setAlignment(Qt.AlignCenter)
        self.lbl_title_col = QWidget()
        self.lbl_title_col.setStyleSheet("background: transparent; border: none;")
        title_col = QVBoxLayout(self.lbl_title_col)
        title_col.setContentsMargins(0, 2, 0, 2)
        title_col.setSpacing(1)
        self.lbl_title = QLabel("FREQCHECKER")
        self.lbl_title.setStyleSheet("font-size: 12px; font-weight: 800; letter-spacing: 1.2px; color: #ffffff; background: transparent; border: none;")
        self.lbl_sub = QLabel("SPEAKER DIAGNOSTIC STUDIO")
        self.lbl_sub.setStyleSheet("font-size: 9px; font-weight: 600; color: #7f7f7f; background: transparent; border: none; letter-spacing: 0.8px;")
        title_col.addWidget(self.lbl_title)
        title_col.addWidget(self.lbl_sub)
        brand_lay.addWidget(self.lbl_icon)
        brand_lay.addWidget(self.lbl_title_col)
        self.brand_btn.clicked.connect(lambda: self._win._go_home())
        lay.addWidget(self.brand_btn)
        lay.addSpacing(6)
        # Window controls - FxSound thin-line SVG glyphs with crimson close hover
        self.btn_min = QPushButton()
        self.btn_min.setIcon(get_svg_icon("minimize", color="#b1b1b1"))
        self.btn_min.setIconSize(QSize(14, 14))
        self.btn_min.setFixedSize(32, 26)
        self.btn_min.setToolTip("Minimize")
        self.btn_min.setStyleSheet("QPushButton { background: transparent; border: none; border-radius: 6px; } QPushButton:hover { background: rgba(255,255,255,0.08); }")
        self.btn_min.clicked.connect(self._win.showMinimized)
        self.btn_max = QPushButton()
        self.btn_max.setIcon(get_svg_icon("maximize", color="#b1b1b1"))
        self.btn_max.setIconSize(QSize(14, 14))
        self.btn_max.setFixedSize(32, 26)
        self.btn_max.setToolTip("Maximize / Restore")
        self.btn_max.setStyleSheet("QPushButton { background: transparent; border: none; border-radius: 6px; } QPushButton:hover { background: rgba(255,255,255,0.08); }")
        self.btn_max.clicked.connect(self._toggle_maximize)
        self.btn_full = QPushButton()
        self.btn_full.setIcon(get_svg_icon("fullscreen", color="#b1b1b1"))
        self.btn_full.setIconSize(QSize(14, 14))
        self.btn_full.setFixedSize(32, 26)
        self.btn_full.setToolTip("Full Screen (F11)")
        self.btn_full.setStyleSheet("QPushButton { background: transparent; border: none; border-radius: 6px; } QPushButton:hover { background: rgba(255,255,255,0.08); }")
        self.btn_full.clicked.connect(self._win.toggleFullscreen)
        self.btn_close = QPushButton()
        self.btn_close.setIcon(get_svg_icon("close", color="#b1b1b1"))
        self.btn_close.setIconSize(QSize(14, 14))
        self.btn_close.setFixedSize(32, 26)
        self.btn_close.setToolTip("Close")
        self.btn_close.setStyleSheet("QPushButton { background: transparent; border: none; border-radius: 6px; } QPushButton:hover { background: #d51535; }")
        self.btn_close.clicked.connect(self._win.close)
        lay.addWidget(self.btn_min)
        lay.addWidget(self.btn_max)
        lay.addWidget(self.btn_full)
        lay.addWidget(self.btn_close)

    def _toggle_maximize(self):
        if self._win.isMaximized():
            self._win.showNormal()
        else:
            self._win.showMaximized()

    def update_theme(self, is_dark: bool):
        bg = "#181818" if is_dark else "#f5f5f5"
        tc = "#ffffff" if is_dark else "#1f1f1f"
        sc = "#7f7f7f"
        ac = "#d51535" if is_dark else "#1ac1ff"
        icon_c = "#b1b1b1" if is_dark else "#5a5a5a"
        # When maximized in frameless mode, remove top radius to fill screen
        is_max = self._win.isMaximized()
        r = 0 if is_max else 12
        self.setStyleSheet(f"background-color: {bg}; border: none; border-top-left-radius: {r}px; border-top-right-radius: {r}px;")
        self.lbl_title.setStyleSheet(f"font-size: 12px; font-weight: 800; letter-spacing: 1.2px; color: {tc}; background: transparent; border: none;")
        self.lbl_sub.setStyleSheet(f"font-size: 9px; font-weight: 600; color: {sc}; background: transparent; border: none; letter-spacing: 0.8px;")
        # premium mark — load from assets/icon.svg if present, else fallback to vector bars
        try:
            _p = Path(__file__).parent / "assets" / "icon.svg"
            if _p.exists():
                _ic = QIcon(str(_p))
                self.lbl_icon.setPixmap(_ic.pixmap(QSize(18, 18)))
            else:
                self.lbl_icon.setPixmap(get_svg_pixmap("logo-bars", color=ac, size=QSize(18, 18)))
        except Exception:
            self.lbl_icon.setPixmap(get_svg_pixmap("logo-bars", color=ac, size=QSize(18, 18)))
        self.btn_back.setIcon(get_svg_icon("arrow-left", color=icon_c))
        self.btn_min.setIcon(get_svg_icon("minimize", color=icon_c))
        self.btn_max.setIcon(get_svg_icon("maximize", color=icon_c))
        # fullscreen icon reflects current state
        is_fs = self._win.isFullScreen()
        self.btn_full.setIcon(get_svg_icon("fullscreen-exit" if is_fs else "fullscreen", color=icon_c))
        self.btn_full.setToolTip("Exit Full Screen (F11/Esc)" if is_fs else "Full Screen (F11)")
        self.btn_close.setIcon(get_svg_icon("close", color=icon_c))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self._win.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton and self._drag_pos is not None:
            self._win.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_pos = None

    def mouseDoubleClickEvent(self, event):
        if self._win.isMaximized():
            self._win.showNormal()
        else:
            self._win.showMaximized()


class FreqCheckerApp(QMainWindow):
    """
    Main application window implementing all diagnostic modes, wizards, and report dashboards.
    """
    def __init__(self, frameless: bool = False):
        super().__init__()
        self.setWindowTitle("FreqChecker — Speaker Diagnostic Studio")
        # Window icon — premium SVG mark (fallback to built-in if file missing)
        try:
            _base = Path(__file__).parent
            _icon_p = _base / "assets" / "icon.svg"
            if _icon_p.exists():
                self.setWindowIcon(QIcon(str(_icon_p)))
            else:
                # fallback: use vector bars pixmap
                self.setWindowIcon(get_svg_icon("logo-bars", color="#d51535"))
        except Exception:
            pass
        self.resize(1120, 740)
        self.setMinimumSize(960, 640)
        self.is_dark_theme: bool = True
        self._frameless = frameless
        self._nav_history: List[int] = []
        self._current_page: int = PAGE_WIZARD
        if frameless:
            self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window | Qt.WindowMinMaxButtonsHint | Qt.WindowSystemMenuHint)
            self.setAttribute(Qt.WA_TranslucentBackground, True)
            # Container for frameless rounded + shadow (FxSound 21px radius homage, 12px practical)
            self._frame_container = QFrame()
            self._frame_container.setObjectName("FramelessContainer")
            self._frame_container.setStyleSheet(f"QFrame#FramelessContainer {{ background-color: {'#181818' if self.is_dark_theme else '#f5f5f5'}; border: 1px solid {'#2b2b2b' if self.is_dark_theme else '#d9d9d9'}; border-radius: 12px; }}")
            outer = QVBoxLayout(self._frame_container)
            outer.setContentsMargins(1, 1, 1, 1)
            outer.setSpacing(0)
            self._title_bar = FxTitleBar(self)
            self._title_bar.update_theme(self.is_dark_theme)
            outer.addWidget(self._title_bar)
            # placeholder for central handled below - keep ref to inject
        else:
            # Ensure native window has Min/Max/Close (fixes missing maximize in screenshot)
            self.setWindowFlags(self.windowFlags() | Qt.WindowMinMaxButtonsHint | Qt.WindowSystemMenuHint)
        
        # Audio Engine & Thread Bridge
        self.audio_engine = AudioEngine(sample_rate=48000, default_peak=0.4)
        self.audio_bridge = AudioSignalBridge()
        self.audio_bridge.playback_started.connect(self._on_playback_started_ui)
        self.audio_bridge.playback_finished.connect(self._on_playback_finished_ui)
        self.audio_bridge.sweep_started.connect(self._on_sweep_started_ui)
        self.audio_bridge.music_started.connect(self._on_music_started_ui)
        self.audio_bridge.music_finished.connect(self._on_music_finished_ui)
        self.audio_bridge.preflight_detected.connect(self._apply_preflight_results)
        
        self.session: Optional[Session] = None
        self.current_channel: str = "left"
        self.channels_to_test: List[str] = ["left", "right"]
        self.channel_idx: int = 0
        self.start_time: float = 0.0
        self._tone_started_at: Optional[float] = None
        self._consecutive_stopped_ticks: int = 0
        self.last_playback_ok: Optional[bool] = None
        self._heard_selection: Optional[bool] = None
        self.sweep_start_time: Optional[float] = None
        self.blind_mode: bool = False
        self._progress_floor: int = 0
        self._max_queue_len: int = 0
        self._sweep_retest_active: bool = False
        self._manual_retest_freqs: List[float] = []
        
        # Music state
        self.music_original: Optional[Any] = None
        self.music_file_sr: int = 48000
        self._music_cache: Optional[Any] = None
        self._music_cache_rate: int = 0
        self.music_channel: str = "both"
        self.music_pos_sec: float = 0.0
        self.music_playing: bool = False
        self._music_active: bool = False
        self._music_started_wall: Optional[float] = None
        self._music_offset_sec: float = 0.0
        self._music_total_sec: float = 0.0
        
        # Diagnostic Controller & Pure Test Scheduler
        self.controller = DiagnosticController(mode="detailed")
        self.scheduler = TestScheduler(mode="detailed")
        
        # Central Widget (frameless wrapper if enabled)
        self.central_widget = QWidget()
        self.central_widget.setObjectName("CentralWidget")
        self.main_layout = QVBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(18, 14, 18, 16)
        self.main_layout.setSpacing(12)
        if self._frameless:
            # Embed central into frameless container
            outer = self._frame_container.layout()
            outer.addWidget(self.central_widget, 1)
            wrapper = QWidget()
            wrapper.setAttribute(Qt.WA_TranslucentBackground, True)
            wlay = QVBoxLayout(wrapper)
            wlay.setContentsMargins(8, 8, 8, 8)
            wlay.addWidget(self._frame_container)
            self.setCentralWidget(wrapper)
        else:
            self.setCentralWidget(self.central_widget)
        
        # Build Global Top Navigation Bar
        self._build_top_navbar()
        
        # Stacked Views — wrapped in QScrollArea so small / short windows scroll instead of clipping (fixes minimized text cut)
        self.stack = QStackedWidget()
        self.stack_scroll = QScrollArea()
        self.stack_scroll.setWidgetResizable(True)
        self.stack_scroll.setFrameShape(QFrame.NoFrame)
        self.stack_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.stack_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.stack_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        _scroll_container = QWidget()
        _scroll_container.setStyleSheet("background: transparent;")
        _scroll_lay = QVBoxLayout(_scroll_container)
        _scroll_lay.setContentsMargins(0, 0, 0, 0)
        _scroll_lay.setSpacing(0)
        _scroll_lay.addWidget(self.stack)
        self.stack_scroll.setWidget(_scroll_container)
        self.main_layout.addWidget(self.stack_scroll, 1)
        
        # Build Subviews
        self._build_wizard_view()
        self._build_testing_view()
        self._build_manual_view()
        self._build_sweep_view()
        self._build_results_view()
        self._build_music_view()
        
        # Keyboard shortcuts
        self._setup_shortcuts()
        
        # Load audio devices
        self._populate_audio_devices()
        
        # Start on wizard
        self._switch_page(PAGE_WIZARD)

    def _has_unsaved_progress(self) -> bool:
        return bool(
            self.session
            and any(len(r.measurements) for r in self.session.channel_results.values())
        )

    def _autosave_session_json(self) -> Optional[str]:
        if not self.session:
            return None
        try:
            if getattr(sys, "frozen", False):
                base_dir = os.path.dirname(sys.executable)
            else:
                base_dir = os.path.dirname(os.path.abspath(__file__))
            save_dir = os.path.join(base_dir, "saved_sessions")
            os.makedirs(save_dir, exist_ok=True)
            path = os.path.join(save_dir, f"session_{self.session.session_id}.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.session.to_dict(), f, indent=2)
            return path
        except Exception:
            return None

    def _offer_partial_save(self) -> bool:
        """
        Ask the user what to do with in-progress session data.
        Returns True when it is OK to proceed (saved or discarded), False to stay.
        """
        if not self._has_unsaved_progress():
            return True
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Question)
        box.setWindowTitle("Unsaved Diagnostic Progress")
        box.setText("This session has recorded ratings that are not saved yet.")
        box.setInformativeText("Save a partial session file before continuing?")
        save_btn = box.addButton("Save Partial", QMessageBox.AcceptRole)
        discard_btn = box.addButton("Discard", QMessageBox.DestructiveRole)
        cancel_btn = box.addButton("Cancel", QMessageBox.RejectRole)
        box.setDefaultButton(cancel_btn)
        box.exec()
        clicked = box.clickedButton()
        if clicked == save_btn:
            path = self._autosave_session_json()
            if path:
                QMessageBox.information(self, "Session Saved", f"Partial session saved to:\n{path}")
            else:
                QMessageBox.warning(self, "Save Failed", "Could not write the session file. Nothing was saved.")
            return True
        if clicked == discard_btn:
            return True
        return False

    def closeEvent(self, event):
        if hasattr(self, "stack") and self.stack.currentIndex() == PAGE_TESTING:
            self.audio_engine.stop_playback()
            if not self._offer_partial_save():
                event.ignore()
                return
            reply = QMessageBox.question(
                self,
                "Exit Diagnostic Test?",
                "Do you want to exit the application now?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                event.ignore()
                return

        if hasattr(self, "sweep_timer"):
            self.sweep_timer.stop()
        if hasattr(self, "music_timer"):
            self.music_timer.stop()
        self.audio_engine.stop_playback()
        event.accept()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Responsive: on narrow windows (<1020px) stack columns vertically so no text clipped / alignment survives minimized
        narrow = self.width() < 1020
        short = self.height() < 700
        for name in ("wizard_splitter", "manual_splitter", "sweep_splitter", "results_splitter"):
            sp = getattr(self, name, None)
            if sp is not None:
                target = Qt.Vertical if narrow else Qt.Horizontal
                # results: also go vertical when window is short
                if name == "results_splitter" and (narrow or short):
                    target = Qt.Vertical
                if sp.orientation() != target:
                    sp.setOrientation(target)
                    if target == Qt.Vertical:
                        total = sp.height() if sp.height() > 100 else (400 if name=="results_splitter" else 600)
                        if name == "results_splitter":
                            sp.setSizes([260, 220])
                        else:
                            sp.setSizes([int(total*0.45), int(total*0.55)])
                    else:
                        if name == "results_splitter":
                            sp.setSizes([620, 360])
                        else:
                            sp.setSizes([480, 520])

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == event.Type.WindowStateChange and hasattr(self, "_title_bar"):
            # update title bar radius / icon color on maximize / restore
            self._title_bar.update_theme(self.is_dark_theme)
            if hasattr(self, "_frame_container"):
                is_max = self.isMaximized()
                r = 0 if is_max else 12
                # frameless container: square when maximized, rounded when restored
                self._frame_container.setStyleSheet(
                    f"QFrame#FramelessContainer {{ background-color: {'#181818' if self.is_dark_theme else '#f5f5f5'}; border: {'none' if is_max else '1px solid ' + ('#2b2b2b' if self.is_dark_theme else '#d9d9d9')}; border-radius: {r}px; }}"
                )

    # =========================================================================
    # GLOBAL TOP NAVBAR & THEME SWITCHER
    # =========================================================================
    def _build_top_navbar(self):
        nav_card = QFrame()
        nav_card.setProperty("class", "card")
        n_layout = QHBoxLayout(nav_card)
        n_layout.setContentsMargins(20, 12, 20, 12)
        n_layout.setSpacing(16)
        
        # Back — always visible, goes to previous page or Home
        self.btn_nav_back = QPushButton()
        self.btn_nav_back.setIcon(get_svg_icon("arrow-left", color="#b1b1b1"))
        self.btn_nav_back.setIconSize(QSize(16, 16))
        self.btn_nav_back.setFixedSize(32, 32)
        self.btn_nav_back.setToolTip("Back")
        self.btn_nav_back.setStyleSheet("QPushButton { background: rgba(255,255,255,0.06); border: 1px solid #2b2b2b; border-radius: 8px; } QPushButton:hover { background: rgba(255,255,255,0.10); border-color:#3a3a3a; } QPushButton:disabled { opacity: 0.35; }")
        self.btn_nav_back.clicked.connect(lambda: self._go_back())
        n_layout.addWidget(self.btn_nav_back)
        # Brand / Logo — clickable to Homepage
        brand_frame = QFrame()
        brand_frame.setCursor(Qt.PointingHandCursor)
        brand_frame.setToolTip("Go to Homepage — click logo to return home")
        brand_frame.setStyleSheet("QFrame { background: transparent; border: none; border-radius: 8px; } QFrame:hover { background: rgba(255,255,255,0.06); }")
        brand_layout = QVBoxLayout(brand_frame)
        brand_layout.setContentsMargins(6, 4, 6, 4)
        brand_layout.setSpacing(0)
        lbl_brand = QLabel("FREQCHECKER")
        lbl_brand.setProperty("class", "brand-title")
        lbl_brand.setStyleSheet("background: transparent; border: none;")
        lbl_tag = QLabel("SPEAKER DIAGNOSTIC STUDIO")
        lbl_tag.setProperty("class", "hint")
        lbl_tag.setStyleSheet("background: transparent; border: none;")
        brand_layout.addWidget(lbl_brand)
        brand_layout.addWidget(lbl_tag)
        # click anywhere on brand goes home
        def _brand_click(event):
            if event.button() == Qt.LeftButton:
                self._go_home()
        brand_frame.mousePressEvent = _brand_click
        n_layout.addWidget(brand_frame)
        n_layout.addStretch()
        
        # Top Center 9-Band Spectrum Visualizer Monitor Box — more enhanced: taller, bordered, live LED
        vis_container = QFrame()
        vis_container.setProperty("class", "card")
        vis_container.setStyleSheet("QFrame[class=\"card\"] { background-color: #0f0f0f; border: 1px solid #2b2b2b; border-radius: 10px; }")
        vis_layout = QVBoxLayout(vis_container)
        vis_layout.setContentsMargins(12, 8, 12, 10)
        vis_layout.setSpacing(6)
        vis_layout.setAlignment(Qt.AlignCenter)
        
        vis_header = QHBoxLayout()
        vis_header.setSpacing(6)
        vis_header.setAlignment(Qt.AlignCenter)
        self.lbl_vis_dot = QLabel()
        self.lbl_vis_dot.setFixedSize(8, 8)
        self.lbl_vis_dot.setStyleSheet("background-color: #3a3a3a; border-radius: 4px; border: none;")
        self.lbl_vis_dot.setToolTip("Live — animates while audio is playing")
        lbl_vis_title = QLabel("LIVE 9-BAND SPECTRUM MONITOR")
        lbl_vis_title.setProperty("class", "section-title")
        lbl_vis_title.setStyleSheet("font-size: 11px; font-weight: 800; letter-spacing: 0.8px; color: #ffffff; background: transparent; border: none;")
        lbl_vis_desc = QLabel("(63 Hz – 16 kHz)")
        lbl_vis_desc.setProperty("class", "hint")
        vis_header.addWidget(self.lbl_vis_dot)
        vis_header.addWidget(lbl_vis_title)
        vis_header.addWidget(lbl_vis_desc)
        vis_layout.addLayout(vis_header)
        
        self.top_visualizer = FxSpectrumVisualizerWidget(height=78)
        self.top_visualizer.set_provider(self._get_spectrum_values)
        # more FxSound-like: subtle inner glow via stylesheet on the custom widget is painted, so keep transparent wrapper
        self.top_visualizer.setStyleSheet("background: transparent; border: none;")
        vis_layout.addWidget(self.top_visualizer)
        n_layout.addWidget(vis_container, 1)
        n_layout.addStretch()

        # Full Screen — prominent so user finds it (was missing)
        self.btn_nav_full = QPushButton()
        self.btn_nav_full.setIcon(get_svg_icon("fullscreen", color="#b1b1b1"))
        self.btn_nav_full.setIconSize(QSize(16, 16))
        self.btn_nav_full.setFixedSize(34, 34)
        self.btn_nav_full.setToolTip("Full Screen (F11)")
        self.btn_nav_full.setStyleSheet("QPushButton { background: rgba(255,255,255,0.06); border: 1px solid #2b2b2b; border-radius: 8px; } QPushButton:hover { background: rgba(255,255,255,0.10); border-color:#3a3a3a; }")
        self.btn_nav_full.clicked.connect(self.toggleFullscreen)
        n_layout.addWidget(self.btn_nav_full)
        
        # Theme Switcher Button with SVG Icon
        self.btn_theme_toggle = QPushButton("Dark Mode")
        self.btn_theme_toggle.setProperty("class", "secondary")
        self.btn_theme_toggle.setFixedHeight(34)
        self.btn_theme_toggle.setIcon(get_svg_icon("moon", color=get_fx_color("primary_accent", True)))
        self.btn_theme_toggle.setIconSize(QSize(16, 16))
        self.btn_theme_toggle.clicked.connect(self._toggle_theme)
        n_layout.addWidget(self.btn_theme_toggle)
        
        self.main_layout.addWidget(nav_card)

    def _get_spectrum_values(self) -> Optional[List[float]]:
        """Data provider for real-time spectrum visualizer during active playback.

        Returns genuine 9-band FFT energies computed by the audio engine from
        the buffer actually being played; None when nothing is playing.
        """
        try:
            return self.audio_engine.get_spectrum_bands()
        except Exception:
            return None

    def _toggle_theme(self):
        self.is_dark_theme = not self.is_dark_theme
        fx_theme.set_theme("dark" if self.is_dark_theme else "light")
        qss = fx_theme.get_qss(self.is_dark_theme)
        QApplication.instance().setStyleSheet(qss)
        accent = get_fx_color("primary_accent", self.is_dark_theme)
        cyan = get_fx_color("cyan_secondary", self.is_dark_theme)
        if self.is_dark_theme:
            self.btn_theme_toggle.setText("Dark Mode")
            self.btn_theme_toggle.setIcon(get_svg_icon("moon", color=accent))
        else:
            self.btn_theme_toggle.setText("Light Mode")
            self.btn_theme_toggle.setIcon(get_svg_icon("sun", color=accent))
        # Update dynamic accent icons across the app
        self._refresh_accent_icons()
        if hasattr(self, "_title_bar"):
            self._title_bar.update_theme(self.is_dark_theme)
            # frameless container border
            self._frame_container.setStyleSheet(f"QFrame#FramelessContainer {{ background-color: {'#181818' if self.is_dark_theme else '#f5f5f5'}; border: 1px solid {'#2b2b2b' if self.is_dark_theme else '#d9d9d9'}; border-radius: 12px; }}")
        # nav fullscreen icon follows theme + fullscreen state
        if hasattr(self, "btn_nav_full"):
            is_fs = self.isFullScreen()
            icon = "fullscreen-exit" if is_fs else "fullscreen"
            col = "#b1b1b1" if self.is_dark_theme else "#5a5a5a"
            self.btn_nav_full.setIcon(get_svg_icon(icon, color=col))
        self.live_plot.set_theme(self.is_dark_theme)
        self.results_plot.set_theme(self.is_dark_theme)
        self._update_channel_badge()
        self.update()  # repaint frameless shadow/border

    def _refresh_accent_icons(self):
        """Refresh all accent-colored SVG icons after theme swap (FxSound palette)."""
        accent = get_fx_color("primary_accent", self.is_dark_theme)
        # Wizard calibration toggle — keep danger white when stop-active
        if hasattr(self, "btn_cal_toggle"):
            if getattr(self, "_is_calibrating", False):
                self.btn_cal_toggle.setIcon(get_svg_icon("stop", color="#FFFFFF"))
            else:
                self.btn_cal_toggle.setIcon(get_svg_icon("play", color=accent))
        if hasattr(self, "btn_autodetect"):
            self.btn_autodetect.setIcon(get_svg_icon("zap", color=accent))
        for name in ("btn_manual", "btn_sweep", "btn_music"):
            if hasattr(self, name):
                getattr(self, name).setIcon(get_svg_icon("activity" if "manual" in name or "sweep" in name else "volume-2", color=accent))
        if hasattr(self, "btn_replay"):
            self.btn_replay.setIcon(get_svg_icon("rotate-ccw", color=accent))
        if hasattr(self, "btn_music_load"):
            self.btn_music_load.setIcon(get_svg_icon("folder", color=accent))
        for name in ("btn_csv", "btn_json", "btn_txt", "btn_load", "btn_stress"):
            btn = getattr(self, name, None)
            if btn is not None:
                icon_name = "file-text" if name == "btn_txt" else ("folder" if name == "btn_load" else "volume-2" if name == "btn_stress" else "download")
                btn.setIcon(get_svg_icon(icon_name, color=accent))
        # arrow backs
        for child in self.findChildren(QPushButton):
            if child.text().strip().startswith("Return"):
                child.setIcon(get_svg_icon("arrow-left", color=accent))

    def _switch_page(self, index: int):
        # track history for Back/Home
        if hasattr(self, "_current_page") and self._current_page != index:
            if not hasattr(self, "_nav_history"):
                self._nav_history = []
            self._nav_history.append(self._current_page)
            if len(self._nav_history) > 20:
                self._nav_history.pop(0)
        self._current_page = index
        self.stack.setCurrentIndex(index)
        self._update_back_buttons()

    def _go_home(self):
        try:
            self.audio_engine.stop_playback()
            self.top_visualizer.stop_and_clear()
        except Exception:
            pass
        # avoid pushing history when going home
        if hasattr(self, "_nav_history"):
            self._nav_history.clear()
        self._current_page = PAGE_WIZARD
        self.stack.setCurrentIndex(PAGE_WIZARD)
        self._update_back_buttons()

    def _go_back(self):
        if hasattr(self, "_nav_history") and self._nav_history:
            prev = self._nav_history.pop()
            self._current_page = prev  # avoid double-push
            self.stack.setCurrentIndex(prev)
            self._update_back_buttons()
        else:
            self._go_home()

    def _update_back_buttons(self):
        has_back = bool(getattr(self, "_nav_history", [])) and getattr(self, "_current_page", PAGE_WIZARD) != PAGE_WIZARD
        for attr in ("btn_nav_back",):
            btn = getattr(self, attr, None)
            if btn is not None:
                btn.setEnabled(has_back)
                btn.setToolTip("Back" if has_back else "Already on Home")
        if hasattr(self, "_title_bar") and hasattr(self._title_bar, "btn_back"):
            self._title_bar.btn_back.setEnabled(has_back)
            self._title_bar.btn_back.setToolTip("Back" if has_back else "Already on Home")

    def toggleFullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()
        # refresh all fullscreen icons (title bar + nav)
        is_fs = self.isFullScreen()
        icon = "fullscreen-exit" if is_fs else "fullscreen"
        col = "#b1b1b1" if self.is_dark_theme else "#5a5a5a"
        tip = "Exit Full Screen (F11/Esc)" if is_fs else "Full Screen (F11)"
        if hasattr(self, "_title_bar") and hasattr(self._title_bar, "btn_full"):
            self._title_bar.btn_full.setIcon(get_svg_icon(icon, color=col))
            self._title_bar.btn_full.setToolTip(tip)
        if hasattr(self, "btn_nav_full"):
            self.btn_nav_full.setIcon(get_svg_icon(icon, color=col))
            self.btn_nav_full.setToolTip(tip)

    def _on_playback_started_ui(self, freq_hz: float = 1000.0):
        self._active_tone_freq = freq_hz
        self.btn_replay.setEnabled(False)
        self.top_visualizer.start_if_playing()
        # enhance live dot — LED turns crimson when playing
        if hasattr(self, "lbl_vis_dot"):
            self.lbl_vis_dot.setStyleSheet("background-color: #d51535; border-radius: 4px; border: none;")

    def _on_playback_finished_ui(self, ok: bool, err_msg: str):
        self.btn_replay.setEnabled(True)
        # Reset single calibration toggle to Play state when tone completes naturally
        if hasattr(self, "btn_cal_toggle") and getattr(self, "_is_calibrating", False):
            self._is_calibrating = False
            self.btn_cal_toggle.setText("Play 1 kHz Calibration Tone")
            self.btn_cal_toggle.setProperty("class", "secondary")
            self.btn_cal_toggle.setIcon(get_svg_icon("play", color="#d51535"))
            self.btn_cal_toggle.style().unpolish(self.btn_cal_toggle)
            self.btn_cal_toggle.style().polish(self.btn_cal_toggle)
            self.top_visualizer.stop_and_clear()
        # reset live dot
        if hasattr(self, "lbl_vis_dot"):
            self.lbl_vis_dot.setStyleSheet("background-color: #3a3a3a; border-radius: 4px; border: none;")
        self.last_playback_ok = ok
        if not ok and err_msg:
            self._show_playback_error(err_msg)

    def _show_playback_error(self, err_msg: str):
        if self.stack.currentIndex() == PAGE_TESTING:
            self.lbl_stage_info.setText("[Alert] Audio playback error - verify audio device")
        elif self.stack.currentIndex() == PAGE_MUSIC:
            self.lbl_music_status.setText(f"[Alert] Playback error: {err_msg}")
        else:
            QMessageBox.warning(self, "Playback Warning", f"Audio playback error:\n{err_msg}")

    # =========================================================================
    # SHORTCUTS (ERGONOMIC 1-TOUCH ADVANCE)
    # =========================================================================
    def _setup_shortcuts(self):
        QShortcut(QKeySequence("Y"), self, self._on_shortcut_yes)
        QShortcut(QKeySequence("N"), self, self._on_shortcut_no)
        QShortcut(QKeySequence("R"), self, self._on_shortcut_r)
        QShortcut(QKeySequence("Z"), self, self._on_shortcut_z)
        QShortcut(QKeySequence(Qt.Key_Escape), self, self._handle_esc)
        QShortcut(QKeySequence("F11"), self, self.toggleFullscreen)
        QShortcut(QKeySequence("T"), self, lambda: self._submit_with(True, 10))
        for i in range(10):
            QShortcut(QKeySequence(str(i)), self, lambda val=i: self._submit_with(True, val))

    def _handle_esc(self):
        if self.isFullScreen():
            self.toggleFullscreen()
        else:
            self._stop_current_test()

    def _on_shortcut_z(self):
        if self.stack.currentIndex() == PAGE_TESTING:
            self._undo_last_rating()

    def _on_shortcut_r(self):
        if self.stack.currentIndex() == PAGE_TESTING:
            self._replay_current_tone()

    def _on_shortcut_yes(self):
        if self.stack.currentIndex() == PAGE_TESTING:
            self._select_heard(True)

    def _on_shortcut_no(self):
        if self.stack.currentIndex() == PAGE_TESTING:
            self._submit_with(False)

    # =========================================================================
    # 1. WIZARD & SETUP VIEW (WITH MOVABLE QSplitter SIDE WINDOWS)
    # =========================================================================
    def _build_wizard_view(self):
        self.wizard_page = QWidget()
        layout = QVBoxLayout(self.wizard_page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        
        # Header Card
        header_card = QFrame()
        header_card.setProperty("class", "card")
        h_layout = QVBoxLayout(header_card)
        h_layout.setContentsMargins(22, 16, 22, 16)
        h_layout.setSpacing(4)
        
        title = QLabel("Speaker Health & Frequency Diagnostic")
        title.setProperty("class", "title")
        title.setWordWrap(True)
        subtitle = QLabel(
            "Perceptual 1/3-octave frequency sweep with adaptive bisection to locate speaker dips, distortion, and rolloff."
        )
        subtitle.setProperty("class", "subtitle")
        subtitle.setWordWrap(True)
        h_layout.addWidget(title)
        h_layout.addWidget(subtitle)
        layout.addWidget(header_card)
        
        # Movable Side Windows (QSplitter)
        self.wizard_splitter = QSplitter(Qt.Horizontal)
        self.wizard_splitter.setHandleWidth(8)
        self.wizard_splitter.setChildrenCollapsible(False)
        
        # Left Column: Device & Output
        col_left = QFrame()
        col_left.setProperty("class", "card")
        cl_layout = QVBoxLayout(col_left)
        cl_layout.setContentsMargins(20, 18, 20, 18)
        cl_layout.setSpacing(12)
        
        cl_title = QLabel("Audio Hardware")
        cl_title.setProperty("class", "section-title")
        cl_layout.addWidget(cl_title)
        cl_layout.addWidget(QLabel("Output Device:"))
        
        self.device_combo = QComboBox()
        self.device_combo.currentIndexChanged.connect(self._on_device_changed)
        cl_layout.addWidget(self.device_combo)
        
        # Single toggle Play/Stop Calibration (FxSound one-button design)
        self._is_calibrating = False
        self.btn_cal_toggle = QPushButton("Play 1 kHz Calibration Tone")
        self.btn_cal_toggle.setProperty("class", "secondary")
        self.btn_cal_toggle.setIcon(get_svg_icon("play", color="#d51535"))
        self.btn_cal_toggle.setIconSize(QSize(16, 16))
        self.btn_cal_toggle.setMinimumHeight(38)
        self.btn_cal_toggle.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.btn_cal_toggle.clicked.connect(self._toggle_calibration_tone)
        # Single button occupies full row — Stop state is the same button styled as danger
        cl_layout.addWidget(self.btn_cal_toggle)
        
        vol_info = QLabel(
            "- Keep system volume steady at 40-60% throughout the test.\n"
            "- Calibration tone plays on both channels to set your hearing baseline.\n"
            "- Use the Stop button anytime to silence calibration immediately."
        )
        vol_info.setStyleSheet("color: #b1b1b1; font-size: 11px;")
        vol_info.setWordWrap(True)
        cl_layout.addWidget(vol_info)
        
        cl_layout.addWidget(QLabel("Channel Configuration:"))
        self.channel_combo = QComboBox()
        self.channel_combo.addItem("Both (Left -> Right Sequential)", "both")
        self.channel_combo.addItem("Left Channel Only", "left")
        self.channel_combo.addItem("Right Channel Only", "right")
        cl_layout.addWidget(self.channel_combo)
        cl_layout.addStretch()
        self.wizard_splitter.addWidget(col_left)
        
        # Right Column: Checklist, Pre-Flight Auto-Detection & Start
        col_right = QFrame()
        col_right.setProperty("class", "card")
        cr_layout = QVBoxLayout(col_right)
        cr_layout.setContentsMargins(20, 18, 20, 18)
        cr_layout.setSpacing(10)
        
        cr_header_row = QHBoxLayout()
        cr_title = QLabel("Pre-Flight Calibration")
        cr_title.setProperty("class", "section-title")
        cr_header_row.addWidget(cr_title)
        cr_header_row.addStretch()
        
        self.btn_autodetect = QPushButton("Auto-Detect Conditions")
        self.btn_autodetect.setProperty("class", "secondary")
        self.btn_autodetect.setIcon(get_svg_icon("zap", color="#d51535"))
        self.btn_autodetect.setIconSize(QSize(14, 14))
        self.btn_autodetect.setFixedHeight(28)
        self.btn_autodetect.setToolTip("Auto-scans running DSP processes, audio hardware configuration, and ambient noise.")
        self.btn_autodetect.clicked.connect(self._run_preflight_autodetect)
        cr_header_row.addWidget(self.btn_autodetect)
        cr_layout.addLayout(cr_header_row)
        
        # Pre-Flight Auto-Detection Status Card
        status_box = QFrame()
        status_box.setStyleSheet(
            "background-color: rgba(15, 15, 15, 0.6); border: 1px solid #2b2b2b; border-radius: 8px; padding: 6px;"
        )
        sb_layout = QVBoxLayout(status_box)
        sb_layout.setContentsMargins(8, 6, 8, 6)
        sb_layout.setSpacing(6)
        
        self.lbl_dsp_badge = QLabel("[Info] DSP/EQ: Scanning processes...")
        self.lbl_dsp_badge.setProperty("class", "badge-info")
        self.lbl_dsp_badge.setWordWrap(True)
        
        self.lbl_hw_badge = QLabel("[Info] Hardware: Scanning audio configuration...")
        self.lbl_hw_badge.setProperty("class", "badge-info")
        self.lbl_hw_badge.setWordWrap(True)
        
        self.lbl_mic_badge = QLabel("[Info] Ambient Noise: Sampling room noise...")
        self.lbl_mic_badge.setProperty("class", "badge-info")
        self.lbl_mic_badge.setWordWrap(True)
        
        self.lbl_preflight_summary = QLabel("[Status] Pre-Flight Auto-Detection Active")
        self.lbl_preflight_summary.setStyleSheet("font-size: 10px; font-weight: 700; color: #d51535;")
        
        sb_layout.addWidget(self.lbl_dsp_badge)
        sb_layout.addWidget(self.lbl_hw_badge)
        sb_layout.addWidget(self.lbl_mic_badge)
        sb_layout.addWidget(self.lbl_preflight_summary)
        cr_layout.addWidget(status_box)
        
        self.chk_fxsound = QCheckBox("FxSound / EQ effects disabled (or accepted)")
        self.chk_fxsound.setChecked(True)
        self.chk_enhancements = QCheckBox("Windows Audio Enhancements / Spatial Sound off")
        self.chk_enhancements.setChecked(True)
        self.chk_quiet = QCheckBox("Quiet ambient listening environment")
        self.chk_quiet.setChecked(True)
        cr_layout.addWidget(self.chk_fxsound)
        cr_layout.addWidget(self.chk_enhancements)
        cr_layout.addWidget(self.chk_quiet)
        
        calib_note = QLabel("[Note] 1 kHz reference tones anchor your personal perception scale.")
        calib_note.setStyleSheet("color: #d51535; font-size: 11px; font-weight: 600;")
        calib_note.setWordWrap(True)
        cr_layout.addWidget(calib_note)
        
        cr_layout.addWidget(QLabel("Diagnostic Mode:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Detailed (25 × 1/3-Octave + Adaptive)", "detailed")
        self.mode_combo.addItem("Quick (6 tones from 250 Hz — laptop friendly)", "quick")
        self.mode_combo.setToolTip("Quick now starts at 250 Hz because most laptop drivers roll off below that. Use Detailed if you have headphones or large monitors.")
        cr_layout.addWidget(self.mode_combo)
        quick_hint = QLabel("Quick starts at 250 Hz to skip inaudible sub-bass on laptop speakers. Use Detailed for 63 Hz–16 kHz with roll-off-aware scoring.")
        quick_hint.setWordWrap(True)
        quick_hint.setStyleSheet("color: #7f7f7f; font-size: 11px; font-style: italic;")
        cr_layout.addWidget(quick_hint)
        self.chk_include_subbass = QCheckBox("Include sub-bass tones (63–200 Hz) even in Quick mode")
        self.chk_include_subbass.setToolTip("Enable to test 63, 80, 100, 125, 160, 200 Hz. Leave off if your speaker cannot reproduce bass — otherwise lows will appear as Expected low-frequency roll-off, not a failure.")
        cr_layout.addWidget(self.chk_include_subbass)

        self.chk_blind = QCheckBox("Blind Mode (hide frequency until rated)")
        self.chk_blind.setToolTip("Reduces expectation bias: the tone frequency stays hidden until the session ends.")
        cr_layout.addWidget(self.chk_blind)
        
        btn_start_diag = QPushButton("Start Diagnostic Test")
        btn_start_diag.setIcon(get_svg_icon("arrow-right", color="#FFFFFF"))
        btn_start_diag.setIconSize(QSize(16, 16))
        btn_start_diag.setStyleSheet("font-size: 14px; padding: 12px 24px; font-weight: 700;")
        btn_start_diag.clicked.connect(self._start_diagnostic_session)
        cr_layout.addWidget(btn_start_diag)
        
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.btn_manual = QPushButton("Manual Tone")
        self.btn_manual.setProperty("class", "secondary")
        self.btn_manual.setIcon(get_svg_icon("activity", color="#d51535"))
        self.btn_manual.clicked.connect(lambda: self._switch_page(PAGE_MANUAL))
        self.btn_sweep = QPushButton("Sweep Mode")
        self.btn_sweep.setProperty("class", "secondary")
        self.btn_sweep.setIcon(get_svg_icon("activity", color="#d51535"))
        self.btn_sweep.clicked.connect(lambda: self._switch_page(PAGE_SWEEP))
        self.btn_music = QPushButton("Music Test")
        self.btn_music.setProperty("class", "secondary")
        self.btn_music.setIcon(get_svg_icon("volume-2", color="#d51535"))
        self.btn_music.clicked.connect(lambda: self._switch_page(PAGE_MUSIC))
        btn_row.addWidget(self.btn_manual)
        btn_row.addWidget(self.btn_sweep)
        btn_row.addWidget(self.btn_music)
        cr_layout.addLayout(btn_row)
        cr_layout.addStretch()
        self.wizard_splitter.addWidget(col_right)
        
        self.wizard_splitter.setSizes([480, 520])
        layout.addWidget(self.wizard_splitter, 1)
        self.stack.addWidget(self.wizard_page)

    def _populate_audio_devices(self):
        self.device_combo.clear()
        devices = self.audio_engine.get_output_devices()
        default_idx = 0
        for i, dev in enumerate(devices):
            self.device_combo.addItem(dev["display_name"], dev["index"])
            if dev["is_default"]:
                default_idx = i
        if devices:
            self.device_combo.setCurrentIndex(default_idx)
        self._run_preflight_autodetect()

    def _on_device_changed(self):
        dev_idx = self.device_combo.currentData()
        self.audio_engine.set_output_device(dev_idx)
        self._run_preflight_autodetect()

    def _run_preflight_autodetect(self):
        dev_idx = self.device_combo.currentData() if hasattr(self, "device_combo") else None
        if hasattr(self, "lbl_preflight_summary"):
            self.lbl_preflight_summary.setText("[Status] Scanning audio environment in background...")
            self.lbl_preflight_summary.setStyleSheet("font-size: 10px; font-weight: 700; color: #7f7f7f;")
        import threading
        def worker():
            res = self.audio_engine.detect_preflight_conditions(dev_idx)
            self.audio_bridge.preflight_detected.emit(res)
        threading.Thread(target=worker, daemon=True).start()

    def _apply_preflight_results(self, res: dict):
        if not hasattr(self, "lbl_dsp_badge") or not hasattr(self, "lbl_hw_badge") or not hasattr(self, "lbl_mic_badge"):
            return
        
        # 1. DSP / EQ Enhancer Detection
        if res["fxsound_running"] or res["detected_enhancers"]:
            enh_str = ", ".join(res["detected_enhancers"]) if res["detected_enhancers"] else "FxSound"
            self.lbl_dsp_badge.setText(f"[Alert] {enh_str} Active (Disable to prevent frequency coloration)")
            self.lbl_dsp_badge.setProperty("class", "badge-warning")
            self.chk_fxsound.setChecked(False)
        else:
            self.lbl_dsp_badge.setText("[OK] No DSP / EQ Enhancers Active (Clean Output)")
            self.lbl_dsp_badge.setProperty("class", "badge-success")
            self.chk_fxsound.setChecked(True)
            
        # 2. Hardware / Enhancements Detection
        if res["is_virtual_device"]:
            self.lbl_hw_badge.setText(f"[Alert] Virtual/Cable Audio Device: {res['output_device_name']}")
            self.lbl_hw_badge.setProperty("class", "badge-warning")
            self.chk_enhancements.setChecked(False)
        elif res["output_channels"] >= 2:
            self.lbl_hw_badge.setText(f"[OK] Direct Hardware Stereo ({res['output_samplerate']:,} Hz · {res['output_channels']} ch)")
            self.lbl_hw_badge.setProperty("class", "badge-success")
            self.chk_enhancements.setChecked(True)
        else:
            self.lbl_hw_badge.setText(f"[Info] Mono Output Device ({res['output_channels']} channel)")
            self.lbl_hw_badge.setProperty("class", "badge-info")
            self.chk_enhancements.setChecked(True)
            
        # 3. Ambient Room Noise Detection (Microphone)
        if res["mic_available"] and res["ambient_dbfs"] is not None:
            if res["is_quiet"]:
                self.lbl_mic_badge.setText(f"[OK] Quiet Listening Environment ({res['ambient_dbfs']:.1f} dBFS)")
                self.lbl_mic_badge.setProperty("class", "badge-success")
                self.chk_quiet.setChecked(True)
            else:
                self.lbl_mic_badge.setText(f"[Alert] Elevated Room Noise ({res['ambient_dbfs']:.1f} dBFS) - Close doors/windows")
                self.lbl_mic_badge.setProperty("class", "badge-warning")
                self.chk_quiet.setChecked(False)
        else:
            self.lbl_mic_badge.setText("[Info] Microphone Unavailable - Please verify quiet room manually")
            self.lbl_mic_badge.setProperty("class", "badge-info")
            self.chk_quiet.setChecked(True)
            
        for badge in (self.lbl_dsp_badge, self.lbl_hw_badge, self.lbl_mic_badge):
            badge.style().unpolish(badge)
            badge.style().polish(badge)
            
        if res["all_clear"]:
            self.lbl_preflight_summary.setText("[Status] System Ready: All Pre-Flight Conditions Verified [OK]")
            self.lbl_preflight_summary.setStyleSheet("font-size: 10px; font-weight: 700; color: #d51535;")
        else:
            self.lbl_preflight_summary.setText("[Status] Pre-Flight Notice: Check recommendations above before starting")
            self.lbl_preflight_summary.setStyleSheet("font-size: 10px; font-weight: 700; color: #faad14;")

    def _toggle_calibration_tone(self):
        if getattr(self, "_is_calibrating", False):
            self._stop_calibration_tone()
        else:
            self._play_calibration_tone()

    def _play_calibration_tone(self):
        self._is_calibrating = True
        if hasattr(self, "btn_cal_toggle"):
            self.btn_cal_toggle.setText("Stop Calibration Tone")
            self.btn_cal_toggle.setProperty("class", "danger")
            self.btn_cal_toggle.setIcon(get_svg_icon("stop", color="#FFFFFF"))
            self.btn_cal_toggle.style().unpolish(self.btn_cal_toggle)
            self.btn_cal_toggle.style().polish(self.btn_cal_toggle)
        tone = self.audio_engine.generate_sine_tone(1000.0, duration_s=2.5, peak=0.4, channel="both")
        self.audio_engine.play_audio(
            tone,
            on_started=lambda: self.audio_bridge.playback_started.emit(1000.0),
            on_finished=lambda ok, err: self.audio_bridge.playback_finished.emit(ok, err or ""),
            spectrum_meta={"buffer": tone, "sample_rate": self.audio_engine.sample_rate}
        )

    def _stop_calibration_tone(self):
        self.audio_engine.stop_playback()
        self._is_calibrating = False
        if hasattr(self, "btn_cal_toggle"):
            self.btn_cal_toggle.setText("Play 1 kHz Calibration Tone")
            self.btn_cal_toggle.setProperty("class", "secondary")
            self.btn_cal_toggle.setIcon(get_svg_icon("play", color="#d51535"))
            self.btn_cal_toggle.style().unpolish(self.btn_cal_toggle)
            self.btn_cal_toggle.style().polish(self.btn_cal_toggle)
        self.top_visualizer.stop_and_clear()

    # =========================================================================
    # 2. ACTIVE DIAGNOSTIC TEST VIEW (STREAMLINED 1-TOUCH ADVANCE)
    # =========================================================================
    def _build_testing_view(self):
        self.testing_page = QWidget()
        layout = QVBoxLayout(self.testing_page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        
        # Top Status Bar
        top_bar = QFrame()
        top_bar.setProperty("class", "card")
        tb_layout = QHBoxLayout(top_bar)
        tb_layout.setContentsMargins(16, 8, 16, 8)
        tb_layout.setSpacing(12)
        
        self.lbl_channel_badge = QLabel("LEFT CHANNEL")
        self.lbl_channel_badge.setStyleSheet(
            "background: #d51535; color: #ffffff; padding: 5px 14px; border-radius: 7px; "
            "font-weight: 800; font-size: 11px; letter-spacing: 0.8px;"
        )
        
        self.lbl_stage_info = QLabel("Stage: Coarse Scan · 1/25")
        self.lbl_stage_info.setProperty("class", "subtitle")
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedWidth(160)
        
        self.lbl_remaining = QLabel("~24 tests left")
        self.lbl_remaining.setProperty("class", "hint")
        
        btn_stop = QPushButton("Stop (Esc)")
        btn_stop.setProperty("class", "danger")
        btn_stop.setIcon(get_svg_icon("stop", color="#FFFFFF"))
        btn_stop.setIconSize(QSize(12, 12))
        btn_stop.setFixedWidth(96)
        btn_stop.setFixedHeight(30)
        btn_stop.clicked.connect(self._stop_current_test)
        
        tb_layout.addWidget(self.lbl_channel_badge)
        tb_layout.addWidget(self.lbl_stage_info)
        tb_layout.addStretch()
        tb_layout.addWidget(self.lbl_remaining)
        tb_layout.addWidget(self.progress_bar)
        tb_layout.addWidget(btn_stop)
        layout.addWidget(top_bar)
        
        # Main Integrated Test Card
        test_card = QFrame()
        test_card.setProperty("class", "card")
        tc_layout = QVBoxLayout(test_card)
        tc_layout.setContentsMargins(22, 16, 22, 16)
        tc_layout.setSpacing(14)
        
        # Tone Header Row (Frequency + Replay/Undo Buttons with SVG Icons)
        freq_row = QHBoxLayout()
        self.lbl_frequency = QLabel("1,000 Hz")
        self.lbl_frequency.setProperty("class", "freq-display")
        self.btn_undo = QPushButton("Undo (Z)")
        self.btn_undo.setProperty("class", "secondary")
        self.btn_undo.setIcon(get_svg_icon("rotate-ccw", color="#d51535"))
        self.btn_undo.setIconSize(QSize(14, 14))
        self.btn_undo.setFixedHeight(38)
        self.btn_undo.setToolTip("Remove the last rating and replay the same tone.")
        self.btn_undo.clicked.connect(self._undo_last_rating)
        self.btn_replay = QPushButton("Replay Tone (R)")
        self.btn_replay.setProperty("class", "secondary")
        self.btn_replay.setIcon(get_svg_icon("rotate-ccw", color="#d51535"))
        self.btn_replay.setIconSize(QSize(16, 16))
        self.btn_replay.setFixedHeight(38)
        self.btn_replay.clicked.connect(self._replay_current_tone)
        freq_row.addWidget(self.lbl_frequency)
        freq_row.addStretch()
        freq_row.addWidget(self.btn_undo)
        freq_row.addWidget(self.btn_replay)
        tc_layout.addLayout(freq_row)
        
        # Prominent Yes / No Choice Buttons with SVG Icons
        choice_row = QHBoxLayout()
        choice_row.setSpacing(14)
        self.btn_choice_yes = QPushButton("Yes, I Heard It (Y)")
        self.btn_choice_yes.setProperty("class", "toggle-choice")
        self.btn_choice_yes.setIcon(get_svg_icon("check", color="#d51535"))
        self.btn_choice_yes.setIconSize(QSize(18, 18))
        self.btn_choice_yes.setFixedHeight(46)
        self.btn_choice_yes.clicked.connect(lambda: self._select_heard(True))
        
        self.btn_choice_no = QPushButton("No, Didn't Hear (N)")
        self.btn_choice_no.setProperty("class", "toggle-choice")
        self.btn_choice_no.setIcon(get_svg_icon("x", color="#ff4d4f"))
        self.btn_choice_no.setIconSize(QSize(18, 18))
        self.btn_choice_no.setFixedHeight(46)
        self.btn_choice_no.clicked.connect(lambda: self._submit_with(False))
        
        choice_row.addWidget(self.btn_choice_yes, 1)
        choice_row.addWidget(self.btn_choice_no, 1)
        tc_layout.addLayout(choice_row)
        
        # Inline Clarity Rating Box (Appears on Yes)
        self.clarity_box = QWidget()
        q2_layout = QVBoxLayout(self.clarity_box)
        q2_layout.setContentsMargins(0, 4, 0, 0)
        q2_layout.setSpacing(8)
        
        c_header = QHBoxLayout()
        c_label = QLabel("Clarity Score — click a score to continue:")
        c_label.setStyleSheet("font-size: 12px; font-weight: 600; color: #b1b1b1;")
        c_header.addWidget(c_label)
        c_header.addStretch()
        
        # Optional Distortion slider
        dist_lbl = QLabel("Buzz / Distortion (opt):")
        dist_lbl.setStyleSheet("color: #7f7f7f; font-size: 11px;")
        self.dist_slider = QSlider(Qt.Horizontal)
        self.dist_slider.setRange(0, 10)
        self.dist_slider.setValue(0)
        self.dist_slider.setFixedWidth(100)
        self.lbl_dist_val = QLabel("0")
        self.lbl_dist_val.setStyleSheet("color: #7f7f7f; font-size: 11px; font-weight: 600;")
        self.dist_slider.valueChanged.connect(lambda v: self.lbl_dist_val.setText(str(v)))
        c_header.addWidget(dist_lbl)
        c_header.addWidget(self.dist_slider)
        c_header.addWidget(self.lbl_dist_val)
        q2_layout.addLayout(c_header)
        
        # 0–10 Number Pills Strip (1-Click Auto-Advance)
        self.num_pills_layout = QHBoxLayout()
        self.num_pills_layout.setSpacing(4)
        self.pill_buttons = []
        for num in range(11):
            b = QPushButton(str(num))
            b.setProperty("class", "num-pill")
            b.clicked.connect(lambda _, v=num: self._submit_with(True, v))
            self.pill_buttons.append(b)
            self.num_pills_layout.addWidget(b)
        self.num_pills_layout.addStretch()
        q2_layout.addLayout(self.num_pills_layout)
        
        tc_layout.addWidget(self.clarity_box)
        self.clarity_box.setVisible(False)
        
        hint = QLabel("Keys: 0–9 rate clarity instantly · T = 10 · N = not heard · R = replay · Esc = stop")
        hint.setStyleSheet("color: #7f7f7f; font-size: 11px;")
        hint.setAlignment(Qt.AlignCenter)
        tc_layout.addWidget(hint)
        
        layout.addWidget(test_card)
        
        # Live Response Plot
        self.live_plot = LogFrequencyPlotWidget()
        self.live_plot.setFixedHeight(210)
        layout.addWidget(self.live_plot, 1)
        self.stack.addWidget(self.testing_page)

    def _select_heard(self, heard: bool):
        self._heard_selection = heard
        if heard:
            self.btn_choice_yes.setProperty("class", "toggle-yes-active")
            self.btn_choice_no.setProperty("class", "toggle-choice")
            self.clarity_box.setVisible(True)
        else:
            self.btn_choice_yes.setProperty("class", "toggle-choice")
            self.btn_choice_no.setProperty("class", "toggle-no-active")
            self.clarity_box.setVisible(False)
        self.btn_choice_yes.style().unpolish(self.btn_choice_yes)
        self.btn_choice_yes.style().polish(self.btn_choice_yes)
        self.btn_choice_no.style().unpolish(self.btn_choice_no)
        self.btn_choice_no.style().polish(self.btn_choice_no)

    def _submit_with(self, heard: bool, clarity: Optional[int] = None):
        if self.stack.currentIndex() != PAGE_TESTING:
            return
        if heard:
            self._select_heard(True)
            c_val = clarity if clarity is not None else 5
            self._update_pill_selection(c_val)
            self._record_current_response(True, c_val, self.dist_slider.value())
        else:
            self._select_heard(False)
            self._record_current_response(False, 0, None)

    def _update_pill_selection(self, active_val: int):
        for i, b in enumerate(self.pill_buttons):
            cls_name = "num-pill-active" if i == active_val else "num-pill"
            b.setProperty("class", cls_name)
            b.style().unpolish(b)
            b.style().polish(b)

    def _record_current_response(self, heard: bool, clarity: int, distortion: Optional[int]):
        if self.stack.currentIndex() != PAGE_TESTING:
            return
        item = self.scheduler.get_current_test()
        if item is None:
            return
        if self.last_playback_ok is False:
            QMessageBox.warning(
                self,
                "Playback Error",
                "The previous tone encountered an audio playback error.\n"
                "Please click 'Replay Tone' to listen before submitting your response."
            )
            return
        # Debounce min-listen time (0.25s)
        if self._tone_started_at is None or (time.time() - self._tone_started_at < 0.25):
            return
        
        freq = item["freq"]
        stage = item["stage"]
        is_retest = item["is_retest"]
        is_control = item["is_control"]
        quality, cls = self.controller.calculate_quality(heard, clarity, distortion)
        anchor = self.controller.rating_anchor(self.scheduler.active_measurements)
        probe = Measurement(
            frequency_hz=freq,
            channel=self.current_channel,
            stage=stage,
            heard=heard,
            clarity=clarity,
            distortion=distortion,
            quality=quality
        )
        m = Measurement(
            frequency_hz=freq,
            channel=self.current_channel,
            stage=stage,
            heard=heard,
            clarity=clarity,
            distortion=distortion,
            quality=quality,
            classification=cls,
            effective_classification=self.controller.effective_classification(probe, anchor),
            is_retest=is_retest,
            is_control=is_control
        )
        self.scheduler.record_measurement(m, self.controller)
        self.audio_engine.stop_playback()
        self._present_next_test()

    # =========================================================================
    # 3. MANUAL TONE GENERATOR VIEW (LOGARITHMIC MAPPING & MOVABLE SPLITTER)
    # =========================================================================
    def _build_manual_view(self):
        self.manual_page = QWidget()
        layout = QVBoxLayout(self.manual_page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        
        top_card = QFrame()
        top_card.setProperty("class", "card")
        tc_layout = QHBoxLayout(top_card)
        tc_layout.setContentsMargins(20, 12, 20, 12)
        title = QLabel("Manual Tone Generator")
        title.setProperty("class", "title")
        btn_back = QPushButton("Return to Setup")
        btn_back.setProperty("class", "secondary")
        btn_back.setIcon(get_svg_icon("arrow-left", color="#d51535"))
        btn_back.setIconSize(QSize(14, 14))
        btn_back.clicked.connect(lambda: self._switch_page(PAGE_WIZARD))
        tc_layout.addWidget(title)
        tc_layout.addStretch()
        tc_layout.addWidget(btn_back)
        layout.addWidget(top_card)
        
        # Movable Splitter for Manual View — responsive: horizontal on wide, vertical on narrow (resizeEvent toggles)
        self.manual_splitter = QSplitter(Qt.Horizontal)
        self.manual_splitter.setHandleWidth(8)
        self.manual_splitter.setChildrenCollapsible(False)
        manual_splitter = self.manual_splitter
        
        # Left Panel: Tone Frequency & Generation Controls
        card_left = QFrame()
        card_left.setProperty("class", "card")
        c_layout = QVBoxLayout(card_left)
        c_layout.setContentsMargins(22, 18, 22, 18)
        c_layout.setSpacing(14)
        
        cl_title = QLabel("Tone Generator Controls")
        cl_title.setProperty("class", "section-title")
        c_layout.addWidget(cl_title)
        
        # Frequency Controls with Log Mapping
        f_row = QHBoxLayout()
        f_row.addWidget(QLabel("Frequency (Hz):"))
        self.spin_manual_freq = QSpinBox()
        self.spin_manual_freq.setRange(20, 20000)
        self.spin_manual_freq.setValue(1000)
        self.spin_manual_freq.setFixedWidth(110)
        f_row.addWidget(self.spin_manual_freq)
        
        self.slider_manual_freq = QSlider(Qt.Horizontal)
        self.slider_manual_freq.setRange(0, 1000)
        init_pos = int(round(1000.0 * math.log(1000.0 / 20.0) / math.log(20000.0 / 20.0)))
        self.slider_manual_freq.setValue(init_pos)
        self.slider_manual_freq.valueChanged.connect(self._on_manual_slider_changed)
        self.spin_manual_freq.valueChanged.connect(self._on_manual_spin_changed)
        f_row.addWidget(self.slider_manual_freq)
        c_layout.addLayout(f_row)
        
        ctrl_row = QHBoxLayout()
        ctrl_row.addWidget(QLabel("Waveform:"))
        self.combo_manual_wave = QComboBox()
        self.combo_manual_wave.addItems(["Sine (Pure Tone)", "Triangle (Harmonics)", "Pink Noise"])
        ctrl_row.addWidget(self.combo_manual_wave)
        ctrl_row.addWidget(QLabel("Channel:"))
        self.combo_manual_ch = QComboBox()
        self.combo_manual_ch.addItems(["Both", "Left", "Right"])
        ctrl_row.addWidget(self.combo_manual_ch)
        ctrl_row.addWidget(QLabel("Duration:"))
        self.spin_manual_dur = QDoubleSpinBox()
        self.spin_manual_dur.setRange(0.5, 10.0)
        self.spin_manual_dur.setValue(2.0)
        self.spin_manual_dur.setSingleStep(0.5)
        self.spin_manual_dur.setSuffix(" s")
        ctrl_row.addWidget(self.spin_manual_dur)
        c_layout.addLayout(ctrl_row)
        
        play_row = QHBoxLayout()
        self.btn_play_manual = QPushButton("Play Tone")
        self.btn_play_manual.setIcon(get_svg_icon("play", color="#ffffff"))
        self.btn_play_manual.setIconSize(QSize(16, 16))
        self.btn_play_manual.setStyleSheet("padding: 12px 28px; font-size: 14px; font-weight: 700;")
        self.btn_play_manual.clicked.connect(self._play_manual_tone)
        self.btn_stop_manual = QPushButton("Stop")
        self.btn_stop_manual.setProperty("class", "danger")
        self.btn_stop_manual.setIcon(get_svg_icon("stop", color="#FFFFFF"))
        self.btn_stop_manual.setIconSize(QSize(14, 14))
        self.btn_stop_manual.clicked.connect(self.audio_engine.stop_playback)
        play_row.addWidget(self.btn_play_manual)
        play_row.addWidget(self.btn_stop_manual)
        play_row.addStretch()
        c_layout.addLayout(play_row)
        c_layout.addStretch()
        manual_splitter.addWidget(card_left)
        
        # Right Panel: Reference & Perceptual Guide
        card_right = QFrame()
        card_right.setProperty("class", "card")
        cr_layout = QVBoxLayout(card_right)
        cr_layout.setContentsMargins(20, 18, 20, 18)
        cr_layout.setSpacing(10)
        cr_title = QLabel("Acoustic Frequency Guide")
        cr_title.setProperty("class", "section-title")
        cr_layout.addWidget(cr_title)
        
        guide_text = QLabel(
            "- Sub-Bass (20-60 Hz): Physical rumble, testing subwoofer output.\n"
            "- Bass (60-250 Hz): Kick drums & basslines; check for speaker enclosure rattles.\n"
            "- Midrange (250-2,000 Hz): Human voice fundamentals & clarity core.\n"
            "- Upper-Mid (2-4 kHz): Presence & attack; ear is most sensitive here.\n"
            "- Highs (4-20 kHz): Air, cymbals, brilliance; tests tweeter fidelity."
        )
        guide_text.setStyleSheet("color: #b1b1b1; font-size: 12px; line-height: 1.5;")
        guide_text.setWordWrap(True)
        cr_layout.addWidget(guide_text)
        cr_layout.addStretch()
        manual_splitter.addWidget(card_right)
        
        manual_splitter.setSizes([560, 440])
        layout.addWidget(manual_splitter, 1)
        self.stack.addWidget(self.manual_page)

    def _on_manual_slider_changed(self, pos: int):
        f = 20.0 * ((20000.0 / 20.0) ** (pos / 1000.0))
        self.spin_manual_freq.blockSignals(True)
        self.spin_manual_freq.setValue(int(round(f)))
        self.spin_manual_freq.blockSignals(False)

    def _on_manual_spin_changed(self, f: int):
        f_clamped = max(20.0, min(20000.0, float(f)))
        pos = int(round(1000.0 * math.log(f_clamped / 20.0) / math.log(20000.0 / 20.0)))
        self.slider_manual_freq.blockSignals(True)
        self.slider_manual_freq.setValue(pos)
        self.slider_manual_freq.blockSignals(False)

    def _play_manual_tone(self):
        freq = float(self.spin_manual_freq.value())
        dur = float(self.spin_manual_dur.value())
        wave_type = self.combo_manual_wave.currentText()
        ch_text = self.combo_manual_ch.currentText()
        ch = "left" if "Left" in ch_text else ("right" if "Right" in ch_text else "both")
        if "Triangle" in wave_type:
            audio = self.audio_engine.generate_triangle_tone(freq, duration_s=dur, channel=ch)
        elif "Pink" in wave_type:
            audio = self.audio_engine.generate_pink_noise(duration_s=dur, channel=ch)
        else:
            audio = self.audio_engine.generate_sine_tone(freq, duration_s=dur, channel=ch)
        self.audio_engine.play_audio(
            audio,
            on_started=lambda: self.audio_bridge.playback_started.emit(freq),
            on_finished=lambda ok, err: self.audio_bridge.playback_finished.emit(ok, err or ""),
            spectrum_meta={"buffer": audio, "sample_rate": self.audio_engine.sample_rate}
        )

    # =========================================================================
    # 4. LOGARITHMIC SWEEP MODE VIEW (WITH MOVABLE QSplitter SIDE WINDOWS)
    # =========================================================================
    def _build_sweep_view(self):
        self.sweep_page = QWidget()
        layout = QVBoxLayout(self.sweep_page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        
        top_card = QFrame()
        top_card.setProperty("class", "card")
        tc_layout = QHBoxLayout(top_card)
        tc_layout.setContentsMargins(20, 12, 20, 12)
        title = QLabel("Logarithmic Frequency Sweep")
        title.setProperty("class", "title")
        btn_back = QPushButton("Return to Setup")
        btn_back.setProperty("class", "secondary")
        btn_back.setIcon(get_svg_icon("arrow-left", color="#d51535"))
        btn_back.setIconSize(QSize(14, 14))
        btn_back.clicked.connect(lambda: self._switch_page(PAGE_WIZARD))
        tc_layout.addWidget(title)
        tc_layout.addStretch()
        tc_layout.addWidget(btn_back)
        layout.addWidget(top_card)
        
        # Movable Splitter for Sweep View — responsive
        self.sweep_splitter = QSplitter(Qt.Horizontal)
        self.sweep_splitter.setHandleWidth(8)
        self.sweep_splitter.setChildrenCollapsible(False)
        sweep_splitter = self.sweep_splitter
        
        # Left Panel: Sweep Configuration & Controls
        card_left = QFrame()
        card_left.setProperty("class", "card")
        c_layout = QVBoxLayout(card_left)
        c_layout.setContentsMargins(22, 18, 22, 18)
        c_layout.setSpacing(14)
        
        sl_title = QLabel("Sweep Configuration & Transport")
        sl_title.setProperty("class", "section-title")
        c_layout.addWidget(sl_title)
        
        info = QLabel(
            "Plays a smooth 100 Hz -> 10,000 Hz continuous logarithmic sweep.\n"
            "Press Spacebar or the Mark button whenever you hear drops, rattles, or distortion."
        )
        info.setStyleSheet("color: #b1b1b1; font-size: 12px;")
        info.setWordWrap(True)
        c_layout.addWidget(info)
        
        cfg_row = QHBoxLayout()
        cfg_row.addWidget(QLabel("Duration:"))
        self.spin_sweep_dur = QSpinBox()
        self.spin_sweep_dur.setRange(10, 60)
        self.spin_sweep_dur.setValue(20)
        self.spin_sweep_dur.setSuffix(" s")
        cfg_row.addWidget(self.spin_sweep_dur)
        cfg_row.addWidget(QLabel("Channel:"))
        self.combo_sweep_ch = QComboBox()
        self.combo_sweep_ch.addItems(["Both", "Left", "Right"])
        cfg_row.addWidget(self.combo_sweep_ch)
        cfg_row.addStretch()
        c_layout.addLayout(cfg_row)
        
        act_row = QHBoxLayout()
        self.btn_start_sweep = QPushButton("Start Sweep")
        self.btn_start_sweep.setIcon(get_svg_icon("play", color="#FFFFFF"))
        self.btn_start_sweep.setIconSize(QSize(16, 16))
        self.btn_start_sweep.setStyleSheet("padding: 12px 24px; font-size: 14px; font-weight: 700;")
        self.btn_start_sweep.setFocusPolicy(Qt.NoFocus)
        self.btn_start_sweep.clicked.connect(self._start_sweep)
        
        self.btn_mark_sweep = QPushButton("Mark Anomaly (Space)")
        self.btn_mark_sweep.setIcon(get_svg_icon("zap", color="#FFFFFF"))
        self.btn_mark_sweep.setIconSize(QSize(16, 16))
        self.btn_mark_sweep.setStyleSheet(
            "padding: 12px 24px; font-size: 14px; font-weight: 700; "
            "background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #d51535, stop:1 #d51535); color: #FFFFFF; border-radius: 9px;"
        )
        self.btn_mark_sweep.setFocusPolicy(Qt.NoFocus)
        self.btn_mark_sweep.clicked.connect(self._mark_sweep_anomaly)
        self.btn_mark_sweep.setEnabled(False)

        self.btn_retest_marks = QPushButton("Retest Marked Freqs")
        self.btn_retest_marks.setProperty("class", "secondary")
        self.btn_retest_marks.setIcon(get_svg_icon("zap", color="#d51535"))
        self.btn_retest_marks.setIconSize(QSize(14, 14))
        self.btn_retest_marks.setToolTip("Run adaptive ratings on each marked frequency through the guided test flow.")
        self.btn_retest_marks.setEnabled(False)
        self.btn_retest_marks.clicked.connect(self._start_sweep_retest)
        
        btn_stop_sw = QPushButton("Stop")
        btn_stop_sw.setProperty("class", "danger")
        btn_stop_sw.setIcon(get_svg_icon("stop", color="#FFFFFF"))
        btn_stop_sw.setIconSize(QSize(14, 14))
        btn_stop_sw.setFocusPolicy(Qt.NoFocus)
        btn_stop_sw.clicked.connect(self._stop_sweep)
        
        act_row.addWidget(self.btn_start_sweep)
        act_row.addWidget(self.btn_mark_sweep)
        act_row.addWidget(btn_stop_sw)
        act_row.addWidget(self.btn_retest_marks)
        act_row.addStretch()
        c_layout.addLayout(act_row)
        
        self.shortcut_space = QShortcut(QKeySequence(Qt.Key_Space), self.sweep_page)
        self.shortcut_space.setContext(Qt.WidgetWithChildrenShortcut)
        self.shortcut_space.activated.connect(self._on_space_sweep)
        c_layout.addStretch()
        sweep_splitter.addWidget(card_left)
        
        # Right Panel: Real-Time Frequency Readout & Anomaly Log
        card_right = QFrame()
        card_right.setProperty("class", "card")
        cr_layout = QVBoxLayout(card_right)
        cr_layout.setContentsMargins(20, 18, 20, 18)
        cr_layout.setSpacing(10)
        
        sr_title = QLabel("Real-Time Frequency & Anomaly Log")
        sr_title.setProperty("class", "section-title")
        cr_layout.addWidget(sr_title)
        
        self.lbl_sweep_progress = QLabel("— Hz")
        self.lbl_sweep_progress.setStyleSheet("font-size: 28px; font-weight: 800; color: #d51535;")
        cr_layout.addWidget(self.lbl_sweep_progress)
        
        self.txt_sweep_marks = QTextEdit()
        self.txt_sweep_marks.setReadOnly(True)
        self.txt_sweep_marks.setPlaceholderText("Marked frequency anomalies will be listed here in real time...")
        cr_layout.addWidget(self.txt_sweep_marks, 1)
        sweep_splitter.addWidget(card_right)
        
        sweep_splitter.setSizes([520, 480])
        layout.addWidget(sweep_splitter, 1)
        self.stack.addWidget(self.sweep_page)
        self.sweep_timer = QTimer(self)
        self.sweep_timer.setInterval(50)
        self.sweep_timer.timeout.connect(self._on_sweep_timer_tick)
        self.sweep_start_time = 0.0
        self.sweep_total_duration = 20.0
        self.sweep_marks = []

    def _start_sweep(self):
        dur = float(self.spin_sweep_dur.value())
        self.sweep_total_duration = dur
        ch_text = self.combo_sweep_ch.currentText()
        ch = "left" if "Left" in ch_text else ("right" if "Right" in ch_text else "both")
        self.sweep_marks = []
        self._sync_sweep_marks_to_session()
        self._consecutive_stopped_ticks = 0
        self.sweep_start_time = None
        self.txt_sweep_marks.clear()
        self.btn_mark_sweep.setEnabled(True)
        self.btn_retest_marks.setEnabled(False)
        audio = self.audio_engine.generate_log_sweep(100.0, 10000.0, duration_s=dur, channel=ch)
        self.audio_engine.play_audio(
            audio,
            on_started=lambda: self.audio_bridge.sweep_started.emit(),
            on_finished=lambda ok, err: self.audio_bridge.playback_finished.emit(ok, err or ""),
            spectrum_meta={"buffer": audio, "sample_rate": self.audio_engine.sample_rate}
        )

    def _on_sweep_started_ui(self):
        self.sweep_start_time = time.time()
        self.sweep_timer.start()
        self._on_playback_started_ui(100.0)

    def _on_sweep_timer_tick(self):
        if self.sweep_start_time is None:
            return
        elapsed = time.time() - self.sweep_start_time
        if elapsed >= self.sweep_total_duration:
            self._stop_sweep()
            return
        if not self.audio_engine.is_playing():
            self._consecutive_stopped_ticks += 1
            if self._consecutive_stopped_ticks >= 4 and elapsed > 0.5:
                self._stop_sweep()
                return
        else:
            self._consecutive_stopped_ticks = 0
        ratio = min(1.0, elapsed / self.sweep_total_duration)
        cur_f = 100.0 * ((10000.0 / 100.0) ** ratio)
        self.lbl_sweep_progress.setText(f"~{cur_f:,.0f} Hz")
        self._active_tone_freq = cur_f
        self.top_visualizer.start_if_playing()

    def _mark_sweep_anomaly(self):
        if self.sweep_start_time is None:
            return
        # Compensate for buffer output latency (~35ms)
        elapsed = max(0.0, (time.time() - 0.035) - self.sweep_start_time)
        ratio = min(1.0, elapsed / self.sweep_total_duration)
        cur_f = 100.0 * ((10000.0 / 100.0) ** ratio)
        self.sweep_marks.append(cur_f)
        self._sync_sweep_marks_to_session()
        self.btn_retest_marks.setEnabled(True)
        self.txt_sweep_marks.append(f"• Anomaly marked at ~{cur_f:,.0f} Hz (at {elapsed:.1f}s)")

    def _sync_sweep_marks_to_session(self):
        if self.session is not None:
            self.session.sweep_marks_hz = list(self.sweep_marks)

    def _on_space_sweep(self):
        if self.stack.currentIndex() == PAGE_SWEEP and self.audio_engine.is_playing():
            self._mark_sweep_anomaly()

    def _stop_sweep(self):
        self.sweep_timer.stop()
        self.audio_engine.stop_playback()
        self.top_visualizer.stop_and_clear()
        self.btn_mark_sweep.setEnabled(False)
        self.btn_retest_marks.setEnabled(bool(self.sweep_marks))
        self.lbl_sweep_progress.setText("Sweep Complete")

    def _start_sweep_retest(self):
        if not self.sweep_marks:
            return
        freqs = sorted({practical_round_freq(f) for f in self.sweep_marks})[:8]
        ch_text = self.combo_sweep_ch.currentText()
        ch = "left" if "Left" in ch_text else ("right" if "Right" in ch_text else "both")
        if self.session is None:
            self.session = Session(
                mode="sweep",
                sample_rate=self.audio_engine.sample_rate,
                duration_per_tone=2.0,
                peak_level=0.4,
                fxsound_disabled=self.chk_fxsound.isChecked(),
                enhancements_disabled=self.chk_enhancements.isChecked(),
                output_device_name=self.device_combo.currentText(),
                channel_mode=ch
            )
            self.start_time = time.time()
        self.session.mode = "sweep"
        self.session.sweep_marks_hz = list(self.sweep_marks)
        self.controller = DiagnosticController(mode="quick")
        self.scheduler = TestScheduler(mode="quick")
        self._manual_retest_freqs = freqs
        self.scheduler.manual_mode = True
        self.blind_mode = self.chk_blind.isChecked()
        self._sweep_retest_active = True
        self._start_channel_test(ch)

    # =========================================================================
    # 5. REAL MUSIC PLAYBACK & A/B SPEAKER COMPARISON VIEW
    # =========================================================================
    def _build_music_view(self):
        self.music_page = QWidget()
        layout = QVBoxLayout(self.music_page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        
        card = QFrame()
        card.setProperty("class", "card")
        c = QVBoxLayout(card)
        c.setContentsMargins(22, 18, 22, 18)
        c.setSpacing(14)
        
        top_row = QHBoxLayout()
        title = QLabel("Real Music Playback & Speaker A/B Comparison")
        title.setProperty("class", "title")
        btn_back = QPushButton("Return to Setup")
        btn_back.setProperty("class", "secondary")
        btn_back.setIcon(get_svg_icon("arrow-left", color="#d51535"))
        btn_back.setIconSize(QSize(14, 14))
        btn_back.clicked.connect(lambda: self._switch_page(PAGE_WIZARD))
        top_row.addWidget(title)
        top_row.addStretch()
        top_row.addWidget(btn_back)
        c.addLayout(top_row)
        
        desc = QLabel(
            "Play your own music through one speaker at a time to listen for subtle rattling, buzzing, and balance differences.\n"
            "- Pure tones are required for calibrated diagnostic detection; real music provides real-world subjective verification."
        )
        desc.setStyleSheet("color: #b1b1b1; font-size: 12px;")
        desc.setWordWrap(True)
        c.addWidget(desc)
        
        # File Loading Row
        file_row = QHBoxLayout()
        self.btn_music_load = QPushButton("Load Music Track...")
        self.btn_music_load.setProperty("class", "secondary")
        self.btn_music_load.setIcon(get_svg_icon("folder", color="#d51535"))
        self.btn_music_load.setIconSize(QSize(16, 16))
        self.btn_music_load.setFixedHeight(36)
        self.btn_music_load.clicked.connect(self._load_music_file)
        self.lbl_music_file = QLabel("No track loaded")
        self.lbl_music_file.setStyleSheet("color: #7f7f7f; font-size: 12px;")
        file_row.addWidget(self.btn_music_load)
        file_row.addWidget(self.lbl_music_file, 1)
        c.addLayout(file_row)
        
        if not SOUNDFILE_AVAILABLE:
            sf_note = QLabel("[Note] Music playback requires the optional 'soundfile' package (pip install soundfile).")
            sf_note.setStyleSheet("color: #ff4d4f; font-size: 11px; font-weight: 600;")
            c.addWidget(sf_note)
        
        # Channel Selection Row
        ch_row = QHBoxLayout()
        ch_row.addWidget(QLabel("Output Channel:"))
        self.btn_mch_both = QPushButton("Both Speakers")
        self.btn_mch_left = QPushButton("Left Speaker Only")
        self.btn_mch_right = QPushButton("Right Speaker Only")
        for b in (self.btn_mch_both, self.btn_mch_left, self.btn_mch_right):
            b.setProperty("class", "secondary")
            b.setFixedHeight(34)
        self.btn_mch_both.clicked.connect(lambda: self._set_music_channel("both"))
        self.btn_mch_left.clicked.connect(lambda: self._set_music_channel("left"))
        self.btn_mch_right.clicked.connect(lambda: self._set_music_channel("right"))
        ch_row.addWidget(self.btn_mch_both)
        ch_row.addWidget(self.btn_mch_left)
        ch_row.addWidget(self.btn_mch_right)
        ch_row.addStretch()
        c.addLayout(ch_row)
        
        # Volume Row
        vol_row = QHBoxLayout()
        vol_row.addWidget(QLabel("Track Volume:"))
        self.slider_music_vol = QSlider(Qt.Horizontal)
        self.slider_music_vol.setRange(0, 100)
        self.slider_music_vol.setValue(60)
        self.slider_music_vol.sliderReleased.connect(self._on_music_volume_released)
        self.lbl_music_vol = QLabel("60%")
        self.lbl_music_vol.setStyleSheet("color: #d51535; font-weight: 700; font-size: 12px;")
        self.slider_music_vol.valueChanged.connect(lambda v: self.lbl_music_vol.setText(f"{v}%"))
        vol_row.addWidget(self.slider_music_vol, 1)
        vol_row.addWidget(self.lbl_music_vol)
        c.addLayout(vol_row)
        
        # Position & Seek Slider
        pos_row = QHBoxLayout()
        self.lbl_music_pos = QLabel("0:00 / 0:00")
        self.lbl_music_pos.setStyleSheet("font-size: 15px; font-weight: 800; color: #d51535;")
        self.slider_music_pos = QSlider(Qt.Horizontal)
        self.slider_music_pos.setRange(0, 1000)
        self.slider_music_pos.setValue(0)
        self.slider_music_pos.sliderMoved.connect(self._on_music_pos_moved)
        self.slider_music_pos.sliderReleased.connect(self._on_music_seek_done)
        pos_row.addWidget(self.lbl_music_pos)
        pos_row.addWidget(self.slider_music_pos, 1)
        c.addLayout(pos_row)
        
        # Transport Buttons with SVG Icons
        trans_row = QHBoxLayout()
        self.btn_music_play = QPushButton("Play Track")
        self.btn_music_play.setIcon(get_svg_icon("play", color="#ffffff"))
        self.btn_music_play.setIconSize(QSize(16, 16))
        self.btn_music_play.setStyleSheet("padding: 12px 28px; font-size: 14px; font-weight: 700;")
        self.btn_music_play.setEnabled(False)
        self.btn_music_play.clicked.connect(self._music_toggle_play)
        
        self.btn_music_stop = QPushButton("Stop Track")
        self.btn_music_stop.setProperty("class", "danger")
        self.btn_music_stop.setIcon(get_svg_icon("stop", color="#FFFFFF"))
        self.btn_music_stop.setIconSize(QSize(14, 14))
        self.btn_music_stop.setFixedHeight(40)
        self.btn_music_stop.setEnabled(False)
        self.btn_music_stop.clicked.connect(self._music_stop)
        
        trans_row.addWidget(self.btn_music_play)
        trans_row.addWidget(self.btn_music_stop)
        trans_row.addStretch()
        c.addLayout(trans_row)
        
        self.lbl_music_status = QLabel("")
        self.lbl_music_status.setStyleSheet("color: #ff4d4f; font-size: 11px;")
        c.addWidget(self.lbl_music_status)
        
        hint_m = QLabel("Tip: Click 'Left' and 'Right' during music playback to instantly isolate and A/B compare each speaker.")
        hint_m.setStyleSheet("color: #7f7f7f; font-size: 11px;")
        c.addWidget(hint_m)
        
        layout.addWidget(card)
        layout.addStretch()
        self.stack.addWidget(self.music_page)
        
        self.music_timer = QTimer(self)
        self.music_timer.setInterval(200)
        self.music_timer.timeout.connect(self._on_music_timer)

    def _load_music_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Music Track", "",
            "Audio Files (*.wav *.flac *.ogg *.mp3 *.aiff *.aif);;All Files (*)"
        )
        if not path:
            return
        try:
            data, sr = self.audio_engine.load_music_file(path)
        except Exception as e:
            self.lbl_music_status.setText(f"[Alert] Could not load file: {e}")
            return
        
        self._music_stop()
        self.music_original = data
        self.music_file_sr = sr
        self._music_cache = None
        self._music_cache_rate = 0
        self.music_pos_sec = 0.0
        self._music_total_sec = len(data) / float(sr)
        
        name = os.path.basename(path)
        self.lbl_music_file.setText(f"{name} · {_fmt_time(self._music_total_sec)} · {sr} Hz")
        self.lbl_music_pos.setText(f"0:00 / {_fmt_time(self._music_total_sec)}")
        self.slider_music_pos.setValue(0)
        self.btn_music_play.setEnabled(True)
        self.btn_music_stop.setEnabled(True)
        self.lbl_music_status.setText("")

    def _get_music_base(self):
        if self._music_cache is not None and self._music_cache_rate == self.audio_engine.sample_rate:
            return self._music_cache
        res = self.audio_engine.resample_linear(
            self.music_original,
            self.music_file_sr,
            self.audio_engine.sample_rate
        )
        self._music_cache = res
        self._music_cache_rate = self.audio_engine.sample_rate
        return res

    def _set_music_channel(self, ch: str):
        self.music_channel = ch
        for b, name in [
            (self.btn_mch_both, "both"),
            (self.btn_mch_left, "left"),
            (self.btn_mch_right, "right")
        ]:
            if name == ch:
                b.setProperty("class", "toggle-yes-active")
            else:
                b.setProperty("class", "secondary")
            b.style().unpolish(b)
            b.style().polish(b)
        if self.music_playing:
            self._music_restart()

    def _music_toggle_play(self):
        if self.music_playing:
            self._music_pause()
        else:
            self._music_play()

    def _music_play(self):
        if self.music_original is None:
            return
        base = self._get_music_base()
        sr = self.audio_engine.sample_rate
        total_samples = len(base)
        start_sample = max(0, min(int(self.music_pos_sec * sr), total_samples - 1))
        vol = self.slider_music_vol.value() / 100.0
        seg = self.audio_engine.prepare_music_segment(base, start_sample, self.music_channel, vol)
        self._music_offset_sec = self.music_pos_sec
        self._music_active = True
        self.audio_engine.play_audio(
            seg,
            on_started=lambda: self.audio_bridge.music_started.emit(),
            on_finished=lambda ok, err: self.audio_bridge.music_finished.emit(ok, err or ""),
            spectrum_meta={"buffer": seg, "sample_rate": self.audio_engine.sample_rate}
        )

    def _music_pause(self):
        self.audio_engine.stop_playback()
        self.music_playing = False
        self._music_active = False
        self.music_timer.stop()
        self.btn_music_play.setText("Play Track")
        self.btn_music_play.setIcon(get_svg_icon("play", color="#ffffff"))

    def _music_stop(self):
        self.audio_engine.stop_playback()
        self.music_playing = False
        self._music_active = False
        self.music_timer.stop()
        self.music_pos_sec = 0.0
        self.slider_music_pos.setValue(0)
        self.lbl_music_pos.setText(f"0:00 / {_fmt_time(self._music_total_sec)}")
        self.btn_music_play.setText("Play Track")
        self.btn_music_play.setIcon(get_svg_icon("play", color="#ffffff"))
        self.top_visualizer.stop_and_clear()

    def _music_restart(self):
        self.audio_engine.stop_playback()
        self.music_playing = False
        self._music_play()

    def _on_music_started_ui(self):
        self._music_started_wall = time.time()
        self.music_playing = True
        self.music_timer.start()
        self.btn_music_play.setText("Pause Track")
        self.btn_music_play.setIcon(get_svg_icon("pause", color="#ffffff"))
        self.top_visualizer.start_if_playing()

    def _on_music_finished_ui(self, ok: bool, err_msg: str):
        was_active = self._music_active
        self.music_playing = False
        self._music_active = False
        self.music_timer.stop()
        self.btn_music_play.setText("Play Track")
        self.btn_music_play.setIcon(get_svg_icon("play", color="#ffffff"))
        self.top_visualizer.stop_and_clear()
        if not ok and err_msg and was_active:
            self.lbl_music_status.setText(f"[Alert] Playback error: {err_msg}")

    def _on_music_timer(self):
        if not self._music_active or not self.music_playing:
            return
        elapsed = time.time() - self._music_started_wall if self._music_started_wall else 0.0
        pos = self._music_offset_sec + elapsed
        if pos >= self._music_total_sec:
            self.music_pos_sec = self._music_total_sec
            self.lbl_music_pos.setText(f"{_fmt_time(self._music_total_sec)} / {_fmt_time(self._music_total_sec)}")
            self.slider_music_pos.blockSignals(True)
            self.slider_music_pos.setValue(1000)
            self.slider_music_pos.blockSignals(False)
            self._music_stop()
            return
        self.music_pos_sec = pos
        self.lbl_music_pos.setText(f"{_fmt_time(pos)} / {_fmt_time(self._music_total_sec)}")
        if self._music_total_sec > 0:
            permille = int(round(1000.0 * (pos / self._music_total_sec)))
            self.slider_music_pos.blockSignals(True)
            self.slider_music_pos.setValue(permille)
            self.slider_music_pos.blockSignals(False)

    def _on_music_pos_moved(self, val: int):
        target_sec = (val / 1000.0) * self._music_total_sec
        self.lbl_music_pos.setText(f"{_fmt_time(target_sec)} / {_fmt_time(self._music_total_sec)}")

    def _on_music_seek_done(self):
        val = self.slider_music_pos.value()
        self.music_pos_sec = (val / 1000.0) * self._music_total_sec
        if self.music_playing:
            self._music_restart()

    def _on_music_volume_released(self):
        if self.music_playing:
            self._music_restart()

    # =========================================================================
    # 6. RESULTS & REPORT DASHBOARD VIEW
    # =========================================================================
    def _build_results_view(self):
        self.results_page = QWidget()
        layout = QVBoxLayout(self.results_page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        top_card = QFrame()
        top_card.setProperty("class", "card")
        tc_layout = QHBoxLayout(top_card)
        tc_layout.setContentsMargins(18, 10, 18, 10)
        self.lbl_res_title = QLabel("Diagnostic Results & Acoustic Analysis")
        self.lbl_res_title.setProperty("class", "title")
        self.btn_filter_both = QPushButton("Both Channels")
        self.btn_filter_left = QPushButton("Left")
        self.btn_filter_right = QPushButton("Right")
        self.btn_filter_both.setProperty("class", "secondary")
        self.btn_filter_left.setProperty("class", "secondary")
        self.btn_filter_right.setProperty("class", "secondary")
        self.btn_filter_both.clicked.connect(lambda: self._set_res_filter("both"))
        self.btn_filter_left.clicked.connect(lambda: self._set_res_filter("left"))
        self.btn_filter_right.clicked.connect(lambda: self._set_res_filter("right"))
        self._res_filter = "both"
        btn_new_test = QPushButton("Start New Test")
        btn_new_test.setIcon(get_svg_icon("arrow-right", color="#ffffff"))
        btn_new_test.setIconSize(QSize(16, 16))
        btn_new_test.clicked.connect(lambda: self._switch_page(PAGE_WIZARD))
        tc_layout.addWidget(self.lbl_res_title)
        tc_layout.addStretch()
        tc_layout.addWidget(self.btn_filter_both)
        tc_layout.addWidget(self.btn_filter_left)
        tc_layout.addWidget(self.btn_filter_right)
        tc_layout.addWidget(btn_new_test)
        layout.addWidget(top_card)
        self.results_plot = LogFrequencyPlotWidget()
        self.results_plot.setFixedHeight(220)
        self.results_plot.setMinimumHeight(160)
        self.results_plot.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.results_plot.point_clicked.connect(self._on_plot_point_clicked)
        layout.addWidget(self.results_plot, 1)
        self.results_splitter = QSplitter(Qt.Horizontal)
        self.results_splitter.setHandleWidth(8)
        self.results_splitter.setChildrenCollapsible(False)
        self.results_splitter.setStyleSheet("QSplitter::handle { background: transparent; }")
        split = self.results_splitter
        self.txt_report = QTextEdit()
        self.txt_report.setReadOnly(True)
        # ensure report has sensible minimum to keep export panel visible on 860px min window
        self.txt_report.setMinimumWidth(420)
        split.addWidget(self.txt_report)
        right_panel = QFrame()
        right_panel.setProperty("class", "card")
        # FxSound panel: tighter 8px control bg but export needs readable buttons
        right_panel.setMinimumWidth(340)
        right_panel.setMaximumWidth(420)
        rp_layout = QVBoxLayout(right_panel)
        rp_layout.setContentsMargins(18, 18, 18, 18)
        rp_layout.setSpacing(10)
        rp_title = QLabel("Export & Share")
        rp_title.setProperty("class", "section-title")
        rp_layout.addWidget(rp_title)
        self.btn_csv = QPushButton("Export Raw CSV Data")
        self.btn_csv.setProperty("class", "secondary")
        self.btn_csv.setIcon(get_svg_icon("download", color="#d51535"))
        self.btn_csv.setIconSize(QSize(16, 16))
        self.btn_csv.setMinimumHeight(36)
        self.btn_csv.clicked.connect(self._export_csv)
        self.btn_json = QPushButton("Save Complete Session JSON")
        self.btn_json.setProperty("class", "secondary")
        self.btn_json.setIcon(get_svg_icon("download", color="#d51535"))
        self.btn_json.setIconSize(QSize(16, 16))
        self.btn_json.setMinimumHeight(36)
        self.btn_json.clicked.connect(self._save_session_json)
        self.btn_txt = QPushButton("Export Premium Report (.html)")
        self.btn_txt.setProperty("class", "secondary")
        self.btn_txt.setIcon(get_svg_icon("file-text", color="#d51535"))
        self.btn_txt.setIconSize(QSize(16, 16))
        self.btn_txt.setMinimumHeight(36)
        self.btn_txt.setToolTip("Premium, print-ready HTML report with FxSound styling — opens in browser, Save as PDF from there")
        self.btn_txt.clicked.connect(self._export_report_html)
        self.btn_load = QPushButton("Load Previous Session JSON")
        self.btn_load.setProperty("class", "secondary")
        self.btn_load.setIcon(get_svg_icon("folder", color="#d51535"))
        self.btn_load.setIconSize(QSize(16, 16))
        self.btn_load.setMinimumHeight(36)
        self.btn_load.clicked.connect(self._load_session_json)
        for b in (self.btn_csv, self.btn_json, self.btn_txt, self.btn_load):
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        rp_layout.addWidget(self.btn_csv)
        rp_layout.addWidget(self.btn_json)
        rp_layout.addWidget(self.btn_txt)
        rp_layout.addWidget(self.btn_load)
        rp_sep = QFrame()
        rp_sep.setFrameShape(QFrame.HLine)
        rp_sep.setStyleSheet(f"color: {get_fx_color('card_border', True)}; background-color: {get_fx_color('card_border', True)}; max-height: 1px; border: none;")
        rp_layout.addWidget(rp_sep)
        self.btn_stress = QPushButton("Stress Replay Worst Point (+75%)")
        self.btn_stress.setProperty("class", "secondary")
        self.btn_stress.setIcon(get_svg_icon("volume-2", color="#d51535"))
        self.btn_stress.setIconSize(QSize(16, 16))
        self.btn_stress.setMinimumHeight(36)
        self.btn_stress.setToolTip("Replays the worst detected frequency ~75% louder. If buzz or distortion appears only at this level, the fault is likely level-dependent (amplifier/driver excursion), not a frequency dip.")
        self.btn_stress.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.btn_stress.clicked.connect(self._stress_replay_worst_point)
        rp_layout.addWidget(self.btn_stress)
        self.lbl_stress_note = QLabel("")
        self.lbl_stress_note.setProperty("class", "hint")
        self.lbl_stress_note.setWordWrap(True)
        rp_layout.addWidget(self.lbl_stress_note)
        rp_layout.addStretch()
        split.addWidget(right_panel)
        # Keep export panel always visible: 61%/39% split, stretch 3:2
        split.setSizes([620, 360])
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        # Persist splitter; ensure at least 340px for export on 860 min width
        split.setCollapsible(0, False)
        split.setCollapsible(1, False)
        layout.addWidget(split, 1)
        self.stack.addWidget(self.results_page)

    def _set_res_filter(self, channel: str):
        self._res_filter = channel
        self.results_plot.set_channel_filter(channel)
        for btn, name in (
            (self.btn_filter_both, "both"),
            (self.btn_filter_left, "left"),
            (self.btn_filter_right, "right")
        ):
            btn.setProperty("class", "toggle-yes-active" if name == channel else "secondary")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _stress_replay_worst_point(self):
        worst_reg, worst_meas = self._find_global_worst_point()
        if worst_reg is None or worst_meas is None:
            self.lbl_stress_note.setText("No anomaly region detected in this session.")
            return
        ch = worst_reg.channel if worst_reg.channel in ("left", "right") else "both"
        freq = worst_meas.frequency_hz
        tone = self.audio_engine.generate_sine_tone(freq, duration_s=2.5, peak=0.7, channel=ch)
        self.audio_engine.play_audio(
            tone,
            on_started=lambda: self.audio_bridge.playback_started.emit(freq),
            on_finished=lambda ok, err: self.audio_bridge.playback_finished.emit(ok, err or ""),
            spectrum_meta={"buffer": tone, "sample_rate": self.audio_engine.sample_rate}
        )
        self.lbl_stress_note.setText(
            f"Replaying ~{freq:,.0f} Hz on {ch.upper()} at +75% level. "
            "Buzz/distortion only now? Likely level-dependent. Clean but quiet? Frequency dip confirmed."
        )

    def _find_global_worst_point(self) -> Tuple[Optional[Region], Optional[Measurement]]:
        best_reg: Optional[Region] = None
        best_m: Optional[Measurement] = None
        for res in self.session.channel_results.values():
            for reg in res.regions:
                if reg.category == RegionCategory.EXPECTED_LOW_ROLLOFF:
                    continue
                if best_reg is None or reg.min_quality < best_reg.min_quality:
                    best_reg = reg
        if best_reg is not None and best_reg.points:
            best_m = min(best_reg.points, key=lambda p: p.quality)
        return best_reg, best_m

    def _on_plot_point_clicked(self, freq: float, channel: str):
        tone = self.audio_engine.generate_sine_tone(freq, duration_s=1.5, channel=channel)
        self.audio_engine.play_audio(
            tone,
            on_started=lambda: self.audio_bridge.playback_started.emit(freq),
            on_finished=lambda ok, err: self.audio_bridge.playback_finished.emit(ok, err or ""),
            spectrum_meta={"buffer": tone, "sample_rate": self.audio_engine.sample_rate}
        )

    def _export_csv(self):
        if not self.session:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export CSV", "measurements.csv", "CSV Files (*.csv)")
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(self.session.export_csv_string())
                QMessageBox.information(self, "Export", f"Measurements saved to:\n{path}")
            except Exception as e:
                QMessageBox.critical(self, "Error", str(e))

    def _save_session_json(self):
        if not self.session:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save JSON", f"session_{self.session.session_id}.json", "JSON Files (*.json)")
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(self.session.to_dict(), f, indent=2)
                QMessageBox.information(self, "Saved", f"Session saved to:\n{path}")
            except Exception as e:
                QMessageBox.critical(self, "Error", str(e))

    def _export_report_html(self):
        if not self.session:
            return
        path, selected = QFileDialog.getSaveFileName(
            self, "Export Premium Report",
            f"FreqChecker_Report_{self.session.session_id}.html",
            "HTML Report (*.html);;Text Report (*.txt)"
        )
        if not path:
            return
        try:
            # Use selected filter to decide format, but also honor explicit extension
            is_html = "HTML" in selected or path.lower().endswith((".html", ".htm"))
            if is_html:
                if not path.lower().endswith((".html", ".htm")):
                    path += ".html"
                html = self.session.generate_html_report()
                with open(path, "w", encoding="utf-8") as f:
                    f.write(html)
                QMessageBox.information(self, "Export", f"Premium HTML report saved to:\n{path}\n\nOpen in browser -> Print -> Save as PDF for a premium PDF.")
            else:
                if not path.lower().endswith(".txt"):
                    path += ".txt"
                with open(path, "w", encoding="utf-8") as f:
                    f.write(self.session.generate_report())
                QMessageBox.information(self, "Export", f"Text report saved to:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    # kept for compatibility (plain text export)
    def _export_report_txt(self):
        if not self.session:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export Text Report", "diagnostic_report.txt", "Text Files (*.txt)")
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(self.session.generate_report())
                QMessageBox.information(self, "Export", f"Report saved to:\n{path}")
            except Exception as e:
                QMessageBox.critical(self, "Error", str(e))

    def _load_session_json(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load Session", "", "JSON Files (*.json)")
        if path:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.session = Session.from_dict(data)
                self._display_results()
            except Exception as e:
                QMessageBox.critical(self, "Error", str(e))

    # =========================================================================
    # 7. ADAPTIVE TEST EXECUTION LIFECYCLE
    # =========================================================================
    def _start_diagnostic_session(self):
        mode = self.mode_combo.currentData()
        ch_mode = self.channel_combo.currentData()
        if ch_mode == "left":
            self.channels_to_test = ["left"]
        elif ch_mode == "right":
            self.channels_to_test = ["right"]
        else:
            self.channels_to_test = ["left", "right"]
        self.channel_idx = 0
        self.current_channel = self.channels_to_test[0]
        self.controller = DiagnosticController(mode=mode)
        self.scheduler = TestScheduler(mode=mode)
        # Handle sub-bass inclusion for quick mode (addresses "125Hz not audible" feedback)
        if mode == "quick" and hasattr(self, "chk_include_subbass") and self.chk_include_subbass.isChecked():
            subbass_quick = [125.0, 250.0, 500.0, 1000.0, 2000.0, 4000.0, 8000.0]
            self.controller.grid = subbass_quick
            self.scheduler.grid = subbass_quick
        self.blind_mode = self.chk_blind.isChecked()
        self._sweep_retest_active = False
        self.start_time = time.time()
        dev_name = self.device_combo.currentText()
        self.session = Session(
            mode=mode,
            sample_rate=self.audio_engine.sample_rate,
            duration_per_tone=2.0,
            peak_level=0.4,
            fxsound_disabled=self.chk_fxsound.isChecked(),
            enhancements_disabled=self.chk_enhancements.isChecked(),
            output_device_name=dev_name,
            channel_mode=ch_mode
        )
        self._start_channel_test(self.current_channel)

    def _start_channel_test(self, channel: str):
        self.current_channel = channel
        self.scheduler.start_channel(channel)
        if self.scheduler.manual_mode:
            self.scheduler.load_manual_queue(self._manual_retest_freqs)
        self._progress_floor = 0
        self._max_queue_len = 0
        self._switch_page(PAGE_TESTING)
        self._update_channel_badge()
        self._present_next_test()

    def _update_channel_badge(self):
        ch = self.current_channel.upper()
        # FxSound-exact: Left = primary_accent (crimson/cyan), Right = cyan_secondary
        left_bg = get_fx_color("primary_accent", self.is_dark_theme)
        right_bg = get_fx_color("cyan_secondary", self.is_dark_theme)
        if ch == "LEFT":
            self.lbl_channel_badge.setText("LEFT CHANNEL")
            self.lbl_channel_badge.setStyleSheet(
                f"background: {left_bg}; color: #ffffff; padding: 5px 14px; border-radius: 7px; "
                f"font-weight: 800; font-size: 11px; letter-spacing: 0.8px;"
            )
        elif ch == "RIGHT":
            self.lbl_channel_badge.setText("RIGHT CHANNEL")
            right_tc = "#0f0f0f" if self.is_dark_theme else "#ffffff"
            self.lbl_channel_badge.setStyleSheet(
                f"background: {right_bg}; color: {right_tc}; padding: 5px 14px; border-radius: 7px; "
                f"font-weight: 800; font-size: 11px; letter-spacing: 0.8px;"
            )
        else:
            self.lbl_channel_badge.setText("BOTH CHANNELS")
            self.lbl_channel_badge.setStyleSheet(
                f"background: {left_bg}; color: #ffffff; padding: 5px 14px; border-radius: 7px; "
                f"font-weight: 800; font-size: 11px; letter-spacing: 0.8px;"
            )

    def _present_next_test(self):
        item = self.scheduler.get_current_test()
        if item is None:
            self._handle_channel_phase_transition()
            return
        freq = item["freq"]
        stage = item["stage"]
        is_control = item.get("is_control", False)
        if self.blind_mode and not is_control:
            self.lbl_frequency.setText("Hidden")
            self.lbl_frequency.setToolTip("Blind Mode active - the frequency is revealed in the final report.")
        else:
            self.lbl_frequency.setText(f"{freq:,.1f} Hz" if freq < 1000 else f"{freq:,.0f} Hz")
            self.lbl_frequency.setToolTip("")
        queue_len = len(self.scheduler.test_queue)
        cur_idx = self.scheduler.current_idx
        if is_control:
            self.lbl_stage_info.setText(f"Reference Tone (1 kHz) · {cur_idx + 1}/{queue_len}")
        else:
            stage_title = stage.replace("_", " ").title()
            self.lbl_stage_info.setText(f"{stage_title} · {cur_idx + 1}/{queue_len}")
        self._max_queue_len = max(self._max_queue_len, queue_len)
        pct = int(100.0 * (cur_idx / float(max(1, self._max_queue_len))))
        pct = max(pct, self._progress_floor)
        self._progress_floor = pct
        self.progress_bar.setValue(pct)
        remaining = max(0, queue_len - cur_idx)
        self.lbl_remaining.setText(f"~{remaining} left")
        
        # Reset selection states
        self._heard_selection = None
        self.last_playback_ok = None
        self.btn_choice_yes.setProperty("class", "toggle-choice")
        self.btn_choice_no.setProperty("class", "toggle-choice")
        self.btn_choice_yes.style().unpolish(self.btn_choice_yes)
        self.btn_choice_yes.style().polish(self.btn_choice_yes)
        self.btn_choice_no.style().unpolish(self.btn_choice_no)
        self.btn_choice_no.style().polish(self.btn_choice_no)
        self.dist_slider.setValue(0)
        self.lbl_dist_val.setText("0")
        self._update_pill_selection(-1)
        self.clarity_box.setVisible(False)
        
        if self.current_channel == "left":
            self.live_plot.set_data(self.scheduler.active_measurements, [])
        else:
            left_done = self.session.channel_results.get("left", ChannelResult("left")).measurements
            self.live_plot.set_data(left_done, self.scheduler.active_measurements)
        self._replay_current_tone()

    def _replay_current_tone(self):
        item = self.scheduler.get_current_test()
        if item is not None:
            freq = item["freq"]
            self._tone_started_at = time.time()
            self.last_playback_ok = None
            tone = self.audio_engine.generate_sine_tone(freq, duration_s=2.0, channel=self.current_channel)
            self.audio_engine.play_audio(
                tone,
                on_started=lambda: self.audio_bridge.playback_started.emit(freq),
                on_finished=lambda ok, err: self.audio_bridge.playback_finished.emit(ok, err or ""),
                spectrum_meta={"buffer": tone, "sample_rate": self.audio_engine.sample_rate}
            )

    def _undo_last_rating(self):
        if self.stack.currentIndex() != PAGE_TESTING:
            return
        if not self.scheduler.active_measurements or self.scheduler.current_idx <= 0:
            return
        self.scheduler.undo_last_measurement()
        self._present_next_test()

    def _handle_channel_phase_transition(self):
        action, reason_or_status, count = self.scheduler.handle_phase_transition(self.controller)
        if action == "ABORT":
            self._finalize_channel(is_global_problem=True, global_problem_type=reason_or_status)
        elif action == "CONTINUE":
            self._present_next_test()
        else:
            result_key = "sweep" if self._sweep_retest_active else None
            self._finalize_channel(is_global_problem=False, result_key=result_key)

    def _finalize_channel(self, is_global_problem: bool = False, global_problem_type: str = "", result_key: Optional[str] = None):
        active_meas = self.scheduler.active_measurements
        anchor = self.controller.rating_anchor(active_meas)
        controls_ok = self.controller.check_control_stability(active_meas)
        analyze_regions = not is_global_problem and not self._sweep_retest_active
        regions = self.controller.detect_regions(active_meas, self.current_channel) if analyze_regions else []
        scored_regions = []
        if analyze_regions:
            for reg in regions:
                reg = self.controller.expand_region_boundaries(reg, active_meas)
                scored = self.controller.score_region(
                    reg,
                    active_meas,
                    fxsound_disabled=self.session.fxsound_disabled,
                    enhancements_disabled=self.session.enhancements_disabled
                )
                scored_regions.append(scored)
        valid_m = [m for m in active_meas if not m.input_error]
        avg_clarity = (sum(m.clarity for m in valid_m) / float(len(valid_m))) if valid_m else 0.0
        res = ChannelResult(
            channel=self.current_channel,
            measurements=list(active_meas),
            regions=scored_regions,
            avg_clarity=round(avg_clarity, 1),
            rating_anchor=round(anchor, 1),
            is_global_problem=is_global_problem,
            global_problem_type=global_problem_type,
            is_control_unstable=(not controls_ok)
        )
        self.session.channel_results[result_key or self.current_channel] = res
        if result_key == "sweep":
            self._finish_all_tests()
            return
        self._sweep_retest_active = False
        self.channel_idx += 1
        if self.channel_idx < len(self.channels_to_test):
            self._start_channel_test(self.channels_to_test[self.channel_idx])
        else:
            self._finish_all_tests()

    def _finish_all_tests(self):
        self.session.elapsed_seconds = time.time() - self.start_time
        self.session.cross_channel_findings = self.controller.evaluate_cross_channel(self.session)
        self._display_results()

    def _display_results(self):
        if not self.session:
            return
        left_res = self.session.channel_results.get("left", ChannelResult("left"))
        right_res = self.session.channel_results.get("right", ChannelResult("right"))
        self.results_plot.set_data(
            left_res.measurements,
            right_res.measurements,
            left_res.regions,
            right_res.regions
        )
        # Premium in-app rendering: try HTML (rich) with fallback to plain if renderer fails
        try:
            html = self.session.generate_html_report()
            self.txt_report.setHtml(html)
        except Exception:
            report_text = self.session.generate_report()
            self.txt_report.setPlainText(report_text)
        self._switch_page(PAGE_RESULTS)

    def _stop_current_test(self):
        self.audio_engine.stop_playback()
        page = self.stack.currentIndex()
        if page == PAGE_SWEEP:
            self._stop_sweep()
        elif page == PAGE_MUSIC:
            self._music_stop()
        elif page == PAGE_TESTING:
            if not self._offer_partial_save():
                return
            self._switch_page(PAGE_WIZARD)


def main():
    import argparse
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--frameless", action="store_true", help="(Default) Use FxSound-exact frameless chrome")
    parser.add_argument("--framed", action="store_true", help="Use the native OS window title bar instead of the FxSound chrome")
    parser.add_argument("--light", action="store_true", help="Start in light theme")
    args, _ = parser.parse_known_args()
    app = QApplication(sys.argv)
    fx_theme.load_app_fonts()
    is_dark_initial = not args.light
    fx_theme.set_theme("dark" if is_dark_initial else "light")
    app.setStyleSheet(fx_theme.get_qss(is_dark_initial))
    frameless = not args.framed
    window = FreqCheckerApp(frameless=frameless)
    window.is_dark_theme = is_dark_initial
    # ensure toggle button text matches initial
    try:
        accent = get_fx_color("primary_accent", is_dark_initial)
        window.btn_theme_toggle.setText("Dark Mode" if is_dark_initial else "Light Mode")
        window.btn_theme_toggle.setIcon(get_svg_icon("moon" if is_dark_initial else "sun", color=accent))
        if hasattr(window, "_title_bar"):
            window._title_bar.update_theme(is_dark_initial)
    except Exception:
        pass
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
