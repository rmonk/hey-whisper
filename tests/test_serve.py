"""Tests for the JSON-lines sidecar (--serve) used by the Joplin plugin."""

import io
import json
import socket
import threading
import time
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
        self.is_loaded = False

    def transcribe(self, audio):
        if FakeTranscriber.error:
            raise FakeTranscriber.error
        self.is_loaded = True
        return FakeTranscriber.text

    def unload(self):
        self.is_loaded = False


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


def test_parse_args_serve_socket():
    assert parse_args([]).serve_socket is None
    assert parse_args(["--serve-socket"]).serve_socket == ""
    assert parse_args(["--serve-socket", "/tmp/x.sock"]).serve_socket == "/tmp/x.sock"
    assert parse_args([]).unload_after == 15
    assert parse_args(["--unload-after", "0"]).unload_after == 0


def test_ready_reports_backend_and_model():
    events = run([], make_config(model="small.en", backend="vulkan"))
    assert events == [{"event": "ready", "protocol": 1, "backend": "vulkan", "model": "small.en", "recording": False}]


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


def lines(stream):
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def test_second_client_cannot_start_while_recording():
    a, b = io.StringIO(), io.StringIO()
    server = serve.Server(make_config(), None)
    server.handle(json.dumps({"cmd": "start"}), a)
    server.handle(json.dumps({"cmd": "start"}), b)
    assert event_names(lines(a)) == ["recording"]
    assert lines(b) == [{"event": "error", "message": "Hey Whisper is already recording for another app."}]


def test_other_clients_cannot_stop_or_cancel_a_recording():
    a, b = io.StringIO(), io.StringIO()
    server = serve.Server(make_config(), None)
    server.handle(json.dumps({"cmd": "start"}), a)
    server.handle(json.dumps({"cmd": "stop"}), b)
    server.handle(json.dumps({"cmd": "cancel"}), b)
    assert server.recorder.is_recording
    assert event_names(lines(b)) == ["cancelled"]  # b's own (empty) cancel is acknowledged

    server.handle(json.dumps({"cmd": "stop"}), a)
    server.wait_idle()
    assert event_names(lines(a)) == ["recording", "transcribing", "transcript"]


def test_transcript_goes_to_the_client_that_recorded():
    a, b = io.StringIO(), io.StringIO()
    server = serve.Server(make_config(), None)
    release = threading.Event()
    original = FakeTranscriber.transcribe

    def slow(self, audio):
        release.wait(5)
        return original(self, audio)

    server.transcriber.transcribe = slow.__get__(server.transcriber)
    server.handle(json.dumps({"cmd": "start"}), a)
    server.handle(json.dumps({"cmd": "stop"}), a)
    # b starts recording while a's audio is still being transcribed
    server.handle(json.dumps({"cmd": "start"}), b)
    release.set()
    server.wait_idle()
    assert event_names(lines(a)) == ["recording", "transcribing", "transcript"]
    assert event_names(lines(b)) == ["recording"]


def test_the_next_client_can_record_once_the_first_stops():
    a, b = io.StringIO(), io.StringIO()
    server = serve.Server(make_config(), None)
    server.handle(json.dumps({"cmd": "start"}), a)
    server.handle(json.dumps({"cmd": "cancel"}), a)
    server.handle(json.dumps({"cmd": "start"}), b)
    assert event_names(lines(b)) == ["recording"]


def test_disconnect_discards_that_clients_recording():
    a = io.StringIO()
    server = serve.Server(make_config(), None)
    server.handle(json.dumps({"cmd": "start"}), a)
    server.disconnect(a)
    assert not server.recorder.is_recording


def test_idle_unload():
    server = serve.Server(make_config(), None, unload_after=60)
    server.transcriber.is_loaded = True
    now = time.monotonic()
    assert server.unload_if_idle(now) is False  # Just created
    assert server.unload_if_idle(now + 61) is True
    assert server.transcriber.is_loaded is False
    assert server.unload_if_idle(now + 120) is False  # Nothing left to free


def test_idle_unload_waits_for_recording_and_is_off_by_default():
    server = serve.Server(make_config(), None, unload_after=60)
    server.transcriber.is_loaded = True
    server.start("toggle", io.StringIO())
    assert server.unload_if_idle(time.monotonic() + 600) is False

    stdio = serve.Server(make_config(), io.StringIO())
    stdio.transcriber.is_loaded = True
    assert stdio.unload_if_idle(time.monotonic() + 10**6) is False


@pytest.fixture
def engine(tmp_path):
    """A --serve-socket engine on a temporary path, running in a thread."""
    path = tmp_path / "engine.sock"
    stop = threading.Event()
    result = {}
    thread = threading.Thread(
        target=lambda: result.setdefault("code", serve.run_serve_socket(make_config(), path, stop=stop)),
        daemon=True,
    )
    thread.start()
    deadline = time.monotonic() + 5
    while not path.exists():
        assert time.monotonic() < deadline, "engine never started listening"
        time.sleep(0.01)
    yield path, stop, thread, result
    stop.set()
    thread.join(5)


class Client:
    def __init__(self, path):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(str(path))
        self.sock.settimeout(5)
        self.rfile = self.sock.makefile("r", encoding="utf-8")

    def send(self, cmd):
        self.sock.sendall((json.dumps(cmd) + "\n").encode())

    def read(self):
        return json.loads(self.rfile.readline())

    def close(self):
        self.rfile.close()
        self.sock.close()


def test_socket_round_trip(engine):
    path, _, _, _ = engine
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700
    client = Client(path)
    assert client.read()["event"] == "ready"
    client.send({"cmd": "start"})
    client.send({"cmd": "stop"})
    assert [client.read()["event"] for _ in range(3)] == ["recording", "transcribing", "transcript"]
    client.close()


def test_socket_quit_closes_only_that_connection(engine):
    path, _, thread, _ = engine
    a = Client(path)
    a.read()
    a.send({"cmd": "quit"})
    assert a.rfile.readline() == ""  # Closed by the engine
    a.close()

    b = Client(path)
    assert b.read()["event"] == "ready"
    b.close()
    assert thread.is_alive()


def test_socket_shutdown_stops_engine_and_removes_socket(engine):
    path, _, thread, result = engine
    client = Client(path)
    client.read()
    client.send({"cmd": "shutdown"})
    thread.join(5)
    client.close()
    assert result["code"] == 0
    assert not path.exists()


def test_socket_disconnect_frees_the_microphone(engine):
    path, _, _, _ = engine
    a = Client(path)
    a.read()
    a.send({"cmd": "start"})
    assert a.read()["event"] == "recording"
    a.close()

    b = Client(path)
    b.read()
    deadline = time.monotonic() + 5
    while True:
        b.send({"cmd": "start"})
        if b.read()["event"] == "recording":
            break
        assert time.monotonic() < deadline, "a's recording was never released"
        time.sleep(0.01)
    b.close()


def test_second_engine_exits_when_one_is_running(engine):
    path, _, _, _ = engine
    assert serve.run_serve_socket(make_config(), path) == 0
    assert Client(path).read()["event"] == "ready"  # The first one is untouched


def test_stale_socket_is_replaced(tmp_path):
    path = tmp_path / "engine.sock"
    stale = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    stale.bind(str(path))
    stale.close()  # Leaves the file with nothing listening

    stop = threading.Event()
    thread = threading.Thread(target=serve.run_serve_socket, args=(make_config(), path), kwargs={"stop": stop}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while True:
        try:
            client = Client(path)
            break
        except OSError:
            assert time.monotonic() < deadline, "engine never replaced the stale socket"
            time.sleep(0.01)
    assert client.read()["event"] == "ready"
    client.close()
    stop.set()
    thread.join(5)
