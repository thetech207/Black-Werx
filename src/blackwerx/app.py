"""Black-Werx main window."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QAction, QKeySequence, QColor, QIcon, QPixmap
from PySide6.QtWidgets import (QMainWindow, QApplication, QWidget,
                               QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
                               QToolBar, QDockWidget, QFileDialog,
                               QMessageBox, QInputDialog, QDialog,
                               QFormLayout, QComboBox, QCheckBox, QSpinBox,
                               QDoubleSpinBox, QDialogButtonBox, QMenu)
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QUndoView

from .core.model import Pattern, Stitch, StitchKind, Transform
from .core.block import Block, BlockInstance
from .core.library import Library
from .core import project as project_io
from .core import palette
from .core.exporters import pdf as pdf_exp, image as img_exp, svg as svg_exp, pat as pat_exp
from .gui.canvas import PatternCanvas, Tool, CELL
from .gui.panels import ColorPanel, LibraryPanel, make_block_from_stitches, color_icon
from .gui.commands import (DrawStitchesCommand, EraseStitchesCommand,
                           DeleteSelectionCommand, MoveStitchesCommand,
                           TransformInstancesCommand, RecolorCommand,
                           PlaceBlockCommand, ExplodeCommand,
                           TransformSelectionCommand, CopySelectionCommand)
from .gui.block_editor import BlockEditorDialog
from .gui.svg_import_dialog import SvgImportDialog
from .gui.rulers import Ruler


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Black-Werx")
        self.resize(1200, 800)

        self.pattern = Pattern()
        self.library = Library()
        self.library_blocks = {b.id: b for b in self.library.all()}
        self.undo_stack = QUndoStack(self)
        self._file_path = None
        self._extra_dirty = False   # non-undoable edits (canvas setup)
        self._saved_index = 0       # undo index at last save
        self._mru = []

        self._build_ui()
        self._build_menus()
        self._wire_canvas()
        self._refresh_all()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        central = QWidget()
        grid = QGridLayout(central)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(0)

        self.canvas = PatternCanvas(self)
        corner = QLabel("")
        corner.setFixedSize(22, 22)
        corner.setStyleSheet("background:#ececec; border-right:1px solid #bbb;"
                             " border-bottom:1px solid #bbb;")
        self.h_ruler = Ruler(self.canvas, Qt.Orientation.Horizontal)
        self.v_ruler = Ruler(self.canvas, Qt.Orientation.Vertical)
        grid.addWidget(corner, 0, 0)
        grid.addWidget(self.h_ruler, 0, 1)
        grid.addWidget(self.v_ruler, 1, 0)
        grid.addWidget(self.canvas, 1, 1)
        grid.setRowStretch(1, 1)
        grid.setColumnStretch(1, 1)
        self.setCentralWidget(central)

        # keep rulers in sync with view transform + scrolling
        self.canvas.view_changed.connect(self._refresh_rulers)
        self.canvas.horizontalScrollBar().valueChanged.connect(
            self._refresh_rulers)
        self.canvas.verticalScrollBar().valueChanged.connect(
            self._refresh_rulers)

        # left tool sidebar
        tb = QToolBar("Tools")
        tb.setIconSize(QSize(22, 22))
        tb.setMovable(False)
        self.addToolBar(Qt.ToolBarArea.LeftToolBarArea, tb)
        self.tool_group = []
        for tool, label in [
            (Tool.PENCIL, "X Stitch"), (Tool.XLINE, "X Line"),
            (Tool.BACKSTITCH, "Backstitch"),
            (Tool.ERASER, "Eraser"),
            (Tool.SELECT, "Select"), (Tool.MOVE, "Move"),
            (Tool.ROTATE, "Rotate"),
            (Tool.BLOCK, "Place Block"), (Tool.PAN, "Pan"),
        ]:
            act = QAction(label, self)
            act.setCheckable(True)
            act.triggered.connect(lambda _=False, t=tool: self._set_tool(t))
            tb.addAction(act)
            self.tool_group.append((tool, act))
        self._set_tool(Tool.PENCIL)

        # options bar (top): array copies + line width
        otb = QToolBar("Options")
        otb.setMovable(False)
        self.addToolBar(otb)
        otb.addWidget(QLabel("Copies:"))
        self.copies_spin = QSpinBox()
        self.copies_spin.setRange(0, 50)
        self.copies_spin.setValue(0)
        self.copies_spin.setToolTip(
            "Array copies for Move/Rotate: 0 moves the original, "
            "N makes N copies spaced by the drag delta/angle")
        self.copies_spin.valueChanged.connect(self._on_copies_changed)
        otb.addWidget(self.copies_spin)
        otb.addSeparator()
        otb.addWidget(QLabel("Line width:"))
        self.width_spin = QSpinBox()
        self.width_spin.setRange(1, 12)
        self.width_spin.setValue(1)
        self.width_spin.setToolTip("X Line thickness in stitches")
        self.width_spin.valueChanged.connect(
            lambda v: setattr(self.canvas, "line_width", v))
        otb.addWidget(self.width_spin)

        # undo view dock
        self.undo_view = QUndoView(self.undo_stack)
        udock = QDockWidget("History", self)
        udock.setWidget(self.undo_view)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, udock)
        udock.hide()

        # right dock: colors + library stacked
        right = QWidget()
        rlay = QVBoxLayout(right)
        rlay.setContentsMargins(4, 4, 4, 4)
        self.color_panel = ColorPanel()
        self.library_panel = LibraryPanel()
        rlay.addWidget(self.color_panel)
        rlay.addWidget(self.library_panel, 1)
        rdock = QDockWidget("Palette & Library", self)
        rdock.setWidget(right)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, rdock)

        self._refresh_rulers()
        self.status_info = QLabel("0 stitches")
        self.statusBar().addPermanentWidget(self.status_info)

    def _refresh_rulers(self, *_):
        self.h_ruler.update()
        self.v_ruler.update()

    def _build_menus(self):
        mb = self.menuBar()
        # File
        m = mb.addMenu("&File")
        self._act(m, "&New", self.new_project, "Ctrl+N")
        self._act(m, "&Open…", self.open_project, "Ctrl+O")
        self._act(m, "&Save", self.save_project, "Ctrl+S")
        self._act(m, "Save &As…", self.save_project_as, "Ctrl+Shift+S")
        m.addSeparator()
        self._act(m, "&Import SVG…", self.import_svg)
        em = m.addMenu("&Export")
        self._act(em, "PDF (symbol chart)…", lambda: self.export("pdf", "symbol"))
        self._act(em, "PDF (realistic)…", lambda: self.export("pdf", "realistic"))
        self._act(em, "PNG (symbol chart)…", lambda: self.export("png", "symbol"))
        self._act(em, "PNG (realistic)…", lambda: self.export("png", "realistic"))
        self._act(em, "SVG (symbol chart)…", lambda: self.export("svg", "symbol"))
        self._act(em, "SVG (realistic)…", lambda: self.export("svg", "realistic"))
        self._act(em, "Stitch file (.pat)…", lambda: self.export("pat", None))
        m.addSeparator()
        self._act(m, "E&xit", self.close, "Ctrl+Q")

        # Edit
        m = mb.addMenu("&Edit")
        self._act(m, "&Undo", self.undo_stack.undo, "Ctrl+Z")
        self._act(m, "&Redo", self.undo_stack.redo, "Ctrl+Y")
        m.addSeparator()
        self._act(m, "&Delete Selection", self.delete_selection, "Del")
        self._act(m, "&Duplicate", self.duplicate_selection, "Ctrl+D")
        m.addSeparator()
        self._act(m, "Select &All", self.select_all, "Ctrl+A")
        self._act(m, "&Clear Selection", self.clear_selection, "Esc")
        m.addSeparator()
        self._act(m, "Canvas &setup…", self.canvas_setup)
        m.addSeparator()
        m2 = m.addMenu("&Rotate Selection 90°")
        self._act(m2, "90°", lambda: self.transform_instances("rot90"))
        self._act(m2, "180°", lambda: self.transform_instances("rot180"))
        self._act(m2, "270°", lambda: self.transform_instances("rot270"))
        m3 = m.addMenu("&Flip Selection")
        self._act(m3, "Horizontal", lambda: self.transform_instances("flipx"))
        self._act(m3, "Vertical", lambda: self.transform_instances("flipy"))
        self._act(m, "Recolor selection…", self.recolor_selection)

        # View
        m = mb.addMenu("&View")
        self._act(m, "Zoom &In", lambda: self.canvas.zoom_centered(1.25), "Ctrl++")
        self._act(m, "Zoom &Out", lambda: self.canvas.zoom_centered(0.8), "Ctrl+-")
        self._act(m, "&Reset Zoom", self.canvas.resetTransform, "Ctrl+0")
        m.addSeparator()
        self.sym_actions = {}
        for axis, label in [("h", "Mirror left/right"), ("v", "Mirror top/bottom"),
                            ("d", "Mirror diagonal"), ("ad", "Mirror anti-diagonal")]:
            act = QAction(label, self)
            act.setCheckable(True)
            act.triggered.connect(lambda _=False, a=axis: self._toggle_sym(a))
            m.addAction(act)
            self.sym_actions[axis] = act

        # Blocks
        m = mb.addMenu("&Blocks")
        self._act(m, "New block from selection", self.new_block_from_selection)
        self._act(m, "Explode selection (flatten)", lambda: self.explode_selected("flatten"))
        self._act(m, "Explode selection (unlink)", lambda: self.explode_selected("unlink"))

        # Help
        m = mb.addMenu("&Help")
        self._act(m, "&About", self.about)

    def _act(self, menu, text, fn, shortcut=None):
        act = QAction(text, self)
        if shortcut:
            act.setShortcut(QKeySequence(shortcut))
        act.triggered.connect(fn)
        menu.addAction(act)
        return act

    # ------------------------------------------------------------- wiring
    def _wire_canvas(self):
        c = self.canvas
        c.set_pattern(self.pattern)
        c.library_blocks = self.library_blocks
        c.current_color = self.color_panel.current_spec
        c.draw_stitches.connect(self._on_draw_stitches)
        c.erase_cells.connect(self._on_erase_cells)
        c.place_block.connect(self._on_place_block)
        c.move_selection.connect(self._on_move_selection)
        c.rotate_selection.connect(self._on_rotate_selection)
        c.tool_changed.connect(self._on_canvas_tool_changed)
        c.context_menu.connect(self._on_context_menu)
        c.cursor_cell_changed.connect(
            lambda x, y: self.statusBar().showMessage(f"cell {x}, {y}"))
        c.selection_changed.connect(self._update_status)
        self.color_panel.color_changed.connect(self._on_color_changed)
        self.library_panel.place_requested.connect(self._on_library_place)
        self.library_panel.new_from_selection.connect(self.new_block_from_selection)
        self.library_panel.edit_requested.connect(self._on_edit_block)
        self.library_panel.delete_requested.connect(self._on_delete_block)
        self.library_panel.promote_requested.connect(self._on_promote_block)

    def _refresh_all(self):
        # keep canvas registry in sync so promoted global blocks resolve
        self.canvas.library_blocks = {**self.library_blocks,
                                      **self.pattern.blocks}
        self.library_panel.global_blocks = dict(self.library_blocks)
        self.library_panel.project_blocks = dict(self.pattern.blocks)
        self.library_panel.refresh()
        self._update_status()

    def _update_status(self):
        n = self.pattern.stitch_count()
        self.status_info.setText(f"{n} stitches")
        self.setWindowTitle(
            f"Black-Werx — {self.pattern.name}" +
            (f" — {self._file_path.name}" if self._file_path else ""))

    def _on_copies_changed(self, v):
        self.canvas.copies_count = v
        self.canvas._update_tool_label()

    # -- MRU / right-click context menu -----------------------------------
    def _record(self, label, fn):
        self._mru = [(l, f) for l, f in self._mru if l != label]
        self._mru.insert(0, (label, fn))
        del self._mru[12:]

    def _on_context_menu(self, viewport_pos):
        menu = QMenu(self)
        for label, fn in self._mru:
            if label == "Tool: Select":
                continue  # select is what right-click returns to anyway
            menu.addAction(label, fn)
        if not self._mru:
            menu.addAction("(no recent commands)").setEnabled(False)
        menu.exec(self.canvas.viewport().mapToGlobal(viewport_pos))

    def _on_canvas_tool_changed(self, tool):
        for t, act in self.tool_group:
            act.setChecked(t is tool)
        names = {Tool.PENCIL: "X Stitch", Tool.XLINE: "X Line",
                 Tool.BACKSTITCH: "Backstitch", Tool.ERASER: "Eraser",
                 Tool.SELECT: "Select", Tool.MOVE: "Move",
                 Tool.ROTATE: "Rotate",
                 Tool.BLOCK: "Place Block", Tool.PAN: "Pan"}
        self._record(f"Tool: {names.get(tool, tool)}",
                     lambda t=tool: self._set_tool(t))

    def _set_tool(self, tool):
        self.canvas.set_tool(tool)
        if tool is Tool.BLOCK and self.canvas.pending_block is None:
            self.statusBar().showMessage(
                "Select a block in the library panel, then click to place.")

    def _toggle_sym(self, axis):
        if self.sym_actions[axis].isChecked():
            self.canvas.symmetry_axes.add(axis)
        else:
            self.canvas.symmetry_axes.discard(axis)

    def canvas_setup(self):
        dlg = CanvasSetupDialog(self.pattern, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            v = dlg.values()
            self.pattern.aida_count = v["aida"]
            if v["size_mode"] == "inches":
                self.pattern.width = max(1, round(v["size_w"] * v["aida"]))
                self.pattern.height = max(1, round(v["size_h"] * v["aida"]))
            else:
                self.pattern.width = max(1, round(v["size_w"]))
                self.pattern.height = max(1, round(v["size_h"]))
            self.canvas._update_scene_rect()
            self.canvas.centerOn(self.canvas.pattern_center_scene())
            self.canvas.viewport().update()
            self.pattern.stitch_w_mm = v["w"]
            self.pattern.stitch_h_mm = v["h"]
            self._extra_dirty = True
            self.statusBar().showMessage(
                f"Fabric: {v['aida']} ct aida, stitch "
                f"{v['w']}×{v['h']} mm")

    def _on_color_changed(self, spec):
        self.canvas.current_color = spec
        self.canvas.refresh_cursor()

    # ------------------------------------------------------- canvas events
    def _on_draw_stitches(self, stitches):
        self.undo_stack.push(DrawStitchesCommand(self.pattern, stitches))
        self.canvas.refresh()
        self._update_status()

    def _on_erase_cells(self, cells):
        keys = []
        for c in cells:
            for s in self.pattern.get_stitches_in_cell(c):
                keys.append(s.key)
        # also erase backstitches passing near cell
        keys = list(dict.fromkeys(keys))
        if keys:
            self.undo_stack.push(EraseStitchesCommand(self.pattern, keys))
            self.canvas.refresh()
            self._update_status()

    def _on_place_block(self, block, scope, gx, gy, anchor,
                        rot=0, mx=False, my=False):
        self._place_block_at(block, scope, gx, gy, anchor, rot, mx, my)

    def _on_library_place(self, payload):
        block, scope = payload
        self.canvas.set_pending_block(block, scope)
        self._set_tool(Tool.BLOCK)
        self.statusBar().showMessage(
            f"Click to place '{block.name}' ({scope}). "
            "1-9 anchor, R rotate, F/V flip, right-click done.")

    def _place_block_at(self, block, scope, gx, gy, anchor=5,
                        rot=0, mx=False, my=False):
        bb = block.bbox() or (0, 0, 0, 0)
        fx, fy = PatternCanvas.PLACE_ANCHORS.get(anchor, (0.5, 0.5))
        ax = int(round(bb[0] + fx * (bb[2] - bb[0])))
        ay = int(round(bb[1] + fy * (bb[3] - bb[1])))
        # pending rot/mirror about the anchor point, in block-local space
        inner = Transform.from_semantic(0, 0, rot, mx, my)
        local = (Transform.translation(-ax, -ay)
                 .then(inner)
                 .then(Transform.translation(ax, ay)))
        inst = BlockInstance(
            uid=self.pattern.next_instance_id(),
            block_id=block.id, scope=scope,
            transform=local.then(Transform.translation(gx - ax, gy - ay)),
            linked=True)
        self.undo_stack.push(PlaceBlockCommand(self.pattern, inst))
        self.canvas.refresh()
        self._update_status()

    # ------------------------------------------------------------ editing
    def delete_selection(self):
        sel = self.canvas.selection
        if sel.empty:
            return
        self._record("Edit: Delete Selection", self.delete_selection)
        self.undo_stack.push(DeleteSelectionCommand(
            self.pattern, sel.stitch_keys, sel.instance_uids))
        sel.clear()
        self.canvas.refresh()
        self.selection_changed = True
        self._update_status()

    def select_all(self):
        self.canvas.selection.stitch_keys = set(self.pattern.stitches.keys())
        self.canvas.selection.instance_uids = {i.uid for i in self.pattern.instances}
        self.canvas.viewport().update()

    def clear_selection(self):
        self.canvas.selection.clear()
        self.canvas.viewport().update()

    def transform_instances(self, op):
        uids = self.canvas.selection.instance_uids
        if uids:
            lib = {**self.library_blocks, **self.pattern.blocks}
            self.undo_stack.push(
                TransformInstancesCommand(self.pattern, uids, op,
                                          library_blocks=lib))
            self._record(f"Edit: Transform ({op})",
                         lambda o=op: self.transform_instances(o))
            self.canvas.refresh()

    # -- move / rotate / duplicate -----------------------------------------
    def _sel_ids(self):
        return (list(self.canvas.selection.stitch_keys),
                list(self.canvas.selection.instance_uids))

    def _on_move_selection(self, dx, dy, copies):
        keys, uids = self._sel_ids()
        if copies <= 0:
            self.undo_stack.push(MoveStitchesCommand(
                self.pattern, keys, uids, dx, dy))
        else:
            specs = [(k * dx, k * dy, 0, 0, 0)
                     for k in range(1, copies + 1)]
            self.undo_stack.push(CopySelectionCommand(
                self.pattern, keys, uids, specs,
                text=f"Move +{copies} copies"))
        self.canvas.refresh()
        self._update_status()

    def _on_rotate_selection(self, cx, cy, q, copies):
        keys, uids = self._sel_ids()
        if copies <= 0:
            self.undo_stack.push(TransformSelectionCommand(
                self.pattern, keys, uids, cx, cy, q))
        else:
            specs = [(0, 0, cx, cy, (k * q) % 4)
                     for k in range(1, copies + 1)]
            self.undo_stack.push(CopySelectionCommand(
                self.pattern, keys, uids, specs,
                text=f"Rotate +{copies} copies"))
        self.canvas.refresh()
        self._update_status()

    def duplicate_selection(self):
        """Copy selection offset by (1,1), select the copies, enter Move."""
        sel = self.canvas.selection
        if sel.empty:
            self.statusBar().showMessage("Select stitches or blocks first.")
            return
        self._record("Edit: Duplicate", self.duplicate_selection)
        keys, uids = self._sel_ids()
        cmd = CopySelectionCommand(
            self.pattern, keys, uids, [(1, 1, 0, 0, 0)], text="Duplicate")
        self.undo_stack.push(cmd)
        # select only the fresh copies so Move acts on them
        sel.stitch_keys = set(cmd.created_stitch_keys)
        sel.instance_uids = set(cmd.created_uids)
        self.canvas.viewport().update()
        self._set_tool(Tool.MOVE)
        self.canvas.refresh()
        self._update_status()

    def recolor_selection(self):
        sel = self.canvas.selection
        if sel.empty:
            return
        color, ok = QColorDialog_getColor(self)
        if not ok:
            return
        new = color.name()
        # map every distinct current color in selection to new color
        old_colors = set()
        for k in sel.stitch_keys:
            s = self.pattern.stitches.get(k)
            if s:
                old_colors.add(s.color)
        for uid in sel.instance_uids:
            for inst in self.pattern.instances:
                if inst.uid == uid:
                    for s in inst.resolve(self.pattern.blocks, self.library_blocks):
                        old_colors.add(s.color)
        mapping = {c: new for c in old_colors}
        self._record("Edit: Recolor selection", self.recolor_selection)
        self.undo_stack.push(RecolorCommand(
            self.pattern, mapping, sel.stitch_keys, sel.instance_uids))
        self.canvas.refresh()

    def explode_selected(self, mode):
        uids = list(self.canvas.selection.instance_uids)
        if not uids:
            self.statusBar().showMessage("No block instances selected.")
            return
        self._record(f"Blocks: Explode ({mode})",
                     lambda m=mode: self.explode_selected(m))
        # group by mode semantics; one command per instance
        for uid in uids:
            inst = next((i for i in self.pattern.instances if i.uid == uid), None)
            if inst:
                self.undo_stack.push(ExplodeCommand(
                    self.pattern, inst, mode, self.library_blocks,
                    text=f"Explode ({mode})"))
        self.canvas.selection.instance_uids.clear()
        self.canvas.refresh()
        self._refresh_all()
        self._update_status()

    # ------------------------------------------------------------- blocks
    def new_block_from_selection(self):
        sel = self.canvas.selection
        stitches = [self.pattern.stitches[k] for k in sel.stitch_keys
                    if k in self.pattern.stitches]
        # include resolved stitches of selected instances
        for uid in sel.instance_uids:
            for inst in self.pattern.instances:
                if inst.uid == uid:
                    stitches.extend(inst.resolve(self.pattern.blocks,
                                                  self.library_blocks))
        if not stitches:
            self.statusBar().showMessage("Select stitches or instances first.")
            return
        name, ok = QInputDialog.getText(self, "New block", "Block name:")
        if not ok or not name:
            return
        self._record("Blocks: New block from selection",
                     self.new_block_from_selection)
        block = make_block_from_stitches(name, stitches)
        self.pattern.blocks[block.id] = block
        self._refresh_all()
        self.statusBar().showMessage(f"Block '{name}' created.")

    def _on_edit_block(self, payload):
        block, scope = payload
        registry = dict(self.library_blocks)
        registry.update(self.pattern.blocks)
        # don't let editor edit global def in place without save-to-global;
        # editing global edits the shared definition directly
        dlg = BlockEditorDialog(block, registry, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            if scope == "project":
                pass  # block mutated in place
            else:
                self.library.save()
            self.canvas.refresh()
            self._refresh_all()

    def _on_delete_block(self, payload):
        block, scope = payload
        if scope == "project":
            # refuse if instances still reference it
            refs = [i for i in self.pattern.instances if i.block_id == block.id]
            if refs:
                QMessageBox.warning(self, "In use",
                                    "Block is still placed in the pattern.")
                return
            del self.pattern.blocks[block.id]
        else:
            self.library.remove(block.id)
            self.library_blocks = {b.id: b for b in self.library.all()}
        self._refresh_all()

    def _on_promote_block(self, payload):
        block, scope = payload
        if scope != "project":
            return
        self.library.add(block)
        self.library_blocks = {b.id: b for b in self.library.all()}
        # re-scope existing instances? leave as project; new placements use global
        self._refresh_all()

    # ------------------------------------------------------------- files
    def new_project(self):
        self.pattern = Pattern()
        self._file_path = None
        self._extra_dirty = False
        self._saved_index = 0
        self.canvas.set_pattern(self.pattern)
        self.undo_stack.clear()
        self._refresh_all()

    def open_project(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open project", "", "Black-Werx project (*.bwpx)")
        if not path:
            return
        try:
            self.pattern = project_io.load_project(path)
        except Exception as e:
            QMessageBox.critical(self, "Open failed", str(e))
            return
        self._file_path = Path(path)
        self._extra_dirty = False
        self._saved_index = 0
        self.canvas.set_pattern(self.pattern)
        self.undo_stack.clear()
        self.library_blocks = {b.id: b for b in self.library.all()}
        self.canvas.library_blocks = self.library_blocks
        self._refresh_all()

    def save_project(self):
        if self._file_path is None:
            self.save_project_as()
            return
        project_io.save_project(self.pattern, self._file_path)
        self._mark_saved()
        self._update_status()

    def save_project_as(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save project", "", "Black-Werx project (*.bwpx)")
        if not path:
            return
        self._file_path = project_io.save_project(self.pattern, path)
        self._mark_saved()
        self._update_status()

    def _mark_saved(self):
        self._saved_index = self.undo_stack.index()
        self._extra_dirty = False

    def import_svg(self):
        dlg = SvgImportDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            r = dlg.get_result()
            if r is None:
                return
            self._record("File: Import SVG", self.import_svg)
            # place at center of current view-ish: offset so result centered
            # on pattern; simple: place at (2,2)
            ox, oy = 2, 2
            stitches = [Stitch(s.kind, (s.a[0] + ox, s.a[1] + oy),
                               (s.b[0] + ox, s.b[1] + oy) if s.b else None,
                               s.color)
                        for s in r.stitches]
            if dlg.as_block.isChecked():
                block = make_block_from_stitches("SVG import", stitches)
                self.pattern.blocks[block.id] = block
                inst = BlockInstance(
                    uid=self.pattern.next_instance_id(), block_id=block.id,
                    scope="project", transform=Transform.translation(0, 0))
                self.undo_stack.push(PlaceBlockCommand(self.pattern, inst))
            else:
                self.undo_stack.push(DrawStitchesCommand(self.pattern, stitches,
                                                         text="Import SVG"))
            self.canvas.refresh()
            self._refresh_all()
            self._update_status()

    # ------------------------------------------------------------- export
    def export(self, fmt, style):
        if self.pattern.stitch_count() == 0 and not self.pattern.instances:
            QMessageBox.information(self, "Export", "Pattern is empty.")
            return
        filters = {
            "pdf": "PDF (*.pdf)", "png": "PNG (*.png)",
            "svg": "SVG (*.svg)", "pat": "Tajima PAT (*.pat)",
        }
        path, _ = QFileDialog.getSaveFileName(
            self, f"Export {fmt.upper()}", "", filters[fmt])
        if not path:
            return
        try:
            lib = {b.id: b for b in self.library.all()}
            if fmt == "pdf":
                pdf_exp.export_pdf(self.pattern, path, style=style or "symbol",
                                   library_blocks=lib)
            elif fmt == "png":
                img_exp.export_png(self.pattern, path,
                                   style=style or "symbol", library_blocks=lib)
            elif fmt == "svg":
                svg_exp.export_svg(self.pattern, path,
                                   style=style or "realistic", library_blocks=lib)
            elif fmt == "pat":
                pat_exp.export_pat(self.pattern, path, library_blocks=lib)
            QMessageBox.information(self, "Export", f"Saved to {path}")
        except Exception as e:
            QMessageBox.critical(self, "Export failed", str(e))

    # -- close guard -------------------------------------------------------
    def _is_dirty(self):
        return (self.undo_stack.index() != self._saved_index
                or self._extra_dirty)

    def closeEvent(self, event):
        import os
        if os.environ.get("QT_QPA_PLATFORM") == "offscreen":
            event.accept()   # headless/test runs: never block on a dialog
            return
        if not self._is_dirty():
            event.accept()
            return
        box = QMessageBox(self)
        box.setWindowTitle("Unsaved changes")
        box.setText("Save changes before closing?")
        save_btn = box.addButton("Save", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Don't save", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked == save_btn:
            if self._file_path is None:
                self.save_project_as()
                if self._file_path is None:
                    event.ignore()
                    return
            else:
                self.save_project()
        elif box.buttonRole(clicked) != QMessageBox.ButtonRole.DestructiveRole:
            event.ignore()
            return
        event.accept()

    def about(self):
        QMessageBox.about(self, "About Black-Werx",
                          "Black-Werx — blackwork embroidery pattern editor\n"
                          "Python + PySide6")


class CanvasSetupDialog(QDialog):
    """Fabric / physical stitch settings for the pattern."""

    AIDA_COUNTS = [11, 14, 16, 18, 22, 25, 28, 32, 36, 40]

    def __init__(self, pattern, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Canvas setup")
        form = QFormLayout(self)

        self.aida = QComboBox()
        self.aida.setEditable(True)
        self.aida.addItems([str(c) for c in self.AIDA_COUNTS])
        self.aida.setCurrentText(str(pattern.aida_count))
        form.addRow("Aida count (threads/inch):", self.aida)

        self.w_spin = QDoubleSpinBox()
        self.w_spin.setRange(0.2, 10.0)
        self.w_spin.setDecimals(2)
        self.w_spin.setSingleStep(0.05)
        self.w_spin.setSuffix(" mm")
        self.w_spin.setValue(pattern.stitch_w_mm)
        form.addRow("Stitch width:", self.w_spin)

        self.h_spin = QDoubleSpinBox()
        self.h_spin.setRange(0.2, 10.0)
        self.h_spin.setDecimals(2)
        self.h_spin.setSingleStep(0.05)
        self.h_spin.setSuffix(" mm")
        self.h_spin.setValue(pattern.stitch_h_mm)
        form.addRow("Stitch height:", self.h_spin)

        # canvas size — stitches or inches (inches uses aida count)
        size_row = QHBoxLayout()
        self.size_mode = QComboBox()
        self.size_mode.addItems(["Stitches", "Inches"])
        self.size_mode.setToolTip(
            "Inches are converted using the aida count above")
        self.size_w = QDoubleSpinBox()
        self.size_w.setRange(1.0, 1000.0)
        self.size_w.setDecimals(2)
        self.size_w.setValue(float(pattern.width))
        self.size_h = QDoubleSpinBox()
        self.size_h.setRange(1.0, 1000.0)
        self.size_h.setDecimals(2)
        self.size_h.setValue(float(pattern.height))
        size_row.addWidget(self.size_mode)
        size_row.addWidget(QLabel("W"))
        size_row.addWidget(self.size_w)
        size_row.addWidget(QLabel("H"))
        size_row.addWidget(self.size_h)
        size_row.addStretch(1)
        w_container = QWidget()
        w_container.setLayout(size_row)
        form.addRow("Canvas size:", w_container)
        self.size_info = QLabel("")
        self.size_info.setStyleSheet("color:#666;")
        form.addRow("", self.size_info)
        self.size_mode.currentTextChanged.connect(self._size_mode_changed)
        self.size_w.valueChanged.connect(self._update_size_info)
        self.size_h.valueChanged.connect(self._update_size_info)
        self.aida.editTextChanged.connect(self._update_size_info)
        self._size_mode_changed(self.size_mode.currentText())

        hint = QLabel(
            "Stitch pitch defaults to 25.4 ÷ aida count mm. "
            "Changing the count auto-fills width/height — edit them "
            "afterwards for custom fabrics.")
        hint.setWordWrap(True)
        form.addRow(hint)

        # auto-fill stitch size from aida count
        self.aida.editTextChanged.connect(self._aida_changed)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        form.addRow(btns)

    def _aida_changed(self, text):
        try:
            count = int(text)
        except ValueError:
            return
        if count > 0:
            pitch = round(25.4 / count, 2)
            self.w_spin.setValue(pitch)
            self.h_spin.setValue(pitch)

    def _size_mode_changed(self, mode):
        inches = mode == "Inches"
        self.size_w.setSuffix(" in" if inches else " st")
        self.size_h.setSuffix(" in" if inches else " st")
        self.size_w.setDecimals(2 if inches else 0)
        self.size_h.setDecimals(2 if inches else 0)
        self._update_size_info()

    def _aida_count(self):
        try:
            return max(1, int(self.aida.currentText()))
        except ValueError:
            return 18

    def _update_size_info(self, *_):
        aida = self._aida_count()
        w, h = self.size_w.value(), self.size_h.value()
        if self.size_mode.currentText() == "Inches":
            self.size_info.setText(
                f"≈ {round(w * aida)} × {round(h * aida)} stitches")
        else:
            self.size_info.setText(
                f"≈ {w / aida:.2f} × {h / aida:.2f} inches "
                f"({aida} ct)")

    def values(self):
        return {"aida": self._aida_count(),
                "w": self.w_spin.value(),
                "h": self.h_spin.value(),
                "size_mode": "inches" if self.size_mode.currentText()
                             == "Inches" else "stitches",
                "size_w": self.size_w.value(),
                "size_h": self.size_h.value()}


def QColorDialog_getColor(parent):
    from PySide6.QtWidgets import QColorDialog
    c = QColorDialog.getColor(parent=parent)
    return (c, c.isValid())


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Black-Werx")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
