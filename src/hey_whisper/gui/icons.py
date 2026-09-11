"""Dynamic crisp vector and pixmap icons for Hey Whisper.

Provides native theme-aware icons for buttons, tree items, tabs, and window icons
without relying on external system icon themes or missing emoji fonts.
"""

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QRectF, QPointF
from PyQt6.QtGui import (
    QIcon,
    QPixmap,
    QPainter,
    QColor,
    QPen,
    QPainterPath,
    QLinearGradient,
)


def get_app_icon() -> QIcon:
    """Load or generate the multi-resolution application icon."""
    icon = QIcon()

    # Search standard installed and local repo paths
    candidate_dirs = [
        Path("/app/share/icons/hicolor"),
        Path.home() / ".local/share/icons/hicolor",
        Path(__file__).parents[3] / "resources/icons",
        Path(__file__).parents[3],
    ]

    sizes = [16, 24, 32, 48, 64, 128, 256, 512]

    # Try loading pre-rendered PNGs
    loaded_any = False
    for base in candidate_dirs:
        for s in sizes:
            png_path = base / f"{s}x{s}" / "apps" / "org.heywhisper.HeyWhisper.png"
            if not png_path.exists():
                png_path = base / f"{s}x{s}" / "org.heywhisper.HeyWhisper.png"
            if png_path.exists():
                pix = QPixmap(str(png_path))
                if not pix.isNull():
                    icon.addPixmap(pix)
                    loaded_any = True

        # Try SVG
        svg_path = base / "scalable" / "apps" / "org.heywhisper.HeyWhisper.svg"
        if not svg_path.exists():
            svg_path = base / "org.heywhisper.HeyWhisper.svg"
        if svg_path.exists():
            svg_icon = QIcon(str(svg_path))
            if not svg_icon.isNull():
                for s in sizes:
                    icon.addPixmap(svg_icon.pixmap(s, s))
                loaded_any = True

    if not loaded_any or icon.isNull():
        # Fallback: dynamically draw the application squircle icon
        for s in sizes:
            icon.addPixmap(_draw_app_icon_pixmap(s))

    return icon


def _draw_app_icon_pixmap(size: int = 128) -> QPixmap:
    """Draw the Hey Whisper brand icon onto a transparent pixmap."""
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Background rounded squircle
    grad = QLinearGradient(0, 0, size, size)
    grad.setColorAt(0.0, QColor("#0969da"))
    grad.setColorAt(1.0, QColor("#1f2328"))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(grad)
    p.drawRoundedRect(
        QRectF(size * 0.0625, size * 0.0625, size * 0.875, size * 0.875),
        size * 0.22,
        size * 0.22,
    )

    # Sound waves
    wave_pen = QPen(QColor(84, 174, 255, 150), size * 0.035, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
    p.setPen(wave_pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawArc(QRectF(size * 0.22, size * 0.22, size * 0.56, size * 0.56), 0, 180 * 16)

    # Microphone capsule
    mic_grad = QLinearGradient(0, size * 0.25, 0, size * 0.6)
    mic_grad.setColorAt(0.0, QColor("#ffffff"))
    mic_grad.setColorAt(1.0, QColor("#ddf4ff"))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(mic_grad)
    p.drawRoundedRect(
        QRectF(size * 0.40, size * 0.25, size * 0.20, size * 0.35),
        size * 0.10,
        size * 0.10,
    )

    # Microphone U-stand
    stand_pen = QPen(QColor("#ffffff"), size * 0.042, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
    p.setPen(stand_pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawArc(QRectF(size * 0.34, size * 0.34, size * 0.32, size * 0.28), 0, -180 * 16)

    # Stem and base
    p.drawLine(QPointF(size * 0.5, size * 0.62), QPointF(size * 0.5, size * 0.74))
    p.drawLine(QPointF(size * 0.36, size * 0.74), QPointF(size * 0.64, size * 0.74))

    # Note accent
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#2da44e"))
    p.drawEllipse(QPointF(size * 0.67, size * 0.30), size * 0.035, size * 0.035)

    p.end()
    return pix


def create_mic_icon(size: int = 20, color: str = "#ffffff") -> QIcon:
    """Create a crisp microphone icon."""
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Capsule
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    p.drawRoundedRect(
        QRectF(size * 0.35, size * 0.12, size * 0.30, size * 0.48),
        size * 0.15,
        size * 0.15,
    )

    # Stand arc
    pen = QPen(QColor(color), max(1.5, size * 0.09), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawArc(QRectF(size * 0.22, size * 0.25, size * 0.56, size * 0.42), 0, -180 * 16)

    # Stem & base
    p.drawLine(QPointF(size * 0.5, size * 0.67), QPointF(size * 0.5, size * 0.85))
    p.drawLine(QPointF(size * 0.3, size * 0.85), QPointF(size * 0.7, size * 0.85))
    p.end()
    return QIcon(pix)


def create_stop_icon(size: int = 20, color: str = "#ffffff") -> QIcon:
    """Create a crisp stop recording square icon."""
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    p.drawRoundedRect(
        QRectF(size * 0.24, size * 0.24, size * 0.52, size * 0.52),
        size * 0.1,
        size * 0.1,
    )
    p.end()
    return QIcon(pix)


def create_gear_icon(size: int = 20, color: str = "#c9d1d9") -> QIcon:
    """Create a crisp configuration gear icon."""
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))

    cx, cy = size / 2.0, size / 2.0
    outer_r = size * 0.44
    inner_r = size * 0.30
    teeth = 8

    # Outer teeth
    for i in range(teeth):
        tooth_w = size * 0.16
        tooth_h = size * 0.22
        p.save()
        p.translate(cx, cy)
        p.rotate(i * (360 / teeth))
        p.drawRoundedRect(
            QRectF(-tooth_w / 2.0, -outer_r, tooth_w, tooth_h),
            1.0,
            1.0,
        )
        p.restore()

    # Main circle body
    p.drawEllipse(QPointF(cx, cy), inner_r, inner_r)

    # Center hole cutout
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
    p.drawEllipse(QPointF(cx, cy), size * 0.14, size * 0.14)
    p.end()
    return QIcon(pix)


def create_save_icon(size: int = 16, color: str = "#ffffff") -> QIcon:
    """Create a crisp save floppy icon."""
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    c = QColor(color)
    pen = QPen(c, 1.4)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    s = float(size)
    # Outer floppy body
    p.drawRoundedRect(QRectF(s * 0.15, s * 0.15, s * 0.70, s * 0.70), s * 0.08, s * 0.08)
    # Top shutter / metal slider
    p.setBrush(c)
    p.drawRect(QRectF(s * 0.32, s * 0.15, s * 0.36, s * 0.28))
    # Bottom label area
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRect(QRectF(s * 0.28, s * 0.52, s * 0.44, s * 0.33))
    p.end()
    return QIcon(pix)


def create_calendar_icon(size: int = 16, color: str = "#54aeff") -> QIcon:
    """Create a crisp calendar year icon."""
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))

    p.drawRoundedRect(
        QRectF(size * 0.15, size * 0.24, size * 0.70, size * 0.62),
        size * 0.08,
        size * 0.08,
    )
    # Ring loops
    p.drawRoundedRect(QRectF(size * 0.28, size * 0.12, size * 0.10, size * 0.20), size * 0.04, size * 0.04)
    p.drawRoundedRect(QRectF(size * 0.62, size * 0.12, size * 0.10, size * 0.20), size * 0.04, size * 0.04)

    # Header bar cutout
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
    p.drawRect(QRectF(size * 0.15, size * 0.42, size * 0.70, size * 0.08))
    p.end()
    return QIcon(pix)


def create_folder_icon(size: int = 16, color: str = "#d29922") -> QIcon:
    """Create a crisp directory folder icon."""
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))

    path = QPainterPath()
    path.moveTo(size * 0.14, size * 0.28)
    path.lineTo(size * 0.42, size * 0.28)
    path.lineTo(size * 0.52, size * 0.38)
    path.lineTo(size * 0.86, size * 0.38)
    path.lineTo(size * 0.86, size * 0.76)
    path.lineTo(size * 0.14, size * 0.76)
    path.closeSubpath()
    p.drawPath(path)
    p.end()
    return QIcon(pix)


def create_document_icon(size: int = 16, color: str = "#c9d1d9") -> QIcon:
    """Create a crisp markdown document file icon."""
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))

    p.drawRoundedRect(
        QRectF(size * 0.20, size * 0.14, size * 0.60, size * 0.72),
        size * 0.08,
        size * 0.08,
    )
    # Text line cutouts
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
    p.drawRect(QRectF(size * 0.32, size * 0.32, size * 0.36, size * 0.07))
    p.drawRect(QRectF(size * 0.32, size * 0.46, size * 0.36, size * 0.07))
    p.drawRect(QRectF(size * 0.32, size * 0.60, size * 0.24, size * 0.07))
    p.end()
    return QIcon(pix)


def create_pin_icon(size: int = 14, color: str = "#8b949e") -> QIcon:
    """Create a crisp pin day icon."""
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    p.drawEllipse(QPointF(size * 0.5, size * 0.34), size * 0.22, size * 0.22)

    p.setPen(QPen(QColor(color), max(1.5, size * 0.10), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawLine(QPointF(size * 0.5, size * 0.54), QPointF(size * 0.5, size * 0.84))
    p.end()
    return QIcon(pix)


def create_edit_icon(size: int = 16, color: str = "#c9d1d9") -> QIcon:
    """Create a crisp pencil edit icon for tab."""
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color), max(1.8, size * 0.13), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.drawLine(QPointF(size * 0.24, size * 0.76), QPointF(size * 0.76, size * 0.24))

    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    p.drawEllipse(QPointF(size * 0.78, size * 0.22), size * 0.12, size * 0.12)
    p.end()
    return QIcon(pix)


def create_preview_icon(size: int = 16, color: str = "#c9d1d9") -> QIcon:
    """Create a crisp book preview icon for tab."""
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color), max(1.5, size * 0.10), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)

    p.drawArc(QRectF(size * 0.16, size * 0.28, size * 0.34, size * 0.42), 0, 180 * 16)
    p.drawArc(QRectF(size * 0.50, size * 0.28, size * 0.34, size * 0.42), 0, 180 * 16)
    p.drawLine(QPointF(size * 0.50, size * 0.28), QPointF(size * 0.50, size * 0.76))
    p.end()
    return QIcon(pix)


def create_check_icon(size: int = 16, color: str = "#ffffff") -> QIcon:
    """Create a crisp checkmark icon."""
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color), max(2.0, size * 0.14), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.drawLine(QPointF(size * 0.22, size * 0.52), QPointF(size * 0.42, size * 0.72))
    p.drawLine(QPointF(size * 0.42, size * 0.72), QPointF(size * 0.78, size * 0.28))
    p.end()
    return QIcon(pix)


def create_keyboard_icon(size: int = 16, color: str = "#c9d1d9") -> QIcon:
    """Create a crisp keyboard shortcut icon."""
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))

    p.drawRoundedRect(
        QRectF(size * 0.15, size * 0.24, size * 0.70, size * 0.52),
        size * 0.08,
        size * 0.08,
    )
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
    p.drawRect(QRectF(size * 0.25, size * 0.36, size * 0.10, size * 0.10))
    p.drawRect(QRectF(size * 0.45, size * 0.36, size * 0.10, size * 0.10))
    p.drawRect(QRectF(size * 0.65, size * 0.36, size * 0.10, size * 0.10))
    p.drawRect(QRectF(size * 0.30, size * 0.54, size * 0.40, size * 0.08))
    p.end()
    return QIcon(pix)
