"""Block definitions, placed instances, and explode semantics."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace

from .model import Stitch, StitchKind, Transform, transform_stitch


@dataclass
class Block:
    """A named reusable pattern fragment.

    Elements are stitches in block-local coordinates and/or nested
    BlockInstances (which carry their own local transform).
    """

    id: str
    name: str
    stitches: list[Stitch] = field(default_factory=list)
    instances: list["BlockInstance"] = field(default_factory=list)

    def bbox(self) -> tuple[int, int, int, int] | None:
        """(minx, miny, maxx, maxy) over all resolved content, or None."""
        xs, ys = [], []
        for s in self.stitches:
            for px, py in s.extent_points():
                xs.append(px)
                ys.append(py)
        for inst in self.instances:
            sub = inst.resolved_bbox()
            if sub:
                xs += [sub[0], sub[2]]
                ys += [sub[1], sub[3]]
        if not xs:
            return None
        return min(xs), min(ys), max(xs), max(ys)

    def resolved_stitches(self, base: Transform | None = None,
                          registry: dict | None = None) -> list[Stitch]:
        """Flatten this block (including nested instances) to absolute stitches.

        ``base`` is the transform already applied to this block's local space.
        ``registry`` maps block ids to Block definitions for resolving nested
        instances (merged project + global blocks).
        """
        t = base or Transform.IDENTITY
        out: list[Stitch] = []
        for s in self.stitches:
            out.append(_transform_stitch(s, t))
        for inst in self.instances:
            blk = registry.get(inst.block_id) if registry else None
            if blk is None:
                blk = inst._find_block(None, None)
            if blk is None:
                continue
            child_t = t.then(inst.transform)
            child_stitches = blk.resolved_stitches(child_t, registry=registry)
            if inst.recolor:
                child_stitches = [
                    replace(s, color=inst.recolor.get(s.color, s.color))
                    for s in child_stitches
                ]
            out.extend(child_stitches)
        return out

    # -- serialization ------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "stitches": [s.to_dict() for s in self.stitches],
            "instances": [i.to_dict() for i in self.instances],
        }

    @staticmethod
    def from_dict(d: dict) -> "Block":
        b = Block(id=d["id"], name=d.get("name", "Block"))
        for sd in d.get("stitches", []):
            b.stitches.append(Stitch.from_dict(sd))
        for idd in d.get("instances", []):
            b.instances.append(BlockInstance.from_dict_local(idd))
        return b


@dataclass
class BlockInstance:
    """A placed reference to a Block.

    ``block_id`` + ``scope`` locate the definition: "project" blocks live in
    ``pattern.blocks``; "global" blocks live in the user library.
    ``linked`` means future edits to the block definition propagate here;
    unlinked instances are detached snapshots.
    """

    uid: str
    block_id: str
    scope: str = "project"          # "project" | "global"
    transform: Transform = field(default_factory=Transform.translation)
    linked: bool = True
    recolor: dict = field(default_factory=dict)  # {src_color: dst_color}
    layer: str | None = None      # layer override; None keeps inner layers
    _block_cache: Block | None = field(default=None, repr=False, compare=False)

    # -- resolution ---------------------------------------------------
    def resolve(self, pattern_blocks: dict | None = None,
                library_blocks: dict | None = None) -> list[Stitch]:
        block = self._find_block(pattern_blocks, library_blocks)
        if block is None:
            return []
        registry = {}
        if library_blocks:
            registry.update(library_blocks)
        if pattern_blocks:
            registry.update(pattern_blocks)
        out = block.resolved_stitches(self.transform, registry=registry)
        if self.recolor:
            out = [replace(s, color=self.recolor.get(s.color, s.color))
                   for s in out]
        if self.layer:
            out = [replace(s, layer=self.layer) for s in out]
        return out

    def resolved_bbox(self, pattern_blocks=None, library_blocks=None):
        stitches = self.resolve(pattern_blocks, library_blocks)
        if not stitches:
            return None
        xs, ys = [], []
        for s in stitches:
            for px, py in s.extent_points():
                xs.append(px)
                ys.append(py)
        return min(xs), min(ys), max(xs), max(ys)

    def _find_block(self, pattern_blocks, library_blocks) -> Block | None:
        if self._block_cache is not None:
            return self._block_cache
        if self.scope == "project" and pattern_blocks:
            b = pattern_blocks.get(self.block_id)
        elif library_blocks:
            b = library_blocks.get(self.block_id)
        else:
            b = None
        if b is None and pattern_blocks:
            b = pattern_blocks.get(self.block_id)
        if b is None and library_blocks:
            b = library_blocks.get(self.block_id)
        self._block_cache = b
        return b

    # -- transforms on the instance ------------------------------------
    # All ops compose in LOCAL space: T' = T ∘ op, so the placement
    # translation is preserved and content rotates/mirrors in place.
    def transform_local(self, local: Transform):
        self.transform = local.then(self.transform)

    def rotate(self, deg: int, center: tuple[int, int] | None = None):
        r = Transform.from_semantic(0, 0, deg % 360)
        if center is not None:
            cx, cy = center
            r = (Transform.translation(-cx, -cy)
                 .then(r)
                 .then(Transform.translation(cx, cy)))
        self.transform_local(r)

    def mirror_x(self, center: tuple[int, int] | None = None):
        m = Transform.from_semantic(0, 0, 0, True, False)
        if center is not None:
            cx, cy = center
            m = (Transform.translation(-cx, -cy)
                 .then(m)
                 .then(Transform.translation(cx, cy)))
        self.transform_local(m)

    def mirror_y(self, center: tuple[int, int] | None = None):
        m = Transform.from_semantic(0, 0, 0, False, True)
        if center is not None:
            cx, cy = center
            m = (Transform.translation(-cx, -cy)
                 .then(m)
                 .then(Transform.translation(cx, cy)))
        self.transform_local(m)

    # -- serialization ------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "uid": self.uid,
            "block_id": self.block_id,
            "scope": self.scope,
            "transform": self.transform.to_dict(),
            "linked": self.linked,
            "recolor": self.recolor,
            "layer": self.layer,
        }

    @staticmethod
    def from_dict(d: dict, _blocks=None) -> "BlockInstance":
        return BlockInstance(
            uid=d.get("uid") or uuid.uuid4().hex[:12],
            block_id=d["block_id"],
            scope=d.get("scope", "project"),
            transform=Transform.from_dict(d["transform"]),
            linked=d.get("linked", True),
            recolor=d.get("recolor", {}),
            layer=d.get("layer"),
        )

    @staticmethod
    def from_dict_local(d: dict) -> "BlockInstance":
        """Nested instance inside a Block (no pattern context)."""
        return BlockInstance.from_dict(d)


def _transform_stitch(s: Stitch, t: Transform) -> Stitch:
    return transform_stitch(s, t)


def explode_instance(inst: BlockInstance, pattern, mode: str,
                     library_blocks: dict | None = None) -> list[Stitch]:
    """Explode a placed instance.

    mode="flatten": bake resolved stitches into pattern.stitches, remove instance.
    mode="unlink":   detach instance from its library definition (linked=False,
                     scope forced to project, block copied into pattern.blocks
                     if it was global), instance stays.
    Returns the stitches now owned by the pattern (flatten) or [].
    """
    if mode == "flatten":
        stitches = inst.resolve(pattern.blocks, library_blocks)
        for s in stitches:
            pattern.add_stitch(s)
        if inst in pattern.instances:
            pattern.instances.remove(inst)
        return stitches
    if mode == "unlink":
        if inst.scope == "global" and library_blocks:
            src = library_blocks.get(inst.block_id)
            if src is not None:
                new_id = uuid.uuid4().hex[:12]
                pattern.blocks[new_id] = Block.from_dict(src.to_dict())
                pattern.blocks[new_id].id = new_id
                inst.block_id = new_id
                inst.scope = "project"
        inst.linked = False
        return []
    raise ValueError(f"unknown explode mode: {mode}")
