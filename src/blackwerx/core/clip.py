"""Region tests for clip-behind operations.

Builds an even-odd interior test from a set of boundary segments using a
scanline fill at SUB samples per cell. Pure Python; cost is
O(rows x segments) once, then O(log) per query point.
"""

from __future__ import annotations

from bisect import bisect_right

SUB = 8  # samples per cell along each axis


def build_inside_test(segments, width: float, height: float):
    """Return inside(x, y) -> bool for the even-odd interior of segments.

    segments: iterable of (x1, y1, x2, y2) in cell coordinates (y down).
    Coordinates outside [0,width]x[0,height] are treated as outside.
    """
    H = max(1, int(height * SUB + 0.5))
    crossings = [[] for _ in range(H)]  # row -> list of x crossings

    for x1, y1, x2, y2 in segments:
        if y1 == y2:
            continue  # horizontal edges never cross a scanline
        ya, yb = (y1, y2) if y1 < y2 else (y2, y1)
        # sample rows whose center yc=(r+0.5)/SUB lies strictly inside (ya,yb)
        r0 = max(0, int(ya * SUB))
        r1 = min(H - 1, int(yb * SUB))
        for r in range(r0, r1 + 1):
            yc = (r + 0.5) / SUB
            if yc <= ya or yc >= yb:
                continue
            t = (yc - y1) / (y2 - y1)
            crossings[r].append(x1 + t * (x2 - x1))

    starts: list[list[float]] = []
    spans: list[list[tuple[float, float]]] = []
    for r in range(H):
        xs = sorted(crossings[r])
        iv = []
        for i in range(0, len(xs) - 1, 2):
            a, b = xs[i], xs[i + 1]
            a = max(0.0, a)
            b = min(float(width), b)
            if b > a:
                iv.append((a, b))
        spans.append(iv)
        starts.append([a for a, _ in iv])

    def inside(x: float, y: float) -> bool:
        r = int(y * SUB)
        if r < 0 or r >= H:
            return False
        st, iv = starts[r], spans[r]
        if not st:
            return False
        i = bisect_right(st, x) - 1
        return i >= 0 and x < iv[i][1]

    return inside
