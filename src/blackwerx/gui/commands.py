"""Undo/redo commands operating on Pattern."""

from __future__ import annotations

import math
from dataclasses import replace

from PySide6.QtGui import QUndoCommand

from ..core import clip
from ..core.model import Stitch, StitchKind, Transform, transform_stitch
from ..core.block import BlockInstance, explode_instance


def _conj(op: Transform, m: Transform) -> Transform:
    """Conjugate ``op`` by symmetry transform ``m``: m ∘ op ∘ m⁻¹.

    Applying the conjugate to m's counterpart produces exactly the mirror
    of applying ``op`` to the original — so edits stay symmetric.
    """
    return m.inverse().then(op).then(m)


def _sym_layers(pattern, stitch_keys, instance_uids, sym_ops):
    """Orbit-anchored symmetry layers: [(keys, uids, m), ...].

    The selection is grouped into symmetry orbits. Each orbit contributes
    ONE anchor — a selected member — to the identity layer, so it receives
    the user's literal edit. Every other orbit member (selected or not)
    appears in exactly one layer, under the group element mapping the
    anchor to it, and receives the conjugated edit. Result: edits always
    preserve symmetry; a fully-selected orbit does NOT move rigidly.
    """
    ops = [Transform()] + list(sym_ops)
    if not sym_ops:
        return [(list(stitch_keys), list(instance_uids), Transform())]
    out_keys = [[] for _ in ops]
    out_uids = [[] for _ in ops]

    # ---- stitch orbits ----
    groups = {}
    for k in stitch_keys:
        s = pattern.stitches.get(k)
        if s is None:
            continue
        orb = [transform_stitch(s, m).key for m in ops]
        orb = [k2 for k2 in orb if k2 in pattern.stitches]
        sig = min(orb, key=repr) if orb else k
        groups.setdefault(sig, []).append(k)
    def _geo_key(k):
        s = pattern.stitches[k]
        return (s.a, s.b if s.b is not None else (-1, -1), repr(k))

    for _sig, keys in groups.items():
        anchor = min(keys, key=_geo_key)
        s = pattern.stitches[anchor]
        for i, m in enumerate(ops):
            mk = transform_stitch(s, m).key
            if mk in pattern.stitches:
                out_keys[i].append(mk)

    # ---- instance orbits (match by block/scope/transform) ----
    sel_insts = [i for i in pattern.instances if i.uid in instance_uids]

    def orbit_sig(inst):
        uids = set()
        for m in ops:
            t = inst.transform.then(m)
            for o in pattern.instances:
                if o.block_id == inst.block_id \
                        and o.scope == inst.scope \
                        and o.transform == t:
                    uids.add(o.uid)
        return min(uids) if uids else inst.uid

    igroups = {}
    for inst in sel_insts:
        igroups.setdefault(orbit_sig(inst), []).append(inst.uid)
    for _sig, uids in igroups.items():
        anchor_uid = min(uids)
        ainst = next(i for i in pattern.instances if i.uid == anchor_uid)
        for i, m in enumerate(ops):
            t = ainst.transform.then(m)
            for o in pattern.instances:
                if o.block_id == ainst.block_id \
                        and o.scope == ainst.scope \
                        and o.transform == t:
                    out_uids[i].append(o.uid)
                    break

    return [(out_keys[i], out_uids[i], ops[i]) for i in range(len(ops))]


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
    def __init__(self, pattern, keys: list, text="Erase", selection=None,
                 sym_ops=None):
        super().__init__(text)
        self.pattern = pattern
        self.keys = list(keys)
        self.selection = selection
        self.sym_ops = list(sym_ops or [])
        self._removed: dict = {}
        self._sel_before = None
        self._sel_after = None
        self._all_keys: list = []

    def redo(self):
        if self._sel_before is None:
            self._sel_before = _sel_snapshot(self.selection)
            layers = _sym_layers(self.pattern, self.keys, [],
                                 self.sym_ops)
            self._all_keys = [k for ks, _u, _m in layers for k in ks]
            gone = set(self._all_keys)
            self._sel_after = (self._sel_before[0] - gone,
                               self._sel_before[1])
        for k in self._all_keys:
            s = self.pattern.stitches.pop(k, None)
            if s is not None:
                self._removed[k] = s
        _set_selection(self.selection, *self._sel_after)

    def undo(self):
        for k, s in self._removed.items():
            self.pattern.stitches[k] = s
        self._removed.clear()
        _set_selection(self.selection, *self._sel_before)


class DeleteSelectionCommand(QUndoCommand):
    def __init__(self, pattern, stitch_keys, instance_uids, text="Delete",
                 selection=None, sym_ops=None):
        super().__init__(text)
        self.pattern = pattern
        self.stitch_keys = list(stitch_keys)
        self.instance_uids = list(instance_uids)
        self.selection = selection
        self.sym_ops = list(sym_ops or [])
        self._stitches: dict = {}
        self._instances: dict = {}
        self._sel_before = None
        self._sel_after = None
        self._all_keys: list = []
        self._all_uids: list = []

    def redo(self):
        if self._sel_before is None:
            self._sel_before = _sel_snapshot(self.selection)
            layers = _sym_layers(self.pattern, self.stitch_keys,
                                 self.instance_uids, self.sym_ops)
            self._all_keys = [k for ks, _u, _m in layers for k in ks]
            self._all_uids = [u for _k, us, _m in layers for u in us]
            gone_k, gone_u = set(self._all_keys), set(self._all_uids)
            self._sel_after = (self._sel_before[0] - gone_k,
                               self._sel_before[1] - gone_u)
        for k in self._all_keys:
            s = self.pattern.stitches.pop(k, None)
            if s is not None:
                self._stitches[k] = s
        for uid in self._all_uids:
            for i, inst in enumerate(self.pattern.instances):
                if inst.uid == uid:
                    self._instances[uid] = (i, inst)
                    del self.pattern.instances[i]
                    break
        _set_selection(self.selection, *self._sel_after)

    def undo(self):
        for k, s in self._stitches.items():
            self.pattern.stitches[k] = s
        self._stitches.clear()
        for uid, (i, inst) in self._instances.items():
            self.pattern.instances.insert(min(i, len(self.pattern.instances)), inst)
        self._instances.clear()
        _set_selection(self.selection, *self._sel_before)


def _set_selection(sel, keys, uids):
    """Update a Selection object in place (no repaint; caller refreshes)."""
    if sel is None:
        return
    sel.stitch_keys = set(keys)
    sel.instance_uids = set(uids)


def _sel_snapshot(sel):
    if sel is None:
        return (set(), set())
    return (set(sel.stitch_keys), set(sel.instance_uids))


class SelectionCommand(QUndoCommand):
    """Undoable record of a user-driven selection change."""

    def __init__(self, selection, before, after, text="Select"):
        super().__init__(text)
        self.selection = selection
        self._before = before
        self._after = after

    def redo(self):
        _set_selection(self.selection, self._after[0], self._after[1])

    def undo(self):
        _set_selection(self.selection, self._before[0], self._before[1])


class MoveStitchesCommand(QUndoCommand):
    """Translate stitches and/or instances by (dx, dy).

    With ``sym_ops`` (live symmetry transforms), symmetric counterparts
    move by the conjugated delta so the pattern stays symmetric.
    """

    def __init__(self, pattern, stitch_keys, instance_uids, dx, dy,
                 text="Move", selection=None, sym_ops=None):
        super().__init__(text)
        self.pattern = pattern
        self.dx, self.dy = dx, dy
        self.stitch_keys = list(stitch_keys)
        self.instance_uids = list(instance_uids)
        self.selection = selection
        self.sym_ops = list(sym_ops or [])
        self._before: dict = {}
        self._inst_before: dict = {}
        self._layers = None
        self._new_keys: list = []
        self._newkey_set: set = set()
        self._displaced: dict = {}

    def _snapshot(self):
        self._before = {}
        self._inst_before = {}
        if self._layers is None:
            self._layers = _sym_layers(
                self.pattern, self.stitch_keys, self.instance_uids,
                self.sym_ops)
        for keys, uids, _m in self._layers:
            for k in keys:
                s = self.pattern.stitches.get(k)
                if s:
                    self._before[k] = s
            for inst in self.pattern.instances:
                if inst.uid in uids:
                    self._inst_before[inst.uid] = inst.transform

    def redo(self):
        self._snapshot()
        self._newkey_set = set()
        self._displaced = {}
        new_keys = []
        all_uids = []
        # collect and remove all sources across every layer BEFORE
        # writing — a moved stitch landing on a not-yet-read source key
        # would otherwise move twice and eat the original
        per_layer = []
        all_src = {}
        for keys, uids, m in self._layers:
            src = {}
            for k in keys:
                s = self.pattern.stitches.get(k)
                if s is not None:
                    src[k] = s
            per_layer.append((src, uids, m))
            all_src.update(src)
        for k in all_src:
            self.pattern.stitches.pop(k, None)
        for src, uids, m in per_layer:
            # conjugated delta: linear part of m applied to (dx, dy)
            ddx = m.m00 * self.dx + m.m01 * self.dy
            ddy = m.m10 * self.dx + m.m11 * self.dy
            for k, s in src.items():
                ns = replace(
                    s, a=(s.a[0] + ddx, s.a[1] + ddy),
                    b=((s.b[0] + ddx, s.b[1] + ddy) if s.b else None))
                existing = self.pattern.stitches.get(ns.key)
                if existing is not None \
                        and ns.key not in self._newkey_set:
                    # stash the displaced stitch so undo restores it
                    self._displaced[ns.key] = existing
                self.pattern.stitches[ns.key] = ns
                self._newkey_set.add(ns.key)
                new_keys.append(ns.key)
            for inst in self.pattern.instances:
                if inst.uid in uids:
                    inst.transform = inst.transform.then(
                        Transform.translation(ddx, ddy))
            all_uids.extend(uids)
        self._new_keys = new_keys
        _set_selection(self.selection, new_keys, all_uids)

    def undo(self):
        for k in self._new_keys:
            self.pattern.stitches.pop(k, None)
        for k, s in self._displaced.items():
            self.pattern.stitches[k] = s
        for k, s in self._before.items():
            self.pattern.stitches[k] = s
        for inst in self.pattern.instances:
            if inst.uid in self._inst_before:
                inst.transform = self._inst_before[inst.uid]
        _set_selection(self.selection, self.stitch_keys,
                       self.instance_uids)
        self._new_keys = []
        self._newkey_set = set()
        self._displaced = {}


def _rot_about_op(cx, cy, q):
    """Transform rotating points q quarter-turns CCW about (cx, cy)."""
    return (Transform.translation(-cx, -cy)
            .then(Transform.from_semantic(0, 0, (q % 4) * 90))
            .then(Transform.translation(cx, cy)))


class TransformSelectionCommand(QUndoCommand):
    """Rotate selected stitches AND instances q quarter-turns about (cx, cy)."""

    def __init__(self, pattern, stitch_keys, instance_uids, cx, cy, q,
                 text="Rotate", selection=None, sym_ops=None):
        super().__init__(text)
        self.pattern = pattern
        self.stitch_keys = list(stitch_keys)
        self.uids = list(instance_uids)
        self.cx, self.cy, self.q = cx, cy, q % 4
        self.selection = selection
        self.sym_ops = list(sym_ops or [])
        self._before = {}
        self._inst_before = {}
        self._layers = None
        self._new_keys: list = []
        self._new_uids: list = []
        self._newkey_set: set = set()
        self._displaced: dict = {}

    def redo(self):
        if self._layers is None:
            self._layers = _sym_layers(
                self.pattern, self.stitch_keys, self.uids, self.sym_ops)
            for keys, uids, _m in self._layers:
                for k in keys:
                    s = self.pattern.stitches.get(k)
                    if s:
                        self._before[k] = s
                for inst in self.pattern.instances:
                    if inst.uid in uids:
                        self._inst_before[inst.uid] = inst.transform
        new_keys, new_uids = [], []
        self._newkey_set = set()
        self._displaced = {}
        # collect and remove all sources across every layer BEFORE
        # writing — a moved stitch landing on a not-yet-read source key
        # would otherwise be re-read and moved twice
        per_layer = []
        all_src = {}
        for keys, uids, m in self._layers:
            src = {}
            for k in keys:
                s = self.pattern.stitches.get(k)
                if s is not None:
                    src[k] = s
            per_layer.append((src, uids, m))
            all_src.update(src)
        for k in all_src:
            self.pattern.stitches.pop(k, None)
        for src, uids, m in per_layer:
            op = _conj(_rot_about_op(self.cx, self.cy, self.q), m)
            for k, s in src.items():
                ns = transform_stitch(s, op)
                existing = self.pattern.stitches.get(ns.key)
                if existing is not None \
                        and ns.key not in self._newkey_set:
                    # stash the displaced stitch so undo restores it
                    self._displaced[ns.key] = existing
                self.pattern.stitches[ns.key] = ns
                self._newkey_set.add(ns.key)
                new_keys.append(ns.key)
            for inst in self.pattern.instances:
                if inst.uid in uids:
                    # rotate in parent space: T' = op ∘ T
                    inst.transform = inst.transform.then(op)
            new_uids.extend(uids)
        self._new_keys, self._new_uids = new_keys, new_uids
        _set_selection(self.selection, new_keys, new_uids)

    def undo(self):
        for k in self._new_keys:
            self.pattern.stitches.pop(k, None)
        for k, s in self._displaced.items():
            self.pattern.stitches[k] = s
        for k, s in self._before.items():
            self.pattern.stitches[k] = s
        for inst in self.pattern.instances:
            if inst.uid in self._inst_before:
                inst.transform = self._inst_before[inst.uid]
        self._newkey_set = set()
        self._displaced = {}
        _set_selection(self.selection, self.stitch_keys, self.uids)
        self._new_keys, self._new_uids = [], []


class CopySelectionCommand(QUndoCommand):
    """Duplicate selected stitches/instances.

    Each spec is (dx, dy, cx, cy, q): the copy is translated by (dx, dy)
    then rotated q quarter-turns about (cx, cy) (pass cx=cy=q=0 to skip
    rotation). Used for array-style "N copies" in move/rotate tools.
    """

    def __init__(self, pattern, stitch_keys, instance_uids, copies,
                 text="Duplicate", orig_op=None, selection=None,
                 sym_ops=None, target_layer=None):
        super().__init__(text)
        self.pattern = pattern
        self.stitch_keys = list(stitch_keys)
        self.uids = list(instance_uids)
        self.copies = list(copies)
        # optional (dx, dy, cx, cy, q): also transform the ORIGINALS by
        # translate-then-rotate-about-(cx,cy), all in one undo step
        self.orig_op = orig_op
        self.selection = selection
        self.sym_ops = list(sym_ops or [])
        # optional layer override for the copies — lets a copy sit at the
        # same position as the original (keys differ by layer)
        self.target_layer = target_layer
        self.skipped = 0    # copies dropped because the cell was occupied
        self.created_stitch_keys: list = []
        self.created_uids: list = []
        self._orig_new_keys: list = []
        self._created_keys: set = set()
        self._moved_keys: set = set()
        self._displaced: dict = {}
        self._orig_before: dict = {}
        self._inst_before: dict = {}
        self._done = False

    @staticmethod
    def _spec_op(dx, dy, cx, cy, q):
        t = Transform.translation(dx, dy)
        if q:
            t = t.then(_rot_about_op(cx, cy, q))
        return t

    def redo(self):
        if self._done:
            return
        self._done = True
        layers = _sym_layers(self.pattern, self.stitch_keys, self.uids,
                             self.sym_ops)
        for keys, uids, m in layers:
            layer_uids = set(uids)
            for dx, dy, cx, cy, q in self.copies:
                op = _conj(self._spec_op(dx, dy, cx, cy, q), m)
                for k in keys:
                    s = self.pattern.stitches.get(k)
                    if s is None:
                        continue
                    ns = transform_stitch(s, op)
                    if self.target_layer is not None:
                        ns = replace(ns, layer=self.target_layer)
                    if ns.key in self.pattern.stitches \
                            and ns.key not in self._created_keys:
                        # never clobber a stitch that was already there —
                        # a copy must not eat whatever it overlaps
                        self.skipped += 1
                        continue
                    self.pattern.stitches[ns.key] = ns
                    self.created_stitch_keys.append(ns.key)
                    self._created_keys.add(ns.key)
                for inst in list(self.pattern.instances):
                    if inst.uid not in layer_uids:
                        continue
                    ni = BlockInstance(
                        uid=self.pattern.next_instance_id(),
                        block_id=inst.block_id, scope=inst.scope,
                        transform=inst.transform.then(op),
                        linked=inst.linked, recolor=dict(inst.recolor),
                        layer=(self.target_layer
                               if self.target_layer is not None
                               else inst.layer))
                    self.pattern.instances.append(ni)
                    self.created_uids.append(ni.uid)
        if self.orig_op is not None:
            dx, dy, cx, cy, q = self.orig_op
            # snapshot every source across all layers BEFORE writing —
            # a moved stitch landing on a not-yet-read source key would
            # otherwise move twice and eat the original
            per_layer = []
            all_src = {}
            for keys, uids, m in layers:
                src = {}
                for k in keys:
                    s = self.pattern.stitches.get(k)
                    if s is None:
                        continue
                    self._orig_before.setdefault(k, s)
                    src[k] = s
                per_layer.append((src, uids, m))
                all_src.update(src)
            for k in all_src:
                self.pattern.stitches.pop(k, None)
            for src, uids, m in per_layer:
                op = _conj(self._spec_op(dx, dy, cx, cy, q), m)
                layer_uids = set(uids)
                for k, s in src.items():
                    ns = transform_stitch(s, op)
                    existing = self.pattern.stitches.get(ns.key)
                    if existing is not None \
                            and ns.key not in self._created_keys \
                            and ns.key not in self._moved_keys:
                        # the moved stitch displaced an unrelated one —
                        # stash it so undo can put it back
                        self._displaced[ns.key] = existing
                    self.pattern.stitches[ns.key] = ns
                    self._moved_keys.add(ns.key)
                    self._orig_new_keys.append(ns.key)
                for inst in self.pattern.instances:
                    if inst.uid in layer_uids:
                        if inst.uid not in self._inst_before:
                            self._inst_before[inst.uid] = inst.transform
                        inst.transform = inst.transform.then(op)
        # copies (and moved originals) become the new selection;
        # untouched originals (keep-original) are deselected
        all_uids = [u for _k, u, _m in layers for u in u]
        _set_selection(self.selection,
                       self.created_stitch_keys + self._orig_new_keys,
                       self.created_uids
                       + (all_uids if self.orig_op else []))

    def undo(self):
        for k in reversed(self.created_stitch_keys):
            self.pattern.stitches.pop(k, None)
        drop = set(self.created_uids)
        self.pattern.instances = [i for i in self.pattern.instances
                                  if i.uid not in drop]
        # restore transformed originals
        for k in self._orig_new_keys:
            self.pattern.stitches.pop(k, None)
        for k, s in self._displaced.items():
            self.pattern.stitches[k] = s
        for k, s in self._orig_before.items():
            self.pattern.stitches[k] = s
        for inst in self.pattern.instances:
            if inst.uid in self._inst_before:
                inst.transform = self._inst_before[inst.uid]
        self._displaced.clear()
        self.created_stitch_keys.clear()
        self.created_uids.clear()
        self._orig_new_keys.clear()
        self._created_keys.clear()
        self._moved_keys.clear()
        self.skipped = 0
        self._done = False
        _set_selection(self.selection, self.stitch_keys, self.uids)


class TransformInstancesCommand(QUndoCommand):
    """Apply rotate/mirror to selected instances (about block-local center).

    ``stitch_keys`` + ``stitch_op`` additionally transform raw stitches with
    an explicit Transform (typically rot/flip about the selection bbox
    center), so mixed selections transform in one undo step.
    """

    def __init__(self, pattern, instance_uids, op, text="Transform",
                 library_blocks=None, stitch_keys=None, stitch_op=None,
                 selection=None, sym_ops=None):
        super().__init__(text)
        self.pattern = pattern
        self.uids = list(instance_uids)
        self.op = op  # "rot90" | "rot180" | "rot270" | "flipx" | "flipy"
        self.library_blocks = library_blocks or {}
        self.stitch_keys = list(stitch_keys or [])
        self.stitch_op = stitch_op
        self.selection = selection
        self.sym_ops = list(sym_ops or [])
        self._before = {}
        self._stitch_before = {}
        self._layers = None
        self._new_keys: list = []
        self._new_uids: list = []
        self._newkey_set: set = set()
        self._displaced: dict = {}

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
        if self._layers is None:
            self._layers = _sym_layers(
                self.pattern, self.stitch_keys, self.uids, self.sym_ops)
            for keys, uids, _m in self._layers:
                for u in uids:
                    for inst in self.pattern.instances:
                        if inst.uid == u:
                            self._before[u] = inst.transform
                for k in keys:
                    s = self.pattern.stitches.get(k)
                    if s:
                        self._stitch_before[k] = s
        new_keys, new_uids = [], []
        self._newkey_set = set()
        self._displaced = {}
        # collect and remove all sources across every layer BEFORE
        # writing — a moved stitch landing on a not-yet-read source key
        # would otherwise be re-read and moved twice
        per_layer = []
        all_src = {}
        for keys, uids, m in self._layers:
            src = {}
            if self.stitch_op is not None:
                for k in keys:
                    s = self.pattern.stitches.get(k)
                    if s is not None:
                        src[k] = s
            per_layer.append((src, uids, m))
            all_src.update(src)
        for k in all_src:
            self.pattern.stitches.pop(k, None)
        for src, uids, m in per_layer:
            if self.stitch_op is not None:
                op = _conj(self.stitch_op, m)
                for k, s in src.items():
                    ns = transform_stitch(s, op)
                    existing = self.pattern.stitches.get(ns.key)
                    if existing is not None \
                            and ns.key not in self._newkey_set:
                        # stash the displaced stitch so undo restores it
                        self._displaced[ns.key] = existing
                    self.pattern.stitches[ns.key] = ns
                    self._newkey_set.add(ns.key)
                    new_keys.append(ns.key)
            # local-space ops are identical on every orbit member:
            # T_i' = (M T) L = M (T L)
            layer_uids = set(uids)
            for inst in self.pattern.instances:
                if inst.uid not in layer_uids:
                    continue
                c = self._center_for(inst)
                if self.op.startswith("rot"):
                    inst.rotate(int(self.op[3:]), center=c)
                elif self.op == "flipx":
                    inst.mirror_x(center=c)
                elif self.op == "flipy":
                    inst.mirror_y(center=c)
            new_uids.extend(uids)
        self._new_keys, self._new_uids = new_keys, new_uids
        _set_selection(self.selection, new_keys, new_uids)

    def undo(self):
        for inst in self.pattern.instances:
            if inst.uid in self._before:
                inst.transform = self._before[inst.uid]
        for k in self._new_keys:
            self.pattern.stitches.pop(k, None)
        for k, s in self._displaced.items():
            self.pattern.stitches[k] = s
        for k, s in self._stitch_before.items():
            self.pattern.stitches[k] = s
        _set_selection(self.selection, self.stitch_keys, self.uids)
        self._new_keys, self._new_uids = [], []
        self._newkey_set = set()
        self._displaced = {}


class RecolorCommand(QUndoCommand):
    def __init__(self, pattern, mapping: dict, keys=None, uids=None,
                 text="Recolor", sym_ops=None):
        super().__init__(text)
        self.pattern = pattern
        self.mapping = mapping          # {old_color: new_color}
        self.keys = list(keys or [])
        self.uids = list(uids or [])
        self.sym_ops = list(sym_ops or [])
        self._before: dict = {}         # key -> old color
        self._inst_before: dict = {}    # uid -> old recolor dict
        self._all_keys: list = []
        self._all_uids: list = []

    def redo(self):
        if self._before or self._inst_before:
            return  # already applied
        layers = _sym_layers(self.pattern, self.keys, self.uids,
                             self.sym_ops)
        self._all_keys = [k for ks, _u, _m in layers for k in ks]
        self._all_uids = [u for _k, us, _m in layers for u in us]
        for k in self._all_keys:
            s = self.pattern.stitches.get(k)
            if s and s.color in self.mapping:
                self._before[k] = s.color
                self.pattern.stitches[k] = replace(
                    s, color=self.mapping[s.color])
        for inst in self.pattern.instances:
            if inst.uid in self._all_uids:
                self._inst_before[inst.uid] = dict(inst.recolor)
                for old, new in self.mapping.items():
                    inst.recolor[old] = new

    def undo(self):
        for k, old in self._before.items():
            s = self.pattern.stitches.get(k)
            if s:
                self.pattern.stitches[k] = replace(s, color=old)
        for inst in self.pattern.instances:
            if inst.uid in self._inst_before:
                inst.recolor = dict(self._inst_before[inst.uid])
        self._before.clear()
        self._inst_before.clear()


class PlaceBlockCommand(QUndoCommand):
    def __init__(self, pattern, inst, text="Place block"):
        super().__init__(text)
        self.pattern = pattern
        self.insts = inst if isinstance(inst, list) else [inst]

    def redo(self):
        for i in self.insts:
            if i not in self.pattern.instances:
                self.pattern.instances.append(i)

    def undo(self):
        for i in self.insts:
            if i in self.pattern.instances:
                self.pattern.instances.remove(i)


class ExplodeCommand(QUndoCommand):
    def __init__(self, pattern, inst: BlockInstance, mode: str,
                 library_blocks=None, text="Explode", selection=None):
        super().__init__(text)
        self.pattern = pattern
        self.inst = inst
        self.mode = mode
        self.library_blocks = library_blocks or {}
        self.selection = selection
        self._flattened: list = []
        self._inst_index = None
        self._inst_snapshot = None
        self._sel_before = None

    def redo(self):
        if self._sel_before is None:
            self._sel_before = _sel_snapshot(self.selection)
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
        if self.mode == "flatten":
            _set_selection(
                self.selection,
                self._sel_before[0],
                self._sel_before[1] - {self.inst.uid})
        else:
            _set_selection(self.selection, *self._sel_before)

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
        _set_selection(self.selection, *self._sel_before)


class MoveToLayerCommand(QUndoCommand):
    """Move selected stitches and/or instances to another layer."""

    def __init__(self, pattern, stitch_keys, instance_uids, layer_id,
                 text="Move to layer", selection=None, sym_ops=None):
        super().__init__(text)
        self.pattern = pattern
        self.stitch_keys = list(stitch_keys)
        self.uids = list(instance_uids)
        self.layer_id = layer_id
        self.selection = selection
        self.sym_ops = list(sym_ops or [])
        self._before = {}      # old stitch key -> Stitch
        self._inst_before = {} # uid -> old layer
        self._new_keys = []
        self._newkey_set: set = set()
        self._displaced: dict = {}
        self._all_keys: list = []
        self._all_uids: list = []

    def redo(self):
        if not self._before:
            layers = _sym_layers(self.pattern, self.stitch_keys,
                                 self.uids, self.sym_ops)
            self._all_keys = [k for ks, _u, _m in layers for k in ks]
            self._all_uids = [u for _k, us, _m in layers for u in us]
            for k in self._all_keys:
                s = self.pattern.stitches.get(k)
                if s:
                    self._before[k] = s
            for inst in self.pattern.instances:
                if inst.uid in self._all_uids:
                    self._inst_before[inst.uid] = inst.layer
        # two-phase: remove all selected keys, then reinsert on target layer
        src = {}
        for k in self._all_keys:
            s = self.pattern.stitches.get(k)
            if s is not None:
                src[k] = s
        for k in src:
            self.pattern.stitches.pop(k, None)
        self._new_keys = []
        self._newkey_set = set()
        self._displaced = {}
        for s in src.values():
            ns = s if s.layer == self.layer_id else replace(
                s, layer=self.layer_id)
            existing = self.pattern.stitches.get(ns.key)
            if existing is not None and ns.key not in self._newkey_set:
                # stash the displaced stitch so undo restores it
                self._displaced[ns.key] = existing
            self.pattern.stitches[ns.key] = ns
            self._newkey_set.add(ns.key)
            self._new_keys.append(ns.key)
        for inst in self.pattern.instances:
            if inst.uid in self._all_uids:
                inst.layer = self.layer_id
        _set_selection(self.selection, self._new_keys, self._all_uids)

    def undo(self):
        for ns_key in self._new_keys:
            s = self.pattern.stitches.get(ns_key)
            if s is not None and s.layer == self.layer_id:
                self.pattern.stitches.pop(ns_key, None)
        for k, s in self._displaced.items():
            self.pattern.stitches[k] = s
        for k, s in self._before.items():
            self.pattern.stitches[k] = s
        for inst in self.pattern.instances:
            if inst.uid in self._inst_before:
                inst.layer = self._inst_before[inst.uid]
        _set_selection(self.selection, self.stitch_keys, self.uids)
        self._new_keys = []


class SplitStitchCommand(QUndoCommand):
    """Split selected backstitches in half along their drawn span.

    A backstitch keeps its integer endpoints a->b plus trim fractions
    ta/tb, so splitting produces two stitches covering [ta,mid] and
    [mid,tb]. Repeatable for quarters, eighths, etc.
    """

    def __init__(self, pattern, stitch_keys, text="Split stitch in half",
                 selection=None, sym_ops=None):
        super().__init__(text)
        self.pattern = pattern
        self.stitch_keys = list(stitch_keys)
        self.selection = selection
        self.sym_ops = list(sym_ops or [])
        self._before = {}   # old key -> Stitch
        self._new_keys = []  # (key_a, key_b) per split
        self._all_keys: list = []

    def _halves(self, s):
        mid = (s.ta + s.tb) / 2.0
        return (Stitch(s.kind, s.a, s.b, s.color, s.layer, s.ta, mid),
                Stitch(s.kind, s.a, s.b, s.color, s.layer, mid, s.tb))

    def redo(self):
        if not self._before:
            layers = _sym_layers(self.pattern, self.stitch_keys, [],
                                 self.sym_ops)
            self._all_keys = [k for ks, _u, _m in layers for k in ks]
            for k in self._all_keys:
                s = self.pattern.stitches.get(k)
                if s is not None and s.kind is StitchKind.BACK \
                        and s.tb - s.ta > 1e-9:
                    self._before[k] = s
        self._new_keys = []
        for k, s in self._before.items():
            self.pattern.stitches.pop(k, None)
            h1, h2 = self._halves(s)
            self.pattern.stitches[h1.key] = h1
            self.pattern.stitches[h2.key] = h2
            self._new_keys.extend([h1.key, h2.key])
        _set_selection(self.selection, self._new_keys, [])

    def undo(self):
        for k in self._new_keys:
            self.pattern.stitches.pop(k, None)
        for k, s in self._before.items():
            self.pattern.stitches[k] = s
        _set_selection(self.selection, self.stitch_keys, [])
        self._new_keys = []


class ClipBehindCommand(QUndoCommand):
    """Remove the parts of non-selected stitches lying inside the closed
    shape formed by the selected backstitches.

    Backstitches crossing the boundary are trimmed (possibly producing
    half/quarter stitches via ta/tb); fully covered stitches are removed.
    Selected stitches themselves are never clipped; only backstitch
    segments among them act as the boundary.
    """

    def __init__(self, pattern, boundary_keys, text="Hide behind selection",
                 boundary_uids=None, library_blocks=None):
        super().__init__(text)
        self.pattern = pattern
        self.boundary_keys = list(boundary_keys)
        self.boundary_uids = list(boundary_uids or [])
        self.library_blocks = library_blocks or {}
        self._removed: dict = {}
        self._added: list = []
        self._applied = False
        self.stats = (0, 0)  # (stitches removed/trimmed, pieces added)

    # -- geometry helpers -------------------------------------------------
    @staticmethod
    def _pieces(s: Stitch, inside):
        """Return list of replacement stitches for s, or [s] if unchanged."""
        if s.kind is not StitchKind.BACK:
            # X stitches are atomic: drop only when their cell center is inside
            return [] if inside(s.a[0] + 0.5, s.a[1] + 0.5) else [s]
        span = (s.tb - s.ta) * max(
            abs(s.b[0] - s.a[0]), abs(s.b[1] - s.a[1]), 1e-9)
        n = max(4, int(math.ceil(span * clip.SUB * 2)))
        kept = []
        for i in range(n):
            t = s.ta + (s.tb - s.ta) * (i + 0.5) / n
            x = s.a[0] + (s.b[0] - s.a[0]) * t
            y = s.a[1] + (s.b[1] - s.a[1]) * t
            kept.append(not inside(x, y))
        # runs of kept bins -> trim ranges
        pieces = []
        i = 0
        while i < n:
            if not kept[i]:
                i += 1
                continue
            j = i
            while j < n and kept[j]:
                j += 1
            t0 = s.ta + (s.tb - s.ta) * i / n
            t1 = s.ta + (s.tb - s.ta) * j / n
            if j - i == n:
                return [s]  # fully kept
            pieces.append(Stitch(s.kind, s.a, s.b, s.color, s.layer,
                                 t0, t1))
            i = j
        return pieces

    def redo(self):
        if self._applied:
            return
        self._applied = True
        p = self.pattern
        boundary = set()
        segs = []
        for k in self.boundary_keys:
            s = p.stitches.get(k)
            if s is not None and s.kind is StitchKind.BACK and s.b:
                boundary.add(k)
                pa, pb = s.endpoints()
                segs.append((pa[0], pa[1], pb[0], pb[1]))
        # block instances contribute their resolved backstitches as walls
        for inst in p.instances:
            if inst.uid not in self.boundary_uids:
                continue
            for s in inst.resolve(p.blocks, self.library_blocks):
                if s.kind is StitchKind.BACK and s.b:
                    pa, pb = s.endpoints()
                    segs.append((pa[0], pa[1], pb[0], pb[1]))
        if not segs:
            return
        inside = clip.build_inside_test(segs, p.width, p.height)
        keep_keys = set(p.stitches) - boundary
        added_by_key = {}
        for k in list(keep_keys):
            s = p.stitches[k]
            pieces = self._pieces(s, inside)
            if pieces == [s]:
                continue
            self._removed[k] = s
            for pc in pieces:
                if pc.key in boundary or pc.key in added_by_key:
                    continue
                if pc.key in p.stitches and pc.key not in self._removed:
                    continue  # don't clobber an untouched stitch
                added_by_key[pc.key] = pc
        for k in self._removed:
            p.stitches.pop(k, None)
        for pc in added_by_key.values():
            p.stitches[pc.key] = pc
        self._added = list(added_by_key)
        self.stats = (len(self._removed), len(self._added))

    def undo(self):
        if not self._applied:
            return
        for k in self._added:
            self.pattern.stitches.pop(k, None)
        for k, s in self._removed.items():
            self.pattern.stitches[k] = s
        self._removed.clear()
        self._added = []
        self._applied = False
