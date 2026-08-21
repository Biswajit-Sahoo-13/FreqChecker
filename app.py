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
from typing import List, Dict, Optional, Tuple, Any

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QStackedWidget, QVBoxLayout,
    QHBoxLayout, QLabel, QPushButton, QSlider, QComboBox, QCheckBox,
    QProgressBar, QTextEdit, QFileDialog, QMessageBox, QFrame,
    QSplitter, QSpinBox, QDoubleSpinBox
)
from PySide6.QtCore import Qt, QTimer, Signal, QObject, Slot, QSize
from PySide6.QtGui import QKeySequence, QShortcut

from models import (
    Measurement, Region, ChannelResult, Session,
    Classification, Stage, RegionCategory
)
from audio_engine import AudioEngine
from diagnostic_core import DiagnosticController, DiagnosticConfig, TestScheduler
from ui_components import (
    LogFrequencyPlotWidget, FxSpectrumVisualizerWidget,
    DARK_THEME_QSS, LIGHT_THEME_QSS
)
from icons import get_svg_icon

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


class FreqCheckerApp(QMainWindow):
    """
    Main application window implementing all diagnostic modes, wizards, and report dashboards.
    """
    def __init__(self):
        super().__init__()
        self.setWindowTitle("FreqChecker — Speaker Diagnostic Studio")
        self.resize(1060, 720)
        self.setMinimumSize(860, 580)
        self.is_dark_theme: bool = True
        
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
        
        # Central Widget
        self.central_widget = QWidget()
        self.central_widget.setObjectName("CentralWidget")
        self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(16, 12, 16, 14)
        self.main_layout.setSpacing(10)
        
        # Build Global Top Navigation Bar
        self._build_top_navbar()
        
        # Stacked Views
        self.stack = QStackedWidget()
        self.main_layout.addWidget(self.stack, 1)
        
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

    def closeEvent(self, event):
        if hasattr(self, "sweep_timer"):
            self.sweep_timer.stop()
        if hasattr(self, "music_timer"):
            self.music_timer.stop()
        self.audio_engine.stop_playback()
        event.accept()

    # =========================================================================
    # GLOBAL TOP NAVBAR & THEME SWITCHER
    # =========================================================================
    def _build_top_navbar(self):
        nav_card = QFrame()
        nav_card.setProperty("class", "card")
        n_layout = QHBoxLayout(nav_card)
        n_layout.setContentsMargins(16, 8, 16, 8)
        n_layout.setSpacing(14)
        
        # Brand / Logo
        brand_layout = QVBoxLayout()
        brand_layout.setSpacing(0)
        lbl_brand = QLabel("FREQCHECKER")
        lbl_brand.setProperty("class", "brand-title")
        lbl_tag = QLabel("SPEAKER DIAGNOSTIC STUDIO")
        lbl_tag.setStyleSheet("font-size: 9px; font-weight: 700; color: #00A2FF; letter-spacing: 1px;")
        brand_layout.addWidget(lbl_brand)
        brand_layout.addWidget(lbl_tag)
        n_layout.addLayout(brand_layout)
        n_layout.addStretch()
        
        # Top Center 9-Band Spectrum Visualizer Monitor Box (Explaining what it does)
        vis_container = QFrame()
        vis_container.setStyleSheet("background: transparent;")
        vis_layout = QVBoxLayout(vis_container)
        vis_layout.setContentsMargins(0, 0, 0, 0)
        vis_layout.setSpacing(2)
        vis_layout.setAlignment(Qt.AlignCenter)
        
        vis_header = QHBoxLayout()
        vis_header.setSpacing(6)
        vis_header.setAlignment(Qt.AlignCenter)
        lbl_vis_title = QLabel("LIVE 9-BAND SPECTRUM MONITOR")
        lbl_vis_title.setStyleSheet("font-size: 9px; font-weight: 700; color: #00A2FF; letter-spacing: 0.8px;")
        lbl_vis_desc = QLabel("(63 Hz – 16 kHz)")
        lbl_vis_desc.setStyleSheet("font-size: 9px; color: #8A99AD;")
        vis_header.addWidget(lbl_vis_title)
        vis_header.addWidget(lbl_vis_desc)
        vis_layout.addLayout(vis_header)
        
        self.top_visualizer = FxSpectrumVisualizerWidget()
        vis_layout.addWidget(self.top_visualizer)
        n_layout.addWidget(vis_container)
        n_layout.addStretch()
        
        # Theme Switcher Button with SVG Icon
        self.btn_theme_toggle = QPushButton("Dark Mode")
        self.btn_theme_toggle.setProperty("class", "secondary")
        self.btn_theme_toggle.setFixedHeight(34)
        self.btn_theme_toggle.setIcon(get_svg_icon("moon", color="#00A2FF"))
        self.btn_theme_toggle.setIconSize(QSize(16, 16))
        self.btn_theme_toggle.clicked.connect(self._toggle_theme)
        n_layout.addWidget(self.btn_theme_toggle)
        
        self.main_layout.addWidget(nav_card)

    def _toggle_theme(self):
        self.is_dark_theme = not self.is_dark_theme
        qss = DARK_THEME_QSS if self.is_dark_theme else LIGHT_THEME_QSS
        QApplication.instance().setStyleSheet(qss)
        if self.is_dark_theme:
            self.btn_theme_toggle.setText("Dark Mode")
            self.btn_theme_toggle.setIcon(get_svg_icon("moon", color="#00A2FF"))
        else:
            self.btn_theme_toggle.setText("Light Mode")
            self.btn_theme_toggle.setIcon(get_svg_icon("sun", color="#0084E6"))
        self.top_visualizer.set_theme(self.is_dark_theme)
        self.live_plot.set_theme(self.is_dark_theme)
        self.results_plot.set_theme(self.is_dark_theme)
        self._update_channel_badge()

    def _switch_page(self, index: int):
        self.stack.setCurrentIndex(index)

    def _on_playback_started_ui(self, freq_hz: float = 1000.0):
        self.btn_replay.setEnabled(False)
        self.top_visualizer.set_playing_state(True, freq_hz)

    def _on_playback_finished_ui(self, ok: bool, err_msg: str):
        self.btn_replay.setEnabled(True)
        if hasattr(self, "btn_cal_play"):
            self.btn_cal_play.setEnabled(True)
        if hasattr(self, "btn_cal_stop"):
            self.btn_cal_stop.setEnabled(False)
        self.last_playback_ok = ok
        self.top_visualizer.set_playing_state(False)
        if not ok and err_msg:
            QTimer.singleShot(100, lambda: self._show_playback_error(err_msg))

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
        QShortcut(QKeySequence(Qt.Key_Escape), self, self._stop_current_test)
        QShortcut(QKeySequence("T"), self, lambda: self._submit_with(True, 10))
        for i in range(10):
            QShortcut(QKeySequence(str(i)), self, lambda val=i: self._submit_with(True, val))

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
        subtitle = QLabel(
            "Perceptual 1/3-octave frequency sweep with adaptive bisection to locate speaker dips, distortion, and rolloff."
        )
        subtitle.setProperty("class", "subtitle")
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
        
        # Calibration Tone Controls (Play + Stop Button with SVG Icons)
        cal_row = QHBoxLayout()
        cal_row.setSpacing(8)
        self.btn_cal_play = QPushButton("Play 1 kHz Calibration Tone")
        self.btn_cal_play.setProperty("class", "secondary")
        self.btn_cal_play.setIcon(get_svg_icon("play", color="#00A2FF"))
        self.btn_cal_play.setIconSize(QSize(16, 16))
        self.btn_cal_play.clicked.connect(self._play_calibration_tone)
        
        self.btn_cal_stop = QPushButton("Stop")
        self.btn_cal_stop.setProperty("class", "danger")
        self.btn_cal_stop.setIcon(get_svg_icon("stop", color="#FFFFFF"))
        self.btn_cal_stop.setIconSize(QSize(14, 14))
        self.btn_cal_stop.setEnabled(False)
        self.btn_cal_stop.setFixedWidth(80)
        self.btn_cal_stop.clicked.connect(self._stop_calibration_tone)
        
        cal_row.addWidget(self.btn_cal_play, 1)
        cal_row.addWidget(self.btn_cal_stop)
        cl_layout.addLayout(cal_row)
        
        vol_info = QLabel(
            "- Keep system volume steady at 40-60% throughout the test.\n"
            "- Calibration tone plays on both channels to set your hearing baseline.\n"
            "- Use the Stop button anytime to silence calibration immediately."
        )
        vol_info.setStyleSheet("color: #B0B0B0; font-size: 11px;")
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
        self.btn_autodetect.setIcon(get_svg_icon("zap", color="#00A2FF"))
        self.btn_autodetect.setIconSize(QSize(14, 14))
        self.btn_autodetect.setFixedHeight(28)
        self.btn_autodetect.setToolTip("Auto-scans running DSP processes, audio hardware configuration, and ambient noise.")
        self.btn_autodetect.clicked.connect(self._run_preflight_autodetect)
        cr_header_row.addWidget(self.btn_autodetect)
        cr_layout.addLayout(cr_header_row)
        
        # Pre-Flight Auto-Detection Status Card
        status_box = QFrame()
        status_box.setStyleSheet(
            "background-color: rgba(30, 36, 48, 0.6); border: 1px solid #2E3542; border-radius: 8px; padding: 6px;"
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
        self.lbl_preflight_summary.setStyleSheet("font-size: 10px; font-weight: 700; color: #00A2FF;")
        
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
        calib_note.setStyleSheet("color: #00A2FF; font-size: 11px; font-weight: 600;")
        calib_note.setWordWrap(True)
        cr_layout.addWidget(calib_note)
        
        cr_layout.addWidget(QLabel("Diagnostic Mode:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Detailed (1/3-Octave + Adaptive Bisection)", "detailed")
        self.mode_combo.addItem("Quick (~8 test frequencies)", "quick")
        cr_layout.addWidget(self.mode_combo)
        
        btn_start_diag = QPushButton("Start Diagnostic Test")
        btn_start_diag.setIcon(get_svg_icon("arrow-right", color="#FFFFFF"))
        btn_start_diag.setIconSize(QSize(16, 16))
        btn_start_diag.setStyleSheet("font-size: 14px; padding: 12px 24px; font-weight: 700;")
        btn_start_diag.clicked.connect(self._start_diagnostic_session)
        cr_layout.addWidget(btn_start_diag)
        
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_manual = QPushButton("Manual Tone")
        btn_manual.setProperty("class", "secondary")
        btn_manual.setIcon(get_svg_icon("activity", color="#00A2FF"))
        btn_manual.clicked.connect(lambda: self._switch_page(PAGE_MANUAL))
        btn_sweep = QPushButton("Sweep Mode")
        btn_sweep.setProperty("class", "secondary")
        btn_sweep.setIcon(get_svg_icon("activity", color="#00A2FF"))
        btn_sweep.clicked.connect(lambda: self._switch_page(PAGE_SWEEP))
        btn_music = QPushButton("Music Test")
        btn_music.setProperty("class", "secondary")
        btn_music.setIcon(get_svg_icon("volume-2", color="#00A2FF"))
        btn_music.clicked.connect(lambda: self._switch_page(PAGE_MUSIC))
        btn_row.addWidget(btn_manual)
        btn_row.addWidget(btn_sweep)
        btn_row.addWidget(btn_music)
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
            self.lbl_preflight_summary.setStyleSheet("font-size: 10px; font-weight: 700; color: #888888;")
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
            self.lbl_preflight_summary.setStyleSheet("font-size: 10px; font-weight: 700; color: #00E5FF;")
        else:
            self.lbl_preflight_summary.setText("[Status] Pre-Flight Notice: Check recommendations above before starting")
            self.lbl_preflight_summary.setStyleSheet("font-size: 10px; font-weight: 700; color: #FFB300;")

    def _play_calibration_tone(self):
        if hasattr(self, "btn_cal_play"):
            self.btn_cal_play.setEnabled(False)
        if hasattr(self, "btn_cal_stop"):
            self.btn_cal_stop.setEnabled(True)
        tone = self.audio_engine.generate_sine_tone(1000.0, duration_s=2.5, peak=0.4, channel="both")
        self.audio_engine.play_audio(
            tone,
            on_started=lambda: self.audio_bridge.playback_started.emit(1000.0),
            on_finished=lambda ok, err: self.audio_bridge.playback_finished.emit(ok, err or "")
        )

    def _stop_calibration_tone(self):
        self.audio_engine.stop_playback()
        if hasattr(self, "btn_cal_play"):
            self.btn_cal_play.setEnabled(True)
        if hasattr(self, "btn_cal_stop"):
            self.btn_cal_stop.setEnabled(False)
        self.top_visualizer.set_playing_state(False)

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
            "background: #00E5FF; color: #14161A; padding: 5px 14px; border-radius: 7px; "
            "font-weight: 800; font-size: 11px; letter-spacing: 0.8px;"
        )
        
        self.lbl_stage_info = QLabel("Stage: Coarse Scan · 1/25")
        self.lbl_stage_info.setStyleSheet("color: #B0B0B0; font-size: 12px; font-weight: 600;")
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedWidth(160)
        
        self.lbl_remaining = QLabel("~24 tests left")
        self.lbl_remaining.setStyleSheet("color: #888888; font-size: 11px;")
        
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
        
        # Tone Header Row (Frequency + Replay Button with SVG Icon)
        freq_row = QHBoxLayout()
        self.lbl_frequency = QLabel("1,000 Hz")
        self.lbl_frequency.setProperty("class", "freq-display")
        self.btn_replay = QPushButton("Replay Tone (R)")
        self.btn_replay.setProperty("class", "secondary")
        self.btn_replay.setIcon(get_svg_icon("rotate-ccw", color="#00A2FF"))
        self.btn_replay.setIconSize(QSize(16, 16))
        self.btn_replay.setFixedHeight(38)
        self.btn_replay.clicked.connect(self._replay_current_tone)
        freq_row.addWidget(self.lbl_frequency)
        freq_row.addStretch()
        freq_row.addWidget(self.btn_replay)
        tc_layout.addLayout(freq_row)
        
        # Prominent Yes / No Choice Buttons with SVG Icons
        choice_row = QHBoxLayout()
        choice_row.setSpacing(14)
        self.btn_choice_yes = QPushButton("Yes, I Heard It (Y)")
        self.btn_choice_yes.setProperty("class", "toggle-choice")
        self.btn_choice_yes.setIcon(get_svg_icon("check", color="#00E5FF"))
        self.btn_choice_yes.setIconSize(QSize(18, 18))
        self.btn_choice_yes.setFixedHeight(46)
        self.btn_choice_yes.clicked.connect(lambda: self._select_heard(True))
        
        self.btn_choice_no = QPushButton("No, Didn't Hear (N)")
        self.btn_choice_no.setProperty("class", "toggle-choice")
        self.btn_choice_no.setIcon(get_svg_icon("x", color="#FF5252"))
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
        c_label.setStyleSheet("font-size: 12px; font-weight: 600; color: #B0B0B0;")
        c_header.addWidget(c_label)
        c_header.addStretch()
        
        # Optional Distortion slider
        dist_lbl = QLabel("Buzz / Distortion (opt):")
        dist_lbl.setStyleSheet("color: #888888; font-size: 11px;")
        self.dist_slider = QSlider(Qt.Horizontal)
        self.dist_slider.setRange(0, 10)
        self.dist_slider.setValue(0)
        self.dist_slider.setFixedWidth(100)
        self.lbl_dist_val = QLabel("0")
        self.lbl_dist_val.setStyleSheet("color: #888888; font-size: 11px; font-weight: 600;")
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
        hint.setStyleSheet("color: #707580; font-size: 11px;")
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
        btn_back.setIcon(get_svg_icon("arrow-left", color="#00A2FF"))
        btn_back.setIconSize(QSize(14, 14))
        btn_back.clicked.connect(lambda: self._switch_page(PAGE_WIZARD))
        tc_layout.addWidget(title)
        tc_layout.addStretch()
        tc_layout.addWidget(btn_back)
        layout.addWidget(top_card)
        
        # Movable Splitter for Manual View
        manual_splitter = QSplitter(Qt.Horizontal)
        manual_splitter.setHandleWidth(8)
        manual_splitter.setChildrenCollapsible(False)
        
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
        self.btn_play_manual.setIcon(get_svg_icon("play", color="#121212"))
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
        guide_text.setStyleSheet("color: #B0B0B0; font-size: 12px; line-height: 1.5;")
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
            on_finished=lambda ok, err: self.audio_bridge.playback_finished.emit(ok, err or "")
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
        btn_back.setIcon(get_svg_icon("arrow-left", color="#00A2FF"))
        btn_back.setIconSize(QSize(14, 14))
        btn_back.clicked.connect(lambda: self._switch_page(PAGE_WIZARD))
        tc_layout.addWidget(title)
        tc_layout.addStretch()
        tc_layout.addWidget(btn_back)
        layout.addWidget(top_card)
        
        # Movable Splitter for Sweep View
        sweep_splitter = QSplitter(Qt.Horizontal)
        sweep_splitter.setHandleWidth(8)
        sweep_splitter.setChildrenCollapsible(False)
        
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
        info.setStyleSheet("color: #B0B0B0; font-size: 12px;")
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
            "background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0077FF, stop:1 #00A2FF); color: #FFFFFF; border-radius: 9px;"
        )
        self.btn_mark_sweep.setFocusPolicy(Qt.NoFocus)
        self.btn_mark_sweep.clicked.connect(self._mark_sweep_anomaly)
        self.btn_mark_sweep.setEnabled(False)
        
        btn_stop_sw = QPushButton("Stop")
        btn_stop_sw.setProperty("class", "danger")
        btn_stop_sw.setIcon(get_svg_icon("stop", color="#FFFFFF"))
        btn_stop_sw.setIconSize(QSize(14, 14))
        btn_stop_sw.setFocusPolicy(Qt.NoFocus)
        btn_stop_sw.clicked.connect(self._stop_sweep)
        
        act_row.addWidget(self.btn_start_sweep)
        act_row.addWidget(self.btn_mark_sweep)
        act_row.addWidget(btn_stop_sw)
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
        self.lbl_sweep_progress.setStyleSheet("font-size: 28px; font-weight: 800; color: #00E5FF;")
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
        self._consecutive_stopped_ticks = 0
        self.sweep_start_time = None
        self.txt_sweep_marks.clear()
        self.btn_mark_sweep.setEnabled(True)
        audio = self.audio_engine.generate_log_sweep(100.0, 10000.0, duration_s=dur, channel=ch)
        self.audio_engine.play_audio(
            audio,
            on_started=lambda: self.audio_bridge.sweep_started.emit(),
            on_finished=lambda ok, err: self.audio_bridge.playback_finished.emit(ok, err or "")
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
        self.top_visualizer.set_playing_state(True, cur_f)

    def _mark_sweep_anomaly(self):
        if self.sweep_start_time is None:
            return
        # Compensate for buffer output latency (~35ms)
        elapsed = max(0.0, (time.time() - 0.035) - self.sweep_start_time)
        ratio = min(1.0, elapsed / self.sweep_total_duration)
        cur_f = 100.0 * ((10000.0 / 100.0) ** ratio)
        self.sweep_marks.append(cur_f)
        self.txt_sweep_marks.append(f"• Anomaly marked at ~{cur_f:,.0f} Hz (at {elapsed:.1f}s)")

    def _on_space_sweep(self):
        if self.stack.currentIndex() == PAGE_SWEEP and self.audio_engine.is_playing():
            self._mark_sweep_anomaly()

    def _stop_sweep(self):
        self.sweep_timer.stop()
        self.audio_engine.stop_playback()
        self.btn_mark_sweep.setEnabled(False)
        self.lbl_sweep_progress.setText("Sweep Complete")
        self.top_visualizer.set_playing_state(False)

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
        btn_back.setIcon(get_svg_icon("arrow-left", color="#00A2FF"))
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
        desc.setStyleSheet("color: #B0B0B0; font-size: 12px;")
        desc.setWordWrap(True)
        c.addWidget(desc)
        
        # File Loading Row
        file_row = QHBoxLayout()
        self.btn_music_load = QPushButton("Load Music Track...")
        self.btn_music_load.setProperty("class", "secondary")
        self.btn_music_load.setIcon(get_svg_icon("folder", color="#00A2FF"))
        self.btn_music_load.setIconSize(QSize(16, 16))
        self.btn_music_load.setFixedHeight(36)
        self.btn_music_load.clicked.connect(self._load_music_file)
        self.lbl_music_file = QLabel("No track loaded")
        self.lbl_music_file.setStyleSheet("color: #888888; font-size: 12px;")
        file_row.addWidget(self.btn_music_load)
        file_row.addWidget(self.lbl_music_file, 1)
        c.addLayout(file_row)
        
        if not SOUNDFILE_AVAILABLE:
            sf_note = QLabel("[Note] Music playback requires the optional 'soundfile' package (pip install soundfile).")
            sf_note.setStyleSheet("color: #FF5252; font-size: 11px; font-weight: 600;")
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
        self.lbl_music_vol.setStyleSheet("color: #00A2FF; font-weight: 700; font-size: 12px;")
        self.slider_music_vol.valueChanged.connect(lambda v: self.lbl_music_vol.setText(f"{v}%"))
        vol_row.addWidget(self.slider_music_vol, 1)
        vol_row.addWidget(self.lbl_music_vol)
        c.addLayout(vol_row)
        
        # Position & Seek Slider
        pos_row = QHBoxLayout()
        self.lbl_music_pos = QLabel("0:00 / 0:00")
        self.lbl_music_pos.setStyleSheet("font-size: 15px; font-weight: 800; color: #00E5FF;")
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
        self.btn_music_play.setIcon(get_svg_icon("play", color="#121212"))
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
        self.lbl_music_status.setStyleSheet("color: #FF5252; font-size: 11px;")
        c.addWidget(self.lbl_music_status)
        
        hint_m = QLabel("Tip: Click 'Left' and 'Right' during music playback to instantly isolate and A/B compare each speaker.")
        hint_m.setStyleSheet("color: #707580; font-size: 11px;")
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
            on_finished=lambda ok, err: self.audio_bridge.music_finished.emit(ok, err or "")
        )

    def _music_pause(self):
        self.audio_engine.stop_playback()
        self.music_playing = False
        self._music_active = False
        self.music_timer.stop()
        self.btn_music_play.setText("Play Track")
        self.btn_music_play.setIcon(get_svg_icon("play", color="#121212"))

    def _music_stop(self):
        self.audio_engine.stop_playback()
        self.music_playing = False
        self._music_active = False
        self.music_timer.stop()
        self.music_pos_sec = 0.0
        self.slider_music_pos.setValue(0)
        self.lbl_music_pos.setText(f"0:00 / {_fmt_time(self._music_total_sec)}")
        self.btn_music_play.setText("Play Track")
        self.btn_music_play.setIcon(get_svg_icon("play", color="#121212"))
        self.top_visualizer.set_playing_state(False)

    def _music_restart(self):
        self.audio_engine.stop_playback()
        self.music_playing = False
        self._music_play()

    def _on_music_started_ui(self):
        self._music_started_wall = time.time()
        self.music_playing = True
        self.music_timer.start()
        self.btn_music_play.setText("Pause Track")
        self.btn_music_play.setIcon(get_svg_icon("pause", color="#121212"))
        self.top_visualizer.set_playing_state(True, 1000.0)

    def _on_music_finished_ui(self, ok: bool, err_msg: str):
        was_active = self._music_active
        self.music_playing = False
        self._music_active = False
        self.music_timer.stop()
        self.btn_music_play.setText("Play Track")
        self.btn_music_play.setIcon(get_svg_icon("play", color="#121212"))
        self.top_visualizer.set_playing_state(False)
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
        btn_new_test = QPushButton("Start New Test")
        btn_new_test.setIcon(get_svg_icon("arrow-right", color="#121212"))
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
        self.results_plot.setFixedHeight(240)
        self.results_plot.point_clicked.connect(self._on_plot_point_clicked)
        layout.addWidget(self.results_plot, 1)
        split = QSplitter(Qt.Horizontal)
        self.txt_report = QTextEdit()
        self.txt_report.setReadOnly(True)
        split.addWidget(self.txt_report)
        right_panel = QFrame()
        right_panel.setProperty("class", "card")
        rp_layout = QVBoxLayout(right_panel)
        rp_layout.setContentsMargins(16, 16, 16, 16)
        rp_layout.setSpacing(10)
        rp_title = QLabel("Export & Share")
        rp_title.setProperty("class", "section-title")
        rp_layout.addWidget(rp_title)
        btn_csv = QPushButton("Export Raw CSV Data")
        btn_csv.setProperty("class", "secondary")
        btn_csv.setIcon(get_svg_icon("download", color="#00A2FF"))
        btn_csv.setIconSize(QSize(16, 16))
        btn_csv.clicked.connect(self._export_csv)
        btn_json = QPushButton("Save Complete Session JSON")
        btn_json.setProperty("class", "secondary")
        btn_json.setIcon(get_svg_icon("download", color="#00A2FF"))
        btn_json.setIconSize(QSize(16, 16))
        btn_json.clicked.connect(self._save_session_json)
        btn_txt = QPushButton("Export Diagnostic Report (.txt)")
        btn_txt.setProperty("class", "secondary")
        btn_txt.setIcon(get_svg_icon("file-text", color="#00A2FF"))
        btn_txt.setIconSize(QSize(16, 16))
        btn_txt.clicked.connect(self._export_report_txt)
        btn_load = QPushButton("Load Previous Session JSON")
        btn_load.setProperty("class", "secondary")
        btn_load.setIcon(get_svg_icon("folder", color="#00A2FF"))
        btn_load.setIconSize(QSize(16, 16))
        btn_load.clicked.connect(self._load_session_json)
        rp_layout.addWidget(btn_csv)
        rp_layout.addWidget(btn_json)
        rp_layout.addWidget(btn_txt)
        rp_layout.addWidget(btn_load)
        rp_layout.addStretch()
        split.addWidget(right_panel)
        split.setSizes([680, 320])
        layout.addWidget(split, 1)
        self.stack.addWidget(self.results_page)

    def _set_res_filter(self, channel: str):
        self.results_plot.set_channel_filter(channel)

    def _on_plot_point_clicked(self, freq: float, channel: str):
        tone = self.audio_engine.generate_sine_tone(freq, duration_s=1.5, channel=channel)
        self.audio_engine.play_audio(
            tone,
            on_started=lambda: self.audio_bridge.playback_started.emit(freq),
            on_finished=lambda ok, err: self.audio_bridge.playback_finished.emit(ok, err or "")
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

    def _export_report_txt(self):
        if not self.session:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export Report", "diagnostic_report.txt", "Text Files (*.txt)")
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
        self._switch_page(PAGE_TESTING)
        self._update_channel_badge()
        self._present_next_test()

    def _update_channel_badge(self):
        ch = self.current_channel.upper()
        if ch == "LEFT":
            self.lbl_channel_badge.setText("LEFT CHANNEL")
            self.lbl_channel_badge.setStyleSheet(
                "background: #00E5FF; color: #14161A; padding: 5px 14px; border-radius: 7px; "
                "font-weight: 800; font-size: 11px; letter-spacing: 0.8px;"
            )
        else:
            self.lbl_channel_badge.setText("RIGHT CHANNEL")
            self.lbl_channel_badge.setStyleSheet(
                "background: #00A2FF; color: #FFFFFF; padding: 5px 14px; border-radius: 7px; "
                "font-weight: 800; font-size: 11px; letter-spacing: 0.8px;"
            )

    def _present_next_test(self):
        item = self.scheduler.get_current_test()
        if item is None:
            self._handle_channel_phase_transition()
            return
        freq = item["freq"]
        stage = item["stage"]
        is_control = item.get("is_control", False)
        self.lbl_frequency.setText(f"{freq:,.1f} Hz" if freq < 1000 else f"{freq:,.0f} Hz")
        queue_len = len(self.scheduler.test_queue)
        cur_idx = self.scheduler.current_idx
        if is_control:
            self.lbl_stage_info.setText(f"Reference Tone (1 kHz) · {cur_idx + 1}/{queue_len}")
        else:
            stage_title = stage.replace("_", " ").title()
            self.lbl_stage_info.setText(f"{stage_title} · {cur_idx + 1}/{queue_len}")
        pct = int(100.0 * (cur_idx / float(max(1, queue_len))))
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
                on_finished=lambda ok, err: self.audio_bridge.playback_finished.emit(ok, err or "")
            )

    def _handle_channel_phase_transition(self):
        action, reason_or_status, count = self.scheduler.handle_phase_transition(self.controller)
        if action == "ABORT":
            self._finalize_channel(is_global_problem=True, global_problem_type=reason_or_status)
        elif action == "CONTINUE":
            self._present_next_test()
        else:
            self._finalize_channel(is_global_problem=False)

    def _finalize_channel(self, is_global_problem: bool = False, global_problem_type: str = ""):
        active_meas = self.scheduler.active_measurements
        anchor = self.controller.rating_anchor(active_meas)
        controls_ok = self.controller.check_control_stability(active_meas)
        regions = self.controller.detect_regions(active_meas, self.current_channel)
        scored_regions = []
        if not is_global_problem:
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
            measurements=active_meas,
            regions=scored_regions,
            avg_clarity=round(avg_clarity, 1),
            rating_anchor=round(anchor, 1),
            is_global_problem=is_global_problem,
            global_problem_type=global_problem_type,
            is_control_unstable=(not controls_ok)
        )
        self.session.channel_results[self.current_channel] = res
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
            reply = QMessageBox.question(
                self, "Stop Diagnostic Test",
                "Are you sure you want to stop the test and return to setup?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                self._switch_page(PAGE_WIZARD)


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(DARK_THEME_QSS)
    window = FreqCheckerApp()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
