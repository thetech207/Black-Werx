"""Block editor dialog: edit a Block definition on a scratch canvas."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
                               QLabel, QDialogButtonBox)
from PySide6.QtGui import QUndoStack, QKeySequence, QShortcut

from ..core.block import Block, BlockInstance
from ..core.model import Pattern, Stitch, Transform
from ..core import palette
from .canvas import PatternCanvas, Tool
from .commands import DrawStitchesCommand, EraseStitchesCommand


class BlockEditorDialog(QDialog):
    """Edit a block's stitches standalone.

    The block is copied into a scratch Pattern for editing; on accept the
    (possibly resized) content is written back into the Block.
    """

    PAD = 4

    def __init__(self, block: Block, registry: dict, parent=None):
        super().__init__(parent)
        self.block = block
        self.registry = dict(registry)  # id -> Block for nested rendering
        self.setWindowTitle(f"Edit block: {block.name}")
        self.resize(700, 500)

        # ---- scratch pattern sized to content ----
        bb = block.bbox() or (0, 0, 10, 10)
        w = bb[2] - bb[0] + 1 + 2 * self.PAD
        h = bb[3] - bb[1] + 1 + 2 * self.PAD
        self.offset = (bb[0] - self.PAD, bb[1] - self.PAD)
        self.pattern = Pattern(width=max(w, 20), height=max(h, 20),
                               name=block.name)
        self.pattern.blocks = dict(self.registry)
        self.pattern.blocks[block.id] = block
        # load block content translated into scratch space
        # copy raw stitches translated (preserving nested instances below)
        for s in block.stitches:
            self.pattern.add_stitch(Stitch(
                s.kind, (s.a[0] - self.offset[0], s.a[1] - self.offset[1]),
                (s.b[0] - self.offset[0], s.b[1] - self.offset[1]) if s.b else None,
                s.color))
        # nested instances translated
        for inst in block.instances:
            ni = BlockInstance(
                uid=inst.uid, block_id=inst.block_id, scope=inst.scope,
                transform=Transform(
                    inst.transform.m00, inst.transform.m01,
                    inst.transform.m10, inst.transform.m11,
                    inst.transform.tx - self.offset[0],
                    inst.transform.ty - self.offset[1]),
                linked=inst.linked, recolor=dict(inst.recolor))
            self.pattern.instances.append(ni)

        # ---- UI ----
        layout = QVBoxLayout(self)
        self.canvas = PatternCanvas(self)
        self.canvas.set_pattern(self.pattern)
        self.canvas.library_blocks = self.registry
        self.undos = QUndoStack(self)
        self.canvas.tool = Tool.PENCIL
        self.canvas.current_color = "#000000"

        self.canvas.draw_stitches.connect(self._on_draw)
        self.canvas.erase_cells.connect(self._on_erase)
        layout.addWidget(self.canvas)

        toolbar = QHBoxLayout()
        for tool, label in [(Tool.PENCIL, "Stitch"), (Tool.BACKSTITCH, "Backstitch"),
                            (Tool.ERASER, "Eraser"), (Tool.PAN, "Pan")]:
            b = QPushButton(label)
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, t=tool: self._set_tool(t, b))
            toolbar.addWidget(b)
            if tool is Tool.PENCIL:
                b.setChecked(True)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                   QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        QShortcut(QKeySequence.StandardKey.Undo, self, self.undos.undo)
        QShortcut(QKeySequence.StandardKey.Redo, self, self.undos.redo)

    def _set_tool(self, tool, btn):
        self.canvas.tool = tool
        # uncheck siblings
        for w in self.findChildren(QPushButton):
            if w.isCheckable() and w is not btn:
                w.setChecked(False)

    def _on_draw(self, stitches):
        cmd = DrawStitchesCommand(self.pattern, stitches)
        self.undos.push(cmd)
        self.canvas.refresh()

    def _on_erase(self, cells):
        keys = []
        for c in cells:
            for s in self.pattern.get_stitches_in_cell(c):
                keys.append(s.key)
        if keys:
            self.undos.push(EraseStitchesCommand(self.pattern, keys))
            self.canvas.refresh()

    def _on_accept(self):
        # write back: raw stitches translated by offset
        self.block.stitches = [
            Stitch(s.kind, (s.a[0] + self.offset[0], s.a[1] + self.offset[1]),
                   (s.b[0] + self.offset[0], s.b[1] + self.offset[1]) if s.b else None,
                   s.color)
            for s in self.pattern.stitches.values()
        ]
        self.block.instances = []
        for inst in self.pattern.instances:
            t = inst.transform
            self.block.instances.append(BlockInstance(
                uid=inst.uid, block_id=inst.block_id, scope=inst.scope,
                transform=Transform(t.m00, t.m01, t.m10, t.m11,
                                    t.tx + self.offset[0],
                                    t.ty + self.offset[1]),
                linked=inst.linked, recolor=dict(inst.recolor)))
        self.accept()
