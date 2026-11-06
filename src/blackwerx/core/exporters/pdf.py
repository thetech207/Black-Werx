"""PDF export via QPdfWriter/QPainter."""

from __future__ import annotations

from pathlib import Path

from .chart import build_chart, draw_chart, draw_symbol_chart, pattern_bounds
from ..model import Pattern


def export_pdf(pattern: Pattern, path: str | Path, *,
               style: str = "symbol", library_blocks: dict | None = None,
               cell: float = 14.0) -> Path:
    """Render chart (symbol) or realistic view to a PDF page sized to fit."""
    from PySide6.QtGui import QPageLayout, QPageSize, QPdfWriter, QPainter
    from PySide6.QtCore import QMarginsF, QSizeF, Qt

    items = build_chart(pattern, library_blocks)
    if not items:
        raise ValueError("pattern has no stitches to export")
    bounds = pattern_bounds(pattern, library_blocks)
    minx, miny, maxx, maxy = bounds

    w_st = maxx - minx + 1
    h_st = maxy - miny + 1
    # page in points; 1pt ~ 1/72in. Use A4 landscape if wide.
    margin = 36.0
    legend_h = len({i.hex_color for i in items}) * 14 + 30 if style == "symbol" else 0
    pw = max(w_st * cell + 2 * margin, 595.0)
    ph = max(h_st * cell + 2 * margin + legend_h, 842.0)
    landscape = pw > ph
    page = QPageSize(QPageSize.PageSizeId.A4)
    if landscape:
        page = QPageSize(QPageSize.PageSizeId.A4)

    path = Path(path)
    if path.suffix.lower() != ".pdf":
        path = path.with_suffix(".pdf")

    writer = QPdfWriter(str(path))
    writer.setPageLayout(QPageLayout(
        page, QPageLayout.Orientation.Landscape if landscape
        else QPageLayout.Orientation.Portrait,
        QMarginsF(margin, margin, margin, margin), QPageLayout.Unit.Point))
    writer.setResolution(300)

    painter = QPainter(writer)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    # scale so pattern fits page area
    page_w = writer.width() / (writer.resolution() / 72.0)
    page_h = writer.height() / (writer.resolution() / 72.0)
    avail_w = page_w - 2 * margin
    avail_h = page_h - 2 * margin - legend_h
    scale = min(avail_w / (w_st * cell), avail_h / (h_st * cell), 1.0)
    c = cell * scale
    ox = margin - minx * c
    oy = margin - miny * c

    painter.save()
    painter.translate(0, 0)
    if style == "symbol":
        draw_symbol_chart(painter, items, c, ox, oy, bounds=bounds)
        from PySide6.QtGui import QColor, QFont
        painter.setFont(QFont("DejaVu Sans", max(6, int(c * 0.45))))
        ly = oy + (maxy - miny + 1) * c + c * 0.8
        seen = {}
        for it in items:
            seen.setdefault(it.hex_color, it.symbol)
        for i, (hexcol, sym) in enumerate(seen.items()):
            painter.setPen(QColor(hexcol))
            painter.drawText(30, ly + i * c * 0.9, f"{sym}  {hexcol}")
    else:
        draw_chart(painter, items, c, ox, oy, realistic=True, bounds=bounds)
    painter.restore()
    painter.end()
    return path
