"""Unit tests for config.py."""

from pathlib import Path
from hey_whisper.config import load_config, AppConfig, DEFAULT_CONFIG_PATH, FALLBACK_CONFIG_PATH


def test_config_name():
    assert DEFAULT_CONFIG_PATH.name == "hey-whisper.conf"
    assert FALLBACK_CONFIG_PATH.name == "spoken-notes.conf"


def test_config_precedence(tmp_path: Path):
    cfg_file = tmp_path / "hey-whisper.conf"
    cfg_file.write_text(
        """
[general]
notes_dir = /tmp/file_notes
mode = toggle
silence_timeout = 2.5
backend = vulkan
vulkan_device = 1
theme = dark
note_prefix = * [%H:%M]

[recording]
hotkey = F9
""",
        encoding="utf-8",
    )

    # 1. Config file values used when no CLI args provided
    cfg = load_config(config_path=cfg_file)
    assert cfg.notes_dir == Path("/tmp/file_notes").resolve()
    assert cfg.mode == "toggle"
    assert cfg.silence_timeout == 2.5
    assert cfg.hotkey == "F9"
    assert cfg.backend == "vulkan"
    assert cfg.vulkan_device == 1
    assert cfg.theme == "dark"
    assert cfg.note_prefix == "* [%H:%M]"

    # 2. CLI overrides config file
    cfg_cli = load_config(
        cli_dir="/tmp/cli_notes",
        cli_mode="silence",
        cli_silence_timeout=3.0,
        cli_backend="faster-whisper",
        cli_theme="light",
        cli_note_prefix="> [%Y-%m-%d]",
        config_path=cfg_file,
    )
    assert cfg_cli.notes_dir == Path("/tmp/cli_notes").resolve()
    assert cfg_cli.mode == "silence"
    assert cfg_cli.silence_timeout == 3.0
    assert cfg_cli.backend == "faster-whisper"
    assert cfg_cli.theme == "light"
    assert cfg_cli.note_prefix == "> [%Y-%m-%d]"

    # 3. Default fallback to CWD and 'hold' mode when no config exists
    non_existent = tmp_path / "does_not_exist.conf"
    cfg_default = load_config(config_path=non_existent)
    assert cfg_default.notes_dir == Path.cwd().resolve()
    assert cfg_default.mode == "hold"
    assert cfg_default.silence_timeout == 1.5
    assert cfg_default.hotkey == "Space"
    assert cfg_default.backend == "auto"
    assert cfg_default.theme == "auto"
    assert cfg_default.note_prefix == "[%Y-%m-%d %H:%M %Z]"


def test_save_config(tmp_path: Path):
    from hey_whisper.config import save_config
    out_file = tmp_path / "saved.conf"
    cfg = AppConfig(
        notes_dir=tmp_path / "my_notes",
        mode="silence",
        hotkey="Ctrl+Alt+R",
        silence_timeout=2.0,
        theme="dark",
        backend="vulkan",
        note_prefix="[%Y/%m/%d %H:%M]",
        config_file=out_file,
    )
    saved_path = save_config(cfg, out_file)
    assert saved_path == out_file
    assert out_file.is_file()

    # Re-read and verify
    reloaded = load_config(config_path=out_file)
    assert reloaded.notes_dir == (tmp_path / "my_notes").resolve()
    assert reloaded.mode == "silence"
    assert reloaded.hotkey == "Ctrl+Alt+R"
    assert reloaded.silence_timeout == 2.0
    assert reloaded.theme == "dark"
    assert reloaded.backend == "vulkan"
    assert reloaded.note_prefix == "[%Y/%m/%d %H:%M]"


