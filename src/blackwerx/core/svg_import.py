"""SVG → stitch-grid conversion.

Rasterizes an SVG with QtSvg, thresholds coverage into grid cells, then
either emits X-stitches (fill mode) or boundary backstitches (outline mode).

Coordinates: cell (x, y) occupies lattice point (x, y); boundary edges of
cell (x, y) run between integer grid points, so fill and outline output
share one lattice.
"""

from __future__ import annotations

from dataclasses import dataclass

from .model import Stitch, StitchKind
from . import palette


@dataclass
class SvgImportResult:
    stitches: list[Stitch]
    width: int
    height: int
    cell_count: int


def _render(svg_path: str, width: int, height: int, supersample: int = 4):
    """Rasterize SVG to a supersampled QImage; return (QImage, scale)."""
    from PySide6.QtCore import QByteArray, QSize
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer
    from pathlib import Path

    data = Path(svg_path).read_bytes()
    renderer = QSvgRenderer(QByteArray(data))
    if not renderer.isValid():
        raise ValueError("invalid or unsupported SVG file")

    w, h = width * supersample, height * supersample
    image = QImage(w, h, QImage.Format.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    renderer.render(painter)
    painter.end()
    return image, supersample


def _cell_coverage(image, width: int, height: int, supersample: int,
                   threshold: int) -> tuple[set[tuple[int, int]], dict]:
    """Return set of covered cells and per-cell average color."""
    covered: set[tuple[int, int]] = set()
    colors: dict[tuple[int, int], tuple[int, int, int]] = {}
    for cy in range(height):
        for cx in range(width):
            rs = gs = bs = n = 0
            for sy in range(supersample):
                for sx in range(supersample):
                    px = image.pixelColor(cx * supersample + sx,
                                          cy * supersample + sy)
                    if px.alpha() > 40:
                        rs += px.red(); gs += px.green(); bs += px.blue(); n += 1
            if n == 0:
                continue
            coverage = n / (supersample * supersample)
            if coverage * 255 >= threshold:
                covered.add((cx, cy))
                colors[(cx, cy)] = (rs // n, gs // n, bs // n)
    return covered, colors


def _despeckle(covered: set[tuple[int, int]], min_neighbors: int = 1) -> set:
    """Remove cells with fewer than min_neighbors covered neighbors."""
    if min_neighbors <= 0:
        return covered
    out = set()
    for c in covered:
        x, y = c
        n = sum((x + dx, y + dy) in covered
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))
        if n >= min_neighbors:
            out.add(c)
    return out


def _smooth(covered: set[tuple[int, int]], passes: int = 0) -> set:
    """3x3 majority filter — reduces stair-stepping on diagonals."""
    cur = set(covered)
    for _ in range(passes):
        xs = [c[0] for c in cur]; ys = [c[1] for c in cur]
        if not xs:
            break
        x0, x1, y0, y1 = min(xs) - 1, max(xs) + 1, min(ys) - 1, max(ys) + 1
        nxt = set()
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                votes = sum((x + dx, y + dy) in cur
                            for dx in (-1, 0, 1) for dy in (-1, 0, 1))
                if votes >= 5:
                    nxt.add((x, y))
        cur = nxt
    return cur


def _boundary_segments(covered: set[tuple[int, int]]):
    """Extract boundary edges as (orientation, fixed, start, end) segments."""
    # vertical edges keyed by X coord; horizontal edges keyed by Y coord
    verts: dict[int, set[int]] = {}
    hors: dict[int, set[int]] = {}
    for x, y in covered:
        # left side: vertical segment X=x, y..y+1
        if (x - 1, y) not in covered:
            verts.setdefault(x, set()).add(y)
        # right side: X=x+1
        if (x + 1, y) not in covered:
            verts.setdefault(x + 1, set()).add(y)
        # top side: horizontal Y=y, x..x+1
        if (x, y - 1) not in covered:
            hors.setdefault(y, set()).add(x)
        # bottom side: Y=y+1
        if (x, y + 1) not in covered:
            hors.setdefault(y + 1, set()).add(x)
    return verts, hors


def _merge_runs(vals: set[int]):
    """Merge sorted ints into contiguous runs -> list[(start,end)]."""
    runs = []
    for v in sorted(vals):
        if runs and v == runs[-1][1]:
            runs[-1][1] = v + 1
        else:
            runs.append([v, v + 1])
    return [(a, b) for a, b in runs if b > a]


def outline_stitches(covered: set[tuple[int, int]], color: str) -> list[Stitch]:
    """Boundary of covered cells -> merged backstitches."""
    verts, hors = _boundary_segments(covered)
    out = []
    for x, ys in verts.items():
        for a, b in _merge_runs(ys):
            out.append(Stitch(StitchKind.BACK, (x, a), (x, b), color))
    for y, xs in hors.items():
        for a, b in _merge_runs(xs):
            out.append(Stitch(StitchKind.BACK, (a, y), (b, y), color))
    return out


def fill_stitches(covered: set[tuple[int, int]], colors: dict,
                  color_mode: str, default_color: str) -> list[Stitch]:
    out = []
    for cell in sorted(covered):
        if color_mode == "preserve" and cell in colors:
            r, g, b = colors[cell]
            spec = f"#{r:02x}{g:02x}{b:02x}"
        else:
            spec = default_color
        out.append(Stitch(StitchKind.X, cell, None, spec))
    return out


def import_svg(svg_path: str, width: int, height: int, *,
               mode: str = "fill", threshold: int = 128,
               smooth_passes: int = 0, min_neighbors: int = 0,
               color_mode: str = "mono", default_color: str = "#000000",
               map_to_dmc: bool = False,
               supersample: int = 4) -> SvgImportResult:
    """Convert an SVG file to stitches on a width×height grid.

    mode: "fill" (X-stitches over covered area) or "outline" (boundary
          backstitches).
    threshold: 0-255 coverage cutoff per cell.
    smooth_passes: majority-filter iterations to reduce jaggies.
    min_neighbors: despeckle — drop cells with fewer orthogonal neighbors.
    color_mode: "mono" (default_color everywhere) or "preserve" (sampled).
    map_to_dmc: convert preserved colors to nearest DMC spec.
    """
    if mode not in ("fill", "outline"):
        raise ValueError("mode must be 'fill' or 'outline'")
    if not (1 <= width <= 2000 and 1 <= height <= 2000):
        raise ValueError("grid size out of range (1..2000)")

    image, ss = _render(svg_path, width, height, supersample)
    covered, colors = _cell_coverage(image, width, height, ss, threshold)
    covered = _smooth(covered, smooth_passes)
    covered = _despeckle(covered, min_neighbors)

    if mode == "fill":
        stitches = fill_stitches(covered, colors, color_mode, default_color)
    else:
        stitches = outline_stitches(covered, default_color)

    if map_to_dmc:
        from dataclasses import replace
        stitches = [replace(s, color=palette.nearest_dmc(s.color))
                    for s in stitches]

    return SvgImportResult(stitches=stitches, width=width, height=height,
                           cell_count=len(covered))
