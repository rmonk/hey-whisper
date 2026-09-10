"""Tests for GUI components using Qt offscreen platform."""

import os
from pathlib import Path
try:
    import pytest
except ImportError:
    pytest = None
from PyQt6.QtWidgets import QApplication

# Set offscreen platform for headless test runs
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from hey_whisper.config import AppConfig
from hey_whisper.gui.main_window import MainWindow
from hey_whisper.gui.month_tree import MonthTreeWidget
from hey_whisper.gui.editor import MarkdownEditorWidget
from hey_whisper.gui.theme import get_theme_colors, LIGHT_THEME, DARK_THEME
from hey_whisper.storage import append_note


if pytest is not None:
    @pytest.fixture(scope="session")
    def qapp():
        app = QApplication.instance()
        if app is None:
            app = QApplication(["pytest-qt"])
        return app



def test_month_tree_population(qapp, tmp_path: Path):
    tree = MonthTreeWidget()
    f1, _ = append_note(tmp_path, "First note", None)
    tree.refresh(tmp_path)
    assert tree.topLevelItemCount() > 0
    tree.deleteLater()
    qapp.processEvents()


def test_editor_load_and_save(qapp, tmp_path: Path):
    editor = MarkdownEditorWidget()
    f, _ = append_note(tmp_path, "Original content", None)
    editor.load_file(f)
    assert "Original content" in editor.plain_edit.toPlainText()

    # Modify and save
    editor.plain_edit.setPlainText("# 2026-09-09\n\n- Updated content\n")
    editor.save()
    assert "- Updated content" in f.read_text()
    editor.deleteLater()
    qapp.processEvents()


def test_editor_scroll_to_entry(qapp, tmp_path: Path):
    editor = MarkdownEditorWidget()
    long_content = "\n".join([f"# Day {i}\n- Old note line {i}" for i in range(1, 60)])
    f = tmp_path / "long_notes.md"
    f.write_text(long_content + "\n\n# Today\n- [2026-09-10 15:20] Jump target item\n")
    editor.load_file(f)

    # Initial position after load_file is at 0
    assert editor.plain_edit.textCursor().position() == 0

    # Jump view down to entry
    editor.scroll_to_entry("- [2026-09-10 15:20] Jump target item", fallback_text="Jump target item")
    qapp.processEvents()

    # Cursor position in raw edit view moved down to the item
    assert editor.plain_edit.textCursor().position() > 500
    editor.deleteLater()
    qapp.processEvents()



def test_main_window_init(qapp, tmp_path: Path):
    cfg = AppConfig(notes_dir=tmp_path, mode="hold", hotkey="Space", theme="dark")
    win = MainWindow(cfg)
    assert win.windowTitle() == "Hey Whisper - Spoken Voice Notes"
    assert win.record_btn.isEnabled()
    assert win._current_mode == "hold"
    assert win._current_colors.is_dark is True
    win.shortcuts_manager.stop()
    win.close()
    win.deleteLater()
    qapp.processEvents()


def test_theme_toggle_and_application(qapp, tmp_path: Path):
    cfg = AppConfig(notes_dir=tmp_path, mode="hold", hotkey="Space", theme="light")
    win = MainWindow(cfg)
    assert win._current_colors.name == "light"

    # Apply dark theme
    win.apply_theme(DARK_THEME)
    assert win._current_colors.is_dark is True
    assert win.month_tree._current_colors.is_dark is True
    assert win.editor._colors.is_dark is True

    win.shortcuts_manager.stop()
    win.close()
    win.deleteLater()
    qapp.processEvents()


def test_global_shortcuts_signals(qapp, tmp_path: Path):
    import numpy as np
    cfg = AppConfig(notes_dir=tmp_path, mode="hold", hotkey="Space", theme="dark")
    win = MainWindow(cfg)

    # Mock audio recorder to decouple signal testing from audio hardware in headless CI
    def mock_start(silence_mode=False):
        win.recorder._is_recording = True
    def mock_stop():
        win.recorder._is_recording = False
        return np.zeros(0, dtype=np.float32)

    win.recorder.start_recording = mock_start
    win.recorder.stop_recording = mock_stop

    # Test portal ready update
    win._on_portal_ready(True, "Ctrl+Alt+R")
    assert win._global_trigger_info == "Ctrl+Alt+R"

    # Test hold mode activation and deactivation
    assert win.recorder.is_recording is False
    win._on_global_shortcut_activated("record_voice_note")
    assert win.recorder.is_recording is True

    win._on_global_shortcut_deactivated("record_voice_note")
    assert win.recorder.is_recording is False

    # Test toggle mode activation
    win._current_mode = "toggle"
    win._on_global_shortcut_activated("record_voice_note")
    assert win.recorder.is_recording is True
    win._on_global_shortcut_activated("record_voice_note")
    assert win.recorder.is_recording is False

    win.shortcuts_manager.stop()
    win.close()
    win.deleteLater()
    qapp.processEvents()


def test_settings_dialog_and_config_button(qapp, tmp_path: Path):
    from hey_whisper.gui.settings_dialog import SettingsDialog
    cfg = AppConfig(
        notes_dir=tmp_path,
        mode="hold",
        hotkey="Space",
        theme="light",
        config_file=tmp_path / "test_gui_settings.conf",
    )
    win = MainWindow(cfg)

    # Verify config button exists and has gear icon / tooltip
    assert win.config_btn is not None
    assert "Config" in win.config_btn.toolTip() or "Configure" in win.config_btn.toolTip()

    # Open and test SettingsDialog
    dlg = SettingsDialog(
        config=cfg,
        current_colors=win._current_colors,
        parent=None,
        global_trigger_info="Ctrl+Alt+R",
    )
    assert dlg.windowTitle() == "Hey Whisper - Configuration"

    # Change settings in dialog
    dlg.mode_combo.setCurrentIndex(1)  # toggle mode
    new_dir = tmp_path / "custom_notes"
    dlg.folder_edit.setText(str(new_dir))
    dlg.theme_combo.setCurrentIndex(1)  # dark

    # Test prefix configuration & preview
    assert dlg.prefix_edit is not None
    assert "Preview:" in dlg.prefix_preview_label.text()
    dlg.prefix_edit.setText("* [%H:%M]")
    assert "* [" in dlg.prefix_preview_label.text()

    # Apply changes
    dlg._save_and_apply()
    assert cfg.mode == "toggle"
    assert cfg.notes_dir == new_dir.resolve()
    assert cfg.theme == "dark"
    assert cfg.note_prefix == "* [%H:%M]"

    # Pass new config to MainWindow
    win._on_settings_applied(cfg)
    assert win._current_mode == "toggle"
    assert win.config.notes_dir == new_dir.resolve()
    assert win.config.note_prefix == "* [%H:%M]"
    assert win._current_colors.is_dark is True

    dlg.deleteLater()
    win.shortcuts_manager.stop()
    win.close()
    win.deleteLater()
    qapp.processEvents()



