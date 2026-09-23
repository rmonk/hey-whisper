"""Tests for the JSON-lines sidecar (--serve) used by the Joplin plugin."""

import io
import json
from pathlib import Path

import numpy as np
import pytest

from hey_whisper import serve
from hey_whisper.config import AppConfig
from hey_whisper.main import parse_args


class FakeRecorder:
    instances = []
    samples = 16000

    def __init__(self, silence_timeout=1.5, silence_threshold=500.0, level_callback=None, silence_stop_callback=None):
        self.level_callback = level_callback
        self.silence_stop_callback = silence_stop_callback
        self.is_recording = False
        self.silence_mode = None
        self.audio = np.ones(FakeRecorder.samples, dtype=np.float32)
        self.fail_start = False
        FakeRecorder.instances.append(self)

    def start_recording(self, silence_mode=False):
        if self.fail_start:
            raise RuntimeError("Failed to open microphone: no device")
        self.is_recording = True
        self.silence_mode = silence_mode

    def stop_recording(self):
        if not self.is_recording:
            return np.zeros(0, dtype=np.float32)
        self.is_recording = False
        return self.audio


class FakeTranscriber:
    text = "hello from joplin"
    error = None

    def __init__(self, model_name="base.en", backend="auto", device="auto", compute_type="int8", vulkan_device=0):
        self.model_name = model_name
        self.active_backend = "faster-whisper" if backend == "auto" else backend

    def transcribe(self, audio):
        if FakeTranscriber.error:
            raise FakeTranscriber.error
        return FakeTranscriber.text


@pytest.fixture(autouse=True)
def fakes(monkeypatch):
    FakeRecorder.instances = []
    FakeRecorder.samples = 16000
    FakeTranscriber.text = "hello from joplin"
    FakeTranscriber.error = None
    monkeypatch.setattr(serve, "AudioRecorder", FakeRecorder)
    monkeypatch.setattr(serve, "Transcriber", FakeTranscriber)


def make_config(**kwargs):
    return AppConfig(notes_dir=Path("."), note_prefix="[%Y-%m-%d %H:%M]", **kwargs)


def run(commands, config=None):
    stdin = io.StringIO("".join(json.dumps(c) + "\n" for c in commands))
    stdout = io.StringIO()
    assert serve.run_serve(config or make_config(), stdin=stdin, stdout=stdout) == 0
    # Every line on stdout must be a JSON event
    return [json.loads(line) for line in stdout.getvalue().splitlines()]


def event_names(events):
    return [e["event"] for e in events]


def test_parse_args_serve_flag():
    assert parse_args(["--serve"]).serve_mode is True
    assert parse_args([]).serve_mode is False


def test_ready_reports_backend_and_model():
    events = run([], make_config(model="small.en", backend="vulkan"))
    assert events == [{"event": "ready", "backend": "vulkan", "model": "small.en", "recording": False}]


def test_start_stop_emits_transcript():
    events = run([{"cmd": "start", "mode": "toggle"}, {"cmd": "stop"}])
    assert event_names(events) == ["ready", "recording", "transcribing", "transcript"]

    transcript = events[-1]
    assert transcript["text"] == "hello from joplin"
    assert transcript["timestamp"].startswith(transcript["day"])
    assert transcript["entry_line"].startswith(f"- [{transcript['day']} ")
    assert transcript["entry_line"].endswith("] hello from joplin")
    assert FakeRecorder.instances[0].silence_mode is False


def test_short_audio_is_empty():
    FakeRecorder.samples = 100
    events = run([{"cmd": "start"}, {"cmd": "stop"}])
    assert event_names(events) == ["ready", "recording", "empty"]


def test_no_speech_is_empty():
    FakeTranscriber.text = "   "
    events = run([{"cmd": "start"}, {"cmd": "stop"}])
    assert event_names(events) == ["ready", "recording", "transcribing", "empty"]


def test_transcriber_exception_reports_error():
    FakeTranscriber.error = RuntimeError("model exploded")
    events = run([{"cmd": "start"}, {"cmd": "stop"}])
    assert events[-1]["event"] == "error"
    assert "model exploded" in events[-1]["message"]


def test_microphone_failure_reports_error():
    stdout = io.StringIO()
    server = serve.Server(make_config(), stdout)
    server.recorder.fail_start = True
    server.start("toggle")
    assert json.loads(stdout.getvalue())["event"] == "error"


def test_silence_mode_auto_stop():
    stdout = io.StringIO()
    server = serve.Server(make_config(), stdout)
    server.handle(json.dumps({"cmd": "start", "mode": "silence"}))
    assert server.recorder.silence_mode is True

    # The recorder invokes this from its own thread when silence is detected
    server.recorder.silence_stop_callback()
    server.wait_idle()
    events = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert event_names(events) == ["recording", "transcribing", "transcript"]


def test_stop_when_idle_is_ignored():
    events = run([{"cmd": "stop"}])
    assert event_names(events) == ["ready"]


def test_cancel_discards_audio():
    events = run([{"cmd": "start"}, {"cmd": "cancel"}])
    assert event_names(events) == ["ready", "recording", "cancelled"]


def test_status_and_invalid_commands():
    stdin = io.StringIO('{"cmd": "status"}\nnot json\n{"cmd": "bogus"}\n{"cmd": "quit"}\n{"cmd": "status"}\n')
    stdout = io.StringIO()
    serve.run_serve(make_config(), stdin=stdin, stdout=stdout)
    events = [json.loads(line) for line in stdout.getvalue().splitlines()]
    # Nothing after "quit" is processed
    assert event_names(events) == ["ready", "status", "error", "error"]


def test_level_events_are_throttled():
    stdout = io.StringIO()
    server = serve.Server(make_config(), stdout)
    for _ in range(50):
        server.recorder.level_callback(1000.0, 2000.0)
    events = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert events == [{"event": "level", "rms": 1000.0, "peak": 2000.0}]
