"""Tests for audio recorder and transcriber modules."""

from pathlib import Path
from unittest.mock import MagicMock, patch
import numpy as np
try:
    import pytest
except ImportError:
    pytest = None

from hey_whisper.audio import AudioRecorder
from hey_whisper.transcriber import (
    Transcriber,
    save_audio_to_wav,
    list_models,
    delete_model,
    get_ggml_model_path,
    get_system_vulkan_devices,
    probe_vulkan_backend,
    KNOWN_GGML_MODELS,
    NEMO_ONNX_MODELS,
    _nemo_repo_id,
    list_nemo_models,
    delete_nemo_model,
    download_nemo_model,
)


def test_audio_recorder_buffer():
    rec = AudioRecorder()
    assert not rec.is_recording

    # Simulate feeding chunks into callback directly
    rec._is_recording = True
    rec._chunks = []
    chunk1 = np.ones((800, 1), dtype=np.float32) * 0.1
    chunk2 = np.ones((800, 1), dtype=np.float32) * 0.2

    rec._chunks.append(chunk1)
    rec._chunks.append(chunk2)

    data = rec.stop_recording()
    assert len(data) == 1600
    assert not rec.is_recording


def test_save_audio_to_wav():
    dummy_audio = np.zeros(16000, dtype=np.float32)
    wav_path = save_audio_to_wav(dummy_audio, 16000)
    assert wav_path.is_file()
    assert wav_path.stat().st_size > 0
    wav_path.unlink()


def test_transcriber_faster_whisper_mock():
    transcriber = Transcriber(model_name="base.en", backend="faster-whisper")
    mock_model = MagicMock()
    mock_segment = MagicMock()
    mock_segment.text = "Hello from faster-whisper"
    mock_model.transcribe.return_value = ([mock_segment], None)

    transcriber._faster_whisper_model = mock_model

    dummy_audio = np.zeros(16000, dtype=np.float32)
    result = transcriber.transcribe(dummy_audio)
    assert result == "Hello from faster-whisper"
    mock_model.transcribe.assert_called_once()


def test_transcriber_vulkan_mock():
    transcriber = Transcriber(model_name="base.en", backend="vulkan")
    transcriber._whisper_cli = "/usr/bin/whisper-cli"

    with patch("subprocess.run") as mock_run, patch("hey_whisper.transcriber.get_ggml_model_path") as mock_get_model:
        mock_get_model.return_value = Path("/tmp/mock_model.bin")
        mock_res = MagicMock()
        mock_res.stdout = "Transcribed text from Vulkan GPU"
        mock_run.return_value = mock_res

        dummy_audio = np.zeros(16000, dtype=np.float32)
        result = transcriber.transcribe(dummy_audio)
        assert result == "Transcribed text from Vulkan GPU"
        mock_run.assert_called_once()


def test_list_models_reports_download_status(tmp_path, monkeypatch):
    monkeypatch.setattr("hey_whisper.transcriber.CACHE_DIR", tmp_path)
    (tmp_path / "ggml-base.en.bin").write_bytes(b"0" * 2_000_000)

    models = list_models()
    assert [m.name for m in models] == KNOWN_GGML_MODELS

    by_name = {m.name: m for m in models}
    assert by_name["base.en"].downloaded is True
    assert by_name["base.en"].size_bytes == 2_000_000
    assert by_name["tiny"].downloaded is False
    assert by_name["tiny"].path is None


def test_delete_model(tmp_path, monkeypatch):
    monkeypatch.setattr("hey_whisper.transcriber.CACHE_DIR", tmp_path)
    model_file = tmp_path / "ggml-tiny.bin"
    model_file.write_bytes(b"0" * 2_000_000)

    assert delete_model("tiny") is True
    assert not model_file.exists()
    assert delete_model("tiny") is False


def test_get_ggml_model_path_reports_progress(tmp_path, monkeypatch):
    monkeypatch.setattr("hey_whisper.transcriber.CACHE_DIR", tmp_path)

    def fake_urlretrieve(url, filename, reporthook=None):
        if reporthook:
            reporthook(0, 1000, 1000)
            reporthook(1, 1000, 1000)
        Path(filename).write_bytes(b"0" * 2_000_000)

    monkeypatch.setattr("urllib.request.urlretrieve", fake_urlretrieve)

    calls = []
    path = get_ggml_model_path("tiny", progress_callback=lambda done, total: calls.append((done, total)))
    assert path.is_file()
    assert calls == [(0, 1000), (1000, 1000)]


def test_get_system_vulkan_devices_parses_summary(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/vulkaninfo")
    mock_result = MagicMock()
    mock_result.stdout = (
        "Devices:\n========\nGPU0:\n\tdeviceName         = AMD Radeon Graphics (RADV RENOIR)\n"
        "GPU1:\n\tdeviceName         = llvmpipe (LLVM 22.1.8, 256 bits)\n"
    )
    with patch("subprocess.run", return_value=mock_result) as mock_run:
        devices = get_system_vulkan_devices()
    mock_run.assert_called_once()
    assert devices == ["AMD Radeon Graphics (RADV RENOIR)", "llvmpipe (LLVM 22.1.8, 256 bits)"]


def test_get_system_vulkan_devices_no_vulkaninfo(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    assert get_system_vulkan_devices() == []


def test_probe_vulkan_backend_no_whisper_cli(monkeypatch):
    monkeypatch.setattr("hey_whisper.transcriber.find_whisper_cli", lambda: None)
    monkeypatch.setattr("hey_whisper.transcriber.get_system_vulkan_devices", lambda: [])

    status = probe_vulkan_backend()
    assert status.whisper_cli_found is False
    assert status.working is False
    assert "whisper-cli not found" in status.detail


def test_probe_vulkan_backend_working(tmp_path, monkeypatch):
    monkeypatch.setattr("hey_whisper.transcriber.find_whisper_cli", lambda: "/usr/bin/whisper-cli")
    monkeypatch.setattr("hey_whisper.transcriber.get_system_vulkan_devices", lambda: ["AMD Radeon Graphics"])

    model_path = tmp_path / "ggml-tiny.bin"
    model_path.write_bytes(b"0" * 2_000_000)

    mock_result = MagicMock()
    mock_result.stderr = (
        "ggml_vulkan: Found 1 Vulkan devices:\n"
        "ggml_vulkan: 0 = AMD Radeon Graphics (RADV RENOIR) (AMD) | uma: 1 | fp16: 1\n"
    )
    with patch("subprocess.run", return_value=mock_result):
        status = probe_vulkan_backend(model_path=model_path)

    assert status.working is True
    assert status.device_name == "AMD Radeon Graphics (RADV RENOIR) (AMD)"


def test_nemo_repo_id_mapping():
    assert _nemo_repo_id("nemo-parakeet-tdt-0.6b-v3") == "istupakov/parakeet-tdt-0.6b-v3-onnx"
    assert _nemo_repo_id("nemo-canary-1b-v2") == "istupakov/canary-1b-v2-onnx"
    assert _nemo_repo_id("istupakov/canary-180m-flash-onnx") == "istupakov/canary-180m-flash-onnx"


def _mock_cache_info(repo_id, size_on_disk=123_456, commit_hash="abc123"):
    revision = MagicMock()
    revision.commit_hash = commit_hash
    repo = MagicMock()
    repo.repo_id = repo_id
    repo.repo_type = "model"
    repo.size_on_disk = size_on_disk
    repo.revisions = {revision}
    cache_info = MagicMock()
    cache_info.repos = [repo]
    return cache_info


def test_list_nemo_models_reports_download_status(monkeypatch):
    downloaded_repo = _nemo_repo_id(NEMO_ONNX_MODELS[0])
    cache_info = _mock_cache_info(downloaded_repo, size_on_disk=700_000_000)
    monkeypatch.setattr("huggingface_hub.scan_cache_dir", lambda cache_dir=None: cache_info)

    models = list_nemo_models()
    assert [m.name for m in models] == NEMO_ONNX_MODELS

    by_name = {m.name: m for m in models}
    assert by_name[NEMO_ONNX_MODELS[0]].downloaded is True
    assert by_name[NEMO_ONNX_MODELS[0]].size_bytes == 700_000_000
    assert by_name[NEMO_ONNX_MODELS[1]].downloaded is False


def test_list_nemo_models_no_cache(monkeypatch):
    def raise_not_found():
        raise Exception("Cache directory not found")

    monkeypatch.setattr("huggingface_hub.scan_cache_dir", lambda cache_dir=None: raise_not_found())
    models = list_nemo_models()
    assert all(not m.downloaded for m in models)


def test_delete_nemo_model(monkeypatch):
    target_name = NEMO_ONNX_MODELS[0]
    repo_id = _nemo_repo_id(target_name)
    cache_info = _mock_cache_info(repo_id)
    monkeypatch.setattr("huggingface_hub.scan_cache_dir", lambda cache_dir=None: cache_info)

    assert delete_nemo_model(target_name) is True
    cache_info.delete_revisions.assert_called_once_with("abc123")
    cache_info.delete_revisions.return_value.execute.assert_called_once()

    assert delete_nemo_model(NEMO_ONNX_MODELS[1]) is False


def test_download_nemo_model_calls_snapshot_download(monkeypatch):
    calls = []
    monkeypatch.setattr("huggingface_hub.snapshot_download", lambda repo_id, cache_dir=None: calls.append(repo_id))
    download_nemo_model("nemo-parakeet-tdt-0.6b-v3")
    assert calls == ["istupakov/parakeet-tdt-0.6b-v3-onnx"]


def test_transcriber_nemo_mock():
    transcriber = Transcriber(model_name="nemo-parakeet-tdt-0.6b-v3", backend="nemo")
    assert transcriber.is_nemo is True
    assert transcriber.is_vulkan is False

    mock_model = MagicMock()
    mock_model.recognize.return_value = "Hello from Parakeet"
    transcriber._nemo_model = mock_model

    dummy_audio = np.zeros(16000, dtype=np.float32)
    result = transcriber.transcribe(dummy_audio)
    assert result == "Hello from Parakeet"
    mock_model.recognize.assert_called_once_with(dummy_audio, sample_rate=16000)


def test_transcriber_nemo_falls_back_to_faster_whisper_on_error():
    transcriber = Transcriber(model_name="base.en", backend="nemo")

    def raise_error(*args, **kwargs):
        raise RuntimeError("onnx-asr not installed")

    transcriber._transcribe_nemo = raise_error

    mock_fw_model = MagicMock()
    mock_segment = MagicMock()
    mock_segment.text = "fallback text"
    mock_fw_model.transcribe.return_value = ([mock_segment], None)
    transcriber._faster_whisper_model = mock_fw_model

    dummy_audio = np.zeros(16000, dtype=np.float32)
    result = transcriber.transcribe(dummy_audio)
    assert result == "fallback text"
