import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from blackwerx.app import MainWindow
from blackwerx.core.model import Stitch, StitchKind, Transform
from blackwerx.core.block import Block, BlockInstance
from blackwerx.gui.panels import make_block_from_stitches
from blackwerx.gui.commands import (DrawStitchesCommand, PlaceBlockCommand,
                                    ExplodeCommand, DeleteSelectionCommand,
                                    CopySelectionCommand, MoveStitchesCommand)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def win(qapp):
    w = MainWindow()
    yield w
    w.close()


def test_window_starts(win):
    assert win.pattern.width == 100


def test_draw_undo_redo(win):
    s = Stitch(StitchKind.X, (5, 5), None, "#000000")
    win.undo_stack.push(DrawStitchesCommand(win.pattern, [s]))
    assert win.pattern.stitch_count() == 1
    win.undo_stack.undo()
    assert win.pattern.stitch_count() == 0
    win.undo_stack.redo()
    assert win.pattern.stitch_count() == 1


def test_block_place_and_explode(win):
    b = Block(id="tb", name="test")
    b.stitches = [Stitch(StitchKind.X, (0, 0), None, "#ff0000"),
                  Stitch(StitchKind.X, (1, 0), None, "#ff0000")]
    win.pattern.blocks["tb"] = b
    inst = BlockInstance(uid="i1", block_id="tb", scope="project",
                         transform=Transform.translation(10, 10))
    win.undo_stack.push(PlaceBlockCommand(win.pattern, inst))
    # resolved stitches visible via canvas cache
    resolved = win.canvas.resolved_stitches(inst)
    assert len(resolved) == 2
    # flatten explode
    win.undo_stack.push(ExplodeCommand(win.pattern, inst, "flatten",
                                       win.library_blocks))
    assert inst not in win.pattern.instances
    assert win.pattern.stitch_count() == 2
    win.undo_stack.undo()  # restore instance, remove flattened stitches
    assert inst in win.pattern.instances
    assert win.pattern.stitch_count() == 0


def test_make_block_from_selection_normalizes(win):
    stitches = [Stitch(StitchKind.X, (5, 5), None, "#000"),
                Stitch(StitchKind.X, (7, 6), None, "#000")]
    b = make_block_from_stitches("norm", stitches)
    pts = [s.a for s in b.stitches]
    assert min(p[0] for p in pts) == 0
    assert min(p[1] for p in pts) == 0


def test_save_load_roundtrip(win, tmp_path):
    from blackwerx.core import project as pio
    s = Stitch(StitchKind.X, (1, 1), None, "dmc:310")
    win.pattern.add_stitch(s)
    path = pio.save_project(win.pattern, tmp_path / "t.bwpx")
    p2 = pio.load_project(path)
    assert p2.stitch_count() == 1


def test_delete_selection(win):
    s1 = Stitch(StitchKind.X, (1, 1), None, "#000")
    s2 = Stitch(StitchKind.X, (2, 2), None, "#000")
    win.undo_stack.push(DrawStitchesCommand(win.pattern, [s1, s2]))
    win.canvas.selection.stitch_keys = {s1.key, s2.key}
    win.delete_selection()
    assert win.pattern.stitch_count() == 0


def test_duplicate_never_clobbers_originals(win):
    # an offset copy landing on an occupied cell must not replace the
    # stitch already there
    sel = Stitch(StitchKind.X, (5, 5), None, "#000")
    other = Stitch(StitchKind.X, (6, 6), None, "#f00")
    win.pattern.add_stitch(sel)
    win.pattern.add_stitch(other)
    cmd = CopySelectionCommand(win.pattern, [sel.key], [], [(1, 1, 0, 0, 0)],
                               selection=win.canvas.selection)
    win.undo_stack.push(cmd)
    assert cmd.skipped == 1
    assert win.pattern.stitches.get(other.key) == other
    assert win.pattern.stitches.get(sel.key) == sel
    assert win.pattern.stitch_count() == 2
    win.undo_stack.undo()
    assert win.pattern.stitches.get(sel.key) == sel
    assert win.pattern.stitches.get(other.key) == other


def test_duplicate_on_top_uses_free_active_layer(win):
    # active layer free of the selection -> literal same-position copy
    win.pattern.layers.append(
        {"id": "layer2", "name": "L2", "visible": True,
         "locked": False, "color": None})
    win.pattern.active_layer = "layer2"
    s = Stitch(StitchKind.X, (5, 5), None, "#000")
    win.pattern.add_stitch(s)
    win.canvas.selection.stitch_keys = {s.key}
    win.duplicate_selection()
    assert win.pattern.stitch_count() == 2
    copies = [st for st in win.pattern.stitches.values()
              if st.layer == "layer2"]
    assert len(copies) == 1 and copies[0].a == (5, 5)
    win.undo_stack.undo()
    assert win.pattern.stitch_count() == 1
    assert win.pattern.stitches.get(s.key) == s


def test_move_displaced_stitch_restored_on_undo(win):
    a = Stitch(StitchKind.X, (1, 1), None, "#000")
    b = Stitch(StitchKind.X, (2, 1), None, "#f00")
    win.pattern.add_stitch(a)
    win.pattern.add_stitch(b)
    win.undo_stack.push(
        MoveStitchesCommand(win.pattern, [a.key], [], 1, 0))
    # b is displaced by the moved stitch but must come back on undo
    assert win.pattern.stitch_count() == 1
    win.undo_stack.undo()
    assert win.pattern.stitches.get(a.key) == a
    assert win.pattern.stitches.get(b.key) == b
    assert win.pattern.stitch_count() == 2


def test_move_selected_stitches_no_interference(win):
    # moving a pair right by 1: A lands where B was — B must still move
    # to its own target, not be eaten or moved twice
    a = Stitch(StitchKind.X, (1, 1), None, "#000")
    b = Stitch(StitchKind.X, (2, 1), None, "#f00")
    win.pattern.add_stitch(a)
    win.pattern.add_stitch(b)
    win.undo_stack.push(
        MoveStitchesCommand(win.pattern, [a.key, b.key], [], 1, 0))
    assert win.pattern.stitch_count() == 2
    loc = {s.a: s.color for s in win.pattern.stitches.values()}
    assert loc[(2, 1)] == "#000"
    assert loc[(3, 1)] == "#f00"
    win.undo_stack.undo()
    assert win.pattern.stitches.get(a.key) == a
    assert win.pattern.stitches.get(b.key) == b
