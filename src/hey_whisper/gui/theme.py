"""Theme management supporting automatic system detection, light, and dark modes."""

import math
from dataclasses import dataclass
from typing import Tuple

from PyQt6.QtCore import Qt, QPointF
from PyQt6.QtGui import QGuiApplication, QPalette, QPainter, QPixmap, QColor, QIcon
from PyQt6.QtWidgets import QApplication


@dataclass(frozen=True)
class ThemeColors:
    name: str
    is_dark: bool

    # Surfaces & Backgrounds
    window_bg: str
    surface_bg: str
    card_bg: str
    input_bg: str
    border: str
    border_muted: str

    # Text
    text_primary: str
    text_secondary: str
    text_muted: str

    # Accents & Buttons
    accent: str
    accent_hover: str
    accent_active: str
    accent_text: str

    # Record & Save buttons
    record_idle_bg: str
    record_idle_hover: str
    record_active_bg: str
    record_active_hover: str

    save_btn_bg: str
    save_btn_hover: str
    save_btn_disabled: str

    # Controls
    vu_meter_bg: str
    vu_meter_chunk: str
    tab_active_indicator: str
    tree_hover_bg: str
    tree_selected_bg: str
    tree_selected_text: str

    # Syntax Highlighting
    syntax_header: str
    syntax_timestamp: str
    syntax_bullet: str


LIGHT_THEME = ThemeColors(
    name="light",
    is_dark=False,
    window_bg="#f6f8fa",
    surface_bg="#ffffff",
    card_bg="#ffffff",
    input_bg="#ffffff",
    border="#d0d7de",
    border_muted="#e1e4e8",
    text_primary="#1f2328",
    text_secondary="#57606a",
    text_muted="#8c959f",
    accent="#0969da",
    accent_hover="#0856b3",
    accent_active="#07448e",
    accent_text="#ffffff",
    record_idle_bg="#0969da",
    record_idle_hover="#0856b3",
    record_active_bg="#cf222e",
    record_active_hover="#a40e26",
    save_btn_bg="#2da44e",
    save_btn_hover="#2c974b",
    save_btn_disabled="#94d3a2",
    vu_meter_bg="#eaeef2",
    vu_meter_chunk="#2da44e",
    tab_active_indicator="#0969da",
    tree_hover_bg="#eaeef2",
    tree_selected_bg="#0969da",
    tree_selected_text="#ffffff",
    syntax_header="#0969da",
    syntax_timestamp="#1a7f37",
    syntax_bullet="#8250df",
)


DARK_THEME = ThemeColors(
    name="dark",
    is_dark=True,
    window_bg="#161b22",
    surface_bg="#0d1117",
    card_bg="#0d1117",
    input_bg="#0d1117",
    border="#30363d",
    border_muted="#21262d",
    text_primary="#f0f6fc",
    text_secondary="#8b949e",
    text_muted="#6e7681",
    accent="#2f81f7",
    accent_hover="#388bfd",
    accent_active="#1f6feb",
    accent_text="#ffffff",
    record_idle_bg="#238636",
    record_idle_hover="#2ea043",
    record_active_bg="#da3633",
    record_active_hover="#b62324",
    save_btn_bg="#238636",
    save_btn_hover="#2ea043",
    save_btn_disabled="#21262d",
    vu_meter_bg="#21262d",
    vu_meter_chunk="#3fb950",
    tab_active_indicator="#58a6ff",
    tree_hover_bg="#21262d",
    tree_selected_bg="#1f6feb",
    tree_selected_text="#ffffff",
    syntax_header="#58a6ff",
    syntax_timestamp="#3fb950",
    syntax_bullet="#bc8cff",
)


def detect_system_is_dark() -> bool:
    """Detect whether OS / Qt is currently running in dark mode."""
    app = QGuiApplication.instance()
    if app:
        try:
            # Check Qt 6.5+ style hints colorScheme
            color_scheme = app.styleHints().colorScheme()
            if color_scheme == Qt.ColorScheme.Dark:
                return True
            if color_scheme == Qt.ColorScheme.Light:
                return False
        except Exception:
            pass

        # Fallback: check window background lightness in active palette
        palette = app.palette()
        win_lightness = palette.color(QPalette.ColorRole.Window).lightness()
        return win_lightness < 128

    return False


def get_theme_colors(theme_mode: str = "auto") -> Tuple[str, ThemeColors]:
    """Resolve theme_mode ('auto', 'light', 'dark') to effective ThemeColors."""
    mode = (theme_mode or "auto").lower().strip()
    if mode == "dark":
        return "dark", DARK_THEME
    if mode == "light":
        return "light", LIGHT_THEME

    # "auto": detect from system
    is_dark = detect_system_is_dark()
    return ("dark", DARK_THEME) if is_dark else ("light", LIGHT_THEME)


def get_preview_html_styles(colors: ThemeColors) -> str:
    """Generate default CSS styles for Markdown rendered view."""
    return f"""
        body {{
            background-color: {colors.surface_bg};
            color: {colors.text_primary};
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
            font-size: 14px;
            line-height: 1.6;
        }}
        h1 {{
            color: {colors.syntax_header};
            border-bottom: 1px solid {colors.border};
            padding-bottom: 6px;
            font-size: 18px;
            margin-top: 16px;
            margin-bottom: 10px;
        }}
        h2, h3, h4 {{
            color: {colors.syntax_header};
            margin-top: 14px;
            margin-bottom: 8px;
        }}
        p, li {{
            color: {colors.text_primary};
            margin-top: 4px;
            margin-bottom: 4px;
        }}
        strong {{
            color: {colors.syntax_timestamp};
        }}
        code {{
            background-color: {colors.border_muted};
            color: {colors.text_primary};
            padding: 2px 5px;
            border-radius: 4px;
            font-family: monospace;
        }}
    """


from hey_whisper.gui.icons import create_gear_icon  # noqa: F401
