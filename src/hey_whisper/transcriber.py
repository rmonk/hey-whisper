"""Transcription engine supporting Vulkan GPU acceleration (whisper.cpp) and faster-whisper."""

import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional, Union
import numpy as np


CACHE_DIR = Path.home() / ".cache" / "hey-whisper" / "models"

# Deliberately pinned to the real home directory rather than left to
# huggingface_hub's default resolution, which honors $XDG_CACHE_HOME. Under
# Flatpak, XDG_CACHE_HOME is redirected to the app-scoped
# ~/.var/app/<id>/cache even with --filesystem=host granted, which would
# otherwise make Parakeet/Canary downloads invisible to (and duplicated by)
# a non-sandboxed install of the same app, unlike the GGML cache above.
HF_CACHE_DIR = Path.home() / ".cache" / "huggingface" / "hub"

# onnx-asr's load_model() doesn't expose a cache_dir argument, so it relies
# entirely on huggingface_hub's own env-based resolution; setdefault() keeps
# it (and our own scan_cache_dir/snapshot_download calls) pointed at
# HF_CACHE_DIR without overriding a user who has already set this themselves.
os.environ.setdefault("HF_HUB_CACHE", str(HF_CACHE_DIR))

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


# Known NVIDIA Parakeet / Canary presets runnable via the onnx-asr package
# (https://github.com/istupakov/onnx-asr), which serves pre-exported ONNX
# weights for NeMo models without requiring the full NeMo/PyTorch toolkit.
NEMO_ONNX_MODELS = [
    "nemo-parakeet-ctc-0.6b",
    "nemo-parakeet-rnnt-0.6b",
    "nemo-parakeet-tdt-0.6b-v2",
    "nemo-parakeet-tdt-0.6b-v3",
    "nemo-canary-1b-v2",
    "istupakov/canary-180m-flash-onnx",
    "istupakov/canary-1b-flash-onnx",
]

# faster-whisper model used when the nemo backend fails and transcribe() falls
# back: self.model_name at that point is a NeMo preset name, which WhisperModel
# cannot resolve, so a known-good faster-whisper model is needed instead.
NEMO_FALLBACK_WHISPER_MODEL = "base.en"


def _nemo_repo_id(model_name: str) -> str:
    """Map an onnx-asr preset name to its backing Hugging Face repo id."""
    if "/" in model_name:
        return model_name
    if model_name.startswith("nemo-"):
        return f"istupakov/{model_name[len('nemo-'):]}-onnx"
    return model_name


@dataclass
class NemoModelInfo:
    """Local availability info for a known Parakeet/Canary onnx-asr model."""

    name: str
    repo_id: str
    downloaded: bool
    size_bytes: Optional[int] = None


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

    # urlretrieve's default block size is 8192 bytes, so a large model (medium.en
    # is ~1.5GB) would otherwise call progress_callback on the order of 180,000
    # times over the whole download. For a GUI callback that emits a cross-thread
    # Qt signal, that floods the receiving thread's event queue faster than it
    # can drain, which has caused a hard crash (no Python traceback - consistent
    # with an OOM kill) right around when a large download finishes. Throttle to
    # a UI-appropriate rate instead, while still always reporting the first and
    # final (100%) updates so the caller's progress display stays accurate.
    MIN_PROGRESS_INTERVAL = 0.1  # seconds
    last_emit_time = 0.0

    def _reporthook(block_num: int, block_size: int, total_size: int) -> None:
        nonlocal last_emit_time
        if progress_callback is None:
            return
        downloaded = block_num * block_size
        if total_size > 0:
            downloaded = min(downloaded, total_size)
        now = time.monotonic()
        is_first = block_num == 0
        is_last = total_size > 0 and downloaded >= total_size
        if is_first or is_last or (now - last_emit_time) >= MIN_PROGRESS_INTERVAL:
            last_emit_time = now
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


def _scan_nemo_cache_sizes() -> dict:
    """Return {repo_id: size_on_disk} for model repos in the local Hugging Face hub cache.

    Scans the cache once regardless of how many presets are being checked, since
    scan_cache_dir() walks the whole cache directory every time it's called.
    """
    try:
        from huggingface_hub import scan_cache_dir
    except ImportError:
        return {}
    try:
        cache_info = scan_cache_dir(cache_dir=str(HF_CACHE_DIR))
    except Exception:
        return {}
    return {repo.repo_id: repo.size_on_disk for repo in cache_info.repos if repo.repo_type == "model"}


def list_nemo_models() -> list:
    """List known Parakeet/Canary onnx-asr presets with their local download status."""
    sizes = _scan_nemo_cache_sizes()
    infos = []
    for name in NEMO_ONNX_MODELS:
        repo_id = _nemo_repo_id(name)
        size = sizes.get(repo_id)
        infos.append(NemoModelInfo(name=name, repo_id=repo_id, downloaded=repo_id in sizes, size_bytes=size))
    return infos


def download_nemo_model(model_name: str) -> None:
    """Download a Parakeet/Canary onnx-asr model's weights into the Hugging Face hub cache."""
    try:
        from huggingface_hub import snapshot_download
    except ImportError as e:
        raise RuntimeError(
            "huggingface_hub is required to download NVIDIA Parakeet/Canary models. "
            "Install with: pip install 'onnx-asr[cpu,hub]'"
        ) from e
    snapshot_download(_nemo_repo_id(model_name), cache_dir=str(HF_CACHE_DIR))


def delete_nemo_model(model_name: str) -> bool:
    """Remove a downloaded Parakeet/Canary model from the Hugging Face hub cache. Returns True if removed."""
    try:
        from huggingface_hub import scan_cache_dir
    except ImportError:
        return False
    repo_id = _nemo_repo_id(model_name)
    try:
        cache_info = scan_cache_dir(cache_dir=str(HF_CACHE_DIR))
    except Exception:
        return False
    for repo in cache_info.repos:
        if repo.repo_id == repo_id and repo.repo_type == "model":
            revisions = {rev.commit_hash for rev in repo.revisions}
            if not revisions:
                return False
            cache_info.delete_revisions(*revisions).execute()
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
        # Deliberately omit -np ("no prints"): it suppresses whisper.cpp's
        # startup log, which is where the Vulkan device banner we need to
        # parse ("ggml_vulkan: 0 = <device name> | ...") gets printed.
        cmd = [cli, "-m", str(model_path), "-f", str(wav_file), "-nt"]
        proc = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout
        )
        stderr = proc.stderr or ""
        if proc.returncode == 0 and "ggml_vulkan" in stderr.lower():
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
        elif proc.returncode != 0:
            status.detail = f"whisper-cli exited with status {proc.returncode}"
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
    """Unified transcription manager supporting Vulkan whisper.cpp, faster-whisper, and
    NVIDIA Parakeet/Canary (via onnx-asr)."""

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
        self._nemo_model = None
        self._whisper_cli = find_whisper_cli()

        # Decide effective backend. "nemo" is never auto-selected: it's a heavier
        # optional dependency the user must opt into explicitly.
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

    @property
    def is_nemo(self) -> bool:
        return self.active_backend == "nemo"

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

    def _transcribe_faster_whisper(self, audio_data: np.ndarray, model_override: Optional[str] = None) -> str:
        """Transcribe using faster-whisper (CTranslate2).

        `model_override`, if given, is used instead of `self.model_name` - needed when
        falling back from the nemo backend, since self.model_name there is a NeMo preset
        (e.g. "nemo-parakeet-tdt-0.6b-v3") that WhisperModel cannot resolve.
        """
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
                model_override or self.model_name,
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

    def _transcribe_nemo(self, audio_data: np.ndarray) -> str:
        """Transcribe using an NVIDIA Parakeet/Canary model via onnx-asr."""
        if self._nemo_model is None:
            try:
                import onnx_asr
            except ImportError as e:
                raise RuntimeError(
                    "onnx-asr is not installed. Install NVIDIA Parakeet/Canary support with: "
                    "pip install 'onnx-asr[cpu,hub]'"
                ) from e
            self._nemo_model = onnx_asr.load_model(self.model_name)

        result = self._nemo_model.recognize(audio_data, sample_rate=16000)
        return str(result).strip()

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
        elif self.active_backend == "nemo":
            try:
                return self._transcribe_nemo(audio_data)
            except Exception as e:
                print(f"Warning: NVIDIA NeMo (onnx-asr) failed ({e}), falling back to faster-whisper...", file=sys.stderr)
                # self.model_name is a NeMo preset here (e.g. "nemo-parakeet-tdt-0.6b-v3"),
                # which WhisperModel can't resolve - use a known-good faster-whisper model.
                return self._transcribe_faster_whisper(audio_data, model_override=NEMO_FALLBACK_WHISPER_MODEL)
        else:
            return self._transcribe_faster_whisper(audio_data)
