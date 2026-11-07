"""SVG export — vector chart and/or realistic preview as standalone SVG."""

from __future__ import annotations

import html
from pathlib import Path

from .chart import build_chart, pattern_bounds
from ..model import Pattern, StitchKind
from .. import palette


def export_svg(pattern: Pattern, path: str | Path, *,
               style: str = "realistic", library_blocks: dict | None = None,
               cell: float = 20.0, symbol_style: str = "shapes",
               grid: bool = False, full_canvas: bool = False) -> Path:
    """Write a standalone SVG of the pattern.

    style: 'realistic' draws X shapes/thread lines in thread colors;
           'symbol' draws per-color glyphs with a legend.
    grid: include grid lines (off by default — stitches only).
    """
    items = build_chart(pattern, library_blocks, symbol_style)
    if not items:
        raise ValueError("pattern has no stitches to export")
    bounds = pattern_bounds(pattern, library_blocks, full_canvas)
    minx, miny, maxx, maxy = bounds

    w = (maxx - minx + 1) * cell
    h = (maxy - miny + 1) * cell
    legend_h = 0.0
    legend_items = []
    if style == "symbol":
        seen = {}
        for it in items:
            seen.setdefault(it.hex_color, it.symbol)
        legend_items = list(seen.items())
        legend_h = len(legend_items) * cell * 0.9 + cell

    W = w + cell
    H = h + cell + legend_h

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{H:.0f}" '
        f'viewBox="0 0 {W:.0f} {H:.0f}">',
        f'<rect width="{W:.0f}" height="{H:.0f}" fill="#F5F0E6"/>',
    ]

    def X(p):
        return ((p[0] - minx) * cell + cell / 2,
                (p[1] - miny) * cell + cell / 2)

    if grid:
        for gx in range(minx, maxx + 2):
            x1 = (gx - minx) * cell
            major = (gx - minx) % 10 == 0
            parts.append(
                f'<line x1="{x1:.1f}" y1="0" x2="{x1:.1f}" y2="{h:.1f}" '
                f'stroke="{"#B0A890" if major else "#D8D0C0"}" '
                f'stroke-width="{0.8 if major else 0.4}"/>')
        for gy in range(miny, maxy + 2):
            y1 = (gy - miny) * cell
            major = (gy - miny) % 10 == 0
            parts.append(
                f'<line x1="0" y1="{y1:.1f}" x2="{w:.1f}" y2="{y1:.1f}" '
                f'stroke="{"#B0A890" if major else "#D8D0C0"}" '
                f'stroke-width="{0.8 if major else 0.4}"/>')

    sw = max(1.0, cell * 0.18)
    if style == "symbol":
        for it in items:
            s = it.stitch
            col = palette.resolve(it.color_spec)
            if s.kind is StitchKind.X:
                cx, cy = X((s.a[0] + 0.5, s.a[1] + 0.5))
            else:
                pa, pb = s.endpoints()
                cx = ((pa[0] + pb[0]) / 2 - minx) * cell + cell / 2
                cy = ((pa[1] + pb[1]) / 2 - miny) * cell + cell / 2
            parts.append(
                f'<text x="{cx:.1f}" y="{cy + cell * 0.18:.1f}" '
                f'font-size="{cell * 0.5:.1f}" fill="{col}" '
                f'text-anchor="middle">{html.escape(it.symbol)}</text>')
    else:
        half = cell * 0.5
        for it in items:
            s = it.stitch
            col = palette.resolve(it.color_spec)
            if s.kind is StitchKind.X:
                cx, cy = X((s.a[0] + 0.5, s.a[1] + 0.5))
                parts.append(
                    f'<path d="M{cx-half:.1f},{cy-half:.1f} L{cx+half:.1f},{cy+half:.1f} '
                    f'M{cx+half:.1f},{cy-half:.1f} L{cx-half:.1f},{cy+half:.1f}" '
                    f'stroke="{col}" stroke-width="{sw:.1f}" fill="none"/>')
            else:
                pa, pb = s.endpoints()
                x1, y1 = X(pa); x2, y2 = X(pb)
                parts.append(
                    f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                    f'stroke="{col}" stroke-width="{sw:.1f}"/>')

    if legend_items:
        from .. import palette as _pal
        lx, ly = cell * 0.5, h + cell * 0.8
        for i, (hexcol, sym) in enumerate(legend_items):
            name = next((_pal.dmc_name(it.color_spec) for it in items
                         if it.hex_color == hexcol), None) or hexcol
            parts.append(
                f'<text x="{lx:.1f}" y="{ly + i * cell * 0.9 + cell * 0.3:.1f}" '
                f'font-size="{cell * 0.45:.1f}" fill="{hexcol}">{html.escape(sym)}  {html.escape(name)}</text>')

    parts.append("</svg>")

    path = Path(path)
    if path.suffix.lower() != ".svg":
        path = path.with_suffix(".svg")
    path.write_text("\n".join(parts))
    return path
