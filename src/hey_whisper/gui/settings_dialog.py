"""Configuration dialog for Hey Whisper settings."""

import logging
from pathlib import Path
from typing import Optional, Callable

logger = logging.getLogger(__name__)

from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QDialogButtonBox,
    QWidget,
)

from hey_whisper.config import AppConfig, save_config
from hey_whisper.storage import format_entry_line, DEFAULT_NOTE_PREFIX
from hey_whisper.gui.theme import ThemeColors
from hey_whisper.gui.icons import (
    get_app_icon,
    create_folder_icon,
    create_check_icon,
    create_keyboard_icon,
)


class SettingsDialog(QDialog):
    """Unified Settings Dialog for configuring Mode, Folder, Shortcuts, and Theme."""

    settings_applied = pyqtSignal(AppConfig)

    def __init__(
        self,
        config: AppConfig,
        current_colors: ThemeColors,
        parent: Optional[QWidget] = None,
        on_configure_global_hotkey: Optional[Callable[[], None]] = None,
        global_trigger_info: str = "Ctrl+Alt+R",
    ):
        super().__init__(parent)
        self.config = config
        self._colors = current_colors
        self.on_configure_global_hotkey = on_configure_global_hotkey
        self.global_trigger_info = global_trigger_info

        self.setWindowTitle("Hey Whisper - Configuration")
        self.setWindowIcon(get_app_icon())
        self.setMinimumWidth(560)
        self.setModal(True)

        self._init_ui()
        self.apply_theme(self._colors)

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(14)

        # 1. Recording Mode & Behavior Group
        mode_group = QGroupBox("Recording Behavior")
        mode_form = QFormLayout(mode_group)
        mode_form.setSpacing(10)

        self.mode_combo = QComboBox()
        self.mode_combo.addItems([
            "Hold (Push-to-Talk) - Default",
            "Toggle (Press to Start / Stop)",
            "Silence (Auto-stop after silence)",
        ])
        mode_map = {"hold": 0, "toggle": 1, "silence": 2}
        self.mode_combo.setCurrentIndex(mode_map.get(self.config.mode, 0))
        self.mode_combo.currentIndexChanged.connect(self._on_mode_combo_changed)
        mode_form.addRow("Trigger Mode:", self.mode_combo)

        self.silence_spin = QDoubleSpinBox()
        self.silence_spin.setRange(0.5, 15.0)
        self.silence_spin.setSingleStep(0.5)
        self.silence_spin.setSuffix(" seconds")
        self.silence_spin.setValue(self.config.silence_timeout)
        self.silence_label = QLabel("Silence Timeout:")
        mode_form.addRow(self.silence_label, self.silence_spin)

        # Show/hide silence spinbox based on mode
        self._on_mode_combo_changed(self.mode_combo.currentIndex())
        main_layout.addWidget(mode_group)

        # 2. Notes Storage Folder Group
        folder_group = QGroupBox("Notes Storage Location")
        folder_layout = QVBoxLayout(folder_group)
        folder_layout.setSpacing(8)

        folder_row = QHBoxLayout()
        self.folder_edit = QLineEdit(str(self.config.notes_dir))
        folder_row.addWidget(self.folder_edit)

        self.browse_btn = QPushButton(" Browse...")
        self.browse_btn.setIcon(create_folder_icon(size=14, color="#d29922"))
        self.browse_btn.setIconSize(QSize(14, 14))
        self.browse_btn.clicked.connect(self._browse_folder)
        folder_row.addWidget(self.browse_btn)

        folder_layout.addLayout(folder_row)
        folder_hint = QLabel("Weekly notes are saved here as spoken-notes-YYYY-MM-DD.md")
        folder_hint.setStyleSheet("font-size: 11px; opacity: 0.8;")
        folder_layout.addWidget(folder_hint)
        main_layout.addWidget(folder_group)

        # 3. Note Prefix & Timestamp Group
        prefix_group = QGroupBox("Note Prefix && Timestamp")
        prefix_layout = QVBoxLayout(prefix_group)
        prefix_layout.setSpacing(6)

        prefix_form = QFormLayout()
        prefix_form.setSpacing(8)

        self.prefix_edit = QLineEdit(self.config.note_prefix)
        self.prefix_edit.setPlaceholderText(DEFAULT_NOTE_PREFIX)
        self.prefix_edit.textChanged.connect(self._update_prefix_preview)
        prefix_form.addRow("Prefix Format:", self.prefix_edit)
        prefix_layout.addLayout(prefix_form)

        self.prefix_preview_label = QLabel()
        self.prefix_preview_label.setWordWrap(True)
        prefix_layout.addWidget(self.prefix_preview_label)

        prefix_hint = QLabel("Time variables: %Y=year, %m=month, %d=day, %H=hour, %M=minute, %S=second, %Z=timezone")
        prefix_hint.setWordWrap(True)
        prefix_hint.setStyleSheet("font-size: 11px; opacity: 0.8;")
        prefix_layout.addWidget(prefix_hint)

        self._update_prefix_preview()
        main_layout.addWidget(prefix_group)

        # 4. Hotkeys & Shortcuts Group
        hotkey_group = QGroupBox("Keyboard Shortcuts")
        hotkey_form = QFormLayout(hotkey_group)
        hotkey_form.setSpacing(10)

        # Global Hotkey
        global_row = QHBoxLayout()
        self.global_hotkey_label = QLabel(f"<b>{self.global_trigger_info}</b> (System-Wide via XDG Portal)")
        global_row.addWidget(self.global_hotkey_label)
        global_row.addStretch()

        if self.on_configure_global_hotkey:
            self.sys_shortcut_btn = QPushButton(" Configure in System...")
            self.sys_shortcut_btn.setIcon(create_keyboard_icon(size=14, color=self._colors.text_primary))
            self.sys_shortcut_btn.setIconSize(QSize(14, 14))
            self.sys_shortcut_btn.setToolTip("Open desktop environment shortcut settings (KDE / GNOME)")
            self.sys_shortcut_btn.clicked.connect(self.on_configure_global_hotkey)
            global_row.addWidget(self.sys_shortcut_btn)
        else:
            self.sys_shortcut_btn = None

        hotkey_form.addRow("Global Hotkey:", global_row)

        # In-App Hotkey
        self.hotkey_combo = QComboBox()
        self.hotkey_combo.addItems(["Space", "Ctrl+Alt+R", "F9", "F10", "F12"])
        if self.config.hotkey in ["Space", "Ctrl+Alt+R", "F9", "F10", "F12"]:
            self.hotkey_combo.setCurrentText(self.config.hotkey)
        else:
            self.hotkey_combo.addItem(self.config.hotkey)
            self.hotkey_combo.setCurrentText(self.config.hotkey)
        hotkey_form.addRow("In-App Hotkey:", self.hotkey_combo)
        main_layout.addWidget(hotkey_group)

        # 5. Appearance & Engine Group
        app_group = QGroupBox("Appearance && Engine")
        app_form = QFormLayout(app_group)
        app_form.setSpacing(10)

        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["Auto (Follow OS)", "Dark Theme", "Light Theme"])
        theme_map = {"auto": 0, "dark": 1, "light": 2}
        self.theme_combo.setCurrentIndex(theme_map.get(self.config.theme, 0))
        app_form.addRow("Color Theme:", self.theme_combo)

        self.backend_combo = QComboBox()
        self.backend_combo.addItems(["Auto (Vulkan GPU if available)", "Vulkan GPU Acceleration", "faster-whisper (CPU/CUDA)"])
        backend_map = {"auto": 0, "vulkan": 1, "faster-whisper": 2}
        self.backend_combo.setCurrentIndex(backend_map.get(self.config.backend, 0))
        app_form.addRow("Whisper Backend:", self.backend_combo)

        main_layout.addWidget(app_group)

        # 6. Dialog Buttons
        btn_box = QDialogButtonBox()
        self.save_btn = btn_box.addButton(" Save && Apply", QDialogButtonBox.ButtonRole.AcceptRole)
        self.save_btn.setIcon(create_check_icon(size=14, color="#ffffff"))
        self.save_btn.setIconSize(QSize(14, 14))
        self.cancel_btn = btn_box.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        btn_box.accepted.connect(self._save_and_apply)
        btn_box.rejected.connect(self.reject)
        main_layout.addWidget(btn_box)

    def _on_mode_combo_changed(self, index: int):
        is_silence = (index == 2)
        self.silence_spin.setVisible(is_silence)
        self.silence_label.setVisible(is_silence)

    def _browse_folder(self):
        chosen = QFileDialog.getExistingDirectory(self, "Select Notes Storage Directory", self.folder_edit.text())
        if chosen:
            self.folder_edit.setText(chosen)

    def _update_prefix_preview(self):
        tpl = self.prefix_edit.text().strip() or DEFAULT_NOTE_PREFIX
        preview = format_entry_line("Sample voice note transcribed here...", prefix_template=tpl)
        if hasattr(self, "_colors") and self._colors:
            self.prefix_preview_label.setText(
                f"<span style='color: {self._colors.text_secondary}; font-size: 11px;'>Preview: </span>"
                f"<span style='color: {self._colors.syntax_timestamp}; font-family: monospace; font-size: 11px;'>{preview}</span>"
            )
        else:
            self.prefix_preview_label.setText(f"Preview: {preview}")

    def _save_and_apply(self):
        # Update config fields
        modes = ["hold", "toggle", "silence"]
        self.config.mode = modes[self.mode_combo.currentIndex()]
        self.config.silence_timeout = float(self.silence_spin.value())
        self.config.notes_dir = Path(self.folder_edit.text().strip()).expanduser().resolve()
        self.config.note_prefix = self.prefix_edit.text().strip() or DEFAULT_NOTE_PREFIX
        self.config.hotkey = self.hotkey_combo.currentText()

        themes = ["auto", "dark", "light"]
        self.config.theme = themes[self.theme_combo.currentIndex()]

        backends = ["auto", "vulkan", "faster-whisper"]
        self.config.backend = backends[self.backend_combo.currentIndex()]

        # Persist to disk
        try:
            save_config(self.config)
        except Exception as e:
            logger.warning("Could not persist configuration to disk: %s", e)

        self.settings_applied.emit(self.config)
        self.accept()

    def apply_theme(self, colors: ThemeColors):
        """Apply light/dark colors to dialog widgets."""
        self._colors = colors
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {colors.window_bg};
                color: {colors.text_primary};
            }}
            QGroupBox {{
                background-color: {colors.card_bg};
                border: 1px solid {colors.border};
                border-radius: 6px;
                margin-top: 10px;
                padding-top: 14px;
                color: {colors.text_primary};
                font-weight: bold;
                font-size: 12px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 5px;
                color: {colors.accent};
            }}
            QLabel {{
                color: {colors.text_primary};
                font-size: 12px;
            }}
            QLineEdit, QComboBox, QDoubleSpinBox {{
                background-color: {colors.window_bg};
                color: {colors.text_primary};
                border: 1px solid {colors.border};
                border-radius: 4px;
                padding: 5px 8px;
                font-size: 12px;
            }}
            QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus {{
                border-color: {colors.accent};
            }}
            QPushButton {{
                background-color: {colors.surface_bg};
                color: {colors.text_primary};
                border: 1px solid {colors.border};
                border-radius: 5px;
                padding: 6px 14px;
                font-size: 12px;
                font-weight: 500;
            }}
            QPushButton:hover {{
                background-color: {colors.tree_hover_bg};
                border-color: {colors.accent};
            }}
            QPushButton:pressed {{
                background-color: {colors.border_muted};
            }}
        """)
        self.save_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.accent};
                color: #ffffff;
                font-weight: bold;
                border-radius: 5px;
                padding: 6px 16px;
            }}
            QPushButton:hover {{
                background-color: #2ea043 if {colors.is_dark} else #1f883d;
            }}
        """)
        if self.sys_shortcut_btn:
            self.sys_shortcut_btn.setIcon(create_keyboard_icon(size=14, color=colors.text_primary))
        self.save_btn.setIcon(create_check_icon(size=14, color="#ffffff"))
        self._update_prefix_preview()
