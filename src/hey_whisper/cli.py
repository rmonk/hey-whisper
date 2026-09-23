"""Command-line interface for Hey Whisper."""

import sys
import time
from typing import Optional

from hey_whisper.config import AppConfig
from hey_whisper.audio import AudioRecorder
from hey_whisper.transcriber import Transcriber
from hey_whisper.storage import append_note


def run_cli(config: AppConfig) -> int:
    """Run interactive audio capture and transcription in terminal."""
    print("=" * 60)
    print("🎙️  Hey Whisper - Spoken Voice Notes (CLI Mode)")
    print(f"Notes directory : {config.notes_dir}")
    print(f"Trigger mode    : {config.mode}")
    print(f"Whisper model   : {config.model}")
    print("=" * 60)

    silence_stopped = False

    def on_silence():
        nonlocal silence_stopped
        silence_stopped = True

    recorder = AudioRecorder(
        silence_timeout=config.silence_timeout,
        silence_threshold=config.silence_threshold,
        silence_stop_callback=on_silence,
    )

    transcriber = Transcriber(
        model_name=config.model,
        backend=config.backend,
        device=config.device,
        compute_type=config.compute_type,
        vulkan_device=config.vulkan_device,
    )

    silence_mode = (config.mode == "silence")

    try:
        recorder.start_recording(silence_mode=silence_mode)
    except Exception as e:
        print(f"❌ Error initializing microphone: {e}", file=sys.stderr)
        return 1

    if config.mode == "silence":
        print(f"🔴 Listening... Speak now (auto-stops after {config.silence_timeout}s of silence, or Ctrl+C)")
        try:
            while not silence_stopped:
                time.sleep(0.1)
        except KeyboardInterrupt:
            print("\nStopped by user.")
    else:
        print("🔴 Recording... Press ENTER when finished (or Ctrl+C to abort):")
        try:
            input()
        except KeyboardInterrupt:
            print("\nAborted.")
            recorder.stop_recording()
            return 0

    print(f"⏳ Stopping capture and transcribing ({transcriber.active_backend})...")
    audio_data = recorder.stop_recording()

    if len(audio_data) < int(16000 * 0.3):
        print("⚠️  Audio was too short (< 0.3s). Nothing recorded.")
        return 0

    try:
        text = transcriber.transcribe(audio_data)
        if not text:
            print("⚠️  No speech detected.")
            return 0

        target_file, entry = append_note(config.notes_dir, text, prefix_template=config.note_prefix)
        print(f"\n✅ Note transcribed and saved successfully!")
        print(f"File : {target_file}")
        print(f"Entry: {entry}")
        return 0
    except Exception as e:
        print(f"❌ Transcription error: {e}", file=sys.stderr)
        return 1
