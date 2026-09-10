"""Configuration management for hey-whisper.

Handles loading settings from ~/.config/hey-whisper.conf (with fallback to
~/.config/spoken-notes.conf), command-line arguments, and defaults.

Storage precedence:
1. Command-line option (--dir / -d)
2. Configuration file (~/.config/hey-whisper.conf)
3. Current working directory (os.getcwd())

Trigger modes:
- hold: Held-down key or button (default)
- toggle: Press to start / press to end
- silence: Stop after configurable silence

Themes:
- auto: Detect system theme (light/dark) automatically (default)
- dark: Force dark theme
- light: Force light theme

Whisper backends:
- auto: Detect Vulkan GPU acceleration; fallback to faster-whisper/CPU
- vulkan: whisper.cpp with Vulkan GGML backend
- faster-whisper: CTranslate2 backend
"""

import os
import configparser
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


DEFAULT_CONFIG_PATH = Path.home() / ".config" / "hey-whisper.conf"
FALLBACK_CONFIG_PATH = Path.home() / ".config" / "spoken-notes.conf"


@dataclass
class AppConfig:
    notes_dir: Path
    mode: str = "hold"  # "hold", "toggle", or "silence"
    hotkey: str = "Space"
    silence_timeout: float = 1.5  # seconds
    silence_threshold: float = 500.0  # RMS audio energy threshold
    model: str = "base.en"
    backend: str = "auto"  # "auto", "vulkan", "faster-whisper"
    theme: str = "auto"  # "auto", "light", "dark"
    note_prefix: str = "[%Y-%m-%d %H:%M %Z]"  # Note timestamp / prefix format
    device: str = "auto"
    compute_type: str = "int8"
    vulkan_device: int = 0
    config_file: Optional[Path] = None


def load_config(
    cli_dir: Optional[str] = None,
    cli_mode: Optional[str] = None,
    cli_silence_timeout: Optional[float] = None,
    cli_model: Optional[str] = None,
    cli_backend: Optional[str] = None,
    cli_theme: Optional[str] = None,
    cli_note_prefix: Optional[str] = None,
    config_path: Optional[Path] = None,
) -> AppConfig:
    """Load configuration with precedence: CLI > config file > default (CWD for notes_dir)."""
    target_config = config_path
    if target_config is None:
        if DEFAULT_CONFIG_PATH.is_file():
            target_config = DEFAULT_CONFIG_PATH
        elif FALLBACK_CONFIG_PATH.is_file():
            target_config = FALLBACK_CONFIG_PATH
        else:
            target_config = DEFAULT_CONFIG_PATH

    # Raw file values
    file_dir: Optional[str] = None
    file_mode: Optional[str] = None
    file_hotkey: Optional[str] = None
    file_silence_timeout: Optional[float] = None
    file_silence_threshold: Optional[float] = None
    file_model: Optional[str] = None
    file_backend: Optional[str] = None
    file_theme: Optional[str] = None
    file_note_prefix: Optional[str] = None
    file_device: Optional[str] = None
    file_compute_type: Optional[str] = None
    file_vulkan_dev: Optional[int] = None

    if target_config.is_file():
        text = target_config.read_text(encoding="utf-8")
        parser = configparser.ConfigParser(interpolation=None)
        if not text.strip().startswith("["):
            text = "[hey_whisper]\n" + text
        try:
            parser.read_string(text)
            section = "general" if parser.has_section("general") else (
                "hey_whisper" if parser.has_section("hey_whisper") else (
                    "spoken_notes" if parser.has_section("spoken_notes") else parser.sections()[0]
                )
            )

            def get_val(key: str) -> Optional[str]:
                if parser.has_option(section, key):
                    return parser.get(section, key)
                for s in parser.sections():
                    if parser.has_option(s, key):
                        return parser.get(s, key)
                return None

            file_dir = get_val("notes_dir") or get_val("dir")
            file_mode = get_val("mode")
            file_hotkey = get_val("hotkey")
            file_model = get_val("model")
            file_backend = get_val("backend")
            file_theme = get_val("theme")
            file_note_prefix = get_val("note_prefix") or get_val("prefix")
            file_device = get_val("device")
            file_compute_type = get_val("compute_type")

            timeout_str = get_val("silence_timeout")
            if timeout_str:
                try:
                    file_silence_timeout = float(timeout_str)
                except ValueError:
                    pass

            thresh_str = get_val("silence_threshold")
            if thresh_str:
                try:
                    file_silence_threshold = float(thresh_str)
                except ValueError:
                    pass

            vk_dev_str = get_val("vulkan_device")
            if vk_dev_str:
                try:
                    file_vulkan_dev = int(vk_dev_str)
                except ValueError:
                    pass
        except Exception:
            pass

    # Resolve notes directory: CLI > config file > CWD
    if cli_dir:
        resolved_dir = Path(cli_dir).expanduser().resolve()
    elif file_dir:
        resolved_dir = Path(file_dir).expanduser().resolve()
    else:
        resolved_dir = Path.cwd().resolve()

    # Resolve trigger mode: CLI > config file > default "hold"
    mode_candidate = (cli_mode or file_mode or "hold").lower().strip()
    if mode_candidate not in ("hold", "toggle", "silence"):
        mode_candidate = "hold"

    # Resolve backend: CLI > config file > default "auto"
    backend_candidate = (cli_backend or file_backend or "auto").lower().strip()
    if backend_candidate not in ("auto", "vulkan", "faster-whisper"):
        backend_candidate = "auto"

    # Resolve theme: CLI > config file > default "auto"
    theme_candidate = (cli_theme or file_theme or "auto").lower().strip()
    if theme_candidate not in ("auto", "light", "dark"):
        theme_candidate = "auto"

    silence_timeout = (
        cli_silence_timeout
        if cli_silence_timeout is not None
        else (file_silence_timeout if file_silence_timeout is not None else 1.5)
    )

    model = cli_model or file_model or "base.en"
    hotkey = file_hotkey or "Space"
    silence_threshold = file_silence_threshold if file_silence_threshold is not None else 500.0
    note_prefix = cli_note_prefix or file_note_prefix or "[%Y-%m-%d %H:%M %Z]"
    device = file_device or "auto"
    compute_type = file_compute_type or "int8"
    vulkan_device = file_vulkan_dev if file_vulkan_dev is not None else 0

    return AppConfig(
        notes_dir=resolved_dir,
        mode=mode_candidate,
        hotkey=hotkey,
        silence_timeout=silence_timeout,
        silence_threshold=silence_threshold,
        model=model,
        backend=backend_candidate,
        theme=theme_candidate,
        note_prefix=note_prefix,
        device=device,
        compute_type=compute_type,
        vulkan_device=vulkan_device,
        config_file=target_config if target_config.is_file() else None,
    )


def save_config(config: AppConfig, path: Optional[Path] = None) -> Path:
    """Save configuration to ~/.config/hey-whisper.conf or specified path."""
    target = path or config.config_file or DEFAULT_CONFIG_PATH
    target.parent.mkdir(parents=True, exist_ok=True)

    parser = configparser.ConfigParser(interpolation=None)
    if target.is_file():
        try:
            parser.read(str(target), encoding="utf-8")
        except Exception:
            pass

    if not parser.has_section("general"):
        parser.add_section("general")
    if not parser.has_section("recording"):
        parser.add_section("recording")

    parser.set("general", "notes_dir", str(config.notes_dir))
    parser.set("general", "backend", str(config.backend))
    parser.set("general", "theme", str(config.theme))
    parser.set("general", "note_prefix", str(config.note_prefix))
    parser.set("general", "model", str(config.model))
    parser.set("general", "device", str(config.device))
    parser.set("general", "compute_type", str(config.compute_type))
    parser.set("general", "vulkan_device", str(config.vulkan_device))

    parser.set("recording", "mode", str(config.mode))
    parser.set("recording", "hotkey", str(config.hotkey))
    parser.set("recording", "silence_timeout", str(config.silence_timeout))
    parser.set("recording", "silence_threshold", str(config.silence_threshold))

    with open(target, "w", encoding="utf-8") as f:
        parser.write(f)

    config.config_file = target
    return target

