"""Tests for icon generation and window/desktop icon support."""

import os
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from hey_whisper.gui.icons import (
    get_app_icon,
    create_mic_icon,
    create_stop_icon,
    create_gear_icon,
    create_save_icon,
    create_calendar_icon,
    create_folder_icon,
    create_document_icon,
    create_pin_icon,
    create_edit_icon,
    create_preview_icon,
    create_check_icon,
    create_keyboard_icon,
)


def test_app_icon_non_null():
    app = QApplication.instance() or QApplication(["test"])
    icon = get_app_icon()
    assert not icon.isNull()
    pix = icon.pixmap(64, 64)
    assert not pix.isNull()
    assert pix.width() == 64
    assert pix.height() == 64


def test_all_control_icons_non_null():
    app = QApplication.instance() or QApplication(["test"])
    icon_funcs = [
        create_mic_icon,
        create_stop_icon,
        create_gear_icon,
        create_save_icon,
        create_calendar_icon,
        create_folder_icon,
        create_document_icon,
        create_pin_icon,
        create_edit_icon,
        create_preview_icon,
        create_check_icon,
        create_keyboard_icon,
    ]

    for fn in icon_funcs:
        ic = fn()
        assert isinstance(ic, QIcon)
        assert not ic.isNull()
        pix = ic.pixmap(24, 24)
        assert not pix.isNull()
