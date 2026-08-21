# FreqChecker - Adaptive Speaker Frequency Diagnostic Tool

**FreqChecker** is an optimized, standalone Windows desktop application (`freqchecker.exe`) engineered to test speaker and playback-chain frequency response adaptively, identify perceptual acoustic anomalies, verify false-positives with local geometric bisection, and evaluate cross-channel differentials.

---

## Technical Specifications & Low-End PC Optimization
For an in-depth breakdown of algorithms, mathematical formulas, memory budgets, and architecture, see:
**[`TECH_SPECS_AND_OPTIMIZATION.md`](TECH_SPECS_AND_OPTIMIZATION.md)**

### Key Highlights
- **Algorithms**:
  - **1/3-Octave Logarithmic Grid** (63 Hz - 16,000 Hz) reducing tests to ~25 points.
  - **Geometric Midpoint Bisection Refinement** with 1/12-octave resolution stop.
  - **False-Abort Bass Roll-Off Shielding**: Excludes sub-200 Hz roll-off from global abort to protect healthy laptop speakers.
  - **Single-Response Outlier Retest**: Discards accidental user inputs before creating problem regions.
  - **Dual Confidence Engine**: Anomaly Confidence (0-95%) and Hardware Attribution Confidence (0-95%).
  - **Cross-Channel Differential Analysis**: Differentiates symmetrical DSP/room standing waves from physical driver faults.
- **Technology Stack**:
  - Python 3.11+ Runtime
  - PySide6 (Qt 6) with custom high-DPI `QPainter` log-frequency plot
  - NumPy vectorized array synthesis
  - PortAudio / `sounddevice` with Windows WASAPI low-latency output
  - PyInstaller single-file standalone distribution (`freqchecker.exe`)
  - Bundled Manrope font (FxSound-style typography) loaded via `QFontDatabase`

---

## Directory Structure

```
freqchecker/
├── freqchecker.exe                 # Standalone Single-File Windows Executable
├── app.py                          # Main PySide6 Application (Wizard, Runner, Manual, Sweep, Music, Dashboard)
├── diagnostic_core.py              # Adaptive Algorithm Controller & Confidence Math
├── audio_engine.py                 # Low-Latency Audio Synthesis, FFT Spectrum & Worker Thread
├── models.py                       # Data Structures, CSV Export, Session JSON, and Text Report
├── ui_components.py                # FxSound Spectrum Visualizer & Log-Frequency Response Plot
├── fx_theme.py                     # FxSound Design Tokens, Dual-Theme QSS Engine & Font Loader
├── icons.py                        # Vector SVG Icon Renderer (No Platform Emoji Glitches)
├── fonts/Manrope.ttf               # Bundled UI Typeface
├── test_diagnostic.py              # Automated Unit Test Suite
├── build_exe.py                    # Optimized Selective PyInstaller Packaging Script
├── requirements.txt                # Pinned Dependency Manifest
├── TECH_SPECS_AND_OPTIMIZATION.md  # Comprehensive Algorithms & Performance Specs
└── README.md                       # Documentation & Quickstart
```

---

## Quickstart

### 1. Launch Standalone Executable
Double-click `freqchecker.exe` inside the `freqchecker/` folder.

### 2. Run from Source
```bash
cd freqchecker
pip install -r requirements.txt
python app.py
```

### 3. Run Automated Tests
```bash
cd freqchecker
python -m unittest test_diagnostic
```

### 4. Recompile Executable
```bash
cd freqchecker
python build_exe.py
```

---

## Command-Line Flags

| Flag | Effect |
| :--- | :--- |
| *(default)* | FxSound-style frameless chrome with custom title bar |
| `--framed` | Use the native OS window title bar instead |
| `--light` | Start in the light theme |

---

## Features

- **Guided adaptive diagnostic**: 1/3-octave grid, periodic 1 kHz reference controls, isolated retests, bounded bisection refinement to ±1/12 octave.
- **Blind Mode**: optionally hide tone frequencies until rated to reduce expectation bias.
- **Undo (Z)**: step back one rating and replay the same tone.
- **Live 9-band spectrum monitor**: genuine Hann-windowed FFT of the playing buffer (not a simulation).
- **Log sweep with anomaly marking**: mark drops/rattles by Space during a 100 Hz - 10 kHz sweep, then run **Retest Marked Freqs** to calibrate those exact points through the guided rating flow.
- **Manual tone generator**: sine/triangle/pink noise, log-mapped slider, L/R/Both.
- **Music A/B mode**: load your own track and switch channels mid-playback.
- **Stress replay**: replay the worst detected point at +75% level to distinguish level-dependent distortion from true frequency dips.
- **Results dashboard**: dual-channel log plot with shaded anomaly bands, hover tooltips, click-to-replay, CSV/JSON/TXT export, session reload.
- **Partial-save protection**: stopping or closing mid-session offers to save recorded ratings automatically.

---

## Troubleshooting

- If the app crashes, check `freqchecker_crash.log` next to the executable/script for the captured stack trace.
- No devices listed? Verify Windows privacy settings allow desktop apps to access audio, and that Enhancements/spatial sound are off.
- Music mode requires the optional `soundfile` package: `pip install soundfile`.
