"""Tests for CLI arguments and entry point."""

from pathlib import Path
from hey_whisper.main import parse_args


def test_parse_args_defaults():
    args = parse_args([])
    assert args.notes_dir is None
    assert args.mode is None
    assert args.silence_timeout is None
    assert args.backend is None
    assert args.theme is None
    assert args.note_prefix is None
    assert not args.cli_mode


def test_parse_args_custom():
    args = parse_args([
        "-d", "/custom/notes",
        "-m", "silence",
        "--silence-timeout", "2.0",
        "--model", "small.en",
        "--backend", "vulkan",
        "--theme", "dark",
        "--prefix", "[%Y-%m-%d %H:%M]",
        "--cli",
    ])
    assert args.notes_dir == "/custom/notes"
    assert args.mode == "silence"
    assert args.silence_timeout == 2.0
    assert args.model == "small.en"
    assert args.backend == "vulkan"
    assert args.theme == "dark"
    assert args.note_prefix == "[%Y-%m-%d %H:%M]"
    assert args.cli_mode is True

