"""Tests for audio recorder and transcriber modules."""

from pathlib import Path
from unittest.mock import MagicMock, patch
import numpy as np
try:
    import pytest
except ImportError:
    pytest = None

from hey_whisper.audio import AudioRecorder
from hey_whisper.transcriber import Transcriber, save_audio_to_wav


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
