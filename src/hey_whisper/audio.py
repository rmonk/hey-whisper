"""Microphone capture and audio recording module using sounddevice and numpy."""

import math
import threading
import time
from typing import Callable, Optional, List
import numpy as np
import sounddevice as sd


SAMPLE_RATE = 16000  # Whisper default sample rate (16kHz)
CHANNELS = 1         # Mono


class AudioRecorder:
    """Manages audio recording from the default microphone."""

    def __init__(
        self,
        sample_rate: int = SAMPLE_RATE,
        silence_timeout: float = 1.5,
        silence_threshold: float = 500.0,
        level_callback: Optional[Callable[[float, float], None]] = None,
        silence_stop_callback: Optional[Callable[[], None]] = None,
    ):
        self.sample_rate = sample_rate
        self.silence_timeout = silence_timeout
        self.silence_threshold = silence_threshold
        self.level_callback = level_callback
        self.silence_stop_callback = silence_stop_callback

        self._stream: Optional[sd.InputStream] = None
        self._chunks: List[np.ndarray] = []
        self._is_recording = False
        self._lock = threading.Lock()

        # Silence / VAD tracking
        self._speech_detected = False
        self._last_speech_time: Optional[float] = None
        self._silence_mode = False

    @property
    def is_recording(self) -> bool:
        return self._is_recording

    def start_recording(self, silence_mode: bool = False):
        """Start capturing audio from default microphone."""
        with self._lock:
            if self._is_recording:
                return

            self._chunks = []
            self._is_recording = True
            self._silence_mode = silence_mode
            self._speech_detected = False
            self._last_speech_time = None

            try:
                self._stream = sd.InputStream(
                    samplerate=self.sample_rate,
                    channels=CHANNELS,
                    dtype="float32",
                    callback=self._audio_callback,
                    blocksize=int(self.sample_rate * 0.05),  # 50ms blocks
                )
                self._stream.start()
            except Exception as e:
                self._is_recording = False
                raise RuntimeError(f"Failed to open microphone: {e}") from e

    def stop_recording(self) -> np.ndarray:
        """Stop capturing audio and return recorded audio as 1D float32 array."""
        with self._lock:
            if not self._is_recording:
                return np.zeros(0, dtype=np.float32)

            self._is_recording = False
            if self._stream is not None:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None

            if not self._chunks:
                return np.zeros(0, dtype=np.float32)

            audio = np.concatenate(self._chunks, axis=0).flatten()
            self._chunks = []
            return audio

    def _audio_callback(self, indata: np.ndarray, frames: int, time_info, status):
        """Internal callback invoked by sounddevice on incoming audio buffer."""
        if not self._is_recording:
            return

        chunk = indata.copy()
        with self._lock:
            self._chunks.append(chunk)

        # Calculate RMS energy
        rms_raw = np.sqrt(np.mean(chunk**2))
        # Scaled to ~0-32767 range for intuitive thresholding
        rms_scaled = float(rms_raw * 32768.0)
        peak_scaled = float(np.max(np.abs(chunk)) * 32768.0)

        # Notify level listeners (e.g. GUI VU meter)
        if self.level_callback is not None:
            try:
                self.level_callback(rms_scaled, peak_scaled)
            except Exception:
                pass

        # Handle silence mode (Voice Activity Detection)
        if self._silence_mode:
            now = time.monotonic()
            if rms_scaled >= self.silence_threshold:
                self._speech_detected = True
                self._last_speech_time = now
            elif self._speech_detected:
                if self._last_speech_time is not None:
                    silence_duration = now - self._last_speech_time
                    if silence_duration >= self.silence_timeout:
                        # Auto-stop triggered by silence (trigger once per session)
                        self._speech_detected = False
                        self._silence_mode = False
                        if self.silence_stop_callback is not None:
                            threading.Thread(
                                target=self.silence_stop_callback,
                                daemon=True,
                            ).start()
