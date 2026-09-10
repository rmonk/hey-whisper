"""Left-side navigation tree grouping spoken notes by Year -> Month -> Weekly Files."""

import calendar
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QTreeWidget,
    QTreeWidgetItem,
    QMenu,
    QHeaderView,
)
from PyQt6.QtGui import QAction, QIcon

from hey_whisper.storage import (
    group_files_by_year_month,
    get_file_days,
    DATE_PATTERN,
)
from hey_whisper.gui.theme import ThemeColors, LIGHT_THEME


class MonthTreeWidget(QTreeWidget):
    """Tree view showing notes grouped by Month and Year."""

    file_selected = pyqtSignal(Path)
    day_selected = pyqtSignal(Path, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderLabels(["Notes by Month"])
        self.header().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.setAnimated(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self.itemClicked.connect(self._on_item_clicked)
        self._current_colors = LIGHT_THEME
        self.apply_theme(LIGHT_THEME)

        self._notes_dir: Optional[Path] = None

    def apply_theme(self, colors: ThemeColors):
        """Update tree widget styling for light or dark mode."""
        self._current_colors = colors
        self.setStyleSheet(f"""
            QTreeWidget {{
                border: 1px solid {colors.border};
                border-radius: 6px;
                padding: 4px;
                font-size: 13px;
                background-color: {colors.card_bg};
                color: {colors.text_primary};
            }}
            QTreeWidget::item {{
                padding: 5px;
                border-radius: 4px;
                color: {colors.text_primary};
            }}
            QTreeWidget::item:hover {{
                background-color: {colors.tree_hover_bg};
            }}
            QTreeWidget::item:selected {{
                background-color: {colors.tree_selected_bg};
                color: {colors.tree_selected_text};
            }}
            QHeaderView::section {{
                background-color: {colors.surface_bg};
                color: {colors.text_secondary};
                padding: 6px;
                border: none;
                border-bottom: 1px solid {colors.border};
                font-weight: bold;
                font-size: 12px;
            }}
        """)

    def refresh(self, notes_dir: Path, select_path: Optional[Path] = None):
        """Re-scan notes_dir and rebuild the tree."""
        self._notes_dir = notes_dir
        self.clear()

        grouped = group_files_by_year_month(notes_dir)
        now = datetime.now()
        current_year = now.year
        current_month = now.month

        selected_item: Optional[QTreeWidgetItem] = None

        # Sort years descending
        for year in sorted(grouped.keys(), reverse=True):
            year_item = QTreeWidgetItem(self, [f"📅 {year}"])
            year_item.setFlags(year_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            year_item.setData(0, Qt.ItemDataRole.UserRole, ("year", year))

            # Auto-expand current year
            if year == current_year:
                year_item.setExpanded(True)

            months_dict = grouped[year]
            # Sort months descending
            for month in sorted(months_dict.keys(), reverse=True):
                month_name = calendar.month_name[month]
                file_count = len(months_dict[month])
                month_item = QTreeWidgetItem(year_item, [f"📁 {month_name} ({file_count})"])
                month_item.setFlags(month_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                month_item.setData(0, Qt.ItemDataRole.UserRole, ("month", year, month))

                # Auto-expand current month
                if year == current_year and month == current_month:
                    month_item.setExpanded(True)

                for file_path in months_dict[month]:
                    # Format weekly file label
                    match = DATE_PATTERN.match(file_path.name)
                    if match:
                        try:
                            fdate = datetime.strptime(match.group(1), "%Y-%m-%d")
                            display_date = fdate.strftime("Week of %b %d")
                        except ValueError:
                            display_date = file_path.name
                    else:
                        display_date = file_path.name

                    file_item = QTreeWidgetItem(month_item, [f"📝 {display_date}"])
                    file_item.setToolTip(0, str(file_path))
                    file_item.setData(0, Qt.ItemDataRole.UserRole, ("file", file_path))

                    if select_path and file_path.resolve() == select_path.resolve():
                        selected_item = file_item

                    # Add day headers as children
                    days = get_file_days(file_path)
                    for day in days:
                        day_item = QTreeWidgetItem(file_item, [f"  📌 {day}"])
                        day_item.setData(0, Qt.ItemDataRole.UserRole, ("day", file_path, day))

        if selected_item:
            self.setCurrentItem(selected_item)
            self.scrollToItem(selected_item)

    def _on_item_clicked(self, item: QTreeWidgetItem, column: int):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return

        item_type = data[0]
        if item_type == "file":
            file_path = data[1]
            self.file_selected.emit(file_path)
        elif item_type == "day":
            file_path = data[1]
            day_str = data[2]
            self.day_selected.emit(file_path, day_str)

    def _show_context_menu(self, position):
        item = self.itemAt(position)
        if not item:
            return

        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data or data[0] not in ("file", "day"):
            return

        file_path: Path = data[1]
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background-color: {self._current_colors.surface_bg};
                color: {self._current_colors.text_primary};
                border: 1px solid {self._current_colors.border};
                border-radius: 6px;
                padding: 4px;
            }}
            QMenu::item {{
                padding: 6px 16px;
                border-radius: 4px;
            }}
            QMenu::item:selected {{
                background-color: {self._current_colors.tree_selected_bg};
                color: {self._current_colors.tree_selected_text};
            }}
        """)

        open_action = QAction("Open in External Viewer", self)
        open_action.triggered.connect(lambda: self._open_external(file_path))
        menu.addAction(open_action)

        copy_action = QAction("Copy File Path", self)
        copy_action.triggered.connect(lambda: self._copy_path(file_path))
        menu.addAction(copy_action)

        menu.exec(self.viewport().mapToGlobal(position))

    def _open_external(self, file_path: Path):
        import subprocess
        try:
            subprocess.Popen(["xdg-open", str(file_path)])
        except Exception:
            pass

    def _copy_path(self, file_path: Path):
        from PyQt6.QtWidgets import QApplication
        QApplication.clipboard().setText(str(file_path))
