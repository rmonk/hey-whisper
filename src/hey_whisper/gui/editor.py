"""Markdown file reader and editor with rendered preview and syntax styling."""

from pathlib import Path
import re
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QFont,
    QSyntaxHighlighter,
    QTextCharFormat,
    QColor,
    QTextCursor,
    QTextDocument,
)
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabWidget,
    QPlainTextEdit,
    QTextEdit,
)

from hey_whisper.gui.theme import ThemeColors, LIGHT_THEME, get_preview_html_styles


class MarkdownHighlighter(QSyntaxHighlighter):
    """Syntax highlighter for Markdown notes supporting light and dark themes."""

    def __init__(self, parent=None, colors: ThemeColors = LIGHT_THEME):
        super().__init__(parent)
        self.rules = []
        self.update_theme(colors)

    def update_theme(self, colors: ThemeColors):
        """Update syntax highlighting colors to match active theme."""
        self.rules = []

        # Headers (# 2026-09-09)
        header_format = QTextCharFormat()
        header_format.setFontWeight(QFont.Weight.Bold)
        header_format.setFontPointSize(13)
        header_format.setForeground(QColor(colors.syntax_header))
        self.rules.append((re.compile(r"^#+\s+.*$", re.MULTILINE), header_format))

        # Timestamps [- [YYYY-MM-DD HH:MM TZ]]
        ts_format = QTextCharFormat()
        ts_format.setFontWeight(QFont.Weight.Bold)
        ts_format.setForeground(QColor(colors.syntax_timestamp))
        self.rules.append((re.compile(r"\[\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}\s+[^\]]+\]"), ts_format))

        # Bullets (- )
        bullet_format = QTextCharFormat()
        bullet_format.setFontWeight(QFont.Weight.Bold)
        bullet_format.setForeground(QColor(colors.syntax_bullet))
        self.rules.append((re.compile(r"^\s*-\s+", re.MULTILINE), bullet_format))

        self.rehighlight()

    def highlightBlock(self, text: str):
        for pattern, fmt in self.rules:
            for match in pattern.finditer(text):
                start = match.start()
                length = match.end() - start
                self.setFormat(start, length, fmt)


class MarkdownEditorWidget(QWidget):
    """Widget containing Markdown raw editor and rendered reader."""

    content_saved = pyqtSignal(Path)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_file: Optional[Path] = None
        self._is_modified = False
        self._colors: ThemeColors = LIGHT_THEME

        self._init_ui()

        # Auto-save timer (debounced 1.5s after editing)
        self._auto_save_timer = QTimer(self)
        self._auto_save_timer.setSingleShot(True)
        self._auto_save_timer.setInterval(1500)
        self._auto_save_timer.timeout.connect(self.save)

        self.apply_theme(LIGHT_THEME)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        # Top Bar
        top_bar = QHBoxLayout()
        self.file_label = QLabel("No file selected")
        self.file_label.setFont(QFont("Sans-Serif", 11, QFont.Weight.Bold))

        self.status_label = QLabel("")
        self.status_label.setFont(QFont("Sans-Serif", 10))

        self.save_btn = QPushButton("Save")
        self.save_btn.clicked.connect(self.save)
        self.save_btn.setEnabled(False)

        top_bar.addWidget(self.file_label)
        top_bar.addStretch()
        top_bar.addWidget(self.status_label)
        top_bar.addWidget(self.save_btn)
        layout.addLayout(top_bar)

        # Tab Widget for Edit vs Preview
        self.tabs = QTabWidget()

        # Edit View
        self.plain_edit = QPlainTextEdit()
        font = QFont("Monospace", 11)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.plain_edit.setFont(font)
        self.plain_edit.textChanged.connect(self._on_text_changed)
        self.highlighter = MarkdownHighlighter(self.plain_edit.document(), self._colors)
        self.tabs.addTab(self.plain_edit, "✏️ Edit (Raw)")

        # Preview View (Rendered Markdown)
        self.preview_edit = QTextEdit()
        self.preview_edit.setReadOnly(True)
        preview_font = QFont("Sans-Serif", 11)
        self.preview_edit.setFont(preview_font)
        self.tabs.addTab(self.preview_edit, "📖 Preview (Rendered)")

        self.tabs.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self.tabs)

    def apply_theme(self, colors: ThemeColors):
        """Update editor styling, colors, and syntax highlighting."""
        self._colors = colors

        self.file_label.setStyleSheet(f"color: {colors.text_primary}; font-weight: bold;")
        self.status_label.setStyleSheet(f"color: {colors.text_secondary}; font-size: 12px;")

        self.save_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.save_btn_bg};
                color: #ffffff;
                font-weight: bold;
                border: 1px solid {colors.border};
                border-radius: 4px;
                padding: 4px 14px;
            }}
            QPushButton:hover {{
                background-color: {colors.save_btn_hover};
            }}
            QPushButton:disabled {{
                background-color: {colors.save_btn_disabled};
                color: {colors.text_muted};
                border: 1px solid {colors.border_muted};
            }}
        """)

        self.tabs.setStyleSheet(f"""
            QTabWidget::pane {{
                border: 1px solid {colors.border};
                border-radius: 6px;
                background-color: {colors.card_bg};
            }}
            QTabBar::tab {{
                padding: 6px 16px;
                font-size: 13px;
                font-weight: 500;
                color: {colors.text_secondary};
                background-color: {colors.window_bg};
                border: 1px solid {colors.border};
                border-bottom: none;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                margin-right: 2px;
            }}
            QTabBar::tab:selected {{
                font-weight: bold;
                color: {colors.tab_active_indicator};
                background-color: {colors.card_bg};
                border-bottom: 2px solid {colors.tab_active_indicator};
            }}
        """)

        self.plain_edit.setStyleSheet(f"""
            QPlainTextEdit {{
                background-color: {colors.card_bg};
                color: {colors.text_primary};
                border: none;
                border-radius: 6px;
                padding: 8px;
                selection-background-color: {colors.tree_selected_bg};
                selection-color: {colors.tree_selected_text};
            }}
        """)

        self.preview_edit.setStyleSheet(f"""
            QTextEdit {{
                background-color: {colors.card_bg};
                color: {colors.text_primary};
                border: none;
                border-radius: 6px;
                padding: 12px;
                selection-background-color: {colors.tree_selected_bg};
                selection-color: {colors.tree_selected_text};
            }}
        """)

        self.preview_edit.document().setDefaultStyleSheet(get_preview_html_styles(colors))
        self.highlighter.update_theme(colors)

        # Re-render preview if loaded
        if self._current_file:
            self._update_preview(self.plain_edit.toPlainText())

    def load_file(self, file_path: Path):
        """Load markdown file into editor and preview."""
        if self._is_modified:
            self.save()

        self._current_file = file_path
        self.file_label.setText(file_path.name)
        self.file_label.setToolTip(str(file_path))

        if file_path.is_file():
            content = file_path.read_text(encoding="utf-8", errors="replace")
        else:
            content = ""

        # Block signals while loading to prevent triggering auto-save
        self.plain_edit.blockSignals(True)
        self.plain_edit.setPlainText(content)
        self.plain_edit.blockSignals(False)

        self._update_preview(content)
        self._is_modified = False
        self.save_btn.setEnabled(False)
        self.status_label.setText("Loaded")

    def _update_preview(self, content: str):
        """Update rendered markdown in preview tab."""
        self.preview_edit.document().setDefaultStyleSheet(get_preview_html_styles(self._colors))
        self.preview_edit.setMarkdown(content)

    def _on_text_changed(self):
        if self._current_file is None:
            return
        self._is_modified = True
        self.save_btn.setEnabled(True)
        self.status_label.setText("Modified • Auto-saving...")
        self._auto_save_timer.start()

    def _on_tab_changed(self, index: int):
        if index == 1:  # Switched to preview tab
            val = self.plain_edit.verticalScrollBar().value()
            max_val = max(1, self.plain_edit.verticalScrollBar().maximum())
            ratio = val / max_val
            self._update_preview(self.plain_edit.toPlainText())
            self.preview_edit.verticalScrollBar().setValue(
                int(ratio * self.preview_edit.verticalScrollBar().maximum())
            )
        elif index == 0:  # Switched to edit tab
            val = self.preview_edit.verticalScrollBar().value()
            max_val = max(1, self.preview_edit.verticalScrollBar().maximum())
            ratio = val / max_val
            self.plain_edit.verticalScrollBar().setValue(
                int(ratio * self.plain_edit.verticalScrollBar().maximum())
            )

    def save(self):
        """Save changes to disk."""
        if not self._current_file:
            return

        content = self.plain_edit.toPlainText()
        try:
            self._current_file.write_text(content, encoding="utf-8")
            self._is_modified = False
            self.save_btn.setEnabled(False)
            self.status_label.setText("Saved")
            self._update_preview(content)
            self.content_saved.emit(self._current_file)
        except Exception as e:
            self.status_label.setText(f"Error saving: {e}")

    def _ensure_views_scrolled(self):
        """Deferred check ensuring active cursor is centered and visible in viewports."""
        self.plain_edit.ensureCursorVisible()
        self.preview_edit.ensureCursorVisible()

    def scroll_to_day(self, day_str: str):
        """Move cursor to specified day header in editor and preview."""
        target_header = f"# {day_str}"
        content = self.plain_edit.toPlainText()
        idx = content.find(target_header)
        if idx != -1:
            cursor = self.plain_edit.textCursor()
            cursor.setPosition(idx)
            self.plain_edit.setTextCursor(cursor)
            self.plain_edit.centerCursor()
            self.plain_edit.ensureCursorVisible()

        # Also scroll preview
        cursor = self.preview_edit.textCursor()
        doc = self.preview_edit.document()
        found = doc.find(day_str)
        if not found.isNull():
            self.preview_edit.setTextCursor(found)
            self.preview_edit.ensureCursorVisible()

        QTimer.singleShot(50, self._ensure_views_scrolled)

    def scroll_to_entry(self, entry_text: str, fallback_text: Optional[str] = None):
        """Jump cursor and viewport down to newly appended markdown item."""
        content = self.plain_edit.toPlainText()
        if not content:
            return

        candidates = []
        if entry_text:
            cleaned_entry = entry_text.strip()
            if cleaned_entry:
                candidates.append(cleaned_entry)
                # Strip leading markdown bullet markers like '- ' or '* '
                no_bullet = re.sub(r"^(\s*[-*+]|\s*\d+\.|\s*>)\s*", "", cleaned_entry).strip()
                if no_bullet and no_bullet not in candidates:
                    candidates.append(no_bullet)

        if fallback_text:
            cleaned_fallback = fallback_text.strip()
            if cleaned_fallback and cleaned_fallback not in candidates:
                candidates.append(cleaned_fallback)
                if len(cleaned_fallback) > 30:
                    candidates.append(cleaned_fallback[:30])

        # 1. Scroll raw plain_edit to the item
        found_pos = -1
        for cand in candidates:
            pos = content.rfind(cand)
            if pos != -1:
                found_pos = pos
                break

        if found_pos != -1:
            cursor = self.plain_edit.textCursor()
            cursor.setPosition(found_pos)
            self.plain_edit.setTextCursor(cursor)
            self.plain_edit.centerCursor()
            self.plain_edit.ensureCursorVisible()
        else:
            self.plain_edit.moveCursor(QTextCursor.MoveOperation.End)
            self.plain_edit.centerCursor()
            self.plain_edit.ensureCursorVisible()

        # 2. Scroll rendered preview_edit to the item
        doc = self.preview_edit.document()
        preview_cursor = None
        for cand in candidates:
            end_cursor = QTextCursor(doc)
            end_cursor.movePosition(QTextCursor.MoveOperation.End)
            match = doc.find(cand, end_cursor, QTextDocument.FindFlag.FindBackward)
            if not match.isNull():
                preview_cursor = match
                break

        if preview_cursor and not preview_cursor.isNull():
            self.preview_edit.setTextCursor(preview_cursor)
            self.preview_edit.ensureCursorVisible()
        else:
            cursor = self.preview_edit.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self.preview_edit.setTextCursor(cursor)
            self.preview_edit.ensureCursorVisible()

        QTimer.singleShot(50, self._ensure_views_scrolled)
