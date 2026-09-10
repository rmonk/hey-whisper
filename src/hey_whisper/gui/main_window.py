"""Main Window for Hey Whisper with month tree, editor, push-to-talk hotkey, theme, and unified settings dialog."""

from datetime import datetime
import logging
import os
from pathlib import Path
from typing import Optional
import numpy as np

logger = logging.getLogger(__name__)

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject, QEvent, QSize
from PyQt6.QtGui import QKeySequence, QKeyEvent, QIcon, QColor, QFont, QCloseEvent
from PyQt6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QSplitter,
    QPushButton,
    QLabel,
    QProgressBar,
    QMessageBox,
    QStatusBar,
    QApplication,
)

from hey_whisper.config import AppConfig, save_config
from hey_whisper.audio import AudioRecorder
from hey_whisper.transcriber import Transcriber
from hey_whisper.storage import (
    get_weekly_file_path,
    append_note,
    list_note_files,
)
from hey_whisper.gui.theme import (
    ThemeColors,
    get_theme_colors,
    LIGHT_THEME,
    DARK_THEME,
    create_gear_icon,
)
from hey_whisper.gui.month_tree import MonthTreeWidget
from hey_whisper.gui.editor import MarkdownEditorWidget
from hey_whisper.gui.shortcuts import PortalShortcutsManager
from hey_whisper.gui.settings_dialog import SettingsDialog


class AudioSignals(QObject):
    """Bridge for background audio callbacks to Qt main thread."""
    level_changed = pyqtSignal(float, float)
    silence_stopped = pyqtSignal()


class TranscribeWorker(QThread):
    """Background worker for whisper transcription."""

    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, transcriber: Transcriber, audio_data: np.ndarray):
        super().__init__()
        self.transcriber = transcriber
        self.audio_data = audio_data

    def run(self):
        try:
            text = self.transcriber.transcribe(self.audio_data)
            self.finished.emit(text)
        except Exception as e:
            self.error.emit(str(e))


class MainWindow(QMainWindow):
    """Main application window for Hey Whisper."""

    def __init__(self, config: AppConfig):
        super().__init__()
        self.config = config
        self.setWindowTitle("Hey Whisper - Spoken Voice Notes")
        self.resize(1050, 680)

        # Transcriber and Audio Engine
        self.transcriber = Transcriber(
            model_name=self.config.model,
            backend=self.config.backend,
            device=self.config.device,
            compute_type=self.config.compute_type,
            vulkan_device=self.config.vulkan_device,
        )

        self.audio_signals = AudioSignals()
        self.audio_signals.level_changed.connect(self._on_audio_level)
        self.audio_signals.silence_stopped.connect(self._on_silence_auto_stop)

        self.recorder = AudioRecorder(
            silence_timeout=self.config.silence_timeout,
            silence_threshold=self.config.silence_threshold,
            level_callback=lambda rms, peak: self.audio_signals.level_changed.emit(rms, peak),
            silence_stop_callback=lambda: self.audio_signals.silence_stopped.emit(),
        )

        self._hotkey_pressed = False
        self._current_mode = self.config.mode
        self._active_worker: Optional[TranscribeWorker] = None
        self._global_trigger_info = "Ctrl+Alt+R"

        # Theme resolution
        self._theme_mode = self.config.theme  # "auto", "light", "dark"
        _, self._current_colors = get_theme_colors(self._theme_mode)

        # System-Wide Global Shortcuts (XDG Desktop Portal)
        preferred_trigger = "Ctrl+Alt+R" if self.config.hotkey in ("Space", "SPACE") else self.config.hotkey
        self.shortcuts_manager = PortalShortcutsManager(self, preferred_trigger=preferred_trigger)
        self.shortcuts_manager.shortcut_activated.connect(self._on_global_shortcut_activated)
        self.shortcuts_manager.shortcut_deactivated.connect(self._on_global_shortcut_deactivated)
        self.shortcuts_manager.portal_ready.connect(self._on_portal_ready)
        self.shortcuts_manager.start()

        self._init_ui()
        self._setup_shortcuts()
        self.apply_theme(self._current_colors)
        self._load_initial_notes()

    def _init_ui(self):
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(12, 10, 12, 10)
        self.main_layout.setSpacing(10)

        # 1. Top Controls Bar: Clean layout with Record, Mic Meter, and Config Gear
        top_bar = QHBoxLayout()
        top_bar.setSpacing(12)

        # Record / Push-to-Talk Button
        self.record_btn = QPushButton("🎙️ Record")
        self.record_btn.setFixedHeight(42)
        self.record_btn.setFont(QFont("Sans-Serif", 11, QFont.Weight.Bold))
        self.record_btn.clicked.connect(self._on_record_btn_clicked)
        top_bar.addWidget(self.record_btn)

        # Audio VU Level Meter
        self.level_label = QLabel("Mic Level:")
        self.level_label.setFont(QFont("Sans-Serif", 10))
        top_bar.addWidget(self.level_label)

        self.vu_meter = QProgressBar()
        self.vu_meter.setRange(0, 5000)
        self.vu_meter.setValue(0)
        self.vu_meter.setTextVisible(False)
        self.vu_meter.setFixedWidth(130)
        self.vu_meter.setFixedHeight(20)
        top_bar.addWidget(self.vu_meter)

        top_bar.addStretch()

        # Configuration button with standard gear icon
        self.config_btn = QPushButton(" Config")
        gear_icon = QIcon.fromTheme("preferences-system")
        if gear_icon.isNull():
            gear_icon = QIcon.fromTheme("configure")
        if not gear_icon.isNull():
            self.config_btn.setIcon(gear_icon)
            self.config_btn.setIconSize(QSize(18, 18))
        else:
            self.config_btn.setText("⚙️ Config")

        self.config_btn.setFont(QFont("Sans-Serif", 10, QFont.Weight.Bold))
        self.config_btn.setToolTip("Configure settings (Mode, Folder, Shortcuts, Theme)")
        self.config_btn.clicked.connect(self._open_settings_dialog)
        top_bar.addWidget(self.config_btn)

        self.main_layout.addLayout(top_bar)

        # 2. Main Splitter: Month Tree on Left, Editor on Right
        self.splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left Month Tree
        self.month_tree = MonthTreeWidget()
        self.month_tree.file_selected.connect(self._on_file_selected)
        self.month_tree.day_selected.connect(self._on_day_selected)
        self.splitter.addWidget(self.month_tree)

        # Right Editor
        self.editor = MarkdownEditorWidget()
        self.editor.content_saved.connect(lambda p: self.month_tree.refresh(self.config.notes_dir, p))
        self.splitter.addWidget(self.editor)

        # 30% left, 70% right
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 7)
        self.main_layout.addWidget(self.splitter)

        # 3. Status Bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        backend_info = "Vulkan GPU" if self.transcriber.is_vulkan else "faster-whisper"
        self.status_bar.showMessage(f"Ready • Backend: {backend_info} • Notes: {self.config.notes_dir}")

    def apply_theme(self, colors: ThemeColors):
        """Apply theme colors across all controls and child widgets."""
        self._current_colors = colors

        # Central window styling
        self.central_widget.setStyleSheet(f"""
            QWidget {{
                background-color: {colors.window_bg};
                color: {colors.text_primary};
            }}
        """)

        self.level_label.setStyleSheet(f"color: {colors.text_secondary};")

        # Config Button styling & Icon
        self.config_btn.setIcon(create_gear_icon(size=20, color=colors.text_primary))
        self.config_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.card_bg};
                color: {colors.text_primary};
                border: 1px solid {colors.border};
                border-radius: 6px;
                padding: 7px 16px;
                font-size: 13px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {colors.tree_hover_bg};
                border-color: {colors.accent};
            }}
            QPushButton:pressed {{
                background-color: {colors.border_muted};
            }}
        """)

        # VU Meter
        self.vu_meter.setStyleSheet(f"""
            QProgressBar {{
                border: 1px solid {colors.border};
                border-radius: 4px;
                background-color: {colors.vu_meter_bg};
            }}
            QProgressBar::chunk {{
                background-color: {colors.vu_meter_chunk};
                border-radius: 3px;
            }}
        """)

        # Splitter
        self.splitter.setStyleSheet(f"""
            QSplitter::handle {{
                background-color: {colors.border};
            }}
        """)

        # Status Bar
        self.status_bar.setStyleSheet(f"""
            QStatusBar {{
                background-color: {colors.surface_bg};
                color: {colors.text_secondary};
                border-top: 1px solid {colors.border};
                font-size: 12px;
            }}
        """)

        # Apply to children
        self.month_tree.apply_theme(colors)
        self.editor.apply_theme(colors)

        # Update record button text and colors
        self._update_record_button_text()

    def _open_settings_dialog(self):
        """Open unified configuration dialog."""
        dlg = SettingsDialog(
            config=self.config,
            current_colors=self._current_colors,
            parent=self,
            on_configure_global_hotkey=self.shortcuts_manager.configure_shortcuts,
            global_trigger_info=self._global_trigger_info,
        )
        dlg.settings_applied.connect(self._on_settings_applied)
        dlg.exec()

    def _on_settings_applied(self, new_config: AppConfig):
        """Handle settings changes saved from SettingsDialog."""
        self.config = new_config
        self._current_mode = self.config.mode
        self.recorder.silence_timeout = self.config.silence_timeout
        self.recorder.silence_threshold = self.config.silence_threshold
        self._theme_mode = self.config.theme

        # Re-apply theme if changed
        _, colors = get_theme_colors(self._theme_mode)
        self.apply_theme(colors)

        # Refresh storage
        self.month_tree.refresh(self.config.notes_dir)
        self._load_initial_notes()
        self._update_record_button_text()
        self.status_bar.showMessage(f"Settings applied • Mode: {self._current_mode.capitalize()} • Notes: {self.config.notes_dir}")

    def changeEvent(self, event):
        """Detect OS system theme change when in auto mode."""
        if event.type() == QEvent.Type.PaletteChange and self._theme_mode == "auto":
            _, colors = get_theme_colors("auto")
            self.apply_theme(colors)
        super().changeEvent(event)

    def closeEvent(self, event: QCloseEvent):
        """Stop background worker and shortcuts listener before exiting."""
        if self._active_worker and self._active_worker.isRunning():
            self._active_worker.terminate()
            self._active_worker.wait(500)
        self.shortcuts_manager.stop()
        super().closeEvent(event)

    def close(self) -> bool:
        if self._active_worker and self._active_worker.isRunning():
            self._active_worker.terminate()
            self._active_worker.wait(500)
        self.shortcuts_manager.stop()
        return super().close()

    def _on_portal_ready(self, success: bool, trigger_info: str):
        """Update hotkey status when portal registration completes."""
        if success:
            self._global_trigger_info = trigger_info or "Ctrl+Alt+R"
            self.status_bar.showMessage(f"System-wide global hotkey active: {self._global_trigger_info}")
        else:
            self._global_trigger_info = "Disabled / Unsupported"

    def _on_global_shortcut_activated(self, shortcut_id: str):
        """Handle system-wide hotkey press from XDG Desktop Portal."""
        if self._current_mode == "hold":
            if not self.recorder.is_recording:
                self.start_capture()
        else:  # toggle or silence mode
            if self.recorder.is_recording:
                self.stop_capture_and_transcribe()
            else:
                self.start_capture()

    def _on_global_shortcut_deactivated(self, shortcut_id: str):
        """Handle system-wide hotkey release from XDG Desktop Portal (for hold-to-talk)."""
        if self._current_mode == "hold":
            if self.recorder.is_recording:
                self.stop_capture_and_transcribe()

    def _setup_shortcuts(self):
        """Install global event filter on application for in-window held-down hotkey."""
        QApplication.instance().installEventFilter(self)

    def eventFilter(self, obj, event):
        """Handle held-down hotkey and mouse events on record button within application window."""
        # Record button mouse events for hold mode
        if obj == self.record_btn and self._current_mode == "hold":
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self.start_capture()
                return True
            elif event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
                self.stop_capture_and_transcribe()
                return True

        # Key press / release for in-app held-down transcription hotkey
        if self._current_mode == "hold":
            hotkey_name = self.config.hotkey.upper()
            if event.type() == QEvent.Type.KeyPress and not event.isAutoRepeat():
                key_text = QKeySequence(event.key()).toString().upper()
                if key_text == hotkey_name or (hotkey_name == "SPACE" and event.key() == Qt.Key.Key_Space):
                    if self.editor.plain_edit.hasFocus() and hotkey_name == "SPACE":
                        return super().eventFilter(obj, event)

                    if not self._hotkey_pressed:
                        self._hotkey_pressed = True
                        self.start_capture()
                        return True

            elif event.type() == QEvent.Type.KeyRelease and not event.isAutoRepeat():
                key_text = QKeySequence(event.key()).toString().upper()
                if key_text == hotkey_name or (hotkey_name == "SPACE" and event.key() == Qt.Key.Key_Space):
                    if self._hotkey_pressed:
                        self._hotkey_pressed = False
                        self.stop_capture_and_transcribe()
                        return True

        return super().eventFilter(obj, event)

    def _update_record_button_text(self):
        colors = self._current_colors
        if self.recorder.is_recording:
            self.record_btn.setText("🔴 Recording... (Release/Click to End)")
            self.record_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {colors.record_active_bg};
                    color: #ffffff;
                    border: 1px solid {colors.record_active_hover};
                    border-radius: 6px;
                    padding: 6px 18px;
                }}
                QPushButton:hover {{
                    background-color: {colors.record_active_hover};
                }}
            """)
        else:
            if self._current_mode == "hold":
                self.record_btn.setText(f"🎙️ Hold to Record [{self.config.hotkey}]")
            elif self._current_mode == "toggle":
                self.record_btn.setText("🎙️ Click to Record")
            else:
                self.record_btn.setText("🎙️ Voice Detection (Click to Arm)")

            self.record_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {colors.record_idle_bg};
                    color: #ffffff;
                    border: 1px solid {colors.record_idle_hover};
                    border-radius: 6px;
                    padding: 6px 18px;
                }}
                QPushButton:hover {{
                    background-color: {colors.record_idle_hover};
                }}
            """)

    def _on_record_btn_clicked(self):
        if self._current_mode in ("toggle", "silence"):
            if self.recorder.is_recording:
                self.stop_capture_and_transcribe()
            else:
                self.start_capture()

    def start_capture(self):
        """Start microphone capture."""
        if self.recorder.is_recording:
            return

        silence_mode = (self._current_mode == "silence")
        try:
            self.recorder.start_recording(silence_mode=silence_mode)
            self._update_record_button_text()
            self.status_bar.showMessage("🔴 Recording audio from default microphone...")
        except Exception as e:
            self._show_error_dialog("Audio Error", f"Could not access microphone:\n{e}")

    def _show_error_dialog(self, title: str, message: str):
        """Display error dialog unless running headless in offscreen or CI mode."""
        self.status_bar.showMessage(f"❌ {title}: {message}")
        logger.error("%s: %s", title, message)
        app = QApplication.instance()
        if app and app.platformName() == "offscreen":
            return
        if os.environ.get("CI") or os.environ.get("QT_QPA_PLATFORM") == "offscreen":
            return
        QMessageBox.critical(self, title, message)

    def stop_capture_and_transcribe(self):
        """Stop microphone capture and launch background transcription."""
        if getattr(self, "_is_stopping", False) or not self.recorder.is_recording:
            return

        self._is_stopping = True
        try:
            audio_data = self.recorder.stop_recording()
            self.vu_meter.setValue(0)
            self._update_record_button_text()

            if len(audio_data) < int(16000 * 0.3):  # Less than 300ms
                self.status_bar.showMessage("Recording was too short to transcribe.")
                return

            backend_name = "Vulkan GPU" if self.transcriber.is_vulkan else "faster-whisper"
            self.status_bar.showMessage(f"⏳ Transcribing audio with {backend_name}...")
            self.record_btn.setEnabled(False)

            # Launch transcription thread
            self._active_worker = TranscribeWorker(self.transcriber, audio_data)
            self._active_worker.finished.connect(self._on_transcription_finished)
            self._active_worker.error.connect(self._on_transcription_error)
            self._active_worker.start()
        finally:
            self._is_stopping = False

    def _on_silence_auto_stop(self):
        """Called by audio detector when silence timeout is reached."""
        if self.recorder.is_recording:
            self.stop_capture_and_transcribe()

    def _on_transcription_finished(self, text: str):
        self.record_btn.setEnabled(True)
        self._update_record_button_text()

        if not text.strip():
            self.status_bar.showMessage("No speech recognized in recording.")
            return

        # Append to weekly markdown file
        try:
            target_file, entry_line = append_note(
                self.config.notes_dir,
                text,
                prefix_template=self.config.note_prefix,
            )
            self.status_bar.showMessage(f"✅ Saved note: \"{text[:60]}...\"")

            # Reload tree and editor
            self.month_tree.refresh(self.config.notes_dir, select_path=target_file)
            self.editor.load_file(target_file)
        except Exception as e:
            self._show_error_dialog("Storage Error", f"Failed to save note:\n{e}")

    def _on_transcription_error(self, err_msg: str):
        self.record_btn.setEnabled(True)
        self._update_record_button_text()
        self._show_error_dialog("Transcription Error", err_msg)

    def _on_audio_level(self, rms: float, peak: float):
        if self.recorder.is_recording:
            self.vu_meter.setValue(int(min(rms * 2, 5000)))

    def _on_file_selected(self, file_path: Path):
        self.editor.load_file(file_path)

    def _on_day_selected(self, file_path: Path, day_str: str):
        self.editor.load_file(file_path)
        self.editor.scroll_to_day(day_str)

    def _load_initial_notes(self):
        """Load the month tree and current weekly file on startup."""
        self.month_tree.refresh(self.config.notes_dir)

        # Check if weekly file exists or load latest
        current_weekly = get_weekly_file_path(self.config.notes_dir)
        if current_weekly.is_file():
            self.month_tree.refresh(self.config.notes_dir, select_path=current_weekly)
            self.editor.load_file(current_weekly)
        else:
            files = list_note_files(self.config.notes_dir)
            if files:
                self.month_tree.refresh(self.config.notes_dir, select_path=files[0])
                self.editor.load_file(files[0])
            else:
                self.editor.file_label.setText(f"New notes will be saved in: {self.config.notes_dir}")
