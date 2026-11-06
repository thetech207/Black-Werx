"""Undo/redo commands operating on Pattern."""

from __future__ import annotations

from PySide6.QtGui import QUndoCommand

from ..core.model import Stitch, Transform
from ..core.block import BlockInstance, explode_instance


class DrawStitchesCommand(QUndoCommand):
    """Add stitches; undo removes them (restoring any overwritten stitches)."""

    def __init__(self, pattern, stitches: list[Stitch], text="Draw"):
        super().__init__(text)
        self.pattern = pattern
        self.stitches = stitches
        self._overwritten: dict = {}

    def redo(self):
        for s in self.stitches:
            if s.key in self.pattern.stitches and s.key not in self._overwritten:
                self._overwritten[s.key] = self.pattern.stitches[s.key]
            self.pattern.add_stitch(s)

    def undo(self):
        for s in self.stitches:
            self.pattern.stitches.pop(s.key, None)
        for k, s in self._overwritten.items():
            self.pattern.stitches[k] = s
        self._overwritten.clear()


class EraseStitchesCommand(QUndoCommand):
    def __init__(self, pattern, keys: list, text="Erase"):
        super().__init__(text)
        self.pattern = pattern
        self.keys = list(keys)
        self._removed: dict = {}

    def redo(self):
        for k in self.keys:
            s = self.pattern.stitches.pop(k, None)
            if s is not None:
                self._removed[k] = s

    def undo(self):
        for k, s in self._removed.items():
            self.pattern.stitches[k] = s
        self._removed.clear()


class DeleteSelectionCommand(QUndoCommand):
    def __init__(self, pattern, stitch_keys, instance_uids, text="Delete"):
        super().__init__(text)
        self.pattern = pattern
        self.stitch_keys = list(stitch_keys)
        self.instance_uids = list(instance_uids)
        self._stitches: dict = {}
        self._instances: dict = {}

    def redo(self):
        for k in self.stitch_keys:
            s = self.pattern.stitches.pop(k, None)
            if s is not None:
                self._stitches[k] = s
        for uid in self.instance_uids:
            for i, inst in enumerate(self.pattern.instances):
                if inst.uid == uid:
                    self._instances[uid] = (i, inst)
                    del self.pattern.instances[i]
                    break

    def undo(self):
        for k, s in self._stitches.items():
            self.pattern.stitches[k] = s
        self._stitches.clear()
        for uid, (i, inst) in self._instances.items():
            self.pattern.instances.insert(min(i, len(self.pattern.instances)), inst)
        self._instances.clear()


class MoveStitchesCommand(QUndoCommand):
    """Translate stitches and/or instances by (dx, dy)."""

    def __init__(self, pattern, stitch_keys, instance_uids, dx, dy,
                 text="Move"):
        super().__init__(text)
        self.pattern = pattern
        self.dx, self.dy = dx, dy
        self.stitch_keys = list(stitch_keys)
        self.instance_uids = list(instance_uids)
        self._before: dict = {}
        self._inst_before: dict = {}

    def _snapshot(self):
        self._before = {}
        for k in self.stitch_keys:
            s = self.pattern.stitches.get(k)
            if s:
                self._before[k] = s
        self._inst_before = {}
        for inst in self.pattern.instances:
            if inst.uid in self.instance_uids:
                self._inst_before[inst.uid] = inst.transform

    def redo(self):
        self._snapshot()
        for k in self.stitch_keys:
            s = self.pattern.stitches.get(k)
            if s:
                self.pattern.stitches.pop(k)
                ns = Stitch(s.kind,
                            (s.a[0] + self.dx, s.a[1] + self.dy),
                            (s.b[0] + self.dx, s.b[1] + self.dy) if s.b else None,
                            s.color)
                self.pattern.stitches[ns.key] = ns
        for inst in self.pattern.instances:
            if inst.uid in self.instance_uids:
                inst.transform = inst.transform.then(
                    Transform.translation(self.dx, self.dy))

    def undo(self):
        for k, s in self._before.items():
            self.pattern.stitches.pop(
                Stitch(s.kind, (s.a[0] + self.dx, s.a[1] + self.dy),
                       (s.b[0] + self.dx, s.b[1] + self.dy) if s.b else None,
                       s.color).key, None)
            self.pattern.stitches[k] = s
        for inst in self.pattern.instances:
            if inst.uid in self._inst_before:
                inst.transform = self._inst_before[inst.uid]


def _rot_about_op(cx, cy, q):
    """Transform rotating points q quarter-turns CCW about (cx, cy)."""
    return (Transform.translation(-cx, -cy)
            .then(Transform.from_semantic(0, 0, (q % 4) * 90))
            .then(Transform.translation(cx, cy)))


class TransformSelectionCommand(QUndoCommand):
    """Rotate selected stitches AND instances q quarter-turns about (cx, cy)."""

    def __init__(self, pattern, stitch_keys, instance_uids, cx, cy, q,
                 text="Rotate"):
        super().__init__(text)
        self.pattern = pattern
        self.stitch_keys = list(stitch_keys)
        self.uids = list(instance_uids)
        self.cx, self.cy, self.q = cx, cy, q % 4
        self._before = {}
        self._inst_before = {}

    def redo(self):
        if not self._before:
            for k in self.stitch_keys:
                s = self.pattern.stitches.get(k)
                if s:
                    self._before[k] = s
            for inst in self.pattern.instances:
                if inst.uid in self.uids:
                    self._inst_before[inst.uid] = inst.transform
        op = _rot_about_op(self.cx, self.cy, self.q)
        for k in self.stitch_keys:
            s = self.pattern.stitches.get(k)
            if s:
                self.pattern.stitches.pop(k)
                ns = Stitch(s.kind, op.apply(s.a),
                            op.apply(s.b) if s.b else None, s.color)
                self.pattern.stitches[ns.key] = ns
        for inst in self.pattern.instances:
            if inst.uid in self.uids:
                # rotate in parent space: T' = Rot_c ∘ T
                inst.transform = inst.transform.then(op)

    def undo(self):
        for k, s in self._before.items():
            cur = Stitch(s.kind,
                         _rot_about_op(self.cx, self.cy, self.q).apply(s.a),
                         _rot_about_op(self.cx, self.cy, self.q).apply(s.b)
                         if s.b else None, s.color)
            self.pattern.stitches.pop(cur.key, None)
            self.pattern.stitches[k] = s
        for inst in self.pattern.instances:
            if inst.uid in self._inst_before:
                inst.transform = self._inst_before[inst.uid]


class CopySelectionCommand(QUndoCommand):
    """Duplicate selected stitches/instances.

    Each spec is (dx, dy, cx, cy, q): the copy is translated by (dx, dy)
    then rotated q quarter-turns about (cx, cy) (pass cx=cy=q=0 to skip
    rotation). Used for array-style "N copies" in move/rotate tools.
    """

    def __init__(self, pattern, stitch_keys, instance_uids, copies,
                 text="Duplicate"):
        super().__init__(text)
        self.pattern = pattern
        self.stitch_keys = list(stitch_keys)
        self.uids = list(instance_uids)
        self.copies = list(copies)
        self.created_stitch_keys: list = []
        self.created_uids: list = []
        self._overwritten: dict = {}
        self._done = False

    def redo(self):
        if self._done:
            return
        self._done = True
        for dx, dy, cx, cy, q in self.copies:
            for k in self.stitch_keys:
                s = self.pattern.stitches.get(k)
                if s is None:
                    continue
                pa = (s.a[0] + dx, s.a[1] + dy)
                pb = ((s.b[0] + dx, s.b[1] + dy) if s.b else None)
                if q:
                    op = _rot_about_op(cx, cy, q)
                    pa, pb = op.apply(pa), (op.apply(pb) if pb else None)
                ns = Stitch(s.kind, pa, pb, s.color)
                if ns.key in self.pattern.stitches \
                        and ns.key not in self._overwritten:
                    self._overwritten[ns.key] = self.pattern.stitches[ns.key]
                self.pattern.stitches[ns.key] = ns
                self.created_stitch_keys.append(ns.key)
            for inst in list(self.pattern.instances):
                if inst.uid not in self.uids:
                    continue
                t = inst.transform.then(Transform.translation(dx, dy))
                if q:
                    t = t.then(_rot_about_op(cx, cy, q))
                ni = BlockInstance(
                    uid=self.pattern.next_instance_id(),
                    block_id=inst.block_id, scope=inst.scope,
                    transform=t, linked=inst.linked,
                    recolor=dict(inst.recolor))
                self.pattern.instances.append(ni)
                self.created_uids.append(ni.uid)

    def undo(self):
        # remove created stitches in reverse so overlapping copies restore
        # earlier copies correctly
        for k in reversed(self.created_stitch_keys):
            self.pattern.stitches.pop(k, None)
        for k, s in self._overwritten.items():
            self.pattern.stitches[k] = s
        drop = set(self.created_uids)
        self.pattern.instances = [i for i in self.pattern.instances
                                  if i.uid not in drop]
        self._overwritten.clear()
        self.created_stitch_keys.clear()
        self.created_uids.clear()
        self._done = False


class TransformInstancesCommand(QUndoCommand):
    """Apply rotate/mirror to selected instances (about block-local center)."""

    def __init__(self, pattern, instance_uids, op, text="Transform",
                 library_blocks=None):
        super().__init__(text)
        self.pattern = pattern
        self.uids = list(instance_uids)
        self.op = op  # "rot90" | "rot180" | "rot270" | "flipx" | "flipy"
        self.library_blocks = library_blocks or {}
        self._before = {}

    def _center_for(self, inst):
        """Integer center of the block definition's local bbox."""
        b = self.pattern.blocks.get(inst.block_id) or \
            self.library_blocks.get(inst.block_id)
        if b is None:
            return None
        bb = b.bbox()
        if bb is None:
            return None
        return ((bb[0] + bb[2]) // 2, (bb[1] + bb[3]) // 2)

    def redo(self):
        if not self._before:
            for inst in self.pattern.instances:
                if inst.uid in self.uids:
                    self._before[inst.uid] = inst.transform
        for inst in self.pattern.instances:
            if inst.uid in self.uids:
                c = self._center_for(inst)
                if self.op.startswith("rot"):
                    inst.rotate(int(self.op[3:]), center=c)
                elif self.op == "flipx":
                    inst.mirror_x(center=c)
                elif self.op == "flipy":
                    inst.mirror_y(center=c)

    def undo(self):
        for inst in self.pattern.instances:
            if inst.uid in self._before:
                inst.transform = self._before[inst.uid]


class RecolorCommand(QUndoCommand):
    def __init__(self, pattern, mapping: dict, keys=None, uids=None,
                 text="Recolor"):
        super().__init__(text)
        self.pattern = pattern
        self.mapping = mapping          # {old_color: new_color}
        self.keys = list(keys or [])
        self.uids = list(uids or [])
        self._before: dict = {}         # key -> old color
        self._inst_before: dict = {}    # uid -> old recolor dict

    def redo(self):
        if self._before or self._inst_before:
            return  # already applied
        for k in self.keys:
            s = self.pattern.stitches.get(k)
            if s and s.color in self.mapping:
                self._before[k] = s.color
                self.pattern.stitches[k] = Stitch(
                    s.kind, s.a, s.b, self.mapping[s.color])
        for inst in self.pattern.instances:
            if inst.uid in self.uids:
                self._inst_before[inst.uid] = dict(inst.recolor)
                for old, new in self.mapping.items():
                    inst.recolor[old] = new

    def undo(self):
        for k, old in self._before.items():
            s = self.pattern.stitches.get(k)
            if s:
                self.pattern.stitches[k] = Stitch(s.kind, s.a, s.b, old)
        for inst in self.pattern.instances:
            if inst.uid in self._inst_before:
                inst.recolor = dict(self._inst_before[inst.uid])
        self._before.clear()
        self._inst_before.clear()


class PlaceBlockCommand(QUndoCommand):
    def __init__(self, pattern, inst: BlockInstance, text="Place block"):
        super().__init__(text)
        self.pattern = pattern
        self.inst = inst

    def redo(self):
        if self.inst not in self.pattern.instances:
            self.pattern.instances.append(self.inst)

    def undo(self):
        if self.inst in self.pattern.instances:
            self.pattern.instances.remove(self.inst)


class ExplodeCommand(QUndoCommand):
    def __init__(self, pattern, inst: BlockInstance, mode: str,
                 library_blocks=None, text="Explode"):
        super().__init__(text)
        self.pattern = pattern
        self.inst = inst
        self.mode = mode
        self.library_blocks = library_blocks or {}
        self._flattened: list = []
        self._inst_index = None
        self._inst_snapshot = None

    def redo(self):
        idx = None
        for i, x in enumerate(self.pattern.instances):
            if x.uid == self.inst.uid:
                idx = i
                self._inst_index = i
                self._inst_snapshot = x
                break
        if self.mode == "flatten":
            self._flattened = explode_instance(self.inst, self.pattern, "flatten",
                                               self.library_blocks)
        else:
            explode_instance(self.inst, self.pattern, "unlink",
                             self.library_blocks)

    def undo(self):
        if self.mode == "flatten":
            for s in self._flattened:
                self.pattern.stitches.pop(s.key, None)
            if self._inst_snapshot is not None and \
                    self._inst_snapshot not in self.pattern.instances:
                self.pattern.instances.append(self._inst_snapshot)
            self._flattened = []
        else:
            # restore linked state — snapshot via stored inst object
            inst = self._inst_snapshot or self.inst
            # re-find current instance object in pattern
            for x in self.pattern.instances:
                if x.uid == inst.uid:
                    x.linked = True
                    # scope/block_id restoration is best-effort
                    break
