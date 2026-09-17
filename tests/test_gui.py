"""Tests for GUI components using Qt offscreen platform."""

import os
from pathlib import Path
from unittest.mock import MagicMock
try:
    import pytest
except ImportError:
    pytest = None
from PyQt6.QtCore import Qt
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

    @pytest.fixture(autouse=True)
    def _no_real_vulkan_probe(monkeypatch):
        """Every SettingsDialog spawns a real VulkanProbeWorker background QThread that
        shells out to vulkaninfo/whisper-cli. Left unmocked, tests that construct a
        dialog and return without pumping the event loop to completion can still have
        that thread alive when the pytest process exits, racing interpreter shutdown
        and crashing the process (self.finished.emit() on a QThread whose Python-level
        signal bindings are already being torn down). Stubbing it out makes the worker
        finish essentially instantly, closing that race, and keeps GUI tests from
        depending on real system state in the first place.
        """
        from hey_whisper.transcriber import VulkanStatus

        fast_status = VulkanStatus(whisper_cli_found=False, detail="mocked for tests")
        monkeypatch.setattr(
            "hey_whisper.gui.settings_dialog.get_vulkan_status",
            lambda probe=True: fast_status,
        )
        yield



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


def test_open_settings_dialog_recreates_transcriber_on_model_change(qapp, tmp_path: Path):
    """Regression test: _open_settings_dialog must hand the dialog a config *copy*.

    SettingsDialog mutates its config in place and emits that same object; if
    MainWindow passed self.config directly, _on_settings_applied's old-vs-new
    comparison would always compare the object to its own already-updated
    fields, so a model/backend change would never rebuild the live Transcriber
    (it would silently only take effect after a restart).
    """
    cfg = AppConfig(notes_dir=tmp_path, model="base.en", backend="faster-whisper")
    win = MainWindow(cfg)
    original_transcriber = win.transcriber
    assert win.config.model == "base.en"

    from hey_whisper.gui.settings_dialog import SettingsDialog

    opened_dialog = {}
    original_exec = SettingsDialog.exec

    def fake_exec(self):
        opened_dialog["dlg"] = self
        # Simulate the user picking a different model, then Save & Apply.
        self.active_model_combo.setCurrentText("small.en")
        self._save_and_apply()
        return 1

    SettingsDialog.exec = fake_exec
    try:
        win._open_settings_dialog()
    finally:
        SettingsDialog.exec = original_exec

    dlg = opened_dialog["dlg"]
    assert dlg.config is not cfg, "SettingsDialog must receive a copy of the live config"
    assert win.config.model == "small.en"
    assert win.transcriber is not original_transcriber
    assert win.transcriber.model_name == "small.en"

    win.shortcuts_manager.stop()
    win.close()
    win.deleteLater()
    qapp.processEvents()


def test_save_and_apply_skips_modal_when_save_fails_headless(qapp, tmp_path: Path, monkeypatch):
    """A failed save must not pop a blocking QMessageBox under the offscreen/CI platform.

    test_gui.py forces QT_QPA_PLATFORM=offscreen for the whole module; a real,
    undismissable modal here would hang this (and any CI) test run rather than
    just failing it.
    """
    from hey_whisper.gui.settings_dialog import SettingsDialog

    assert qapp.platformName() == "offscreen"

    cfg = AppConfig(notes_dir=tmp_path, config_file=tmp_path / "unwritable.conf")
    dlg = SettingsDialog(config=cfg, current_colors=get_theme_colors("light")[1])

    def raise_save_error(_config):
        raise OSError("simulated disk write failure")

    monkeypatch.setattr("hey_whisper.gui.settings_dialog.save_config", raise_save_error)

    dlg._save_and_apply()  # must return promptly, not block on a modal dialog

    dlg.deleteLater()
    qapp.processEvents()


def test_settings_dialog_unified_model_list(qapp, tmp_path, monkeypatch):
    """Whisper and NVIDIA models share one list, base.en is flagged default, and delete works."""
    from hey_whisper.gui.settings_dialog import SettingsDialog
    from hey_whisper import transcriber as t

    ggml_cache = tmp_path / "ggml"
    ggml_cache.mkdir()
    monkeypatch.setattr(t, "CACHE_DIR", ggml_cache)
    (ggml_cache / "ggml-base.en.bin").write_bytes(b"0" * 2_000_000)

    empty_cache_info = MagicMock()
    empty_cache_info.repos = []
    monkeypatch.setattr("huggingface_hub.scan_cache_dir", lambda cache_dir=None: empty_cache_info)

    cfg = AppConfig(notes_dir=tmp_path, model="base.en")
    _, colors = get_theme_colors("light")
    dlg = SettingsDialog(config=cfg, current_colors=colors)

    def find_item(kind: str, name: str):
        for row in range(dlg.model_list.count()):
            item = dlg.model_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == (kind, name):
                return item
        return None

    # Both engines' section headers are present as non-selectable rows.
    header_texts = [
        dlg.model_list.item(row).text()
        for row in range(dlg.model_list.count())
        if not (dlg.model_list.item(row).flags() & Qt.ItemFlag.ItemIsSelectable)
    ]
    assert any("Whisper" in h for h in header_texts)
    assert any("Parakeet" in h for h in header_texts)

    # A NVIDIA model is selectable in the same list as the Whisper models.
    assert find_item("nemo", "nemo-parakeet-tdt-0.6b-v3") is not None

    base_en_item = find_item("ggml", "base.en")
    assert base_en_item is not None
    assert "(default)" in base_en_item.text()
    assert "[active]" in base_en_item.text()
    assert "✓" in base_en_item.text()

    # Deleting the selected downloaded model removes it via the unified Delete button.
    dlg.model_list.setCurrentItem(base_en_item)
    assert dlg.delete_model_btn.isEnabled()
    dlg._delete_selected_model()

    refreshed = find_item("ggml", "base.en")
    assert "not downloaded" in refreshed.text()
    assert not (ggml_cache / "ggml-base.en.bin").exists()

    dlg.deleteLater()
    qapp.processEvents()



