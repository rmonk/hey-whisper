"""Transcription engine supporting Vulkan GPU acceleration (whisper.cpp) and faster-whisper."""

import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import wave
from pathlib import Path
from typing import Optional, Union
import numpy as np


CACHE_DIR = Path.home() / ".cache" / "hey-whisper" / "models"


def find_whisper_cli() -> Optional[str]:
    """Find whisper-cli executable in PATH or standard Flatpak / local locations."""
    # Check PATH
    cli_path = shutil.which("whisper-cli")
    if cli_path:
        return cli_path

    # Check /app/bin (Flatpak)
    flatpak_path = Path("/app/bin/whisper-cli")
    if flatpak_path.is_file() and os.access(flatpak_path, os.X_OK):
        return str(flatpak_path)

    # Check /usr/local/bin or ~/.local/bin
    for candidate in [
        Path.home() / ".local" / "bin" / "whisper-cli",
        Path("/usr/local/bin/whisper-cli"),
        Path.cwd() / "bin" / "whisper-cli",
    ]:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)

    return None


def get_ggml_model_path(model_name: str) -> Path:
    """Ensure GGML model file is available locally, downloading if necessary."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    clean_name = model_name.replace(".en", ".en")
    if not clean_name.startswith("ggml-"):
        filename = f"ggml-{clean_name}.bin"
    else:
        filename = f"{clean_name}.bin"

    target_file = CACHE_DIR / filename
    if target_file.is_file() and target_file.stat().st_size > 1_000_000:
        return target_file

    url = f"https://huggingface.co/ggerganov/whisper.cpp/resolve/main/{filename}"
    print(f"Downloading Vulkan-compatible GGML model from {url}...")
    temp_target = target_file.with_suffix(".tmp")
    try:
        urllib.request.urlretrieve(url, temp_target)
        temp_target.rename(target_file)
        print(f"Model saved to {target_file}")
    except Exception as e:
        if temp_target.is_file():
            temp_target.unlink()
        raise RuntimeError(f"Failed to download GGML model {filename}: {e}")

    return target_file


def save_audio_to_wav(audio_data: np.ndarray, sample_rate: int = 16000) -> Path:
    """Write float32 numpy audio array to a 16-bit mono WAV file."""
    temp_wav = Path(tempfile.mktemp(suffix=".wav"))
    # Normalize and convert float32 (-1.0 to 1.0) to int16
    clamped = np.clip(audio_data, -1.0, 1.0)
    int16_data = (clamped * 32767).astype(np.int16)

    with wave.open(str(temp_wav), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16 bits = 2 bytes
        wf.setframerate(sample_rate)
        wf.writeframes(int16_data.tobytes())

    return temp_wav


class Transcriber:
    """Unified transcription manager supporting both Vulkan whisper.cpp and faster-whisper."""

    def __init__(
        self,
        model_name: str = "base.en",
        backend: str = "auto",
        device: str = "auto",
        compute_type: str = "int8",
        vulkan_device: int = 0,
    ):
        self.model_name = model_name
        self.backend = backend
        self.device = device
        self.compute_type = compute_type
        self.vulkan_device = vulkan_device
        self._faster_whisper_model = None
        self._whisper_cli = find_whisper_cli()

        # Decide effective backend
        if self.backend == "auto":
            if self._whisper_cli is not None:
                self.active_backend = "vulkan"
            else:
                self.active_backend = "faster-whisper"
        else:
            self.active_backend = self.backend

    @property
    def is_vulkan(self) -> bool:
        return self.active_backend == "vulkan"

    def _transcribe_vulkan(self, audio_data: np.ndarray) -> str:
        """Transcribe using whisper-cli with Vulkan acceleration."""
        cli = self._whisper_cli or find_whisper_cli()
        if not cli:
            raise RuntimeError(
                "whisper-cli not found. Ensure whisper.cpp is built with Vulkan support or install whisper-cli."
            )

        model_path = get_ggml_model_path(self.model_name)
        wav_file = save_audio_to_wav(audio_data)

        try:
            cmd = [
                cli,
                "-m", str(model_path),
                "-f", str(wav_file),
                "-np",  # No prints / debug info
                "-nt",  # No timestamps in output
            ]
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
            text = result.stdout.strip()
            # Clean up extra brackets or artifacts if any
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            return " ".join(lines)
        finally:
            if wav_file.is_file():
                wav_file.unlink()

    def _transcribe_faster_whisper(self, audio_data: np.ndarray) -> str:
        """Transcribe using faster-whisper (CTranslate2)."""
        if self._faster_whisper_model is None:
            from faster_whisper import WhisperModel
            import ctranslate2

            dev = self.device
            if dev == "auto":
                dev = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"

            comp_type = self.compute_type
            if dev == "cpu" and comp_type == "float16":
                comp_type = "int8"

            self._faster_whisper_model = WhisperModel(
                self.model_name,
                device=dev,
                compute_type=comp_type,
            )

        segments, info = self._faster_whisper_model.transcribe(
            audio_data,
            beam_size=5,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500),
        )

        texts = [s.text.strip() for s in segments if s.text.strip()]
        return " ".join(texts)

    def transcribe(self, audio_data: np.ndarray) -> str:
        """Transcribe float32 16kHz audio array."""
        if len(audio_data) == 0:
            return ""

        if self.active_backend == "vulkan":
            try:
                return self._transcribe_vulkan(audio_data)
            except Exception as e:
                print(f"Warning: Vulkan whisper failed ({e}), falling back to faster-whisper...", file=sys.stderr)
                return self._transcribe_faster_whisper(audio_data)
        else:
            return self._transcribe_faster_whisper(audio_data)
