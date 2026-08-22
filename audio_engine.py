"""
audio_engine.py - Low-latency programmatic audio generation and non-blocking playback engine for FreqChecker.
"""

import re
import math
import threading
import time
from typing import List, Dict, Any, Optional, Callable
import numpy as np
import sounddevice as sd

import fx_theme
from fx_theme import SPECTRUM_BANDS

# Geometric band edges used for spectrum binning (ISO centers from the theme).
_LOW_EDGE = 20.0
_HIGH_EDGE = 20000.0
_BAND_EDGES = [_LOW_EDGE] + [
    math.sqrt(SPECTRUM_BANDS[i] * SPECTRUM_BANDS[i + 1])
    for i in range(len(SPECTRUM_BANDS) - 1)
] + [_HIGH_EDGE]
_FFT_WINDOW = 2048

# Serializes EVERY python-sounddevice global-API call (sd.play / sd.stop / sd.rec).
# PortAudio's module-global stream is NOT thread-safe: concurrent stop/play from
# the GUI thread, playback worker threads, and preflight mic sampling corrupts
# native memory (heap corruption 0xc0000374). All entry points must hold this.
_PORTAUDIO_LOCK = threading.RLock()


def _normalize_device_key(name: str) -> str:
    """
    Extract a stable dedup key from a device name that may be truncated differently
    across host APIs. Strategy: take first 24 chars, strip trailing junk, lowercase.
    WASAPI truncates at ~63 chars, DirectSound can be longer. The physical device
    identity is always in the first ~24 chars before driver suffixes diverge.
    """
    # Strip leading/trailing whitespace
    s = name.strip()
    # Remove trailing incomplete parenthesized fragment (truncation artifact)
    # e.g. "CABLE In 16ch (VB-Audio Virtual" -> "CABLE In 16ch"
    s = re.sub(r'\s*\([^)]*$', '', s)
    # Take first 24 chars as the stable prefix
    s = s[:24].strip().lower()
    # Remove trailing punctuation/spaces
    s = s.rstrip(' -_(')
    return s


class AudioEngine:
    """
    Thread-safe audio engine for generating click-free tones and controlling playback.
    """

    def __init__(self, sample_rate: int = 48000, default_peak: float = 0.4):
        self.sample_rate = sample_rate
        self.default_peak = default_peak
        self.current_device_index: Optional[int] = None
        self._playback_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._is_playing = False
        self._generation = 0
        self._lock = threading.Lock()
        # Spectrum context for the live visualizer (what is actually playing)
        self._spectrum_meta: Optional[Dict[str, Any]] = None
        self._spectrum_start: Optional[float] = None

    @staticmethod
    def get_output_devices() -> List[Dict[str, Any]]:
        """
        Query audio output devices, filtered and deduplicated by physical device name.
        Prefers WASAPI > DirectSound. Drops MME entirely.
        """
        devices = []
        try:
            device_list = sd.query_devices()
            host_apis = sd.query_hostapis()
            default_out = sd.default.device[1] if isinstance(sd.default.device, (list, tuple)) else -1

            # Rank host APIs: WASAPI > DirectSound > everything else
            def api_rank(api_name: str) -> int:
                if "WASAPI" in api_name:
                    return 0
                if "DirectSound" in api_name:
                    return 1
                return 99  # MME and others — will be filtered out

            # Collect all output devices
            all_devs = []
            for idx, dev in enumerate(device_list):
                if dev.get("max_output_channels", 0) > 0:
                    api_idx = dev.get("hostapi", 0)
                    api_name = host_apis[api_idx]["name"] if api_idx < len(host_apis) else "Unknown"
                    rank = api_rank(api_name)
                    if rank >= 99:
                        continue  # Skip MME and other legacy APIs
                    all_devs.append({
                        "index": idx,
                        "name": dev["name"].strip(),
                        "host_api": api_name,
                        "api_rank": rank,
                        "channels": dev["max_output_channels"],
                        "default_samplerate": dev["default_samplerate"],
                        "is_default": (idx == default_out),
                    })

            # Deduplicate by normalized key, keeping the best API rank
            seen: Dict[str, Dict[str, Any]] = {}
            for dev in all_devs:
                key = _normalize_device_key(dev["name"])
                existing = seen.get(key)
                if existing is None or dev["api_rank"] < existing["api_rank"]:
                    seen[key] = dev
                # Propagate default flag
                if dev["is_default"] and key in seen:
                    seen[key]["is_default"] = True

            # Build final list: default first, then alphabetical
            deduped = sorted(seen.values(), key=lambda d: (not d["is_default"], d["name"]))
            for dev in deduped:
                # Clean display name: strip trailing incomplete parens from WASAPI truncation
                clean_name = dev["name"]
                # If name has unbalanced parens (truncation), close them
                open_count = clean_name.count('(') - clean_name.count(')')
                if open_count > 0:
                    clean_name += ')' * open_count
                mark = " (Default)" if dev["is_default"] else ""
                devices.append({
                    "index": dev["index"],
                    "name": dev["name"],
                    "host_api": dev["host_api"],
                    "channels": dev["channels"],
                    "default_samplerate": dev["default_samplerate"],
                    "is_default": dev["is_default"],
                    "display_name": f"{clean_name}{mark}",
                })
        except Exception as e:
            print(f"Error querying audio devices: {e}")
        return devices

    def set_output_device(self, device_index: Optional[int]):
        with self._lock:
            self.current_device_index = device_index
        # Adapt synthesis rate to device default samplerate to prevent pitch deviation
        dev = device_index
        if dev is None:
            try:
                dev = sd.default.device[1] if isinstance(sd.default.device, (list, tuple)) else None
            except Exception:
                dev = None
        if dev is not None and dev >= 0:
            try:
                info = sd.query_devices(dev)
                native = int(info.get("default_samplerate", 0) or 0)
                if 8000 <= native <= 192000:
                    with self._lock:
                        self.sample_rate = native
            except Exception:
                pass

    @staticmethod
    def detect_preflight_conditions(device_index: Optional[int] = None) -> Dict[str, Any]:
        """
        Auto-detect system, hardware, and acoustic pre-flight conditions:
        1. Running processes for active DSP/EQ enhancers (FxSound, Equalizer APO, Nahimic, Waves MaxxAudio, etc.)
        2. Selected/default output device configuration (sample rate, channels, virtual/cable driver status)
        3. Ambient noise measurement using default microphone (if present)
        """
        import subprocess

        # 1. Process scan for audio enhancers
        processes = []
        try:
            res = subprocess.run(
                ["tasklist", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                timeout=2.0
            )
            for line in res.stdout.splitlines():
                if line.strip():
                    p_name = line.split(",")[0].strip('"').lower()
                    processes.append(p_name)
        except Exception:
            pass

        enhancer_signatures = {
            "fxsound.exe": "FxSound Enhancer",
            "equalizerapo.exe": "Equalizer APO",
            "nahimicservice.exe": "Nahimic Audio Service",
            "nahimic2svc.exe": "Nahimic Audio Service",
            "sonicstudio3.exe": "Sonic Studio",
            "wavesguisvc.exe": "Waves MaxxAudio",
            "maxxaudio.exe": "Waves MaxxAudio",
            "dts_audio.exe": "DTS Audio Processing",
            "dolbyatmos.exe": "Dolby Atmos Spatial Audio"
        }

        detected_enhancers = [name for exe, name in enhancer_signatures.items() if exe in processes]
        fxsound_running = any("fxsound" in p for p in processes)

        # 2. Output Device Analysis
        dev_idx = device_index
        if dev_idx is None:
            try:
                dev_idx = sd.default.device[1] if isinstance(sd.default.device, (list, tuple)) else None
            except Exception:
                dev_idx = None

        dev_name = "Default Output Device"
        dev_sr = 48000
        dev_ch = 2
        is_virtual = False

        if dev_idx is not None and dev_idx >= 0:
            try:
                info = sd.query_devices(dev_idx)
                dev_name = info.get("name", "Unknown Device")
                dev_sr = int(info.get("default_samplerate", 48000) or 48000)
                dev_ch = int(info.get("max_output_channels", 2) or 2)
                is_virtual = any(k in dev_name.lower() for k in ["fxsound", "virtual", "cable", "voicemeeter"])
            except Exception:
                pass

        # 3. Ambient Room Noise Measurement (Microphone)
        mic_available = False
        mic_name = "None"
        ambient_dbfs = None
        is_quiet = True

        try:
            default_in = sd.default.device[0] if isinstance(sd.default.device, (list, tuple)) else -1
            if default_in is not None and default_in >= 0:
                in_info = sd.query_devices(default_in)
                mic_name = in_info.get("name", "Default Microphone")
                in_sr = int(in_info.get("default_samplerate", 44100) or 44100)
                if in_sr > 0:
                    with _PORTAUDIO_LOCK:
                        rec = sd.rec(int(0.25 * in_sr), samplerate=in_sr, channels=1, device=default_in, blocking=True)
                    rms = float(np.sqrt(np.mean(rec ** 2)))
                    ambient_dbfs = float(20.0 * np.log10(max(1e-7, rms)))
                    mic_available = True
                    is_quiet = bool(ambient_dbfs < -40.0)
        except Exception:
            mic_available = False
            ambient_dbfs = None
            is_quiet = True

        return {
            "fxsound_running": fxsound_running,
            "detected_enhancers": detected_enhancers,
            "is_virtual_device": is_virtual,
            "output_device_name": dev_name,
            "output_samplerate": dev_sr,
            "output_channels": dev_ch,
            "mic_available": mic_available,
            "mic_name": mic_name,
            "ambient_dbfs": ambient_dbfs,
            "is_quiet": is_quiet,
            "fxsound_clean": not fxsound_running and not is_virtual,
            "hardware_clean": (dev_ch >= 2) and not is_virtual,
            "all_clear": (not fxsound_running and not is_virtual and is_quiet and dev_ch >= 2)
        }

    def resample_linear(self, data: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
        """
        Resample 1D or 2D audio data linearly using numpy without requiring scipy.
        """
        if orig_sr == target_sr or data.size == 0:
            return data.astype(np.float32, copy=False)
        duration = len(data) / float(orig_sr)
        n_out = max(1, int(round(duration * target_sr)))
        t_out = np.arange(n_out, dtype=np.float64) / float(target_sr)
        x_orig = np.arange(len(data), dtype=np.float64) / float(orig_sr)
        if data.ndim == 1:
            out = np.interp(t_out, x_orig, data)
        else:
            out = np.stack([np.interp(t_out, x_orig, data[:, c]) for c in range(data.shape[1])], axis=1)
        return out.astype(np.float32)

    def route_stereo(self, data: np.ndarray, channel: str) -> np.ndarray:
        """
        Zero out inactive channel for pure left/right speaker isolation without altering program material.
        """
        out = data.copy()
        if channel == "left":
            out[:, 1] = 0.0
        elif channel == "right":
            out[:, 0] = 0.0
        return out

    def load_music_file(self, path: str, normalize: bool = True) -> Any:
        """
        Load user music file (WAV, FLAC, OGG, MP3, etc.) using optional soundfile library.
        Returns float32 stereo array normalized to [-1.0, 1.0] and file's native sample rate.
        Includes a 10-minute duration safety guard: stereo float32 at 96 kHz would already
        consume ~700 MB at 30 minutes, which thrashes 4 GB laptops.
        """
        import soundfile as sf
        info = sf.info(path)
        # 10 minutes limit at native sample rate to avoid memory exhaustion on low-RAM systems
        if info.duration > 600.0:
            raise ValueError(f"Audio file duration ({info.duration / 60.0:.1f} min) exceeds maximum safe limit of 10 minutes.")

        data, sr = sf.read(path, dtype="float32", always_2d=True)
        if data.shape[1] == 1:
            data = np.repeat(data, 2, axis=1)
        elif data.shape[1] > 2:
            data = data[:, :2].copy()
        if normalize:
            peak = float(np.max(np.abs(data))) if data.size else 0.0
            if peak > 1e-9:
                data = data * (1.0 / peak)
        # Apply 10ms smooth ramp at track boundaries
        n = int(0.01 * sr)
        if n > 0 and len(data) > 2 * n:
            ramp = 0.5 * (1.0 - np.cos(np.linspace(0, np.pi, n)))
            data[:n] *= ramp[:, None]
            data[-n:] *= ramp[::-1][:, None]
        return data.astype(np.float32), int(sr)

    def prepare_music_segment(
        self,
        base: np.ndarray,
        start_sample: int,
        channel: str,
        volume: float,
        fade_ms: float = 8.0,
        max_segment_s: float = 300.0
    ) -> np.ndarray:
        """
        Slice and process music segment from start_sample with channel routing, volume scaling, and fade-in.
        The slice is bounded to `max_segment_s` seconds so long tracks never allocate a
        full remaining-tail copy on every play/seek/volume change; playback continues
        seamlessly across consecutive windows.
        """
        start = max(0, min(start_sample, len(base) - 1))
        max_samples = max(1, int(max_segment_s * self.sample_rate))
        # Single copy slice, window-bounded
        seg = np.array(base[start:start + max_samples], dtype=np.float32, copy=True)
        if channel == "left":
            seg[:, 1] = 0.0
        elif channel == "right":
            seg[:, 0] = 0.0
        vol = max(0.0, min(1.0, volume))
        seg *= vol
        n = int((fade_ms / 1000.0) * self.sample_rate)
        if n > 0 and len(seg) > 2 * n:
            ramp = 0.5 * (1.0 - np.cos(np.linspace(0, np.pi, n)))
            seg[:n, 0] *= ramp
            seg[:n, 1] *= ramp
        return seg

    def _get_device_samplerate(self) -> int:
        """Return current engine sample rate (aligned to active device)."""
        return self.sample_rate

    def _validate_frequency(self, freq_hz: float):
        nyquist = self.sample_rate / 2.0
        if freq_hz <= 0.0:
            raise ValueError(f"Frequency must be positive (> 0 Hz), got {freq_hz} Hz.")
        if freq_hz >= nyquist * 0.95:
            raise ValueError(
                f"Frequency {freq_hz:.1f} Hz exceeds safe Nyquist limit for sample rate {self.sample_rate} Hz."
            )

    def _finalize_audio(
        self,
        wave: np.ndarray,
        peak: Optional[float],
        channel: str = "both",
        fade_ms: float = 50.0
    ) -> np.ndarray:
        """
        Centralized helper: applies raised-cosine fade ramps, zero DC offset, peak scaling, and stereo routing.
        """
        if peak is None:
            peak = self.default_peak
        peak = max(0.01, min(0.8, float(peak)))

        n_samples = len(wave)
        ramp_samples = int((fade_ms / 1000.0) * self.sample_rate)
        if ramp_samples * 2 > n_samples:
            ramp_samples = n_samples // 2

        if ramp_samples > 0:
            ramp_in = 0.5 * (1.0 - np.cos(np.linspace(0.0, np.pi, ramp_samples, dtype=np.float64)))
            wave[:ramp_samples] *= ramp_in
            wave[-ramp_samples:] *= ramp_in[::-1]

        wave = wave - np.mean(wave)
        max_abs = np.max(np.abs(wave))
        if max_abs > 1e-7:
            wave = wave * (peak / max_abs)

        if channel == "left":
            stereo = np.stack([wave, np.zeros_like(wave)], axis=1)
        elif channel == "right":
            stereo = np.stack([np.zeros_like(wave), wave], axis=1)
        else:
            stereo = np.stack([wave, wave], axis=1)

        return stereo.astype(np.float32)

    def generate_sine_tone(self, freq_hz: float, duration_s: float = 2.0, peak: Optional[float] = None, channel: str = "both", fade_ms: float = 50.0) -> np.ndarray:
        self._validate_frequency(freq_hz)
        n_samples = max(1, int(duration_s * self.sample_rate))
        t = np.arange(n_samples, dtype=np.float64) / self.sample_rate
        wave = np.sin(2.0 * np.pi * freq_hz * t)
        return self._finalize_audio(wave, peak, channel, fade_ms)

    def generate_triangle_tone(self, freq_hz: float, duration_s: float = 2.0, peak: Optional[float] = None, channel: str = "both", fade_ms: float = 50.0) -> np.ndarray:
        self._validate_frequency(freq_hz)
        n_samples = max(1, int(duration_s * self.sample_rate))
        t = np.arange(n_samples, dtype=np.float64) / self.sample_rate
        cycles = t * freq_hz
        wave = 2.0 * np.abs(2.0 * (cycles - np.floor(cycles + 0.5))) - 1.0
        return self._finalize_audio(wave, peak, channel, fade_ms)

    def generate_pink_noise(self, duration_s: float = 2.0, peak: Optional[float] = None, channel: str = "both", fade_ms: float = 50.0) -> np.ndarray:
        n_samples = max(1, int(duration_s * self.sample_rate))
        white = np.random.randn(n_samples)
        fft_white = np.fft.rfft(white)
        freqs = np.fft.rfftfreq(n_samples, d=1.0 / self.sample_rate)
        freqs[0] = 1.0
        s = 1.0 / np.sqrt(freqs)
        s[0] = 0.0
        fft_pink = fft_white * s
        wave = np.fft.irfft(fft_pink, n=n_samples)
        return self._finalize_audio(wave, peak, channel, fade_ms)

    def generate_log_sweep(self, f_start: float = 100.0, f_end: float = 10000.0, duration_s: float = 20.0, peak: Optional[float] = None, channel: str = "both", fade_ms: float = 50.0) -> np.ndarray:
        self._validate_frequency(f_start)
        self._validate_frequency(f_end)
        n_samples = max(1, int(duration_s * self.sample_rate))
        t = np.arange(n_samples, dtype=np.float64) / self.sample_rate
        k = np.log(f_end / f_start)
        phi = 2.0 * np.pi * f_start * (np.exp(k * t / duration_s) - 1.0) / (k / duration_s)
        wave = np.sin(phi)
        return self._finalize_audio(wave, peak, channel, fade_ms)

    def is_playing(self) -> bool:
        with self._lock:
            return self._is_playing

    def stop_playback(self):
        with self._lock:
            self._generation += 1
            self._is_playing = False
            self._spectrum_meta = None
            self._spectrum_start = None
        self._stop_event.set()
        with _PORTAUDIO_LOCK:
            try:
                sd.stop()
            except Exception:
                pass

    def get_spectrum_bands(self) -> Optional[List[float]]:
        """
        Real 9-band energy snapshot of the audio currently being played.
        Returns None when nothing is playing; otherwise a list of floats in
        [0, 1] matching fx_theme.SPECTRUM_BANDS. Computed from a Hann-windowed
        FFT of the most recent ~43 ms of the actual output buffer, so the
        visualizer always reflects genuine signal content.
        """
        with self._lock:
            if not self._is_playing or self._spectrum_meta is None or self._spectrum_start is None:
                return None
            meta = dict(self._spectrum_meta)
            start = self._spectrum_start

        buffer = meta.get("buffer")
        if buffer is None or len(buffer) == 0:
            return None

        sr = float(meta.get("sample_rate", self.sample_rate))
        elapsed = max(0.0, time.time() - start)
        pos = int(elapsed * sr)

        mono = buffer[:, 0] if buffer.ndim == 2 else buffer
        end = min(len(mono), pos)
        begin = max(0, end - _FFT_WINDOW)
        window = mono[begin:end].astype(np.float64)
        if len(window) < 64:
            return [0.0] * len(SPECTRUM_BANDS)

        window = window * np.hanning(len(window))
        spec = np.abs(np.fft.rfft(window))
        freqs = np.fft.rfftfreq(len(window), d=1.0 / sr)

        total = float(np.sum(spec)) + 1e-9
        band_vals = []
        for i in range(len(SPECTRUM_BANDS)):
            lo, hi = _BAND_EDGES[i], _BAND_EDGES[i + 1]
            mask = (freqs >= lo) & (freqs < hi)
            energy = float(np.sum(spec[mask])) if np.any(mask) else 0.0
            band_vals.append(energy / total)

        # Shape normalization: loudest band maps near full scale, scaled by
        # overall activity so quiet passages visually shrink.
        peak = max(band_vals) if band_vals else 0.0
        if peak <= 1e-9:
            return [0.0] * len(SPECTRUM_BANDS)
        shape = [v / peak for v in band_vals]
        rms = float(np.sqrt(np.mean(window ** 2))) + 1e-9
        activity = min(1.0, rms * 6.0)
        return [min(1.0, s * activity * 0.92) for s in shape]

    def play_audio(
        self,
        audio_data: np.ndarray,
        on_started: Optional[Callable[[], None]] = None,
        on_finished: Optional[Callable[[bool, Optional[str]], None]] = None,
        block: bool = False,
        spectrum_meta: Optional[Dict[str, Any]] = None
    ):
        with self._lock:
            self._generation += 1
            gen = self._generation
            self._spectrum_meta = (
                dict(spectrum_meta) if spectrum_meta is not None else None
            )
            self._spectrum_start = None

        self._stop_event.set()
        with _PORTAUDIO_LOCK:
            try:
                sd.stop()
            except Exception:
                pass

        old_thread = self._playback_thread
        if old_thread is not None and old_thread.is_alive():
            old_thread.join(timeout=0.5)

        self._stop_event.clear()

        def _worker():
            with self._lock:
                owns = (gen == self._generation)
                if owns:
                    self._is_playing = True
                    self._spectrum_start = time.time()

            if on_started and owns:
                try:
                    on_started()
                except Exception:
                    pass

            success = True
            error_msg = None

            try:
                dev = self.current_device_index
                sr = self._get_device_samplerate()
                total_duration = len(audio_data) / float(self.sample_rate)
                start_time = None
                with _PORTAUDIO_LOCK:
                    if gen == self._generation and not self._stop_event.is_set():
                        sd.play(audio_data, samplerate=sr, device=dev, blocking=False)
                        start_time = time.time()

                if start_time is None:
                    return

                while not self._stop_event.wait(timeout=0.05):
                    if gen != self._generation:
                        return
                    if (time.time() - start_time) >= total_duration + 0.05:
                        break

                if self._stop_event.is_set() and gen == self._generation:
                    with _PORTAUDIO_LOCK:
                        try:
                            sd.stop()
                        except Exception:
                            pass
            except Exception as e:
                success = False
                error_msg = str(e)
            finally:
                with self._lock:
                    if gen == self._generation:
                        self._is_playing = False
                        self._spectrum_start = None

                if on_finished and gen == self._generation:
                    try:
                        on_finished(success, error_msg)
                    except TypeError:
                        try:
                            on_finished()
                        except Exception:
                            pass
                    except Exception:
                        pass

        self._playback_thread = threading.Thread(target=_worker, daemon=True)
        self._playback_thread.start()

        if block:
            self._playback_thread.join()
