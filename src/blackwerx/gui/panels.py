"""Dock panels: block library and thread color picker."""

from __future__ import annotations

from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QListWidget,
                               QListWidgetItem, QPushButton, QLabel,
                               QHBoxLayout, QColorDialog, QComboBox,
                               QGroupBox, QInputDialog)

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
        self.preview.setFixedSize(40, 40)
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
    """Block library: global + project blocks with actions."""

    place_requested = Signal(object)     # Block, scope
    new_from_selection = Signal()
    edit_requested = Signal(object)      # (block, scope)
    delete_requested = Signal(object)
    promote_requested = Signal(object)   # project block -> global

    def __init__(self, parent=None):
        super().__init__(parent)
        self.global_blocks: dict = {}
        self.project_blocks: dict = {}
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Global library"))
        self.global_list = QListWidget()
        self.global_list.itemDoubleClicked.connect(
            lambda it: self.place_requested.emit(
                (self.global_blocks[it.data(Qt.ItemDataRole.UserRole)], "global")))
        layout.addWidget(self.global_list)

        layout.addWidget(QLabel("Project blocks"))
        self.project_list = QListWidget()
        self.project_list.itemDoubleClicked.connect(
            lambda it: self.place_requested.emit(
                (self.project_blocks[it.data(Qt.ItemDataRole.UserRole)], "project")))
        layout.addWidget(self.project_list)

        btn_row = QHBoxLayout()
        for text, sig in [
            ("Place", self._place_selected),
            ("New from selection", self.new_from_selection),
            ("Edit", self._edit_selected),
            ("Delete", self._delete_selected),
            ("Promote", self._promote_selected),
        ]:
            b = QPushButton(text)
            b.clicked.connect(sig)
            btn_row.addWidget(b)
        layout.addLayout(btn_row)

    def refresh(self):
        self.global_list.clear()
        for bid, b in sorted(self.global_blocks.items(), key=lambda kv: kv[1].name):
            it = QListWidgetItem(f"{b.name} ({len(b.stitches)}st)")
            it.setData(Qt.ItemDataRole.UserRole, bid)
            self.global_list.addItem(it)
        self.project_list.clear()
        for bid, b in sorted(self.project_blocks.items(), key=lambda kv: kv[1].name):
            it = QListWidgetItem(f"{b.name} ({len(b.stitches)}st)")
            it.setData(Qt.ItemDataRole.UserRole, bid)
            self.project_list.addItem(it)

    def _selected(self, lst):
        it = lst.currentItem()
        return it.data(Qt.ItemDataRole.UserRole) if it else None

    def _place_selected(self):
        bid = self._selected(self.global_list)
        if bid:
            self.place_requested.emit((self.global_blocks[bid], "global"))
            return
        bid = self.project_list and self._selected(self.project_list)
        if bid:
            self.place_requested.emit((self.project_blocks[bid], "project"))

    def _edit_selected(self):
        bid = self._selected(self.global_list)
        if bid:
            self.edit_requested.emit((self.global_blocks[bid], "global"))
            return
        bid = self._selected(self.project_list)
        if bid:
            self.edit_requested.emit((self.project_blocks[bid], "project"))

    def _delete_selected(self):
        bid = self._selected(self.global_list)
        if bid:
            self.delete_requested.emit((self.global_blocks[bid], "global"))
            return
        bid = self._selected(self.project_list)
        if bid:
            self.delete_requested.emit((self.project_blocks[bid], "project"))

    def _promote_selected(self):
        bid = self._selected(self.project_list)
        if bid:
            self.promote_requested.emit((self.project_blocks[bid], "project"))


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
        b.stitches.append(Stitch(
            s.kind, (s.a[0] - ox, s.a[1] - oy),
            (s.b[0] - ox, s.b[1] - oy) if s.b else None, s.color))
    for inst in instances or []:
        # shift nested instance translation
        t = inst.transform
        from ..core.model import Transform
        inst.transform = Transform(t.m00, t.m01, t.m10, t.m11,
                                   t.tx - ox, t.ty - oy)
        b.instances.append(inst)
    return b
