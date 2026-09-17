"""Entry point for Hey Whisper application."""

import argparse
import os
import sys
from pathlib import Path

from hey_whisper.config import load_config
from hey_whisper.cli import run_cli


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog="hey-whisper",
        description="Listen on default microphone, transcribe speech using faster-whisper / Vulkan whisper, and append to weekly markdown logs.",
    )
    parser.add_argument(
        "-d", "--dir",
        dest="notes_dir",
        type=str,
        default=None,
        help="Directory to store markdown notes (defaults to ~/.config/hey-whisper.conf, then CWD)",
    )
    parser.add_argument(
        "-m", "--mode",
        dest="mode",
        choices=["hold", "toggle", "silence"],
        default=None,
        help="Recording trigger mode: hold (default), toggle (press to start/stop), silence (stop on silence)",
    )
    parser.add_argument(
        "--silence-timeout",
        dest="silence_timeout",
        type=float,
        default=None,
        help="Duration of silence in seconds to auto-stop recording (for silence mode)",
    )
    parser.add_argument(
        "--model",
        dest="model",
        type=str,
        default=None,
        help="Whisper model size/name (e.g. tiny.en, base.en, small.en, default: base.en)",
    )
    parser.add_argument(
        "--backend",
        dest="backend",
        choices=["auto", "vulkan", "faster-whisper", "nemo"],
        default=None,
        help="Transcription backend: auto (detects Vulkan GPU acceleration), vulkan, faster-whisper, "
        "or nemo (NVIDIA Parakeet/Canary via onnx-asr, never auto-selected)",
    )
    parser.add_argument(
        "--theme",
        dest="theme",
        choices=["auto", "light", "dark"],
        default=None,
        help="GUI color theme: auto (detects system dark/light mode), light, or dark",
    )
    parser.add_argument(
        "--prefix", "--note-prefix",
        dest="note_prefix",
        type=str,
        default=None,
        help="Prefix string template for new notes (default: '[%%Y-%%m-%%d %%H:%%M %%Z]')",
    )
    parser.add_argument(
        "--config",
        dest="config_path",
        type=Path,
        default=None,
        help="Path to custom config file (default: ~/.config/hey-whisper.conf)",
    )
    parser.add_argument(
        "--cli",
        dest="cli_mode",
        action="store_true",
        help="Run in command-line mode instead of launching GUI",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    config = load_config(
        cli_dir=args.notes_dir,
        cli_mode=args.mode,
        cli_silence_timeout=args.silence_timeout,
        cli_model=args.model,
        cli_backend=args.backend,
        cli_theme=args.theme,
        cli_note_prefix=args.note_prefix,
        config_path=args.config_path,
    )

    # If --cli explicitly passed, or headless environment (no DISPLAY / WAYLAND_DISPLAY)
    has_display = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
    if args.cli_mode or not has_display:
        return run_cli(config)

    # Launch GUI
    try:
        from PyQt6.QtWidgets import QApplication
        from hey_whisper.gui import MainWindow
        from hey_whisper.gui.icons import get_app_icon

        app = QApplication(sys.argv)
        app.setApplicationName("Hey Whisper")
        app.setDesktopFileName("org.heywhisper.HeyWhisper")
        app.setWindowIcon(get_app_icon())

        window = MainWindow(config)
        window.show()
        return app.exec()
    except Exception as e:
        print(f"Warning: Failed to launch GUI ({e}). Falling back to CLI mode...", file=sys.stderr)
        return run_cli(config)


if __name__ == "__main__":
    sys.exit(main())
