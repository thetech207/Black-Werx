"""Chart layout engine: collect effective stitches, assign symbols,
draw onto any QPainter (used by PDF and PNG exporters)."""

from __future__ import annotations

from dataclasses import dataclass

from ..model import Stitch, StitchKind, Pattern
from .. import palette

# glyph sets used for symbol charts, cycled per color
SYMBOL_SETS = {
    "shapes": list("•▲■◆★⬟⬢✚✖◇▣▤▥▦▧▨▩▭▮▯"),
    "letters": list("ABCDEFGHIJKLMNOPQRSTUVWXYZ"),
    "numbers": [str(i) for i in range(1, 37)],
}
SYMBOL_STYLES = ["shapes", "letters", "numbers", "dmc"]


def _dmc_symbol(spec: str) -> str:
    """DMC number for a color spec (nearest match for custom hex)."""
    from .. import palette
    if spec.startswith("dmc:"):
        return spec[4:]
    return palette.nearest_dmc(spec)[4:]


@dataclass
class ChartItem:
    stitch: Stitch
    symbol: str
    color_spec: str
    hex_color: str


def collect_stitches(pattern: Pattern,
                     library_blocks: dict | None = None) -> list[Stitch]:
    """All effective stitches: raw pattern stitches + resolved instances."""
    out = list(pattern.stitches.values())
    for inst in pattern.instances:
        out.extend(inst.resolve(pattern.blocks, library_blocks))
    return out


def assign_symbols(stitches: list[Stitch],
                   style: str = "shapes") -> dict[str, str]:
    """Map each distinct color spec to a chart symbol."""
    colors = sorted({s.color for s in stitches})
    if style == "dmc":
        return {c: _dmc_symbol(c) for c in colors}
    table = SYMBOL_SETS.get(style, SYMBOL_SETS["shapes"])
    return {c: table[i % len(table)] for i, c in enumerate(colors)}


def build_chart(pattern: Pattern,
                library_blocks: dict | None = None,
                symbol_style: str = "shapes") -> list[ChartItem]:
    stitches = collect_stitches(pattern, library_blocks)
    syms = assign_symbols(stitches, symbol_style)
    return [
        ChartItem(s, syms[s.color], s.color, palette.resolve(s.color))
        for s in stitches
    ]


def pattern_bounds(pattern: Pattern,
                   library_blocks: dict | None = None,
                   full_canvas: bool = False) -> tuple[int, int, int, int]:
    """Bounds around stitch extents, or the whole canvas if full_canvas."""
    if full_canvas:
        return (0, 0, pattern.width - 1, pattern.height - 1)
    xs, ys = [], []
    for s in collect_stitches(pattern, library_blocks):
        for px, py in s.extent_points():
            xs.append(px); ys.append(py)
    if not xs:
        return (0, 0, pattern.width - 1, pattern.height - 1)
    import math
    return (math.floor(min(xs)), math.floor(min(ys)),
            math.ceil(max(xs)), math.ceil(max(ys)))


def draw_chart(painter, items: list[ChartItem], cell: float,
               ox: float, oy: float, *, realistic: bool = False,
               fabric: str = "#F5F0E6", grid_major: int = 10,
               bounds=None):
    """Draw the pattern onto a QPainter.

    (ox, oy) is the scene position of lattice point (0,0); cell is px per
    stitch. ``bounds`` = (minx, miny, maxx, maxy) of drawn area.
    """
    from PySide6.QtGui import QColor, QPen, QPainterPath
    from PySide6.QtCore import QPointF, Qt

    if bounds is None:
        xs = [0]; ys = [0]
        for it in items:
            for px, py in it.stitch.extent_points():
                xs.append(px); ys.append(py)
        bounds = (min(xs), min(ys), max(xs), max(ys))
    minx, miny, maxx, maxy = bounds

    def X(p):
        return QPointF(ox + (p[0] - minx) * cell, oy + (p[1] - miny) * cell)

    # fabric background
    painter.fillRect(
        int(ox), int(oy),
        int((maxx - minx + 1) * cell) + 1,
        int((maxy - miny + 1) * cell) + 1,
        QColor(fabric),
    )

    # grid lines: minor every cell, major every grid_major
    pen_minor = QPen(QColor("#D8D0C0"), 0.4)
    pen_major = QPen(QColor("#B0A890"), 0.8)
    painter.setPen(pen_minor)
    for gx in range(minx, maxx + 2):
        painter.drawLine(X((gx, miny)), X((gx, maxy + 1)))
    for gy in range(miny, maxy + 2):
        painter.drawLine(X((minx, gy)), X((maxx + 1, gy)))
    painter.setPen(pen_major)
    for gx in range(minx - (minx % grid_major), maxx + 2, grid_major):
        painter.drawLine(X((gx, miny)), X((gx, maxy + 1)))
    for gy in range(miny - (miny % grid_major), maxy + 2, grid_major):
        painter.drawLine(X((minx, gy)), X((maxx + 1, gy)))

    # stitches
    for it in items:
        s = it.stitch
        pen = QPen(QColor(it.hex_color), max(1.0, cell * 0.18))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        if s.kind is StitchKind.X:
            c = X((s.a[0] + 0.5, s.a[1] + 0.5))
            half = cell * 0.5
            path = QPainterPath()
            path.moveTo(c.x() - half, c.y() - half)
            path.lineTo(c.x() + half, c.y() + half)
            path.moveTo(c.x() + half, c.y() - half)
            path.lineTo(c.x() - half, c.y() + half)
            painter.drawPath(path)
        else:
            pa, pb = s.endpoints()
            painter.drawLine(X(pa), X(pb))


def draw_symbol_chart(painter, items: list[ChartItem], cell: float,
                      ox: float, oy: float, *, bounds=None):
    """Symbol chart: one glyph per stitch/color + legend drawn by caller."""
    from PySide6.QtGui import QColor, QPen, QFont
    from PySide6.QtCore import QPointF, Qt

    if bounds is None:
        xs = [0]; ys = [0]
        for it in items:
            for px, py in it.stitch.extent_points():
                xs.append(px); ys.append(py)
        bounds = (min(xs), min(ys), max(xs), max(ys))
    minx, miny, maxx, maxy = bounds

    def X(p):
        return QPointF(ox + (p[0] - minx) * cell, oy + (p[1] - miny) * cell)

    painter.fillRect(int(ox), int(oy),
                     int((maxx - minx + 1) * cell) + 1,
                     int((maxy - miny + 1) * cell) + 1,
                     QColor("white"))

    # grid
    pen_minor = QPen(QColor("#CCCCCC"), 0.4)
    pen_major = QPen(QColor("#999999"), 0.8)
    painter.setPen(pen_minor)
    for gx in range(minx, maxx + 2):
        painter.drawLine(X((gx, miny)), X((gx, maxy + 1)))
    for gy in range(miny, maxy + 2):
        painter.drawLine(X((minx, gy)), X((maxx + 1, gy)))
    painter.setPen(pen_major)
    for gx in range(minx - (minx % 10), maxx + 2, 10):
        painter.drawLine(X((gx, miny)), X((gx, maxy + 1)))
    for gy in range(miny - (miny % 10), maxy + 2, 10):
        painter.drawLine(X((minx, gy)), X((maxx + 1, gy)))

    font = QFont("DejaVu Sans", max(6, int(cell * 0.45)))
    painter.setFont(font)
    for it in items:
        s = it.stitch
        painter.setPen(QPen(QColor(it.hex_color), 1))
        if s.kind is StitchKind.X:
            c = X((s.a[0] + 0.5, s.a[1] + 0.5))
            painter.drawText(int(c.x() - cell / 2), int(c.y() + cell / 3),
                             it.symbol)
        else:
            # symbol chart convention: show line stitches with their glyph
            # placed at midpoint
            pa, pb = s.endpoints()
            mid = ((pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2)
            c = X((round(mid[0]), round(mid[1])))
            painter.drawText(int(c.x() - cell / 2), int(c.y() + cell / 3),
                             it.symbol)
