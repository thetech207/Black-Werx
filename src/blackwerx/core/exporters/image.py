"""PNG export via QImage/QPainter."""

from __future__ import annotations

from pathlib import Path

from .chart import build_chart, draw_chart, draw_symbol_chart, pattern_bounds
from ..model import Pattern


def export_png(pattern: Pattern, path: str | Path, *,
               cell: int = 24, style: str = "realistic",
               library_blocks: dict | None = None,
               symbol_style: str = "shapes",
               full_canvas: bool = False) -> Path:
    """style: 'realistic' | 'symbol'."""
    from PySide6.QtGui import QImage, QPainter

    items = build_chart(pattern, library_blocks, symbol_style)
    if not items:
        raise ValueError("pattern has no stitches to export")
    bounds = pattern_bounds(pattern, library_blocks, full_canvas)
    minx, miny, maxx, maxy = bounds
    w = int((maxx - minx + 1) * cell) + 40
    h = int((maxy - miny + 1) * cell) + 40
    # room for legend
    legend_rows = len({i.hex_color for i in items})
    h += legend_rows * 22 + 30

    img = QImage(w, h, QImage.Format.Format_ARGB32)
    img.fill(0xFFFFFFFF)
    painter = QPainter(img)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    ox, oy = 20.0, 20.0  # draw_* X() already offsets by -minx/-miny
    if style == "symbol":
        draw_symbol_chart(painter, items, cell, ox, oy, bounds=bounds)
        # legend
        from PySide6.QtGui import QColor, QFont
        painter.setFont(QFont("DejaVu Sans", 10))
        ly = oy + (maxy - miny + 1) * cell + 25
        from .. import palette as _pal
        seen = {}
        for it in items:
            seen.setdefault(it.hex_color,
                            (_pal.dmc_name(it.color_spec) or it.hex_color,
                             it.symbol))
        for i, (hexcol, (name, sym)) in enumerate(seen.items()):
            painter.setPen(QColor(hexcol))
            painter.drawText(30, ly + i * 20, f"{sym}  {name}")
    else:
        draw_chart(painter, items, cell, ox, oy, realistic=True,
                   bounds=bounds)
    painter.end()

    path = Path(path)
    if path.suffix.lower() != ".png":
        path = path.with_suffix(".png")
    img.save(str(path))
    return path
