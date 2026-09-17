"""Configuration dialog for Hey Whisper settings."""

import logging
from pathlib import Path
from typing import Optional, Callable, Tuple, Union

logger = logging.getLogger(__name__)

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize
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
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QTabWidget,
    QScrollArea,
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
from hey_whisper.transcriber import (
    KNOWN_GGML_MODELS,
    NEMO_ONNX_MODELS,
    ModelInfo,
    NemoModelInfo,
    VulkanStatus,
    delete_model,
    delete_nemo_model,
    download_nemo_model,
    get_ggml_model_path,
    get_vulkan_status,
    list_models,
    list_nemo_models,
)


def _format_size(size_bytes: Optional[int]) -> str:
    if not size_bytes:
        return ""
    mb = size_bytes / (1024 * 1024)
    if mb >= 1024:
        return f"{mb / 1024:.2f} GB"
    return f"{mb:.0f} MB"


class ModelDownloadWorker(QThread):
    """Background worker that downloads a GGML model without blocking the UI."""

    progress = pyqtSignal(int, int)
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, model_name: str):
        super().__init__()
        self.model_name = model_name

    def run(self):
        try:
            get_ggml_model_path(
                self.model_name,
                progress_callback=lambda done, total: self.progress.emit(done, total),
            )
            self.finished.emit(self.model_name)
        except Exception as e:
            self.error.emit(str(e))


class NemoDownloadWorker(QThread):
    """Background worker that downloads a Parakeet/Canary onnx-asr model without blocking the UI.

    Unlike ModelDownloadWorker, onnx-asr/huggingface_hub don't expose a simple byte-progress
    hook here, so callers should show an indeterminate progress indicator while this runs.
    """

    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, model_name: str):
        super().__init__()
        self.model_name = model_name

    def run(self):
        try:
            download_nemo_model(self.model_name)
            self.finished.emit(self.model_name)
        except Exception as e:
            self.error.emit(str(e))


class VulkanProbeWorker(QThread):
    """Background worker that checks Vulkan availability without blocking the UI."""

    finished = pyqtSignal(object)

    def run(self):
        try:
            status = get_vulkan_status(probe=True)
        except Exception as e:
            status = VulkanStatus(whisper_cli_found=False, detail=f"Vulkan check failed: {e}")
        self.finished.emit(status)


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
        self.setMinimumWidth(600)
        self.resize(600, 640)
        self.setModal(True)

        self._init_ui()
        self.apply_theme(self._colors)

    @staticmethod
    def _make_scroll_tab(content: QWidget) -> QScrollArea:
        """Wrap a tab page's content in a scroll area so the dialog's own
        height stays fixed no matter how many groups a tab ends up holding."""
        scroll = QScrollArea()
        scroll.setWidget(content)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        return scroll

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(14)

        self.tabs = QTabWidget()
        general_page = self._build_general_tab()
        engine_page = self._build_engine_tab()
        self.tabs.addTab(self._make_scroll_tab(general_page), "General")
        self.tabs.addTab(self._make_scroll_tab(engine_page), "Engine")
        main_layout.addWidget(self.tabs)

        # Dialog Buttons (shared across tabs)
        btn_box = QDialogButtonBox()
        self.save_btn = btn_box.addButton(" Save && Apply", QDialogButtonBox.ButtonRole.AcceptRole)
        self.save_btn.setIcon(create_check_icon(size=14, color="#ffffff"))
        self.save_btn.setIconSize(QSize(14, 14))
        self.cancel_btn = btn_box.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        btn_box.accepted.connect(self._save_and_apply)
        btn_box.rejected.connect(self.reject)
        main_layout.addWidget(btn_box)

    def _build_general_tab(self) -> QWidget:
        page = QWidget()
        main_layout = QVBoxLayout(page)
        main_layout.setContentsMargins(4, 4, 4, 4)
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

        # 4. Hotkeys, Shortcuts && Appearance Group
        hotkey_group = QGroupBox("Shortcuts && Appearance")
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

        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["Auto (Follow OS)", "Dark Theme", "Light Theme"])
        theme_map = {"auto": 0, "dark": 1, "light": 2}
        self.theme_combo.setCurrentIndex(theme_map.get(self.config.theme, 0))
        hotkey_form.addRow("Color Theme:", self.theme_combo)

        main_layout.addWidget(hotkey_group)
        main_layout.addStretch()
        return page

    def _build_engine_tab(self) -> QWidget:
        page = QWidget()
        main_layout = QVBoxLayout(page)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(14)

        # 1. Backend & Active Model Group
        app_group = QGroupBox("Backend && Active Model")
        app_form = QFormLayout(app_group)
        app_form.setSpacing(10)

        self.backend_combo = QComboBox()
        self.backend_combo.addItems([
            "Auto (Vulkan GPU if available)",
            "Vulkan GPU Acceleration",
            "faster-whisper (CPU/CUDA)",
            "NVIDIA Parakeet / Canary (onnx-asr)",
        ])
        backend_map = {"auto": 0, "vulkan": 1, "faster-whisper": 2, "nemo": 3}
        self.backend_combo.setCurrentIndex(backend_map.get(self.config.backend, 0))
        app_form.addRow("Whisper Backend:", self.backend_combo)

        known_model_names = KNOWN_GGML_MODELS + NEMO_ONNX_MODELS
        self.active_model_combo = QComboBox()
        self.active_model_combo.addItems(known_model_names)
        if self.config.model in known_model_names:
            self.active_model_combo.setCurrentText(self.config.model)
        else:
            self.active_model_combo.addItem(self.config.model)
            self.active_model_combo.setCurrentText(self.config.model)
        app_form.addRow("Active Model:", self.active_model_combo)

        main_layout.addWidget(app_group)

        # 2. Model Management Group (Whisper GGML + NVIDIA Parakeet/Canary, one list)
        models_group = QGroupBox("Models (Loaded / Available)")
        models_layout = QVBoxLayout(models_group)
        models_layout.setSpacing(8)

        self.model_list = QListWidget()
        self.model_list.setFixedHeight(220)
        self.model_list.currentRowChanged.connect(self._on_model_row_changed)
        models_layout.addWidget(self.model_list)

        self.model_download_progress = QProgressBar()
        self.model_download_progress.setRange(0, 100)
        self.model_download_progress.setVisible(False)
        models_layout.addWidget(self.model_download_progress)

        self.model_status_label = QLabel("")
        self.model_status_label.setWordWrap(True)
        models_layout.addWidget(self.model_status_label)

        model_btn_row = QHBoxLayout()
        model_btn_row.addStretch()

        self.download_model_btn = QPushButton("Download")
        self.download_model_btn.clicked.connect(self._download_selected_model)
        model_btn_row.addWidget(self.download_model_btn)

        self.delete_model_btn = QPushButton("Delete")
        self.delete_model_btn.clicked.connect(self._delete_selected_model)
        model_btn_row.addWidget(self.delete_model_btn)

        self.set_active_model_btn = QPushButton("Set Active")
        self.set_active_model_btn.clicked.connect(self._set_model_active)
        model_btn_row.addWidget(self.set_active_model_btn)

        models_layout.addLayout(model_btn_row)
        main_layout.addWidget(models_group)

        self._download_worker: Optional[Union[ModelDownloadWorker, NemoDownloadWorker]] = None
        self._refresh_model_list()

        # 3. Vulkan GPU Status Group
        vulkan_group = QGroupBox("Vulkan GPU Status")
        vulkan_layout = QVBoxLayout(vulkan_group)
        vulkan_layout.setSpacing(6)

        self.vulkan_status_label = QLabel("Checking Vulkan status...")
        self.vulkan_status_label.setWordWrap(True)
        vulkan_layout.addWidget(self.vulkan_status_label)

        self.vulkan_device_label = QLabel("")
        self.vulkan_device_label.setWordWrap(True)
        vulkan_layout.addWidget(self.vulkan_device_label)

        vulkan_btn_row = QHBoxLayout()
        vulkan_btn_row.addStretch()
        self.recheck_vulkan_btn = QPushButton("Re-check Vulkan")
        self.recheck_vulkan_btn.clicked.connect(self._check_vulkan_status)
        vulkan_btn_row.addWidget(self.recheck_vulkan_btn)
        vulkan_layout.addLayout(vulkan_btn_row)

        main_layout.addWidget(vulkan_group)

        self._vulkan_probe_worker: Optional[VulkanProbeWorker] = None
        self._check_vulkan_status()

        main_layout.addStretch()
        return page

    def _on_mode_combo_changed(self, index: int):
        is_silence = (index == 2)
        self.silence_spin.setVisible(is_silence)
        self.silence_label.setVisible(is_silence)

    def _browse_folder(self):
        chosen = QFileDialog.getExistingDirectory(self, "Select Notes Storage Directory", self.folder_edit.text())
        if chosen:
            self.folder_edit.setText(chosen)

    def _add_model_header(self, text: str):
        """Add a non-selectable section header row to the unified model list."""
        header = QListWidgetItem(text)
        header.setFlags(Qt.ItemFlag.NoItemFlags)
        self.model_list.addItem(header)

    def _add_model_item(self, kind: str, info: Union[ModelInfo, NemoModelInfo]):
        label = f"{'✓' if info.downloaded else '·'} {info.name}"
        if info.downloaded:
            label += f"  ({_format_size(info.size_bytes)})"
        else:
            label += "  — not downloaded"
        if kind == "ggml" and info.name == "base.en":
            label += "  (default)"
        if info.name == self.config.model:
            label += "  [active]"
        item = QListWidgetItem(label)
        item.setData(Qt.ItemDataRole.UserRole, (kind, info.name))
        self.model_list.addItem(item)
        if info.name == self.active_model_combo.currentText():
            self.model_list.setCurrentItem(item)

    def _refresh_model_list(self):
        """Repopulate the unified model list with current on-disk / cache download status."""
        self.model_list.blockSignals(True)
        self.model_list.clear()

        self._add_model_header("Whisper (Vulkan / faster-whisper)")
        for info in list_models():
            self._add_model_item("ggml", info)

        self._add_model_header("NVIDIA Parakeet && Canary (onnx-asr)")
        for info in list_nemo_models():
            self._add_model_item("nemo", info)

        self.model_list.blockSignals(False)
        self._on_model_row_changed(self.model_list.currentRow())

    def _selected_model_entry(self) -> Optional[Tuple[str, Union[ModelInfo, NemoModelInfo]]]:
        item = self.model_list.currentItem()
        if not item:
            return None
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return None
        kind, name = data
        infos = list_models() if kind == "ggml" else list_nemo_models()
        for info in infos:
            if info.name == name:
                return kind, info
        return None

    def _on_model_row_changed(self, _row: int):
        entry = self._selected_model_entry()
        busy = self._download_worker is not None
        if entry is None:
            self.model_status_label.setText("")
            self.download_model_btn.setEnabled(False)
            self.delete_model_btn.setEnabled(False)
            self.set_active_model_btn.setEnabled(False)
            return
        _kind, info = entry
        self.download_model_btn.setEnabled(not info.downloaded and not busy)
        self.delete_model_btn.setEnabled(info.downloaded and not busy)
        self.set_active_model_btn.setEnabled(not busy)
        if info.downloaded:
            self.model_status_label.setText(f"{info.name}: downloaded ({_format_size(info.size_bytes)})")
        else:
            self.model_status_label.setText(f"{info.name}: not downloaded")

    def _download_selected_model(self):
        entry = self._selected_model_entry()
        if entry is None or self._download_worker is not None:
            return
        kind, info = entry
        if info.downloaded:
            return

        self.download_model_btn.setEnabled(False)
        self.delete_model_btn.setEnabled(False)
        self.set_active_model_btn.setEnabled(False)
        self.model_download_progress.setVisible(True)

        if kind == "ggml":
            self.model_download_progress.setRange(0, 100)
            self.model_download_progress.setValue(0)
            self.model_status_label.setText(f"Downloading {info.name}...")
            worker: Union[ModelDownloadWorker, NemoDownloadWorker] = ModelDownloadWorker(info.name)
            worker.progress.connect(self._on_download_progress)
        else:
            self.model_download_progress.setRange(0, 0)  # indeterminate: no byte-level progress hook
            self.model_status_label.setText(f"Downloading {info.name}... (this can take a while for larger models)")
            worker = NemoDownloadWorker(info.name)

        worker.finished.connect(self._on_download_finished)
        worker.error.connect(self._on_download_error)
        self._download_worker = worker
        worker.start()

    def _on_download_progress(self, downloaded: int, total: int):
        if total > 0:
            pct = int(downloaded * 100 / total)
            self.model_download_progress.setValue(pct)
            self.model_status_label.setText(f"Downloading... {_format_size(downloaded)} / {_format_size(total)}")
        else:
            self.model_status_label.setText(f"Downloading... {_format_size(downloaded)}")

    def _on_download_finished(self, model_name: str):
        self._download_worker = None
        self.model_download_progress.setRange(0, 100)
        self.model_download_progress.setVisible(False)
        self._refresh_model_list()

    def _on_download_error(self, message: str):
        self._download_worker = None
        self.model_download_progress.setRange(0, 100)
        self.model_download_progress.setVisible(False)
        self.model_status_label.setText(f"Download failed: {message}")
        logger.warning("Model download failed: %s", message)
        self._on_model_row_changed(self.model_list.currentRow())

    def _delete_selected_model(self):
        entry = self._selected_model_entry()
        if entry is None:
            return
        kind, info = entry
        if not info.downloaded:
            return
        try:
            if kind == "ggml":
                delete_model(info.name)
            else:
                delete_nemo_model(info.name)
        except Exception as e:
            logger.warning("Could not delete model %s: %s", info.name, e)
            self.model_status_label.setText(f"Delete failed: {e}")
            return
        self._refresh_model_list()

    def _set_model_active(self):
        entry = self._selected_model_entry()
        if entry is None:
            return
        kind, info = entry
        if self.active_model_combo.findText(info.name) < 0:
            self.active_model_combo.addItem(info.name)
        self.active_model_combo.setCurrentText(info.name)
        if kind == "nemo":
            self.backend_combo.setCurrentIndex(3)  # nemo
        elif self.backend_combo.currentIndex() == 3:
            # A GGML model can't run on the nemo backend; fall back to auto-detection.
            self.backend_combo.setCurrentIndex(0)
        self._refresh_model_list()

    def _check_vulkan_status(self):
        if self._vulkan_probe_worker is not None:
            return
        self.recheck_vulkan_btn.setEnabled(False)
        self.vulkan_status_label.setText("Checking Vulkan status...")
        self.vulkan_device_label.setText("")

        worker = VulkanProbeWorker()
        worker.finished.connect(self._on_vulkan_status_ready)
        self._vulkan_probe_worker = worker
        worker.start()

    def _on_vulkan_status_ready(self, status: VulkanStatus):
        self._vulkan_probe_worker = None
        self.recheck_vulkan_btn.setEnabled(True)

        if not status.whisper_cli_found:
            self.vulkan_status_label.setText("Vulkan: whisper-cli not found — Vulkan backend unavailable")
        elif status.working:
            self.vulkan_status_label.setText("Vulkan: enabled and working")
        else:
            self.vulkan_status_label.setText(f"Vulkan: not confirmed — {status.detail}")

        device_lines = []
        if status.device_name:
            device_lines.append(f"In use: {status.device_name}")
        if status.system_devices:
            device_lines.append("System devices: " + ", ".join(status.system_devices))
        self.vulkan_device_label.setText("\n".join(device_lines))

    def _cleanup_workers(self):
        """Disconnect and stop any in-flight background workers before the dialog closes."""
        for attr in ("_download_worker", "_vulkan_probe_worker"):
            worker = getattr(self, attr, None)
            if worker is not None:
                try:
                    worker.finished.disconnect()
                except TypeError:
                    pass
                if worker.isRunning():
                    worker.terminate()
                    worker.wait(500)
                setattr(self, attr, None)

    def done(self, result: int):
        self._cleanup_workers()
        super().done(result)

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

        backends = ["auto", "vulkan", "faster-whisper", "nemo"]
        self.config.backend = backends[self.backend_combo.currentIndex()]

        self.config.model = self.active_model_combo.currentText().strip() or self.config.model

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
            QTabWidget::pane {{
                border: 1px solid {colors.border};
                border-radius: 6px;
                top: -1px;
            }}
            QTabBar::tab {{
                background-color: {colors.surface_bg};
                color: {colors.text_secondary};
                border: 1px solid {colors.border};
                border-bottom: none;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                padding: 7px 18px;
                font-size: 12px;
                font-weight: 500;
            }}
            QTabBar::tab:selected {{
                background-color: {colors.card_bg};
                color: {colors.accent};
                font-weight: bold;
            }}
            QTabBar::tab:hover:!selected {{
                background-color: {colors.tree_hover_bg};
            }}
            QScrollArea {{
                background-color: transparent;
                border: none;
            }}
            QScrollArea > QWidget > QWidget {{
                background-color: transparent;
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
