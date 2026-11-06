"""Core data model for Black-Werx patterns.

Everything in this module is GUI-free so it can be unit-tested headlessly.

Coordinates are integer grid intersections ("holes" in the Aida cloth).
An X-stitch occupies one cell; a backstitch connects two grid points.
"""

from __future__ import annotations

import enum
import itertools
import uuid
from dataclasses import dataclass, field


class StitchKind(enum.Enum):
    X = "x"          # full cross stitch occupying one cell
    BACK = "back"    # backstitch / running line between two grid points


def _norm_point(p: tuple[int, int]) -> tuple[int, int]:
    return (int(p[0]), int(p[1]))


@dataclass(frozen=True)
class Stitch:
    """A single stitch.

    For X stitches, ``a`` is the cell coordinate and ``b`` is None.
    For backstitches, ``a`` and ``b`` are the two endpoint grid points
    (normalized so a <= b lexicographically).
    """

    kind: StitchKind
    a: tuple[int, int]
    b: tuple[int, int] | None
    color: str  # color spec: "#rrggbb" or "dmc:NNN" — resolved via palette

    def __post_init__(self):
        object.__setattr__(self, "a", _norm_point(self.a))
        if self.b is not None:
            p = _norm_point(self.b)
            pa, pb = self.a, p
            if pb < pa:
                pa, pb = pb, pa
            object.__setattr__(self, "a", pa)
            object.__setattr__(self, "b", pb)
        if self.kind is StitchKind.X and self.b is not None:
            raise ValueError("X stitch must not have two endpoints")
        if self.kind is StitchKind.BACK and self.b is None:
            raise ValueError("backstitch requires two endpoints")

    @property
    def key(self) -> tuple:
        return (self.kind.value, self.a, self.b)

    def cells(self) -> list[tuple[int, int]]:
        """Grid cells this stitch touches (for hit-testing / bounds)."""
        if self.kind is StitchKind.X:
            return [self.a]
        (x1, y1), (x2, y2) = self.a, self.b
        cells = []
        # walk the line and collect cells it passes through
        steps = max(abs(x2 - x1), abs(y2 - y1), 1)
        for i in range(steps + 1):
            t = i / steps
            cx = round(x1 + (x2 - x1) * t)
            cy = round(y1 + (y2 - y1) * t)
            cells.append((cx, cy))
        # dedupe preserving order
        seen, out = set(), []
        for c in cells:
            if c not in seen:
                seen.add(c)
                out.append(c)
        return out

    def to_dict(self) -> dict:
        d = {
            "kind": self.kind.value,
            "a": list(self.a),
            "color": self.color,
        }
        if self.b is not None:
            d["b"] = list(self.b)
        return d

    @staticmethod
    def from_dict(d: dict) -> "Stitch":
        return Stitch(
            kind=StitchKind(d["kind"]),
            a=tuple(d["a"]),
            b=tuple(d["b"]) if d.get("b") is not None else None,
            color=d.get("color", "#000000"),
        )


class Transform:
    """Integer-lattice affine transform: p' = M·p + t.

    M is one of the 8 orthogonal signed-permutation matrices (rotations
    composed with optional axis mirrors), so integer grid coordinates are
    preserved exactly.
    """

    __slots__ = ("m00", "m01", "m10", "m11", "tx", "ty")

    IDENTITY = None  # set below

    def __init__(self, m00=1, m01=0, m10=0, m11=1, tx=0, ty=0):
        self.m00, self.m01, self.m10, self.m11 = m00, m01, m10, m11
        self.tx, self.ty = tx, ty

    # -- constructors -------------------------------------------------
    @staticmethod
    def from_semantic(dx=0, dy=0, rot=0, mirror_x=False, mirror_y=False) -> "Transform":
        """Build from user-facing semantics.

        Order of application to a point: mirror (about local origin),
        rotate rot*90 CCW about origin, then translate by (dx, dy).
        """
        # mirror matrix
        m00, m11 = (-1 if mirror_x else 1), (-1 if mirror_y else 1)
        m01 = m10 = 0
        # rotation r (CCW, multiples of 90)
        r = rot % 360
        if r == 90:
            # (x,y) -> (-y, x); compose mirror first then rot:
            # new matrix = R * M
            n00, n01 = -m10, -m11
            n10, n11 = m00, m01
            m00, m01, m10, m11 = n00, n01, n10, n11
        elif r == 180:
            m00, m01, m10, m11 = -m00, -m01, -m10, -m11
        elif r == 270:
            n00, n01 = m10, m11
            n10, n11 = -m00, -m01
            m00, m01, m10, m11 = n00, n01, n10, n11
        return Transform(m00, m01, m10, m11, dx, dy)

    @staticmethod
    def translation(dx, dy) -> "Transform":
        return Transform(1, 0, 0, 1, dx, dy)

    # -- algebra ------------------------------------------------------
    def apply(self, p: tuple[int, int]) -> tuple[int, int]:
        x, y = p
        return (
            self.m00 * x + self.m01 * y + self.tx,
            self.m10 * x + self.m11 * y + self.ty,
        )

    def then(self, other: "Transform") -> "Transform":
        """Return transform equivalent to applying self, then other."""
        o = other
        m00 = o.m00 * self.m00 + o.m01 * self.m10
        m01 = o.m00 * self.m01 + o.m01 * self.m11
        m10 = o.m10 * self.m00 + o.m11 * self.m10
        m11 = o.m10 * self.m01 + o.m11 * self.m11
        tx = o.m00 * self.tx + o.m01 * self.ty + o.tx
        ty = o.m10 * self.tx + o.m11 * self.ty + o.ty
        return Transform(m00, m01, m10, m11, tx, ty)

    def inverse(self) -> "Transform":
        # M is orthogonal: M^-1 = M^T
        m00, m01, m10, m11 = self.m00, self.m10, self.m01, self.m11
        # t' = -M^T t
        tx = -(m00 * self.tx + m01 * self.ty)
        ty = -(m10 * self.tx + m11 * self.ty)
        return Transform(m00, m01, m10, m11, tx, ty)

    @property
    def rotation(self) -> int:
        # recover semantic rotation for serialization of simple transforms
        if (self.m00, self.m01, self.m10, self.m11) == (1, 0, 0, 1):
            return 0
        if (self.m00, self.m01, self.m10, self.m11) == (0, -1, 1, 0):
            return 90
        if (self.m00, self.m01, self.m10, self.m11) == (-1, 0, 0, -1):
            return 180
        if (self.m00, self.m01, self.m10, self.m11) == (0, 1, -1, 0):
            return 270
        return -1  # mirrored or otherwise non-pure-rotation

    def to_dict(self) -> dict:
        return {
            "m": [self.m00, self.m01, self.m10, self.m11],
            "t": [self.tx, self.ty],
        }

    @staticmethod
    def from_dict(d: dict) -> "Transform":
        m = d["m"]
        t = d["t"]
        return Transform(m[0], m[1], m[2], m[3], t[0], t[1])

    def __eq__(self, other):
        return (
            isinstance(other, Transform)
            and (self.m00, self.m01, self.m10, self.m11, self.tx, self.ty)
            == (other.m00, other.m01, other.m10, other.m11, other.tx, other.ty)
        )

    def __repr__(self):
        return f"Transform({self.m00},{self.m01},{self.m10},{self.m11},{self.tx},{self.ty})"


Transform.IDENTITY = Transform()


@dataclass
class Pattern:
    """A cross-stitch pattern: sparse stitches + placed block instances."""

    width: int = 100
    height: int = 100
    name: str = "Untitled"
    # fabric / physical stitch geometry (canvas setup)
    aida_count: int = 18            # aida cloth count (threads per inch)
    stitch_w_mm: float = 1.41       # stitched X width in mm
    stitch_h_mm: float = 1.41       # stitched X height in mm
    stitches: dict[tuple, Stitch] = field(default_factory=dict)
    instances: list = field(default_factory=list)  # list[BlockInstance]
    blocks: dict = field(default_factory=dict)      # project-embedded blocks {id: Block}
    threads: dict = field(default_factory=dict)     # thread usage stats cache

    # -- stitch access ------------------------------------------------
    def add_stitch(self, s: Stitch) -> Stitch:
        self.stitches[s.key] = s
        return s

    def remove_stitch(self, key: tuple) -> Stitch | None:
        return self.stitches.pop(key, None)

    def get_stitches_in_cell(self, cell: tuple[int, int]) -> list[Stitch]:
        out = []
        for s in self.stitches.values():
            if cell in s.cells():
                out.append(s)
        return out

    def stitches_in_rect(self, x0, y0, x1, y1) -> list[Stitch]:
        x0, x1 = min(x0, x1), max(x0, x1)
        y0, y1 = min(y0, y1), max(y0, y1)
        out = []
        for s in self.stitches.values():
            pts = [s.a] + ([s.b] if s.b else [])
            if all(x0 <= x <= x1 and y0 <= y <= y1 for x, y in pts):
                out.append(s)
        return out

    # -- blocks -------------------------------------------------------
    def next_instance_id(self) -> str:
        return uuid.uuid4().hex[:12]

    # -- stats --------------------------------------------------------
    def stitch_count(self) -> int:
        return len(self.stitches)

    def used_colors(self) -> set[str]:
        cols = {s.color for s in self.stitches.values()}
        # include colors used inside linked instances via resolution is
        # caller's job; raw pattern colors only here.
        return cols

    # -- serialization ------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "format": "bwpx",
            "version": 1,
            "name": self.name,
            "width": self.width,
            "height": self.height,
            "aida_count": self.aida_count,
            "stitch_w_mm": self.stitch_w_mm,
            "stitch_h_mm": self.stitch_h_mm,
            "stitches": [s.to_dict() for s in self.stitches.values()],
            "instances": [inst.to_dict() for inst in self.instances],
            "blocks": {bid: b.to_dict() for bid, b in self.blocks.items()},
        }

    @staticmethod
    def from_dict(d: dict) -> "Pattern":
        from .block import Block, BlockInstance  # local import avoids cycle

        p = Pattern(
            width=d.get("width", 100),
            height=d.get("height", 100),
            name=d.get("name", "Untitled"),
            aida_count=d.get("aida_count", 18),
            stitch_w_mm=d.get("stitch_w_mm", 1.41),
            stitch_h_mm=d.get("stitch_h_mm", 1.41),
        )
        for sd in d.get("stitches", []):
            s = Stitch.from_dict(sd)
            p.stitches[s.key] = s
        p.blocks = {bid: Block.from_dict(bd) for bid, bd in d.get("blocks", {}).items()}
        for idd in d.get("instances", []):
            p.instances.append(BlockInstance.from_dict(idd, p.blocks))
        return p
