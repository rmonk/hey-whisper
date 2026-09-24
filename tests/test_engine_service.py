"""Tests for keeping a background engine running for Joplin."""

import asyncio
import sys
import threading
import time
from pathlib import Path

import pytest

from hey_whisper import engine_service, serve
from hey_whisper.config import AppConfig


class QuietRecorder:
    is_recording = False

    def __init__(self, **kwargs):
        pass


class QuietTranscriber:
    active_backend = "faster-whisper"
    is_loaded = False

    def __init__(self, **kwargs):
        pass


@pytest.fixture(autouse=True)
def no_hardware(monkeypatch):
    monkeypatch.setattr(serve, "AudioRecorder", QuietRecorder)
    monkeypatch.setattr(serve, "Transcriber", QuietTranscriber)


def run_engine_thread():
    """Start an in-process engine on the (test-isolated) default socket path."""
    stop = threading.Event()
    config = AppConfig(notes_dir=Path("."))
    thread = threading.Thread(target=serve.run_serve_socket, args=(config,), kwargs={"stop": stop}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not engine_service.engine_running():
        assert time.monotonic() < deadline, "engine never started"
        time.sleep(0.01)
    return thread, stop


class FakePopen:
    """Records the command; optionally 'starts' an in-process engine for it."""

    calls = []
    starts_engine = True
    engines = []

    def __init__(self, argv, **kwargs):
        FakePopen.calls.append(argv)
        assert kwargs["start_new_session"] is True
        if FakePopen.starts_engine:
            FakePopen.engines.append(run_engine_thread())


@pytest.fixture
def popen(monkeypatch):
    FakePopen.calls = []
    FakePopen.starts_engine = True
    FakePopen.engines = []
    monkeypatch.setattr(engine_service.subprocess, "Popen", FakePopen)
    yield FakePopen
    for thread, stop in FakePopen.engines:
        stop.set()
        thread.join(5)


def test_host_autostart_file(isolate_engine_service):
    path = engine_service.autostart_file()
    assert path == isolate_engine_service / "config" / "autostart" / "org.heywhisper.HeyWhisper-engine.desktop"
    assert engine_service.autostart_enabled() is False

    engine_service.set_autostart(True)
    text = path.read_text()
    assert "Exec=" in text and "-m hey_whisper.main --serve-socket" in text
    assert "NoDisplay=true" in text
    assert engine_service.autostart_enabled() is True

    engine_service.set_autostart(False)
    assert not path.exists()
    assert engine_service.autostart_enabled() is False


def test_desktop_exec_quoting():
    assert engine_service._desktop_exec_quote("/usr/bin/python3") == "/usr/bin/python3"
    assert engine_service._desktop_exec_quote("/opt/My Env/bin/python") == '"/opt/My Env/bin/python"'
    assert engine_service._desktop_exec_quote('/a"b$c') == '"/a\\"b\\$c"'


def test_flatpak_autostart_goes_through_the_portal(monkeypatch):
    monkeypatch.setattr(engine_service, "in_flatpak", lambda: True)
    requests = []

    async def fake_request(autostart):
        requests.append(autostart)

    monkeypatch.setattr(engine_service, "_request_background", fake_request)
    engine_service.set_autostart(True)
    engine_service.set_autostart(False)
    assert requests == [True, False]
    # The portal's file lives in the host's ~/.config, whatever XDG_CONFIG_HOME says
    assert engine_service.autostart_file() == Path.home() / ".config" / "autostart" / "org.heywhisper.HeyWhisper.desktop"


def test_flatpak_portal_refusal_is_reported(monkeypatch):
    monkeypatch.setattr(engine_service, "in_flatpak", lambda: True)

    async def refuse(autostart):
        raise RuntimeError("Running in the background was not allowed.")

    monkeypatch.setattr(engine_service, "_request_background", refuse)
    with pytest.raises(RuntimeError, match="not allowed"):
        engine_service.enable()


def test_start_engine_on_host(popen):
    engine_service.start_engine()
    assert popen.calls == [[sys.executable, "-m", "hey_whisper.main", "--serve-socket"]]
    assert engine_service.log_file().exists()


def test_start_engine_in_flatpak_uses_the_portal(popen, monkeypatch):
    monkeypatch.setattr(engine_service, "in_flatpak", lambda: True)
    spawned = []

    async def fake_spawn(argv, out_fd, env=None):
        spawned.append(argv)
        FakePopen.engines.append(run_engine_thread())
        return 1234

    monkeypatch.setattr(engine_service, "_portal_spawn", fake_spawn)
    engine_service.start_engine()
    assert spawned == [["hey-whisper", "--serve-socket"]]
    assert popen.calls == []


def test_start_engine_does_nothing_when_already_running(popen):
    thread, stop = run_engine_thread()
    try:
        engine_service.start_engine()
        assert popen.calls == []
    finally:
        stop.set()
        thread.join(5)


def test_start_engine_times_out(popen, monkeypatch):
    popen.starts_engine = False
    monkeypatch.setattr(engine_service, "START_TIMEOUT", 0.3)
    with pytest.raises(RuntimeError, match="did not start"):
        engine_service.start_engine()


def test_enable_and_disable(popen):
    engine_service.enable()
    assert engine_service.autostart_enabled()
    assert engine_service.engine_running()

    engine_service.disable()
    assert not engine_service.autostart_enabled()
    thread, _ = popen.engines[0]
    thread.join(5)
    assert not thread.is_alive()
    assert not engine_service.engine_running()


def test_stop_engine_when_not_running():
    engine_service.stop_engine()  # No error
