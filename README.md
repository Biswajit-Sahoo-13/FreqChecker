# FreqChecker - Adaptive Speaker Frequency Diagnostic Tool

**FreqChecker** is an optimized, standalone Windows desktop application (`freqchecker.exe`) engineered to test speaker and playback-chain frequency response adaptively, identify perceptual acoustic anomalies, verify false-positives with local geometric bisection, and evaluate cross-channel differentials.

---

## Technical Specifications & Low-End PC Optimization
For an in-depth breakdown of algorithms, mathematical formulas, memory budgets, and architecture, see:
📄 **[`TECH_SPECS_AND_OPTIMIZATION.md`](file:///c:/Users/KIIT/Desktop/Volume/freqchecker/TECH_SPECS_AND_OPTIMIZATION.md)**

### Key Highlights
- **Algorithms**:
  - **1/3-Octave Logarithmic Grid** (63 Hz – 16,000 Hz) reducing tests to ~25 points.
  - **Geometric Midpoint Bisection Refinement** ($f_{\text{mid}} = \sqrt{f_1 \cdot f_2}$) with $1/12$-octave resolution stop.
  - **False-Abort Bass Roll-Off Shielding**: Excludes sub-200 Hz roll-off from global abort to protect healthy laptop speakers.
  - **Single-Response Outlier Retest**: Discards accidental user inputs before creating problem regions.
  - **Dual Confidence Engine**: Anomaly Confidence (0–95%) and Hardware Attribution Confidence (0–95%).
  - **Cross-Channel Differential Analysis**: Differentiates symmetrical DSP/room standing waves from physical driver faults.
- **Technology Stack**:
  - Python 3.11+ Runtime
  - PySide6 (Qt 6) with custom high-DPI `QPainter` 60 FPS Log-Frequency Plot
  - NumPy 2.x vectorized array synthesis
  - PortAudio / `sounddevice` with Windows WASAPI low-latency output
  - PyInstaller single-file standalone distribution (`freqchecker.exe`)
- **Low-End PC Optimization**:
  - **RAM**: Under 60 MB total consumption (audio buffers $< 400$ KB).
  - **CPU**: $< 1\%$ active usage, 0.0% idle load.
  - **Startup**: 56.99 MB standalone executable with 30+ unused Qt submodules pruned.
  - **Instant Cancellation**: Audio stops in $< 25$ ms on `Esc` or Stop button.

---

## Directory Structure

```
freqchecker/
├── freqchecker.exe                 # Standalone Single-File Windows Executable (56.99 MB)
├── app.py                          # Main PySide6 Application (Wizard, Runner, Manual, Sweep, Dashboard)
├── diagnostic_core.py              # Adaptive Algorithm Controller & Confidence Math
├── audio_engine.py                 # Low-Latency Audio Synthesis & Worker Thread
├── models.py                       # Data Structures, CSV Export, Session JSON, and Text Report
├── ui_components.py                # High-DPI Log-Frequency Response Plot & Dark Theme QSS
├── icons.py                        # Vector SVG Icon Renderer (No Platform Emoji Glitches)
├── test_diagnostic.py              # Automated Unit Test Suite (31 Tests Passing)
├── build_exe.py                    # Optimized Selective PyInstaller Packaging Script
├── requirements.txt                # Pinned Dependency Manifest
├── TECH_SPECS_AND_OPTIMIZATION.md  # Comprehensive Algorithms & Performance Specs
├── questions.txt                   # User Review Questions & Operational Notes
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
python -m unittest test_diagnostic.py
```
*(All 31 unit tests validate in < 1.0 second)*

### 4. Recompile Executable
```bash
cd freqchecker
python build_exe.py
```
>>>>>>> f58a9a8 (Initial commit of FreqChecker project)
