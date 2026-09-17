"""Transcription engine supporting Vulkan GPU acceleration (whisper.cpp) and faster-whisper."""

import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional, Union
import numpy as np


CACHE_DIR = Path.home() / ".cache" / "hey-whisper" / "models"

# Known GGML models published under ggerganov/whisper.cpp on Hugging Face,
# usable by the Vulkan whisper.cpp backend.
KNOWN_GGML_MODELS = [
    "tiny",
    "tiny.en",
    "base",
    "base.en",
    "small",
    "small.en",
    "medium",
    "medium.en",
    "large-v1",
    "large-v2",
    "large-v3",
    "large-v3-turbo",
]


@dataclass
class ModelInfo:
    """Local availability info for a known whisper GGML model."""

    name: str
    downloaded: bool
    size_bytes: Optional[int] = None
    path: Optional[Path] = None


@dataclass
class VulkanStatus:
    """Snapshot of Vulkan availability and whisper.cpp backend health."""

    whisper_cli_found: bool
    whisper_cli_path: Optional[str] = None
    system_devices: list = field(default_factory=list)
    working: bool = False
    device_name: Optional[str] = None
    detail: str = "Not tested"


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


def _ggml_filename(model_name: str) -> str:
    clean_name = model_name.strip()
    if not clean_name.startswith("ggml-"):
        return f"ggml-{clean_name}.bin"
    return f"{clean_name}.bin"


def _ggml_model_file(model_name: str) -> Path:
    return CACHE_DIR / _ggml_filename(model_name)


def get_ggml_model_path(
    model_name: str,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> Path:
    """Ensure GGML model file is available locally, downloading if necessary.

    `progress_callback`, if given, is invoked with (bytes_downloaded, total_bytes)
    as the download proceeds; total_bytes is 0 if the server didn't report a size.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    filename = _ggml_filename(model_name)

    target_file = CACHE_DIR / filename
    if target_file.is_file() and target_file.stat().st_size > 1_000_000:
        return target_file

    url = f"https://huggingface.co/ggerganov/whisper.cpp/resolve/main/{filename}"
    print(f"Downloading Vulkan-compatible GGML model from {url}...")
    temp_target = target_file.with_suffix(".tmp")

    def _reporthook(block_num: int, block_size: int, total_size: int) -> None:
        if progress_callback is not None:
            downloaded = block_num * block_size
            if total_size > 0:
                downloaded = min(downloaded, total_size)
            progress_callback(downloaded, max(total_size, 0))

    try:
        urllib.request.urlretrieve(
            url, temp_target, reporthook=_reporthook if progress_callback else None
        )
        temp_target.rename(target_file)
        print(f"Model saved to {target_file}")
    except Exception as e:
        if temp_target.is_file():
            temp_target.unlink()
        raise RuntimeError(f"Failed to download GGML model {filename}: {e}")

    return target_file


def list_models() -> list:
    """List all known GGML models with their local download status."""
    infos = []
    for name in KNOWN_GGML_MODELS:
        path = _ggml_model_file(name)
        downloaded = path.is_file() and path.stat().st_size > 1_000_000
        infos.append(
            ModelInfo(
                name=name,
                downloaded=downloaded,
                size_bytes=path.stat().st_size if downloaded else None,
                path=path if downloaded else None,
            )
        )
    return infos


def delete_model(model_name: str) -> bool:
    """Remove a downloaded GGML model file from the local cache. Returns True if removed."""
    path = _ggml_model_file(model_name)
    if path.is_file():
        path.unlink()
        return True
    return False


def get_system_vulkan_devices() -> list:
    """Query system Vulkan devices via `vulkaninfo --summary`, independent of whisper.cpp."""
    vulkaninfo = shutil.which("vulkaninfo")
    if not vulkaninfo:
        return []
    try:
        result = subprocess.run(
            [vulkaninfo, "--summary"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
        )
        devices = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith("deviceName"):
                parts = line.split("=", 1)
                if len(parts) == 2:
                    devices.append(parts[1].strip())
        return devices
    except Exception:
        return []


def probe_vulkan_backend(model_path: Optional[Path] = None, timeout: float = 30.0) -> VulkanStatus:
    """Run whisper-cli on a short silent clip and inspect stderr to confirm Vulkan is active.

    Requires a locally downloaded GGML model to actually exercise the backend; if none is
    available, reports whisper-cli/Vulkan discovery info without running an inference.
    """
    cli = find_whisper_cli()
    system_devices = get_system_vulkan_devices()
    status = VulkanStatus(
        whisper_cli_found=cli is not None,
        whisper_cli_path=cli,
        system_devices=system_devices,
    )

    if not cli:
        status.detail = "whisper-cli not found; Vulkan backend unavailable"
        return status

    if model_path is None:
        for info in list_models():
            if info.downloaded:
                model_path = info.path
                break

    if model_path is None:
        status.detail = "whisper-cli found, but no local model is downloaded to test with"
        return status

    silent_audio = np.zeros(8000, dtype=np.float32)  # 0.5s of silence
    wav_file = save_audio_to_wav(silent_audio)
    try:
        cmd = [cli, "-m", str(model_path), "-f", str(wav_file), "-np", "-nt"]
        proc = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout
        )
        stderr = proc.stderr or ""
        if "ggml_vulkan" in stderr.lower():
            status.working = True
            device = None
            for line in stderr.splitlines():
                s = line.strip()
                if s.lower().startswith("ggml_vulkan:") and " = " in s:
                    after = s.split(":", 1)[1].strip()
                    namepart = after.split("=", 1)[1].strip() if "=" in after else None
                    if namepart:
                        device = namepart.split("|")[0].strip()
                        break
            status.device_name = device
            status.detail = f"Vulkan backend active on {device}" if device else "Vulkan backend active"
        else:
            status.detail = "whisper-cli ran but did not report using Vulkan (CPU fallback or non-Vulkan build)"
    except subprocess.TimeoutExpired:
        status.detail = f"Vulkan probe timed out after {timeout:.0f}s"
    except Exception as e:
        status.detail = f"Vulkan probe failed: {e}"
    finally:
        if wav_file.is_file():
            wav_file.unlink()

    return status


def get_vulkan_status(probe: bool = True, model_path: Optional[Path] = None) -> VulkanStatus:
    """Return current Vulkan availability/health. Set probe=False to skip running whisper-cli."""
    if probe:
        return probe_vulkan_backend(model_path=model_path)

    cli = find_whisper_cli()
    return VulkanStatus(
        whisper_cli_found=cli is not None,
        whisper_cli_path=cli,
        system_devices=get_system_vulkan_devices(),
        working=False,
        device_name=None,
        detail="Not tested",
    )


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
