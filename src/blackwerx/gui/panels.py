"""Dock panels: block library and thread color picker."""

from __future__ import annotations

from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QColor, QIcon, QPixmap, QPalette
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QListWidget,
                               QListWidgetItem, QPushButton, QLabel,
                               QHBoxLayout, QColorDialog, QComboBox,
                               QGroupBox, QInputDialog, QScrollArea,
                               QFrame, QCheckBox, QTreeWidget,
                               QTreeWidgetItem, QDialog,
                               QDialogButtonBox, QApplication)

from ..core import palette
from ..core.block import Block, BlockInstance
from ..core.model import Transform


def color_icon(hexcol: str, size: int = 20) -> QIcon:
    pm = QPixmap(size, size)
    pm.fill(QColor(hexcol))
    return QIcon(pm)


class ColorPanel(QWidget):
    """Current thread color selector: DMC list + custom color."""

    color_changed = Signal(str)   # color spec

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_spec = "dmc:310"
        layout = QVBoxLayout(self)

        self.preview = QLabel()
        self.preview.setFixedSize(30, 30)
        self.preview.setFrameShape(QLabel.Shape.Box)
        layout.addWidget(self.preview, alignment=Qt.AlignmentFlag.AlignCenter)

        self.filter_box = QComboBox()
        self.filter_box.addItems(["All", "Blacks/Grays", "Reds", "Yellows",
                                  "Greens", "Blues", "Purples", "Browns/Tans"])
        self.filter_box.currentIndexChanged.connect(self._repopulate)
        layout.addWidget(self.filter_box)

        self.list = QListWidget()
        self.list.itemClicked.connect(self._pick)
        layout.addWidget(self.list)

        btn_row = QHBoxLayout()
        custom = QPushButton("Custom…")
        custom.clicked.connect(self._custom_color)
        btn_row.addWidget(custom)
        layout.addLayout(btn_row)

        self._repopulate()
        self._set_current("dmc:310")

    def _category(self, hexcol: str) -> str:
        h = hexcol.lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        mx, mn = max(r, g, b), min(r, g, b)
        if mx - mn < 30:
            return "Blacks/Grays"
        if r == mx and g > b:
            return "Reds" if g < 120 else "Browns/Tans"
        if r == mx:
            return "Reds"
        if g == mx:
            return "Yellows" if r > 150 else "Greens"
        if b == mx:
            return "Blues" if g < 150 else "Purples"
        return "Browns/Tans"

    def _repopulate(self):
        self.list.clear()
        cat = self.filter_box.currentText()
        for spec, label, hexcol in palette.all_colors():
            if cat != "All" and self._category(hexcol) != cat:
                continue
            it = QListWidgetItem(color_icon(hexcol), label)
            it.setData(Qt.ItemDataRole.UserRole, spec)
            self.list.addItem(it)

    def _pick(self, item: QListWidgetItem):
        self._set_current(item.data(Qt.ItemDataRole.UserRole))

    def _custom_color(self):
        c = QColorDialog.getColor()
        if c.isValid():
            self._set_current(c.name())

    def _set_current(self, spec: str):
        self.current_spec = spec
        hexcol = palette.resolve(spec)
        self.preview.setStyleSheet(f"background-color: {hexcol};")
        name = palette.dmc_name(spec) or spec
        self.preview.setToolTip(f"{spec} {name}")
        self.color_changed.emit(spec)


class LibraryPanel(QWidget):
    """Block library: global + project blocks grouped into folders."""

    place_requested = Signal(object)     # Block, scope
    new_from_selection = Signal()
    edit_requested = Signal(object)      # (block, scope)
    delete_requested = Signal(object)
    promote_requested = Signal(object)   # project block -> global
    folder_requested = Signal(object, object, str)  # (block, scope, folder)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.global_blocks: dict = {}
        self.project_blocks: dict = {}
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Global library"))
        self.global_tree = self._make_tree()
        layout.addWidget(self.global_tree)

        layout.addWidget(QLabel("Project blocks"))
        self.project_tree = self._make_tree()
        layout.addWidget(self.project_tree)

        btn_row = QHBoxLayout()
        for text, sig in [
            ("Place", self._place_selected),
            ("New from selection", self.new_from_selection),
            ("Edit", self._edit_selected),
        ]:
            b = QPushButton(text)
            b.clicked.connect(sig)
            btn_row.addWidget(b)
        layout.addLayout(btn_row)
        btn_row2 = QHBoxLayout()
        for text, sig in [
            ("Delete", self._delete_selected),
            ("Promote", self._promote_selected),
            ("Folder…", self._set_folder),
        ]:
            b = QPushButton(text)
            b.clicked.connect(sig)
            btn_row2.addWidget(b)
        layout.addLayout(btn_row2)

    def _make_tree(self) -> QTreeWidget:
        tree = QTreeWidget()
        tree.setHeaderHidden(True)
        tree.setMinimumHeight(80)
        tree.itemDoubleClicked.connect(self._on_double_click)
        return tree

    @staticmethod
    def _block_item(tree: QTreeWidget, parent: QTreeWidgetItem | None,
                    bid: str, b: Block):
        it = QTreeWidgetItem([f"{b.name} ({len(b.stitches)}st)"])
        it.setData(0, Qt.ItemDataRole.UserRole, bid)
        if parent is not None:
            parent.addChild(it)
        else:
            tree.addTopLevelItem(it)
        return it

    def _fill_tree(self, tree: QTreeWidget, blocks: dict,
                   scope: str):
        tree.clear()
        folders: dict[str, QTreeWidgetItem] = {}
        for bid, b in sorted(blocks.items(), key=lambda kv: kv[1].name):
            if b.folder:
                if b.folder not in folders:
                    f = QTreeWidgetItem([b.folder])
                    f.setFlags(f.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                    tree.addTopLevelItem(f)
                    folders[b.folder] = f
                parent = folders[b.folder]
                it = self._block_item(tree, parent, bid, b)
            else:
                # unfiled blocks sit at the top level, no pseudo-folder
                it = self._block_item(tree, None, bid, b)
            it.setData(0, Qt.ItemDataRole.UserRole + 1, scope)
        tree.expandAll()

    def refresh(self):
        self._fill_tree(self.global_tree, self.global_blocks, "global")
        self._fill_tree(self.project_tree, self.project_blocks, "project")

    # -- selection helpers ----------------------------------------------
    def _selected_leaf(self, tree: QTreeWidget):
        """Return (bid, scope, block) for the selected block leaf."""
        it = tree.currentItem()
        if it is None:
            return None
        bid = it.data(0, Qt.ItemDataRole.UserRole)
        scope = it.data(0, Qt.ItemDataRole.UserRole + 1)
        if bid is None or scope is None:
            return None
        blocks = self.global_blocks if scope == "global" \
            else self.project_blocks
        b = blocks.get(bid)
        return (bid, scope, b) if b else None

    def _on_double_click(self, item: QTreeWidgetItem):
        tree = item.treeWidget()
        sel = self._selected_leaf(tree)
        if sel is None:
            return
        bid, scope, b = sel
        self.place_requested.emit((b, scope))

    def _place_selected(self):
        for tree in (self.global_tree, self.project_tree):
            sel = self._selected_leaf(tree)
            if sel:
                self.place_requested.emit((sel[2], sel[1]))
                return

    def _edit_selected(self):
        for tree in (self.global_tree, self.project_tree):
            sel = self._selected_leaf(tree)
            if sel:
                self.edit_requested.emit((sel[2], sel[1]))
                return

    def _delete_selected(self):
        for tree in (self.global_tree, self.project_tree):
            sel = self._selected_leaf(tree)
            if sel:
                self.delete_requested.emit((sel[2], sel[1]))
                return

    def _promote_selected(self):
        sel = self._selected_leaf(self.project_tree)
        if sel:
            self.promote_requested.emit((sel[2], "project"))

    def _set_folder(self):
        """Move the selected block into a folder.

        Dropdown lists every folder already in use (both libraries);
        still editable so new folder names can be typed."""
        for tree in (self.global_tree, self.project_tree):
            sel = self._selected_leaf(tree)
            if sel is None:
                continue
            bid, scope, b = sel
            folders = sorted(
                {x.folder for d in (self.global_blocks,
                                    self.project_blocks)
                 for x in d.values() if x.folder})
            dlg = QDialog(self)
            dlg.setWindowTitle("Block folder")
            lay = QVBoxLayout(dlg)
            lay.addWidget(QLabel(f"Folder for '{b.name}':"))
            combo = QComboBox()
            combo.setEditable(True)
            combo.addItem("(unfiled)")
            combo.addItems(folders)
            combo.setCurrentText(b.folder or "(unfiled)")
            lay.addWidget(combo)
            btns = QDialogButtonBox(
                QDialogButtonBox.StandardButton.Ok
                | QDialogButtonBox.StandardButton.Cancel)
            btns.accepted.connect(dlg.accept)
            btns.rejected.connect(dlg.reject)
            lay.addWidget(btns)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                text = combo.currentText().strip()
                folder = "" if text in ("", "(unfiled)") else text
                self.folder_requested.emit(b, scope, folder)
            return


def make_block_from_stitches(name: str, stitches: list,
                             instances: list | None = None) -> Block:
    """Create a Block normalized so its bbox min corner is (0,0)."""
    import uuid
    from ..core.model import Stitch
    b = Block(id=uuid.uuid4().hex[:12], name=name)
    xs, ys = [], []
    for s in stitches:
        for p in ([s.a] + ([s.b] if s.b else [])):
            xs.append(p[0]); ys.append(p[1])
    ox, oy = (min(xs), min(ys)) if xs else (0, 0)
    for s in stitches:
        from dataclasses import replace
        b.stitches.append(replace(
            s, a=(s.a[0] - ox, s.a[1] - oy),
            b=(s.b[0] - ox, s.b[1] - oy) if s.b else None))
    for inst in instances or []:
        # shift nested instance translation
        t = inst.transform
        from ..core.model import Transform
        inst.transform = Transform(t.m00, t.m01, t.m10, t.m11,
                                   t.tx - ox, t.ty - oy)
        b.instances.append(inst)
    return b


class _LayerNameLabel(QLabel):
    double_clicked = Signal()

    def mouseDoubleClickEvent(self, event):
        self.double_clicked.emit()
        super().mouseDoubleClickEvent(event)


class _LayerRow(QFrame):
    activated = Signal()

    def mousePressEvent(self, event):
        self.activated.emit()
        super().mousePressEvent(event)


class LayerPanel(QWidget):
    """Layer list: visibility, lock, display color, active layer.

    The top row is a pseudo-layer for view guides (non-printing).
    """

    layers_changed = Signal()        # any layer property changed
    active_changed = Signal(str)     # new active layer id
    guides_toggled = Signal(bool)    # guides pseudo-layer visibility
    guides_locked_toggled = Signal(bool)  # guides pseudo-layer lock
    layer_delete_requested = Signal(str, str)  # deleted id, migration target
    move_selection_requested = Signal(str)     # move selection to layer id
    merge_requested = Signal(list)             # checked layer ids, top first

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pattern = None
        self._guides_visible = True
        self._guides_locked = False
        self.checked_layer_ids: set = set()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("Layers"))

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.rows_widget = QWidget()
        self.rows_layout = QVBoxLayout(self.rows_widget)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(2)
        self.rows_layout.addStretch(1)
        self.scroll.setWidget(self.rows_widget)
        layout.addWidget(self.scroll, 1)

        btn_row = QHBoxLayout()
        add_above = QPushButton("Add above")
        add_above.setToolTip("Add a layer above the active layer")
        add_above.clicked.connect(lambda: self._add_layer(above=True))
        btn_row.addWidget(add_above)
        add_below = QPushButton("Add below")
        add_below.setToolTip("Add a layer below the active layer")
        add_below.clicked.connect(lambda: self._add_layer(above=False))
        btn_row.addWidget(add_below)
        self.merge_btn = QPushButton("Merge checked")
        self.merge_btn.setToolTip(
            "Merge checked layers into the topmost checked layer")
        self.merge_btn.clicked.connect(self._merge_checked)
        btn_row.addWidget(self.merge_btn)
        layout.addLayout(btn_row)

    # -- data ----------------------------------------------------------
    def refresh(self, pattern):
        self.pattern = pattern
        self._rebuild()

    def set_guides_visible(self, visible: bool):
        self._guides_visible = visible
        self._rebuild_guides_row()

    def set_guides_locked(self, locked: bool):
        self._guides_locked = locked
        self._rebuild_guides_row()

    def _rebuild(self):
        while self.rows_layout.count():
            item = self.rows_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.spacerItem():
                pass
        self._build_guides_row()
        p = self.pattern
        # display topmost (last in draw order) first, like other apps
        for l in reversed(p.layers):
            self.rows_layout.addWidget(self._layer_row(l))
        self.rows_layout.addStretch(1)

    def _guides_row(self):
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(4, 2, 4, 2)
        h.setSpacing(4)
        self.guides_vis_btn = QPushButton(
            "Hide" if self._guides_visible else "Unhide")
        self.guides_vis_btn.setCheckable(True)
        self.guides_vis_btn.setChecked(self._guides_visible)
        self.guides_vis_btn.clicked.connect(self._toggle_guides)
        h.addWidget(self.guides_vis_btn)

        self.guides_lock_btn = QPushButton(
            "Unlock" if self._guides_locked else "Lock")
        self.guides_lock_btn.setCheckable(True)
        self.guides_lock_btn.setChecked(self._guides_locked)
        self.guides_lock_btn.setToolTip(
            "Locked guides can't be grabbed or moved")
        self.guides_lock_btn.clicked.connect(self._toggle_guides_lock)
        h.addWidget(self.guides_lock_btn)

        name = QLabel("Guides (non-printing)")
        _mid = QApplication.palette().color(
            QPalette.ColorRole.Mid).name()
        name.setStyleSheet(f"font-style:italic; color:{_mid};")
        h.addWidget(name, 1)
        return row

    def _build_guides_row(self):
        self.rows_layout.insertWidget(0, self._guides_row())

    def _rebuild_guides_row(self):
        w = self.rows_layout.itemAt(0).widget()
        if w:
            w.deleteLater()
        self._build_guides_row()

    def _toggle_guides(self, _=False):
        self._guides_visible = self.guides_vis_btn.isChecked()
        self.guides_vis_btn.setText(
            "Hide" if self._guides_visible else "Unhide")
        self.guides_toggled.emit(self._guides_visible)

    def _toggle_guides_lock(self, _=False):
        self._guides_locked = self.guides_lock_btn.isChecked()
        self.guides_lock_btn.setText(
            "Unlock" if self._guides_locked else "Lock")
        self.guides_locked_toggled.emit(self._guides_locked)

    # -- layer rows ------------------------------------------------------
    def _layer_row(self, layer: dict) -> QWidget:
        p = self.pattern
        row = _LayerRow()
        active = p.active_layer == layer["id"]
        total = len(p.layers)
        # app palette — widget palettes can be frozen by the style
        pal = QApplication.palette()
        win = pal.color(QPalette.ColorRole.Window)
        hi = pal.color(QPalette.ColorRole.Highlight)
        lum = (0.299 * win.red() + 0.587 * win.green()
               + 0.114 * win.blue())
        dark = lum < 140
        if dark:
            inact_bg = win.lighter(112)
            inact_bd = win.lighter(160)
        else:
            inact_bg = win.darker(102)
            inact_bd = win.darker(115)
        if active:
            act_bg = QColor(hi)
            act_bg.setAlpha(90)
            row.setStyleSheet(
                "QFrame { background:"
                f"{act_bg.name(QColor.NameFormat.HexArgb)};"
                f" border:1px solid {hi.name()}; border-radius:4px; }}")
        else:
            row.setStyleSheet(
                "QFrame { background:"
                f"{inact_bg.name()}; border:1px solid "
                f"{inact_bd.name()}; border-radius:4px; }}")
        h = QHBoxLayout(row)
        h.setContentsMargins(4, 2, 4, 2)
        h.setSpacing(4)

        cb = QCheckBox()
        cb.setChecked(layer["id"] in self.checked_layer_ids)
        cb.setToolTip("Check to include in 'Merge checked'")
        cb.toggled.connect(
            lambda c, lid=layer["id"]: self._on_row_check(lid, c))
        h.addWidget(cb)

        dot = QLabel("●" if active else "○")
        dot.setStyleSheet(
            "color:#dd2222; font-size:14px;" if active
            else "color:#bbb; font-size:14px;")
        dot.setToolTip("Active layer (new stitches go here)")
        h.addWidget(dot)

        vis = QPushButton("Hide" if layer.get("visible", True) else "Unhide")
        vis.setCheckable(True)
        vis.setChecked(bool(layer.get("visible", True)))
        vis.setToolTip("Toggle layer visibility")
        vis.clicked.connect(
            lambda _=False, l=layer, b=vis: self._toggle_prop(
                l, "visible", b.isChecked()))
        h.addWidget(vis)

        lock = QPushButton("Unlock" if layer.get("locked") else "Lock")
        lock.setCheckable(True)
        lock.setChecked(bool(layer.get("locked")))
        lock.setToolTip("Locked layers can't be selected or edited")
        lock.clicked.connect(
            lambda _=False, l=layer, b=lock: self._toggle_prop(
                l, "locked", b.isChecked()))
        h.addWidget(lock)

        col = layer.get("color")
        cbtn = QPushButton("Color" if not col else "■")
        cbtn.setToolTip("Display color override (view only) — click to set, "
                        "right-click to clear")
        if col:
            cbtn.setStyleSheet(f"background:{col}; color:white;")
        cbtn.clicked.connect(
            lambda _=False, l=layer: self._pick_display_color(l))
        cbtn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        cbtn.customContextMenuRequested.connect(
            lambda _p, l=layer: self._clear_display_color(l))
        h.addWidget(cbtn)

        name = _LayerNameLabel(layer["name"])
        name.setToolTip("Double-click to rename; click row to activate")
        name.double_clicked.connect(lambda l=layer: self._rename_layer(l))
        h.addWidget(name, 1)
        row.activated.connect(lambda lid=layer["id"]: self._set_active(lid))

        idx = p.layers.index(layer)
        raise_btn = QPushButton("↑")
        raise_btn.setFixedWidth(20)
        raise_btn.setEnabled(idx < total - 1)
        raise_btn.setToolTip("Raise layer (drawn on top)")
        raise_btn.clicked.connect(
            lambda _=False, l=layer: self._move_layer(l, +1))
        h.addWidget(raise_btn)
        lower_btn = QPushButton("↓")
        lower_btn.setFixedWidth(20)
        lower_btn.setEnabled(idx > 0)
        lower_btn.setToolTip("Lower layer (drawn underneath)")
        lower_btn.clicked.connect(
            lambda _=False, l=layer: self._move_layer(l, -1))
        h.addWidget(lower_btn)

        move = QPushButton("»")
        move.setFixedWidth(22)
        move.setToolTip("Move current selection to this layer")
        move.clicked.connect(
            lambda _=False, lid=layer["id"]: self.move_selection_requested.emit(lid))
        h.addWidget(move)

        if total > 1:
            dele = QPushButton("×")
            dele.setFixedWidth(22)
            dele.setToolTip("Delete layer (stitches move to layer below)")
            dele.clicked.connect(
                lambda _=False, l=layer: self._delete_layer(l))
            h.addWidget(dele)
        return row

    # -- mutations -------------------------------------------------------
    def _emit_changed(self):
        self.layers_changed.emit()
        self._rebuild()

    def _toggle_prop(self, layer, prop, value):
        layer[prop] = value
        self._emit_changed()

    def _set_active(self, lid):
        if self.pattern.active_layer != lid:
            self.pattern.active_layer = lid
            self.active_changed.emit(lid)
            self._rebuild()

    def _rename_layer(self, layer):
        name, ok = QInputDialog.getText(
            self, "Rename layer", "Layer name:", text=layer["name"])
        if ok and name.strip():
            layer["name"] = name.strip()
            self._emit_changed()

    def _pick_display_color(self, layer):
        c = QColorDialog.getColor()
        if c.isValid():
            layer["color"] = c.name()
            self._emit_changed()

    def _clear_display_color(self, layer):
        if layer.get("color"):
            layer["color"] = None
            self._emit_changed()

    def _add_layer(self, above=True):
        import uuid
        p = self.pattern
        if p is None:
            return
        default = f"Layer {len(p.layers) + 1}"
        name, ok = QInputDialog.getText(
            self, "New layer", "Layer name:", text=default)
        if not ok:
            return
        name = name.strip() or default
        lid = "layer" + uuid.uuid4().hex[:6]
        try:
            idx = next(i for i, l in enumerate(p.layers)
                       if l["id"] == p.active_layer)
        except StopIteration:
            idx = len(p.layers) - 1
        new_layer = {"id": lid, "name": name,
                     "visible": True, "locked": False, "color": None}
        # 'above' the active layer = later in draw order (on top)
        p.layers.insert(idx + 1 if above else idx, new_layer)
        p.active_layer = lid
        self.active_changed.emit(lid)
        self._emit_changed()

    def _move_layer(self, layer, delta):
        p = self.pattern
        idx = p.layers.index(layer)
        j = idx + delta
        if 0 <= j < len(p.layers):
            p.layers[idx], p.layers[j] = p.layers[j], p.layers[idx]
            self._emit_changed()

    def _on_row_check(self, lid, checked):
        if checked:
            self.checked_layer_ids.add(lid)
        else:
            self.checked_layer_ids.discard(lid)

    def _merge_checked(self):
        p = self.pattern
        if not p:
            return
        # topmost checked layer first (matches display order)
        ids = [l["id"] for l in reversed(p.layers)
               if l["id"] in self.checked_layer_ids]
        if len(ids) < 2:
            return
        self.merge_requested.emit(ids)

    def _delete_layer(self, layer):
        p = self.pattern
        idx = next(i for i, l in enumerate(p.layers) if l is layer)
        self.checked_layer_ids.discard(layer["id"])
        # contents migrate to the layer below (or above if deleting bottom)
        if len(p.layers) > 1:
            target = p.layers[idx - 1]["id"] if idx > 0 else \
                p.layers[1]["id"]
            self.layer_delete_requested.emit(layer["id"], target)
        del p.layers[idx]
        if p.active_layer == layer["id"]:
            p.active_layer = p.layers[0]["id"]
            self.active_changed.emit(p.active_layer)
        self._emit_changed()
