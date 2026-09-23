"""JSON-lines sidecar mode for driving Hey Whisper from another process.

Used by the Joplin plugin (joplin-plugin/), which spawns `hey-whisper --serve`
and exchanges one JSON object per line over stdin/stdout.

Commands (stdin):
  {"cmd": "start", "mode": "toggle" | "silence"}
  {"cmd": "stop"}      stop recording and transcribe
  {"cmd": "cancel"}    stop recording and discard the audio
  {"cmd": "status"}
  {"cmd": "quit"}

Events (stdout):
  ready, recording, level, transcribing, transcript, empty, cancelled,
  status, error
"""

import json
import os
import sys
import threading
import time
from datetime import datetime
from typing import Optional, TextIO

from hey_whisper.config import AppConfig
from hey_whisper.audio import AudioRecorder, SAMPLE_RATE
from hey_whisper.transcriber import Transcriber
from hey_whisper.storage import format_entry_line


MIN_AUDIO_SAMPLES = int(SAMPLE_RATE * 0.3)
LEVEL_INTERVAL = 1.0 / 15  # Throttle VU level events to ~15/s


class Server:
    """Owns the recorder/transcriber and translates commands into events."""

    def __init__(self, config: AppConfig, out: TextIO):
        self.config = config
        self._out = out
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
        line = json.dumps({"event": event, **fields})
        with self._write_lock:
            self._out.write(line + "\n")
            self._out.flush()

    def _status_fields(self) -> dict:
        return {
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

    def start(self, mode: str) -> None:
        with self._state_lock:
            self._start(mode)

    def _start(self, mode: str) -> None:
        if self.recorder.is_recording:
            return
        try:
            self.recorder.start_recording(silence_mode=(mode == "silence"))
        except Exception as e:
            self.emit("error", message=str(e))
            return
        self.emit("recording", mode=mode)

    def stop(self) -> None:
        with self._state_lock:
            self._stop()

    def _stop(self) -> None:
        if not self.recorder.is_recording:
            return
        audio = self.recorder.stop_recording()
        if len(audio) < MIN_AUDIO_SAMPLES:
            self.emit("empty", reason="Audio was too short.")
            return
        self.emit("transcribing")
        worker = threading.Thread(target=self._transcribe, args=(audio,), daemon=True)
        self._workers = [w for w in self._workers if w.is_alive()] + [worker]
        worker.start()

    def cancel(self) -> None:
        with self._state_lock:
            if self.recorder.is_recording:
                self.recorder.stop_recording()
        self.emit("cancelled")

    def _transcribe(self, audio) -> None:
        with self._transcribe_lock:
            try:
                text = self.transcriber.transcribe(audio)
            except Exception as e:
                self.emit("error", message=f"Transcription error: {e}")
                return
            text = (text or "").strip()
            if not text:
                self.emit("empty", reason="No speech detected.")
                return
            dt = datetime.now().astimezone()
            self.emit(
                "transcript",
                text=text,
                timestamp=dt.isoformat(),
                day=dt.strftime("%Y-%m-%d"),
                entry_line=format_entry_line(text, self.config.note_prefix, dt),
            )

    def handle(self, line: str) -> bool:
        """Process one command line. Returns False when the server should exit."""
        line = line.strip()
        if not line:
            return True
        try:
            msg = json.loads(line)
            cmd = msg["cmd"]
        except (ValueError, KeyError, TypeError):
            self.emit("error", message=f"Invalid command: {line}")
            return True

        if cmd == "start":
            self.start(msg.get("mode", "toggle"))
        elif cmd == "stop":
            self.stop()
        elif cmd == "cancel":
            self.cancel()
        elif cmd == "status":
            self.emit("status", **self._status_fields())
        elif cmd == "quit":
            return False
        else:
            self.emit("error", message=f"Unknown command: {cmd}")
        return True

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
