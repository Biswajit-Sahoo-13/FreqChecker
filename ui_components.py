"""
ui_components.py - Custom-painted widgets for FreqChecker.

Contains:
- FxSpectrumVisualizerWidget: a faithful reproduction of the FxSound scrolling
  spectrum visualizer (rounded control panel, 4 px bars on a 9.1 px pitch,
  center-mirrored scroll history, vertical GraphHigh/GraphLow gradient).
  Unlike decorative fake analyzers, it renders REAL band energies supplied by
  AudioEngine.get_spectrum_bands(), and its animation timer runs ONLY while
  audio is actually playing - zero idle repaints.
- LogFrequencyPlotWidget: interactive log-frequency response plot with
  anomaly shading, hover tooltips and click-to-replay.
"""

import math
from typing import List, Optional, Tuple, Callable
from PySide6.QtWidgets import QWidget, QToolTip, QSizePolicy
from PySide6.QtCore import Qt, QRectF, QPointF, Signal, QTimer
from PySide6.QtGui import (
    QPainter, QColor, QPen, QBrush, QFont, QPainterPath,
    QLinearGradient, QRadialGradient
)

import fx_theme
from fx_theme import (
    VIS_PANEL_RADIUS, VIS_BAR_WIDTH, VIS_BAR_PITCH, VIS_FPS,
    SPECTRUM_BANDS, FONT_FAMILY_STACK
)
from models import Measurement, Region, Classification, RegionCategory


def _color(hex_str: str, alpha: float = 1.0) -> QColor:
    c = QColor(hex_str)
    c.setAlphaF(max(0.0, min(1.0, alpha)))
    return c


# ══════════════════════════════════════════════════════════════════════════════
# FXSOUND-STYLE SPECTRUM VISUALIZER (data-driven)
# ══════════════════════════════════════════════════════════════════════════════

class FxSpectrumVisualizerWidget(QWidget):
    """
    Scrolling 9-band spectrum visualizer matching FxSound's rendering:

    - Rounded ControlBackground panel (radius 8)
    - 4 px wide bars on a 9.1 px pitch, drawn vertically centered
    - Per-band scroll history mirrored outwards from the panel center
    - Vertical gradient GraphHigh -> GraphLow -> GraphHigh
    - Alpha 1.0 while audio plays, 0.75 while decaying

    Data comes from `provider`, a callable returning either None (no audio)
    or a list of SPECTRUM_BANDS floats in [0, 1]. The internal timer runs at
    30 FPS only while audio is active (plus a short post-stop decay), then
    stops completely - replicating FxSound's VBlank-listener teardown.
    """

    def __init__(self, parent=None, height: int = 100):
        super().__init__(parent)
        self.setFixedHeight(height)
        self.setMinimumWidth(240)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self._provider: Optional[Callable[[], Optional[List[float]]]] = None
        self._n_bands = len(SPECTRUM_BANDS)
        self._history: List[float] = [0.0] * (self._n_bands * 12)
        self._is_playing = False
        self._decay_frames_left = 0

        self._timer = QTimer(self)
        self._timer.setInterval(int(round(1000.0 / VIS_FPS)))
        self._timer.timeout.connect(self._on_tick)

    def set_provider(self, provider: Callable[[], Optional[List[float]]]):
        self._provider = provider

    # ── lifecycle ────────────────────────────────────────────────────────────
    def _slots(self) -> int:
        """History slots per the current widget width (bars must fit)."""
        usable = max(120.0, self.width() - 16.0)
        return max(12, int(usable / VIS_BAR_PITCH) // self._n_bands) * self._n_bands

    def start_if_playing(self):
        if self._provider is not None and self._provider() is not None:
            self._is_playing = True
            self._decay_frames_left = 0
            if not self._timer.isActive():
                self._timer.start()

    def stop_and_clear(self):
        self._timer.stop()
        self._is_playing = False
        self._decay_frames_left = 0
        self._history = [0.0] * len(self._history)
        self.update()

    def showEvent(self, event):
        super().showEvent(event)
        self.start_if_playing()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._timer.stop()

    # ── simulation/update ────────────────────────────────────────────────────
    def _on_tick(self):
        try:
            values = self._provider() if self._provider is not None else None
        except Exception:
            values = None

        if values is not None:
            self._is_playing = True
            self._decay_frames_left = 12  # ~400ms of decay once audio stops
            self._push(values)
        elif self._decay_frames_left > 0:
            self._decay_frames_left -= 1
            self._push([0.0] * self._n_bands)  # history scrolls flat
        else:
            self.stop_and_clear()
            return

        self.update()

    def _push(self, values: List[float]):
        """Port of FxVisualizer::update(): shift history outwards from center."""
        n = self._n_bands
        slots = len(self._history) // n
        for i in range(n):
            base = i * slots
            v = values[i] if i < len(values) else 0.0
            if v < 0.0 or v > 1.0:
                v = 0.0
            half = slots // 2
            for j in range(half):
                src = self._history[base + j + 1]
                self._history[base + j] = src
                self._history[base + (slots - 1) - j] = src
            self._history[base + slots // 2] = v

    # ── painting ─────────────────────────────────────────────────────────────
    def paintEvent(self, event):
        p = fx_theme.painter_palette()
        dark = fx_theme.is_dark()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w, h = float(self.width()), float(self.height())
        bounds = QRectF(0.5, 0.5, w - 1.0, h - 1.0)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(_color(p["vis_panel"])))
        painter.drawRoundedRect(bounds, VIS_PANEL_RADIUS, VIS_PANEL_RADIUS)

        alpha = 1.0 if self._is_playing else 0.75
        high_top = _color(p["vis_high"], alpha)
        if not self._is_playing:
            hh, ss, vv, aa = high_top.getHsvF()
            high_top = QColor.fromHsvF(hh, ss * 0.35, vv, aa)

        grad = QLinearGradient(2.0, 0.0, 2.0, h)
        grad.setColorAt(0.0, high_top)
        grad.setColorAt(0.5, _color(p["vis_low"], alpha))
        grad.setColorAt(1.0, high_top)

        slots = len(self._history) // self._n_bands
        total_bars = slots * self._n_bands
        block_w = total_bars * VIS_BAR_PITCH
        start_x = max(8.0, (w - block_w) / 2.0)

        # enhanced: slightly wider bars for prominence + cap highlight
        bar_w = VIS_BAR_WIDTH * 1.25  # 5.0 instead of 4 for more presence
        pitch = VIS_BAR_PITCH * 1.05  # ~9.55
        # recompute centered start with new pitch
        block_w = total_bars * pitch
        start_x = max(8.0, (w - block_w) / 2.0)
        painter.setBrush(QBrush(grad))
        # subtle outer glow when playing
        if self._is_playing:
            glow = QColor(p["vis_high"])
            glow.setAlpha(28)
            painter.setPen(QPen(glow, 1.5))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(bounds.adjusted(0.5, 0.5, -0.5, -0.5), VIS_PANEL_RADIUS, VIS_PANEL_RADIUS)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(grad))
        bars_path = QPainterPath()
        x = start_x
        draw_h = h - 12.0  # taller bars (was -16)
        mid_y = h / 2.0
        caps = []
        for v in self._history:
            bh = max(2.0, v * draw_h)
            rect = QRectF(x, mid_y - bh / 2.0, bar_w, bh)
            bars_path.addRoundedRect(rect, 1.2, 1.2)
            if self._is_playing and v > 0.62:
                # peak cap: 2.5px bright tip
                caps.append(QRectF(x, rect.top(), bar_w, 2.5))
            x += pitch
        painter.drawPath(bars_path)
        # draw bright caps
        if caps:
            cap_color = QColor("#ffffff")
            cap_color.setAlpha(210 if dark else 190)
            painter.setBrush(QBrush(cap_color))
            painter.setPen(Qt.NoPen)
            for cr in caps:
                painter.drawRoundedRect(cr, 1.0, 1.0)


# ══════════════════════════════════════════════════════════════════════════════
# LOG FREQUENCY RESPONSE PLOT
# ══════════════════════════════════════════════════════════════════════════════

class LogFrequencyPlotWidget(QWidget):
    """
    Interactive log-frequency response plot with theme awareness,
    click-to-replay, multi-channel curves, and shaded anomaly regions.
    """
    point_clicked = Signal(float, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(400, 200)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True)

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
        pal = fx_theme.painter_palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        ml, mr, mt, mb = 44, 20, 22, 34
        plot_rect = QRectF(ml, mt, max(10, w - ml - mr), max(10, h - mt - mb))

        bg_outer = _color(pal["bg_outer"])
        bg_plot = _color(pal["bg_plot"])
        grid_maj = _color(pal["grid_maj"], 0.55)
        grid_min = _color(pal["grid_min"], 0.60)
        axis_c = _color(pal["axis"], 0.70)
        text_c = _color(pal["text_hint"])
        clr_left = _color(pal["left"])
        clr_right = _color(pal["right"])

        painter.fillRect(self.rect(), bg_outer)
        painter.fillRect(plot_rect, bg_plot)
        painter.setFont(QFont(FONT_FAMILY_STACK.replace("'", "").split(",")[0], 8))

        ticks = SPECTRUM_BANDS
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
            lbl = f"{f // 1000}k" if f >= 1000 else str(f)
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

        anom_fill = _color(pal["anom_fill"])
        anom_top = _color(pal["anom_top"])
        roll_fill = _color(pal["roll_fill"])

        regs = []
        if self.active_channel_filter in ("both", "left"):
            regs.extend(self.regions_left)
        if self.active_channel_filter in ("both", "right"):
            regs.extend(self.regions_right)
        for reg in regs:
            est_lo = reg.start_estimate if reg.start_estimate > 0 else reg.f_low
            est_hi = reg.end_estimate if reg.end_estimate > 0 else reg.f_high
            rx_l = self._freq_to_x(est_lo, plot_rect)
            rx_r = self._freq_to_x(est_hi, plot_rect)
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
            self._draw_channel(painter, plot_rect, self.measurements_left, clr_left, pal)
        if self.active_channel_filter in ("both", "right"):
            self._draw_channel(painter, plot_rect, self.measurements_right, clr_right, pal)
        self._draw_legend(painter, plot_rect, clr_left, clr_right, pal)

    def _draw_channel(self, painter, rect, points, color, pal):
        if not points:
            return
        sorted_pts = sorted(points, key=lambda p: p.frequency_hz)

        path = QPainterPath()
        for i, p in enumerate(sorted_pts):
            pt = QPointF(self._freq_to_x(p.frequency_hz, rect), self._y_to_pixel(p.quality, rect))
            if i == 0:
                path.moveTo(pt)
            else:
                path.lineTo(pt)

        # FxSound-EQ style gradient fill under the response curve
        if len(sorted_pts) >= 2:
            fill_path = QPainterPath(path)
            x_first = self._freq_to_x(sorted_pts[0].frequency_hz, rect)
            x_last = self._freq_to_x(sorted_pts[-1].frequency_hz, rect)
            fill_path.lineTo(x_last, rect.bottom())
            fill_path.lineTo(x_first, rect.bottom())
            fill_path.closeSubpath()
            fc = QColor(color)
            fc.setAlpha(70)
            fade = QColor(color)
            fade.setAlpha(0)
            grad = QLinearGradient(0.0, rect.top(), 0.0, rect.bottom())
            grad.setColorAt(0.0, fc)
            grad.setColorAt(1.0, fade)
            painter.save()
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(grad))
            painter.drawPath(fill_path)
            painter.restore()

        lc = QColor(color)
        lc.setAlpha(185)
        painter.setPen(QPen(lc, 2.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.drawPath(path)

        for p in sorted_pts:
            px = self._freq_to_x(p.frequency_hz, rect)
            py = self._y_to_pixel(p.quality, rect)
            eff = p.effective_classification or p.classification
            if p.is_control:
                dc = _color(pal["control_pt"])
            elif p.is_retest:
                dc = _color(pal["retest_pt"])
            elif eff == Classification.GOOD:
                dc = _color(pal["good"])
            elif eff == Classification.BORDERLINE:
                dc = _color(pal["borderline"])
            else:
                dc = _color(pal["bad"])

            gc = QColor(dc)
            gc.setAlpha(35)
            gg = QRadialGradient(QPointF(px, py), 10)
            gg.setColorAt(0, gc)
            gg.setColorAt(1, QColor(0, 0, 0, 0))
            painter.setBrush(QBrush(gg))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(QPointF(px, py), 10, 10)

            r = 4.5
            pr = QRectF(px - r, py - r, r * 2, r * 2)
            self._point_rects.append((pr, p))
            painter.setBrush(QBrush(dc))
            painter.setPen(QPen(QColor(255, 255, 255, 160), 1))
            painter.drawEllipse(pr)

    def _draw_legend(self, painter, rect, clr_l, clr_r, pal):
        font = QFont(FONT_FAMILY_STACK.replace("'", "").split(",")[0], 8, QFont.Bold)
        painter.setFont(font)
        x, y = rect.right() - 230, rect.top() + 8
        for i, (c, t) in enumerate([(clr_l, "Left"), (clr_r, "Right")]):
            painter.setPen(Qt.NoPen)
            painter.setBrush(c)
            painter.drawEllipse(QPointF(x + i * 60, y + 6), 4, 4)
            painter.setPen(c)
            painter.drawText(QRectF(x + i * 60 + 10, y, 46, 14), Qt.AlignLeft | Qt.AlignVCenter, t)
        anom = _color(pal["anom_top"])
        painter.fillRect(QRectF(x + 124, y + 1, 9, 9), _color(pal["anom_fill"]))
        painter.setPen(anom)
        painter.drawText(QRectF(x + 138, y, 75, 14), Qt.AlignLeft | Qt.AlignVCenter, "Anomaly")

    def mouseMoveEvent(self, event):
        pos = event.position()
        for pr, m in self._point_rects:
            if pr.adjusted(-5, -5, 5, 5).contains(pos):
                self.setCursor(Qt.PointingHandCursor)
                eff = m.effective_classification or m.classification
                st = f" [{m.stage}]" if m.stage else ""
                QToolTip.showText(
                    event.globalPosition().toPoint(),
                    f"{m.frequency_hz:.1f} Hz ({m.channel.upper()})\n"
                    f"Clarity: {m.clarity}/10 · Quality: {m.quality:.1f}\n"
                    f"{eff}{st}  ·  Click to replay",
                    self,
                )
                return
        self.setCursor(Qt.ArrowCursor)
        QToolTip.hideText()
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            pos = event.position()
            for pr, m in self._point_rects:
                if pr.adjusted(-6, -6, 6, 6).contains(pos):
                    self.point_clicked.emit(m.frequency_hz, m.channel)
                    return
        super().mousePressEvent(event)
