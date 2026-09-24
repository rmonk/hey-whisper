"""JSON-lines sidecar mode for driving Hey Whisper from another process.

Used by the Joplin plugin (joplin-plugin/), which either spawns
`hey-whisper --serve` and exchanges one JSON object per line over
stdin/stdout, or connects to `hey-whisper --serve-socket` over a Unix socket.
The socket lets a sandboxed app (e.g. Joplin as a Flatpak) use an engine it
has no permission to start.

Commands (stdin, or each socket connection):
  {"cmd": "start", "mode": "toggle" | "silence"}
  {"cmd": "stop"}      stop recording and transcribe
  {"cmd": "cancel"}    stop recording and discard the audio
  {"cmd": "status"}
  {"cmd": "quit"}      --serve: exit; --serve-socket: close this connection
  {"cmd": "shutdown"}  exit, closing every connection

Events (stdout, or each socket connection):
  ready, recording, level, transcribing, transcript, empty, cancelled,
  status, error

Over the socket several clients can connect at once, but only one can record:
a "start" from another client while one is recording gets an error. Events
about a recording go to the client that started it.
"""

import json
import os
import signal
import socket
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, TextIO

from hey_whisper.config import AppConfig
from hey_whisper.audio import AudioRecorder, SAMPLE_RATE
from hey_whisper.transcriber import Transcriber
from hey_whisper.storage import format_entry_line


MIN_AUDIO_SAMPLES = int(SAMPLE_RATE * 0.3)
LEVEL_INTERVAL = 1.0 / 15  # Throttle VU level events to ~15/s
# Bumped when the protocol changes in a way clients need to know about
PROTOCOL_VERSION = 1
DEFAULT_UNLOAD_AFTER = 15 * 60  # seconds an idle --serve-socket engine keeps the model loaded
# How often the socket engine wakes to check for shutdown and idle unload
POLL_INTERVAL = 1.0


class Server:
    """Owns the recorder/transcriber and translates commands into events."""

    def __init__(self, config: AppConfig, out: Optional[TextIO], unload_after: float = 0):
        self.config = config
        # The only client in --serve mode; None in socket mode, where every
        # command names the connection it came from.
        self._out = out
        # The client that started the current (or last) recording
        self._owner = out
        self._unload_after = unload_after
        self._last_used = time.monotonic()
        self.shutdown_requested = False
        self._write_lock = threading.Lock()
        self._transcribe_lock = threading.Lock()
        # Serializes start/stop/cancel: a silence auto-stop can race a "stop" command.
        self._state_lock = threading.Lock()
        self._last_level = 0.0
        self._workers: list = []

        self.recorder = AudioRecorder(
            silence_timeout=config.silence_timeout,
            silence_threshold=config.silence_threshold,
            level_callback=self._on_level,
            silence_stop_callback=self._on_silence,
        )
        self.transcriber = Transcriber(
            model_name=config.model,
            backend=config.backend,
            device=config.device,
            compute_type=config.compute_type,
            vulkan_device=config.vulkan_device,
        )

    def emit(self, event: str, **fields) -> None:
        """Send an event about the current recording to the client that started it."""
        self.send(self._owner, event, **fields)

    def send(self, out: Optional[TextIO], event: str, **fields) -> None:
        if out is None:
            return
        line = json.dumps({"event": event, **fields})
        with self._write_lock:
            try:
                out.write(line + "\n")
                out.flush()
            except (OSError, ValueError):
                pass  # That client has disconnected

    def _status_fields(self) -> dict:
        return {
            "protocol": PROTOCOL_VERSION,
            "backend": self.transcriber.active_backend,
            "model": self.config.model,
            "recording": self.recorder.is_recording,
        }

    def _on_level(self, rms: float, peak: float) -> None:
        now = time.monotonic()
        if now - self._last_level < LEVEL_INTERVAL:
            return
        self._last_level = now
        self.emit("level", rms=round(rms, 1), peak=round(peak, 1))

    def _on_silence(self) -> None:
        self.stop()

    def start(self, mode: str, out: Optional[TextIO] = None) -> None:
        out = self._out if out is None else out
        with self._state_lock:
            if self.recorder.is_recording:
                if out is not self._owner:
                    self.send(out, "error", message="Hey Whisper is already recording for another app.")
                return
            self._owner = out
            self._start(mode)

    def _start(self, mode: str) -> None:
        if self.recorder.is_recording:
            return
        try:
            self.recorder.start_recording(silence_mode=(mode == "silence"))
        except Exception as e:
            self.emit("error", message=str(e))
            return
        self._last_used = time.monotonic()
        self.emit("recording", mode=mode)

    def stop(self, out: Optional[TextIO] = None) -> None:
        """Stop and transcribe. `out` is the client asking; None means the
        engine itself (silence detection), which may stop anyone's recording."""
        with self._state_lock:
            if out is not None and out is not self._owner:
                return
            self._stop()

    def _stop(self) -> None:
        if not self.recorder.is_recording:
            return
        audio = self.recorder.stop_recording()
        if len(audio) < MIN_AUDIO_SAMPLES:
            self.emit("empty", reason="Audio was too short.")
            return
        self._last_used = time.monotonic()
        self.emit("transcribing")
        # Bind the result to this recording's client: another client may start
        # recording before the transcription finishes.
        worker = threading.Thread(target=self._transcribe, args=(audio, self._owner), daemon=True)
        self._workers = [w for w in self._workers if w.is_alive()] + [worker]
        worker.start()

    def cancel(self, out: Optional[TextIO] = None) -> None:
        out = self._owner if out is None else out
        with self._state_lock:
            # Never discard another client's recording
            if self.recorder.is_recording and out is self._owner:
                self.recorder.stop_recording()
        self.send(out, "cancelled")

    def disconnect(self, out: TextIO) -> None:
        """A socket client went away: drop its recording, since nobody is left to receive it."""
        with self._state_lock:
            if self._owner is out:
                if self.recorder.is_recording:
                    self.recorder.stop_recording()
                self._owner = None

    def _transcribe(self, audio, out: Optional[TextIO]) -> None:
        with self._transcribe_lock:
            try:
                text = self.transcriber.transcribe(audio)
            except Exception as e:
                self.send(out, "error", message=f"Transcription error: {e}")
                return
            finally:
                self._last_used = time.monotonic()
            text = (text or "").strip()
            if not text:
                self.send(out, "empty", reason="No speech detected.")
                return
            dt = datetime.now().astimezone()
            self.send(
                out,
                "transcript",
                text=text,
                timestamp=dt.isoformat(),
                day=dt.strftime("%Y-%m-%d"),
                entry_line=format_entry_line(text, self.config.note_prefix, dt),
            )

    def handle(self, line: str, out: Optional[TextIO] = None) -> bool:
        """Process one command line from `out` (the only client when None).
        Returns False when that client's session should end."""
        out = self._out if out is None else out
        line = line.strip()
        if not line:
            return True
        try:
            msg = json.loads(line)
            cmd = msg["cmd"]
        except (ValueError, KeyError, TypeError):
            self.send(out, "error", message=f"Invalid command: {line}")
            return True

        if cmd == "start":
            self.start(msg.get("mode", "toggle"), out)
        elif cmd == "stop":
            self.stop(out)
        elif cmd == "cancel":
            self.cancel(out)
        elif cmd == "status":
            self.send(out, "status", **self._status_fields())
        elif cmd == "quit":
            return False
        elif cmd == "shutdown":
            self.shutdown_requested = True
            return False
        else:
            self.send(out, "error", message=f"Unknown command: {cmd}")
        return True

    def unload_if_idle(self, now: Optional[float] = None) -> bool:
        """Free the speech model once nothing has used it for `unload_after`
        seconds. It loads again on the next transcription."""
        if not self._unload_after:
            return False
        now = time.monotonic() if now is None else now
        with self._state_lock:
            if self.recorder.is_recording or now - self._last_used < self._unload_after:
                return False
        if not self._transcribe_lock.acquire(blocking=False):
            return False  # Transcribing right now
        try:
            if not self.transcriber.is_loaded:
                return False
            self.transcriber.unload()
            return True
        finally:
            self._transcribe_lock.release()

    def wait_idle(self, timeout: Optional[float] = None) -> None:
        """Block until any in-flight transcription has finished."""
        for worker in list(self._workers):
            worker.join(timeout)


def run_serve(config: AppConfig, stdin: Optional[TextIO] = None, stdout: Optional[TextIO] = None) -> int:
    """Run the JSON-lines server until stdin closes or a quit command arrives."""
    stdin = stdin or sys.stdin
    out = stdout
    if out is None:
        # Keep the protocol stream clean: move the real stdout to a private fd
        # and point fd 1 at stderr, so anything else that prints (Python
        # warnings, native libraries, download progress) lands on stderr.
        sys.stdout.flush()
        out = os.fdopen(os.dup(1), "w", encoding="utf-8")
        os.dup2(2, 1)
        sys.stdout = sys.stderr

    server = Server(config, out)
    server.emit("ready", **server._status_fields())

    try:
        for line in stdin:
            if not server.handle(line):
                break
    except KeyboardInterrupt:
        pass
    finally:
        if server.recorder.is_recording:
            server.recorder.stop_recording()
        # Let a transcription that is already running report its result.
        server.wait_idle(timeout=120)
    return 0


def default_socket_path() -> Path:
    # Not $XDG_STATE_HOME or $XDG_RUNTIME_DIR: inside a Flatpak those point at
    # directories private to that app, where another sandboxed app can't see
    # the socket. The real home directory is shared with apps that have home
    # access, which Joplin's Flatpak does.
    return Path.home() / ".local" / "state" / "hey-whisper" / "engine.sock"


def _engine_listening(path: Path) -> bool:
    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        probe.connect(str(path))
        return True
    except OSError:
        return False
    finally:
        probe.close()


def _serve_client(server: Server, conn: socket.socket, stop: threading.Event) -> None:
    conn.settimeout(None)
    rfile = conn.makefile("r", encoding="utf-8")
    wfile = conn.makefile("w", encoding="utf-8")
    server.send(wfile, "ready", **server._status_fields())
    try:
        for line in rfile:
            if not server.handle(line, wfile):
                break
    except OSError:
        pass
    finally:
        server.disconnect(wfile)
        for f in (rfile, wfile, conn):
            try:
                # wfile may still hold an event that failed to send; closing
                # flushes it again, into a connection the client already closed.
                f.close()
            except OSError:
                pass
    if server.shutdown_requested:
        stop.set()


def run_serve_socket(
    config: AppConfig,
    path: Optional[Path] = None,
    unload_after: float = DEFAULT_UNLOAD_AFTER,
    stop: Optional[threading.Event] = None,
) -> int:
    """Run the engine on a Unix socket until SIGTERM/SIGINT, a "shutdown"
    command, or `stop` is set. Exits at once if an engine is already listening."""
    path = Path(path) if path else default_socket_path()
    stop = stop or threading.Event()

    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    if _engine_listening(path):
        print(f"A Hey Whisper engine is already running on {path}", file=sys.stderr)
        return 0
    path.unlink(missing_ok=True)  # Left behind by an engine that didn't exit cleanly

    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    old_umask = os.umask(0o177)  # Owner-only from the moment the socket exists
    try:
        listener.bind(str(path))
    finally:
        os.umask(old_umask)
    listener.listen()
    listener.settimeout(POLL_INTERVAL)
    inode = path.stat().st_ino

    if threading.current_thread() is threading.main_thread():
        for signum in (signal.SIGTERM, signal.SIGINT):
            signal.signal(signum, lambda *_: stop.set())

    server = Server(config, None, unload_after=unload_after)
    print(f"Hey Whisper engine listening on {path}", file=sys.stderr)
    try:
        while not stop.is_set():
            try:
                conn, _ = listener.accept()
            except socket.timeout:
                server.unload_if_idle()
                continue
            threading.Thread(target=_serve_client, args=(server, conn, stop), daemon=True).start()
    finally:
        listener.close()
        # Only remove the socket if it is still ours
        try:
            if path.stat().st_ino == inode:
                path.unlink()
        except FileNotFoundError:
            pass
        if server.recorder.is_recording:
            server.recorder.stop_recording()
        server.wait_idle(timeout=120)
    return 0
