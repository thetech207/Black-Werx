"""Symmetry helpers: mirror transforms applied to drawn strokes.

Axes are named: "h" (vertical mirror), "v" (horizontal mirror),
"d" (main diagonal y=x), "ad" (anti-diagonal). Each selected axis mirrors
the source stroke once; axes are not composed recursively.
"""

from __future__ import annotations

from .model import Stitch

AXES = ("h", "v", "d", "ad")


def _swap(a, b):
    return (b, a) if b < a else (a, b)


def _mirror(s: Stitch, fn) -> Stitch:
    a = fn(s.a)
    b = fn(s.b) if s.b else None
    if b is not None and b < a:
        a, b = b, a
    return Stitch(s.kind, a, b, s.color)


def apply_symmetry(stitches: list[Stitch], axes,
                   width: int, height: int) -> list[Stitch]:
    """Expand source stitches into mirrored copies for each axis in ``axes``."""
    axes = set(axes or ())
    if not axes or not stitches:
        return list(stitches)

    cx = (width - 1) / 2.0
    cy = (height - 1) / 2.0

    fns = {}
    if "h" in axes:
        fns["h"] = lambda p: (round(2 * cx - p[0]), p[1])
    if "v" in axes:
        fns["v"] = lambda p: (p[0], round(2 * cy - p[1]))
    if "d" in axes:
        fns["d"] = lambda p: (p[1], p[0])
    if "ad" in axes:
        w, h = width - 1, height - 1
        fns["ad"] = lambda p: (w - p[0], h - p[1])

    out = list(stitches)
    keys = {s.key for s in out}
    for fn in fns.values():
        for s in stitches:
            m = _mirror(s, fn)
            if m.key not in keys:
                keys.add(m.key)
                out.append(m)
    return out
