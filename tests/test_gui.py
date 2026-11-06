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
                                    ExplodeCommand, DeleteSelectionCommand)


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
