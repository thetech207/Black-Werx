"""Tajima .pat stitch-file export."""

from __future__ import annotations

from pathlib import Path

from .chart import collect_stitches
from ..model import Pattern, StitchKind
from .. import palette


def export_pat(pattern: Pattern, path: str | Path, *,
               library_blocks: dict | None = None,
               name: str | None = None) -> Path:
    """Write a Tajima-compatible .pat file.

    Units are stitches. X stitches map to color-change jumps between
    adjacent cells; backstitches map to jump stitches along their line.
    This produces a stitchable approximation — verify on your machine's
    software before stitching.
    """
    stitches = collect_stitches(pattern, library_blocks)
    if not stitches:
        raise ValueError("pattern has no stitches to export")

    # group by color, preserve first-seen order for thread list
    colors: list[str] = []
    for s in stitches:
        if s.color not in colors:
            colors.append(s.color)

    bounds = pattern_bounds_all(stitches)
    minx, miny = bounds[0], bounds[1]

    lines = []
    lines.append("LA:%d" % len(stitches))
    lines.append("ST:")
    for s in stitches:
        if s.kind is StitchKind.X:
            # two half stitches approximated as jump + stitch
            x, y = s.a[0] - minx, s.a[1] - miny
            lines.append(f"{x + 1:5d}{y + 1:5d} +1")
            lines.append(f"{x + 1:5d}{y + 1:5d} -1")
        else:
            x1, y1 = s.a[0] - minx + 1, s.a[1] - miny + 1
            x2, y2 = s.b[0] - minx + 1, s.b[1] - miny + 1
            # interpolate intermediate points along the line
            steps = max(abs(x2 - x1), abs(y2 - y1), 1)
            for i in range(steps):
                t0, t1 = i / steps, (i + 1) / steps
                ax = round(x1 + (x2 - x1) * t0); ay = round(y1 + (y2 - y1) * t0)
                bx = round(x1 + (x2 - x1) * t1); by = round(y1 + (y2 - y1) * t1)
                if (ax, ay) != (bx, by):
                    lines.append(f"{ax:5d}{ay:5d} +{bx - ax} +{by - ay}")
    # color change markers: naive — all stitches listed, color table at end
    lines.append("CO")
    for c in colors:
        hexcol = palette.resolve(c)
        # Tajima color entries: index, RGB, description
        r = int(hexcol[1:3], 16); g = int(hexcol[3:5], 16); b = int(hexcol[5:7], 16)
        lines.append(f"{colors.index(c) + 1:3d} {r:3d} {g:3d} {b:3d} {c}")
    lines.append("END")

    path = Path(path)
    if path.suffix.lower() != ".pat":
        path = path.with_suffix(".pat")
    path.write_text("\n".join(lines) + "\n")
    return path


def pattern_bounds_all(stitches) -> tuple[int, int, int, int]:
    xs, ys = [], []
    for s in stitches:
        for px, py in s.extent_points():
            xs.append(px); ys.append(py)
    if not xs:
        return (0, 0, 0, 0)
    return min(xs), min(ys), max(xs), max(ys)
