"""Grid-snapped pattern canvas (QGraphicsView + custom item)."""

from __future__ import annotations

from enum import Enum

from PySide6.QtCore import Qt, Signal, QRectF, QPointF
from PySide6.QtGui import (QColor, QPen, QPainter, QPainterPath, QFont,
                           QWheelEvent, QMouseEvent, QCursor, QPixmap,
                           QImage)
from PySide6.QtWidgets import (QGraphicsView, QGraphicsScene,
                               QGraphicsItem, QAbstractScrollArea, QLabel)

from ..core.model import Pattern, Stitch, StitchKind
from ..core import palette

CELL = 20.0          # scene units per stitch
MARGIN = 4           # cells of margin around pattern
GRID_MAJOR = 10


class Tool(Enum):
    PAN = "pan"
    PENCIL = "pencil"        # X stitches, click/drag freehand
    XLINE = "xline"          # X-stitch line, click-click
    BACKSTITCH = "backstitch"  # backstitch line, click-click
    ERASER = "eraser"
    SELECT = "select"
    MOVE = "move"            # translate selection (click base point, drag)
    ROTATE = "rotate"        # rotate selection about picked center
    BLOCK = "block"          # place library block


class PatternItem(QGraphicsItem):
    """Paints fabric, grid, stitches, and resolved block instances."""

    def __init__(self, canvas: "PatternCanvas"):
        super().__init__()
        self.canvas = canvas

    def boundingRect(self) -> QRectF:
        c = self.canvas
        return QRectF(-MARGIN * CELL, -MARGIN * CELL,
                      (c.pattern.width + 2 * MARGIN) * CELL,
                      (c.pattern.height + 2 * MARGIN) * CELL)

    def _grid_bounds(self):
        c = self.canvas
        return (-MARGIN, -MARGIN,
                c.pattern.width + MARGIN - 1,
                c.pattern.height + MARGIN - 1)

    def paint(self, painter: QPainter, option, widget=None):
        c = self.canvas
        p = c.pattern
        minx, miny, maxx, maxy = self._grid_bounds()

        # fabric background
        painter.fillRect(
            QRectF(minx * CELL, miny * CELL,
                   (maxx - minx + 1) * CELL, (maxy - miny + 1) * CELL),
            QColor(c.fabric_color))

        # pattern extent outline (stitches live on intersections, so the
        # visible area extends half a cell beyond the outer points)
        painter.setPen(QPen(QColor("#8a7f6a"), 1.5, Qt.PenStyle.DashLine))
        painter.drawRect(QRectF(-0.5 * CELL, -0.5 * CELL,
                                p.width * CELL, p.height * CELL))

        # grid lines
        pen_minor = QPen(QColor("#d8d0c0"), 0.4)
        pen_major = QPen(QColor("#a89880"), 0.8)
        painter.setPen(pen_minor)
        for gx in range(minx, maxx + 2):
            painter.drawLine(gx * CELL, miny * CELL, gx * CELL, (maxy + 1) * CELL)
        for gy in range(miny, maxy + 2):
            painter.drawLine(minx * CELL, gy * CELL, (maxx + 1) * CELL, gy * CELL)
        painter.setPen(pen_major)
        for gx in range(minx - (minx % GRID_MAJOR), maxx + 2, GRID_MAJOR):
            painter.drawLine(gx * CELL, miny * CELL, gx * CELL, (maxy + 1) * CELL)
        for gy in range(miny - (miny % GRID_MAJOR), maxy + 2, GRID_MAJOR):
            painter.drawLine(minx * CELL, gy * CELL, (maxx + 1) * CELL, gy * CELL)

        # stitches (raw pattern)
        for s in p.stitches.values():
            self._draw_stitch(painter, s, palette.resolve(s.color))

        # canvas center marker (always visible)
        ccx = (p.width - 1) / 2 * CELL
        ccy = (p.height - 1) / 2 * CELL
        painter.setPen(QPen(QColor("#cc2266"), 1.2))
        painter.drawLine(ccx - 7, ccy, ccx + 7, ccy)
        painter.drawLine(ccx, ccy - 7, ccx, ccy + 7)
        painter.drawEllipse(QRectF(ccx - 2.5, ccy - 2.5, 5, 5))

        # resolved block instances (cached)
        for inst in p.instances:
            for s in c.resolved_stitches(inst):
                col = palette.resolve(c.instance_color(inst, s.color))
                self._draw_stitch(painter, s, col, alpha=0.95)

        # selection highlight
        sel = c.selection
        if sel:
            painter.setPen(QPen(QColor("#2266ff"), 1.5, Qt.PenStyle.DashLine))
            painter.setBrush(QColor(34, 102, 255, 30))
            for key in sel.stitch_keys:
                s = p.stitches.get(key)
                if s:
                    self._draw_stitch_outline(painter, s)
            for uid in sel.instance_uids:
                for s in c.resolved_stitches_by_uid(uid):
                    self._draw_stitch_outline(painter, s)

    def _draw_stitch(self, painter, s: Stitch, hexcol: str, alpha=255):
        col = QColor(hexcol)
        col.setAlpha(int(alpha * 255) if alpha <= 1.0 else int(alpha))
        pen = QPen(col, max(1.2, CELL * 0.16))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        if s.kind is StitchKind.X:
            cx, cy = s.a[0] * CELL, s.a[1] * CELL
            h = CELL * 0.42
            path = QPainterPath()
            path.moveTo(cx - h, cy - h); path.lineTo(cx + h, cy + h)
            path.moveTo(cx + h, cy - h); path.lineTo(cx - h, cy + h)
            painter.drawPath(path)
        else:
            painter.drawLine(s.a[0] * CELL, s.a[1] * CELL,
                             s.b[0] * CELL, s.b[1] * CELL)

    def _draw_stitch_outline(self, painter, s: Stitch):
        pen = QPen(QColor("#2266ff"), 2.5)
        painter.setPen(pen)
        if s.kind is StitchKind.X:
            cx, cy = s.a[0] * CELL, s.a[1] * CELL
            h = CELL * 0.45
            painter.drawLine(cx - h, cy - h, cx + h, cy + h)
            painter.drawLine(cx + h, cy - h, cx - h, cy + h)
        else:
            painter.drawLine(s.a[0] * CELL, s.a[1] * CELL,
                             s.b[0] * CELL, s.b[1] * CELL)


class Selection:
    def __init__(self):
        self.stitch_keys: set = set()
        self.instance_uids: set = set()

    def clear(self):
        self.stitch_keys.clear()
        self.instance_uids.clear()

    @property
    def empty(self) -> bool:
        return not self.stitch_keys and not self.instance_uids


class PatternCanvas(QGraphicsView):
    """View hosting the pattern; emits high-level edit signals."""

    # signals
    cursor_cell_changed = Signal(int, int)
    draw_stitches = Signal(list)          # list[Stitch] already symmetry-expanded
    erase_cells = Signal(set)             # set of cell coords
    place_block = Signal(object, str, int, int, int, int, bool, bool)
    # Block, scope, gx, gy, anchor, rot, mirror_x, mirror_y
    tool_changed = Signal(object)
    context_menu = Signal(object)   # viewport pos for right-click menu
    move_selection = Signal(int, int, int)          # dx, dy, copies
    rotate_selection = Signal(int, int, int, int)   # cx, cy, quarters, copies
    view_changed = Signal()                          # zoom/resize for rulers
    selection_changed = Signal()
    status_message = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pattern = Pattern()
        self.library_blocks: dict = {}
        self.tool = Tool.PAN
        self.current_color = "#000000"
        self.fabric_color = "#F5F0E6"
        self.symmetry_axes: set = set()
        self.selection = Selection()
        self.pending_block = None  # Block to place
        self.pending_scope = "project"
        self.place_anchor = 5      # 3x3 anchor key (numpad layout, 5=center)
        self.place_rot = 0         # pending placement rotation (deg)
        self.place_mx = False      # pending placement mirror X
        self.place_my = False      # pending placement mirror Y
        self.line_width = 1        # X-line thickness in stitches
        self._drag_start_cell = None
        self._drag_last_cell = None
        self._back_start = None
        self._rubber_start = None
        self._press_scene = None      # scene pos at mouse press
        self._press_moved = False     # dragged beyond click threshold
        self._press_point = None      # grid point at press (backstitch)
        self._anchor = None           # X-line anchor: ("x", cell)
        self._poly: list | None = None  # backstitch polyline vertices
        self._pan_start = None
        self._panning = False
        self._resolve_cache: dict = {}
        self._last_mouse_scene = QPointF(0, 0)
        self._ghost_cell = None
        self._back_current = None
        self.copies_count = 1        # array copies for move/rotate tools
        # MOVE tool state (scene coords)
        self._move_anchor = None
        self._move_cur = None
        self._move_target = None
        # ROTATE tool state
        self._rot_center = None      # grid cell (cx, cy)
        self._rot_ref = None         # scene pos of angle reference
        self._rot_q = 0              # pending quarter-turns

        # floating tool indicator, top-center of viewport
        self.tool_label = QLabel(self.viewport())
        self.tool_label.setStyleSheet(
            "background: rgba(0,0,0,160); color: white; padding: 3px 10px;"
            " border-radius: 6px; font-weight: bold;")
        self.tool_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._update_tool_label()

        self.scene = QGraphicsScene(self)
        self.item = PatternItem(self)
        self.scene.addItem(self.item)
        self.setScene(self.scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setMouseTracking(True)
        self._update_scene_rect()
        self.refresh_cursor()

    # -- cursor ---------------------------------------------------------
    TOOL_LABELS = {
        Tool.PENCIL: "✕  X Stitch",
        Tool.XLINE: "╱  X Line",
        Tool.BACKSTITCH: "─  Backstitch",
        Tool.ERASER: "⌫  Eraser",
        Tool.SELECT: "⬚  Select",
        Tool.MOVE: "✥  Move",
        Tool.ROTATE: "⟳  Rotate",
        Tool.BLOCK: "▣  Place Block",
        Tool.PAN: "✋  Pan",
    }

    # 3x3 placement anchors, numpad layout: (fx, fy) fractions of block bbox
    PLACE_ANCHORS = {
        7: (0.0, 0.0), 8: (0.5, 0.0), 9: (1.0, 0.0),
        4: (0.0, 0.5), 5: (0.5, 0.5), 6: (1.0, 0.5),
        1: (0.0, 1.0), 2: (0.5, 1.0), 3: (1.0, 1.0),
    }

    def set_tool(self, tool: Tool):
        self.tool = tool
        self._clear_anchor()
        self._poly = None
        self._move_anchor = self._move_cur = self._move_target = None
        self._rot_center = self._rot_ref = None
        self._rot_q = 0
        self._update_tool_label()
        self.refresh_cursor()
        self.tool_changed.emit(tool)

    def set_pending_block(self, block, scope="project"):
        self.pending_block = block
        self.pending_scope = scope
        self.place_anchor = 5
        self.place_rot = 0
        self.place_mx = self.place_my = False
        self._update_tool_label()

    def _update_tool_label(self):
        text = self.TOOL_LABELS.get(self.tool, str(self.tool))
        if self.tool is Tool.BLOCK and self.pending_block is not None:
            text += f"  ·anchor {self.place_anchor}"
            extras = []
            if self.place_rot:
                extras.append(f"rot{self.place_rot}")
            if self.place_mx:
                extras.append("flipH")
            if self.place_my:
                extras.append("flipV")
            if extras:
                text += " " + "/".join(extras)
        if self.tool in (Tool.MOVE, Tool.ROTATE) and self.copies_count > 0:
            text += f"  ×{self.copies_count}"
        self.tool_label.setText(text)
        self.tool_label.adjustSize()
        vp = self.viewport()
        self.tool_label.move((vp.width() - self.tool_label.width()) // 2, 8)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_tool_label()
        self.view_changed.emit()

    def _set_anchor(self, anchor):
        self._anchor = anchor
        self.viewport().update()

    def _clear_anchor(self):
        if self._anchor is not None:
            self._anchor = None
            self.viewport().update()

    def refresh_cursor(self):
        """Tool-specific cursor showing the stitch glyph in thread color."""
        if self._panning:
            return
        if self.tool is Tool.MOVE:
            self.setCursor(Qt.CursorShape.SizeAllCursor)
            return
        if self.tool is Tool.ROTATE:
            self.setCursor(Qt.CursorShape.CrossCursor)
            return
        size = 36
        img = QImage(size, size, QImage.Format.Format_ARGB32)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        col = QColor(palette.resolve(self.current_color))
        c = size / 2
        m = 7

        def draw_pencil(tip_color: QColor):
            """Angled edit-pencil cursor; tip takes the thread color."""
            # body: thick gray line along the pencil axis
            body = QPen(QColor("#5a5a5a"), 6)
            body.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(body)
            p.drawLine(int(m + 4), int(m + 4), int(size - m - 2),
                       int(size - m - 2))
            # wooden tip
            tip = QPen(QColor("#c8a06a"), 4)
            tip.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(tip)
            p.drawLine(int(m + 1), int(m + 1), int(m + 6), int(m + 6))
            # lead point in thread color
            lead = QPen(tip_color, 2.5)
            lead.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(lead)
            p.drawLine(int(m - 1), int(m - 1), int(m + 4), int(m + 4))
            # eraser band
            p.setPen(QPen(QColor("#d05050"), 6))
            p.drawLine(int(size - m - 4), int(size - m - 4),
                       int(size - m + 2), int(size - m + 2))

        if self.tool in (Tool.PENCIL, Tool.XLINE, Tool.BACKSTITCH):
            draw_pencil(col)
        elif self.tool is Tool.ERASER:
            pen = QPen(QColor("#d33"), 3.5)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawLine(int(m), int(m), int(size - m), int(size - m))
            p.drawLine(int(size - m), int(m), int(m), int(size - m))
            p.setPen(QPen(QColor("#ffffff"), 1.5))
            p.drawLine(int(m), int(m), int(size - m), int(size - m))
            p.drawLine(int(size - m), int(m), int(m), int(size - m))
        elif self.tool is Tool.SELECT:
            pen = QPen(QColor("#2266ff"), 2)
            p.setPen(pen)
            L = 10
            for sx, sy in [(1, 1), (-1, 1), (1, -1), (-1, -1)]:
                x0 = c + sx * (c - m); y0 = c + sy * (c - m)
                x1 = c + sx * (c - m - L); y1 = y0
                x2 = x0; y2 = c + sy * (c - m - L)
                p.drawLine(int(x0), int(y0), int(x1), int(y1))
                p.drawLine(int(x0), int(y0), int(x2), int(y2))
        elif self.tool is Tool.BLOCK:
            pen = QPen(QColor("#2266ff"), 2, Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.drawRect(int(m), int(m), int(size - 2 * m), int(size - 2 * m))
        # PAN keeps default arrow
        p.end()

        if self.tool in (Tool.PENCIL, Tool.XLINE, Tool.BACKSTITCH, Tool.ERASER,
                         Tool.SELECT, Tool.BLOCK):
            # hotspot at the pencil tip for stitch tools, center otherwise
            hx = hy = int(size / 2)
            if self.tool in (Tool.PENCIL, Tool.XLINE, Tool.BACKSTITCH):
                hx = hy = int(m - 1)
            self.setCursor(QCursor(QPixmap.fromImage(img), hx, hy))
        else:
            self.unsetCursor()

    # -- scene management ---------------------------------------------
    def _update_scene_rect(self):
        # center the scene rect on the pattern so scrollbar centering and
        # zoom-out land on the fabric, not the scene origin
        cx = (self.pattern.width - 1) / 2 * CELL
        cy = (self.pattern.height - 1) / 2 * CELL
        m = (max(self.pattern.width, self.pattern.height) / 2
             + 2 * MARGIN) * CELL
        self.scene.setSceneRect(cx - m, cy - m, 2 * m, 2 * m)

    def pattern_center_scene(self):
        return QPointF((self.pattern.width - 1) / 2 * CELL,
                       (self.pattern.height - 1) / 2 * CELL)

    def set_pattern(self, pattern: Pattern):
        self.pattern = pattern
        self.selection.clear()
        self._resolve_cache.clear()
        self._update_scene_rect()
        self.centerOn(self.pattern_center_scene())
        self.viewport().update()

    def refresh(self):
        self._resolve_cache.clear()
        self.viewport().update()

    # -- coordinate helpers --------------------------------------------
    def cell_from_scene(self, pos) -> tuple[int, int] | None:
        """Nearest grid intersection to the scene position."""
        p = self.mapToScene(pos)
        gx = int(round(p.x() / CELL))
        gy = int(round(p.y() / CELL))
        if 0 <= gx < self.pattern.width and 0 <= gy < self.pattern.height:
            return (gx, gy)
        return None

    def point_from_scene(self, pos) -> tuple[float, float]:
        p = self.mapToScene(pos)
        return (p.x() / CELL, p.y() / CELL)

    # -- block resolution cache ----------------------------------------
    def resolved_stitches(self, inst) -> list[Stitch]:
        key = (inst.uid, inst.block_id, inst.scope,
               (inst.transform.m00, inst.transform.m01, inst.transform.m10,
                inst.transform.m11, inst.transform.tx, inst.transform.ty),
               tuple(sorted(inst.recolor.items())),
               self._block_fingerprint(inst))
        if key not in self._resolve_cache:
            self._resolve_cache[key] = inst.resolve(
                self.pattern.blocks, self.library_blocks)
        return self._resolve_cache[key]

    def _block_fingerprint(self, inst) -> tuple:
        b = self.pattern.blocks.get(inst.block_id) or self.library_blocks.get(inst.block_id)
        if b is None:
            return ()
        return (len(b.stitches), len(b.instances), b.name)

    def resolved_stitches_by_uid(self, uid: str) -> list[Stitch]:
        for inst in self.pattern.instances:
            if inst.uid == uid:
                return self.resolved_stitches(inst)
        return []

    def instance_color(self, inst, color: str) -> str:
        return inst.recolor.get(color, color)

    # -- zoom / pan ------------------------------------------------------
    def wheelEvent(self, event: QWheelEvent):
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.zoom_at(event.position().toPoint(), factor)

    def scale(self, sx, sy):
        super().scale(sx, sy)
        self.view_changed.emit()

    def zoom_at(self, view_pos, factor):
        """Zoom keeping the scene point under view_pos stationary."""
        scene_pt = self.mapToScene(view_pos)
        self.scale(factor, factor)
        nv = self.mapFromScene(scene_pt)
        self.horizontalScrollBar().setValue(
            self.horizontalScrollBar().value()
            + int(round(nv.x() - view_pos.x())))
        self.verticalScrollBar().setValue(
            self.verticalScrollBar().value()
            + int(round(nv.y() - view_pos.y())))

    def zoom_centered(self, factor):
        self.zoom_at(self.viewport().rect().center(), factor)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            if self.tool is Tool.BLOCK and self.pending_block is not None:
                self.set_tool(Tool.SELECT)
                self.status_message.emit("block placement ended")
                event.accept()
                return
            if self._move_anchor is not None:
                self._move_anchor = self._move_cur = self._move_target = None
                self.status_message.emit("move cancelled")
                self.viewport().update()
                event.accept()
                return
            if self._rot_center is not None:
                self._rot_center = self._rot_ref = None
                self._rot_q = 0
                self.status_message.emit("rotate cancelled")
                self.viewport().update()
                event.accept()
                return
            cleared = False
            if self._poly is not None:
                self._poly = None
                self.status_message.emit("polyline cancelled")
                cleared = True
            if self._anchor is not None:
                self._clear_anchor()
                self.status_message.emit("anchor cancelled")
                cleared = True
            if cleared:
                event.accept()
                return
        # placement anchor + transform keys while block tool is active
        if self.tool is Tool.BLOCK and self.pending_block is not None:
            key = event.key()
            mods = event.modifiers()
            if key == Qt.Key.Key_R:
                step = 270 if (mods & Qt.KeyboardModifier.ShiftModifier) else 90
                self.place_rot = (self.place_rot + step) % 360
                self._update_tool_label()
                self.viewport().update()
                event.accept()
                return
            if key == Qt.Key.Key_F:
                self.place_mx = not self.place_mx
                self._update_tool_label()
                self.viewport().update()
                event.accept()
                return
            if key == Qt.Key.Key_V:
                self.place_my = not self.place_my
                self._update_tool_label()
                self.viewport().update()
                event.accept()
                return
            num = {Qt.Key.Key_1: 1, Qt.Key.Key_2: 2, Qt.Key.Key_3: 3,
                   Qt.Key.Key_4: 4, Qt.Key.Key_5: 5, Qt.Key.Key_6: 6,
                   Qt.Key.Key_7: 7, Qt.Key.Key_8: 8, Qt.Key.Key_9: 9}.get(key)
            if num in self.PLACE_ANCHORS:
                self.place_anchor = num
                self._update_tool_label()
                self.status_message.emit(f"placement anchor: {num}")
                event.accept()
                return
        if event.key() == Qt.Key.Key_Space:
            self._panning = True
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key.Key_Space:
            self._panning = False
            self.unsetCursor()
            self.refresh_cursor()
        super().keyReleaseEvent(event)

    # -- mouse -----------------------------------------------------------
    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.MiddleButton or self._panning \
                or (self.tool is Tool.PAN
                    and event.button() == Qt.MouseButton.LeftButton):
            if self.tool is Tool.PAN \
                    and event.button() == Qt.MouseButton.LeftButton:
                self._panning = True
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
            self._pan_start = event.position().toPoint()
            event.accept()
            return
        if event.button() == Qt.MouseButton.RightButton:
            action_active = (
                (self.tool is Tool.BACKSTITCH and self._poly is not None) or
                self._anchor is not None or
                (self.tool is Tool.BLOCK and self.pending_block is not None) or
                self._move_anchor is not None or
                self._rot_center is not None)
            if action_active:
                # end current action -> back to select tool
                if self.tool is Tool.BACKSTITCH and self._poly is not None:
                    self._finish_poly(commit=len(self._poly) >= 2)
                self._clear_anchor()
                self._move_anchor = self._move_cur = self._move_target = None
                self._rot_center = self._rot_ref = None
                self._rot_q = 0
                if self.tool is Tool.BLOCK:
                    self.status_message.emit("block placement ended")
                self.set_tool(Tool.SELECT)
            elif self.tool is not Tool.SELECT:
                self.set_tool(Tool.SELECT)
            else:
                self.context_menu.emit(event.position().toPoint())
            event.accept()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return

        cell = self.cell_from_scene(event.position().toPoint())
        scene_pt = self.mapToScene(event.position().toPoint())
        self._press_scene = scene_pt
        self._press_moved = False

        if self.tool is Tool.PENCIL:
            if cell:
                self._drag_start_cell = cell
                self._drag_last_cell = cell
        elif self.tool is Tool.BACKSTITCH:
            gp = (round(scene_pt.x() / CELL), round(scene_pt.y() / CELL))
            self._back_start = gp
            self._press_point = gp
        elif self.tool is Tool.XLINE:
            if cell:
                self._press_point = cell
        elif self.tool is Tool.ERASER:
            if cell:
                self._drag_start_cell = cell
                self.erase_cells.emit(self._cells_along(cell, cell))
        elif self.tool is Tool.SELECT:
            self._rubber_start = scene_pt
        elif self.tool is Tool.BLOCK and self.pending_block is not None:
            if cell:
                self.place_block.emit(self.pending_block, self.pending_scope,
                                      cell[0], cell[1], self.place_anchor,
                                      self.place_rot, self.place_mx,
                                      self.place_my)
        elif self.tool is Tool.MOVE:
            if self.selection.empty:
                self.status_message.emit("Move: select stitches or blocks first.")
            elif self._move_anchor is None:
                self._move_anchor = scene_pt
                self._move_cur = scene_pt
                self._move_target = None
                n = self.copies_count
                self.status_message.emit(
                    "move: drag or click target"
                    + (f" ({n} cop{'ies' if n > 1 else 'y'})"
                       if n > 0 else ""))
                self.viewport().update()
            else:
                self._move_target = scene_pt
        elif self.tool is Tool.ROTATE:
            if self.selection.empty:
                self.status_message.emit("Rotate: select stitches or blocks first.")
            elif self._rot_center is None:
                gp = (round(scene_pt.x() / CELL), round(scene_pt.y() / CELL))
                self._rot_center = gp
                self._rot_ref = None
                self._rot_q = 0
                n = self.copies_count
                self.status_message.emit(
                    "rotate: press-drag from a point to set the angle"
                    + (f" ({n} cop{'ies' if n > 1 else 'y'})"
                       if n > 0 else ""))
                self.viewport().update()
            elif self._rot_ref is None:
                self._rot_ref = scene_pt
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        cell = self.cell_from_scene(event.position().toPoint())
        self._last_mouse_scene = self.mapToScene(event.position().toPoint())
        # repaint only when the snapped target changes (cheap hover dot)
        sp = self._last_mouse_scene
        snap = (int(round(sp.x() / CELL)), int(round(sp.y() / CELL)))
        if snap != getattr(self, "_last_snap", None):
            self._last_snap = snap
            self.viewport().update()
        if cell is not None:
            self.cursor_cell_changed.emit(*cell)
        if cell is not None:
            self._ghost_cell = cell
        # click-vs-drag detection
        if self._press_scene is not None:
            d = self._last_mouse_scene - self._press_scene
            if abs(d.x()) > CELL * 0.4 or abs(d.y()) > CELL * 0.4:
                self._press_moved = True
        if self.tool in (Tool.BACKSTITCH, Tool.XLINE):
            self._back_current = (
                round(self._last_mouse_scene.x() / CELL),
                round(self._last_mouse_scene.y() / CELL))

        if self._pan_start is not None and (
                event.buttons() & Qt.MouseButton.MiddleButton or self._panning):
            delta = event.position().toPoint() - self._pan_start
            self._pan_start = event.position().toPoint()
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - delta.y())
            return

        if self.tool is Tool.PENCIL and self._drag_last_cell is not None \
                and (event.buttons() & Qt.MouseButton.LeftButton):
            if cell and cell != self._drag_last_cell:
                cells = self._cells_along(self._drag_last_cell, cell)
                for c in cells:
                    self._emit_pencil(c)
                self._drag_last_cell = cell
        elif self.tool is Tool.ERASER and self._drag_start_cell is not None \
                and (event.buttons() & Qt.MouseButton.LeftButton):
            if cell:
                self.erase_cells.emit(self._cells_along(self._drag_start_cell, cell))
                self._drag_start_cell = cell
        elif self.tool is Tool.BLOCK and self.pending_block is not None:
            self.viewport().update()
        elif self.tool is Tool.MOVE and self._move_anchor is not None:
            self._move_cur = self._last_mouse_scene
            self.viewport().update()
        elif self.tool is Tool.ROTATE and self._rot_ref is not None \
                and self._rot_center is not None:
            self._update_rot_preview()
            self.viewport().update()
        elif self.tool is Tool.SELECT and self._rubber_start is not None \
                and (event.buttons() & Qt.MouseButton.LeftButton):
            self.viewport().update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan_start = None
            return
        if self.tool is Tool.PAN and self._panning \
                and event.button() == Qt.MouseButton.LeftButton:
            self._panning = False
            self._pan_start = None
            self.refresh_cursor()
            event.accept()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            super().mouseReleaseEvent(event)
            return

        scene_pt = self.mapToScene(event.position().toPoint())
        cell = self.cell_from_scene(event.position().toPoint())
        moved = self._press_moved
        self._press_scene = None
        self._press_moved = False

        if self.tool is Tool.PENCIL:
            if cell and not moved:
                self._emit_pencil(cell)
            self._clear_anchor()
            self._drag_start_cell = self._drag_last_cell = None
        elif self.tool is Tool.XLINE:
            end_pt = cell  # cell coords, None outside pattern
            press_pt = getattr(self, "_press_point", None)
            if moved and press_pt is not None and end_pt is not None:
                if end_pt != press_pt:
                    self._commit_xline(press_pt, end_pt)
                self._clear_anchor()
            elif not moved and end_pt is not None:
                # click-click line tool: first click anchors, second commits
                if self._anchor is None:
                    self._set_anchor(("x", end_pt))
                    self.status_message.emit(
                        "anchor set — click to finish line, right-click/Esc cancels")
                else:
                    kind, a = self._anchor
                    if kind == "x" and end_pt != a:
                        self._commit_xline(a, end_pt)
                    self._clear_anchor()
            self._back_start = None
        elif self.tool is Tool.BACKSTITCH:
            gp = (round(scene_pt.x() / CELL), round(scene_pt.y() / CELL))
            press_gp = getattr(self, "_press_point", None)
            if self._poly is not None:
                # polyline mode: clicks append vertices; right-click finishes
                if not moved and gp != self._poly[-1]:
                    self._poly.append(gp)
                    self.status_message.emit(
                        f"{len(self._poly)} points — right-click to finish, Esc cancels")
                self.viewport().update()
            elif moved and press_gp is not None:
                # drag: commit straight segment press->release
                if gp != press_gp:
                    self._commit_backline(press_gp, gp)
            elif not moved:
                # start a polyline
                self._poly = [press_gp if press_gp is not None else gp]
                self.status_message.emit(
                    "polyline started — click to add points, right-click to finish")
                self.viewport().update()
            self._back_start = None
        elif self.tool is Tool.ERASER:
            self._drag_start_cell = None
        elif self.tool is Tool.MOVE:
            self._commit_move()
        elif self.tool is Tool.ROTATE:
            self._commit_rotate()
        elif self.tool is Tool.SELECT and self._rubber_start is not None:
            if not moved and cell is not None:
                self._click_select(
                    cell, additive=bool(
                        event.modifiers()
                        & Qt.KeyboardModifier.ShiftModifier))
            else:
                self._finish_rubber(scene_pt)
            self._rubber_start = None
        self.viewport().update()
        super().mouseReleaseEvent(event)

    # -- block placement anchors ------------------------------------------
    def _block_anchor(self, bb) -> tuple[float, float]:
        """Anchor point in block coords for self.place_anchor."""
        fx, fy = self.PLACE_ANCHORS.get(self.place_anchor, (0.5, 0.5))
        return (bb[0] + fx * (bb[2] - bb[0]),
                bb[1] + fy * (bb[3] - bb[1]))

    def _placement_local_transform(self, bb):
        """Local-space transform for pending rot/mirror about the anchor."""
        ax, ay = self._block_anchor(bb)
        ax, ay = int(round(ax)), int(round(ay))
        inner = Transform.from_semantic(0, 0, self.place_rot,
                                        self.place_mx, self.place_my)
        return (Transform.translation(-ax, -ay)
                .then(inner)
                .then(Transform.translation(ax, ay)))

    def _ghost_bbox(self, bb):
        """Block bbox after pending rot/mirror (for ghost outline)."""
        if not (self.place_rot or self.place_mx or self.place_my):
            return bb
        t = self._placement_local_transform(bb)
        xs, ys = [], []
        for cx in (bb[0], bb[2]):
            for cy in (bb[1], bb[3]):
                px, py = t.apply((cx, cy))
                xs.append(px); ys.append(py)
        return min(xs), min(ys), max(xs), max(ys)

    # -- move / rotate tools ----------------------------------------------
    def _selection_bbox(self):
        """Cell-space bbox of selected stitches + instances, or None."""
        xs, ys = [], []
        for k in self.selection.stitch_keys:
            s = self.pattern.stitches.get(k)
            if s:
                xs.append(s.a[0]); ys.append(s.a[1])
                if s.b:
                    xs.append(s.b[0]); ys.append(s.b[1])
        for inst in self.pattern.instances:
            if inst.uid in self.selection.instance_uids:
                bb = inst.resolved_bbox(self.pattern.blocks,
                                        self.library_blocks)
                if bb:
                    xs += [bb[0], bb[2]]
                    ys += [bb[1], bb[3]]
        if not xs:
            return None
        return min(xs), min(ys), max(xs), max(ys)

    def _update_rot_preview(self):
        """Snap pending rotation to quarter turns from ref->current angle."""
        import math
        cx, cy = self._rot_center
        cpt = QPointF(cx * CELL, cy * CELL)
        a0 = math.atan2(self._rot_ref.y() - cpt.y(),
                        self._rot_ref.x() - cpt.x())
        a1 = math.atan2(self._last_mouse_scene.y() - cpt.y(),
                        self._last_mouse_scene.x() - cpt.x())
        d = a1 - a0
        while d > math.pi:
            d -= 2 * math.pi
        while d < -math.pi:
            d += 2 * math.pi
        self._rot_q = int(round(d / (math.pi / 2))) % 4

    def _commit_move(self):
        if self._move_anchor is None:
            return
        end = self._move_target if self._move_target is not None \
            else self._move_cur
        anchor = self._move_anchor
        self._move_anchor = self._move_cur = self._move_target = None
        if end is None:
            return
        dx = int(round((end.x() - anchor.x()) / CELL))
        dy = int(round((end.y() - anchor.y()) / CELL))
        if dx == 0 and dy == 0:
            self.viewport().update()
            return
        self.move_selection.emit(dx, dy, self.copies_count)
        self.viewport().update()

    def _commit_rotate(self):
        if self._rot_center is None:
            return
        if self._rot_ref is not None and self._rot_q:
            cx, cy = self._rot_center
            self.rotate_selection.emit(cx, cy, self._rot_q,
                                       self.copies_count)
        # q == 0 or no drag: keep center armed for another attempt
        if self._rot_q == 0:
            self._rot_ref = None
            self.status_message.emit(
                "rotate: press-drag from a point to set the angle")
        else:
            self._rot_center = self._rot_ref = None
            self._rot_q = 0
        self.viewport().update()

    # -- pen-tool commits -----------------------------------------------
    def _commit_xline(self, a_cell, b_cell):
        """X-stitch line; line_width>1 fills a perpendicular band."""
        from ..core.symmetry import apply_symmetry
        width = max(1, getattr(self, "line_width", 1))
        cells = set()
        if width == 1:
            cells = self._cells_along(a_cell, b_cell)
        else:
            dx, dy = b_cell[0] - a_cell[0], b_cell[1] - a_cell[1]
            length = (dx * dx + dy * dy) ** 0.5
            if length == 0:
                cells = {a_cell}
            else:
                nx, ny = -dy / length, dx / length
                for k in range(width):
                    off = k - (width - 1) / 2.0
                    cells |= self._cells_along_float(
                        a_cell[0] + nx * off, a_cell[1] + ny * off,
                        b_cell[0] + nx * off, b_cell[1] + ny * off)
        stitches = [Stitch(StitchKind.X, c, None, self.current_color)
                    for c in sorted(cells)]
        stitches = apply_symmetry(stitches, self.symmetry_axes,
                                  self.pattern.width, self.pattern.height)
        self.draw_stitches.emit(stitches)

    @staticmethod
    def _backline_stitches(a_pt, b_pt, color) -> list:
        """Segment a line into per-grid-unit backstitches (no symmetry)."""
        dx, dy = b_pt[0] - a_pt[0], b_pt[1] - a_pt[1]
        steps = max(abs(dx), abs(dy), 1)
        pts = []
        for i in range(steps + 1):
            t = i / steps
            pts.append((round(a_pt[0] + dx * t), round(a_pt[1] + dy * t)))
        dedup = [pts[0]]
        for p in pts[1:]:
            if p != dedup[-1]:
                dedup.append(p)
        return [Stitch(StitchKind.BACK, p, q, color)
                for p, q in zip(dedup, dedup[1:]) if p != q]

    def _commit_backline(self, a_pt, b_pt):
        """Segment the line into per-grid-unit backstitches."""
        from ..core.symmetry import apply_symmetry
        stitches = self._backline_stitches(a_pt, b_pt, self.current_color)
        stitches = apply_symmetry(stitches, self.symmetry_axes,
                                  self.pattern.width, self.pattern.height)
        self.draw_stitches.emit(stitches)

    def _finish_poly(self, commit: bool):
        """Right-click on backstitch tool: commit (>=2 pts) or cancel."""
        if commit and self._poly and len(self._poly) >= 2:
            from ..core.symmetry import apply_symmetry
            stitches = []
            for a, b in zip(self._poly, self._poly[1:]):
                if a != b:
                    stitches.extend(
                        self._backline_stitches(a, b, self.current_color))
            stitches = apply_symmetry(stitches, self.symmetry_axes,
                                      self.pattern.width, self.pattern.height)
            self.draw_stitches.emit(stitches)
            self.status_message.emit(f"polyline committed ({len(self._poly)} points)")
        else:
            self.status_message.emit("polyline cancelled")
        self._poly = None
        self.viewport().update()

    def _emit_pencil(self, cell):
        from ..core.symmetry import apply_symmetry
        s = Stitch(StitchKind.X, cell, None, self.current_color)
        stitches = apply_symmetry([s], self.symmetry_axes,
                                  self.pattern.width, self.pattern.height)
        self.draw_stitches.emit(stitches)

    def _cells_along(self, a, b) -> set:
        """Cells on the line between grid cells a and b (Bresenham-ish)."""
        return self._cells_along_float(a[0], a[1], b[0], b[1])

    @staticmethod
    def _cells_along_float(x0, y0, x1, y1, step=0.5) -> set:
        """Integer lattice points sampled along a (possibly fractional) line."""
        cells = set()
        dist = max(abs(x1 - x0), abs(y1 - y0), step)
        n = max(int(dist / step) + 1, 2)
        for i in range(n + 1):
            t = i / n
            cells.add((int(round(x0 + (x1 - x0) * t)),
                       int(round(y0 + (y1 - y0) * t))))
        return cells

    def _items_at_cell(self, cell):
        """(stitch keys, instance uids) touching a grid cell."""
        keys = {s.key for s in self.pattern.get_stitches_in_cell(cell)}
        uids = set()
        for inst in self.pattern.instances:
            for s in self.resolved_stitches(inst):
                if cell in s.cells():
                    uids.add(inst.uid)
                    break
        return keys, uids

    def _click_select(self, cell, additive=False):
        """Click-select: plain replaces selection, Shift toggles items."""
        keys, uids = self._items_at_cell(cell)
        if additive:
            for k in keys:
                if k in self.selection.stitch_keys:
                    self.selection.stitch_keys.discard(k)
                else:
                    self.selection.stitch_keys.add(k)
            for u in uids:
                if u in self.selection.instance_uids:
                    self.selection.instance_uids.discard(u)
                else:
                    self.selection.instance_uids.add(u)
        else:
            self.selection.stitch_keys = set(keys)
            self.selection.instance_uids = set(uids)
        self.selection_changed.emit()
        self.viewport().update()

    # fraction of a stitch that must lie inside the rubber-band rect
    SELECT_COVERAGE = 0.5

    @staticmethod
    def _frac_inside_1d(lo, hi, a, b) -> float:
        """Fraction of interval [lo,hi] covered by [a,b]."""
        if hi <= lo:
            return 0.0
        return max(0.0, min(hi, b) - max(lo, a)) / (hi - lo)

    def _stitch_cover(self, s: Stitch, x0, y0, x1, y1) -> float:
        """Fraction of stitch s's extent inside cell-space rect."""
        if s.kind is StitchKind.X:
            # X occupies the unit cell centered on its intersection
            return (self._frac_inside_1d(s.a[0] - 0.5, s.a[0] + 0.5, x0, x1)
                    * self._frac_inside_1d(s.a[1] - 0.5, s.a[1] + 0.5, y0, y1))
        # backstitch: parametric fraction of the segment inside the rect
        ax, ay = s.a
        bx, by = s.b
        dx, dy = bx - ax, by - ay
        t0, t1 = 0.0, 1.0
        for p, d, lo, hi in ((ax, dx, x0, x1), (ay, dy, y0, y1)):
            if d == 0:
                if p < lo or p > hi:
                    return 0.0
                continue
            ta, tb = (lo - p) / d, (hi - p) / d
            t0 = max(t0, min(ta, tb))
            t1 = min(t1, max(ta, tb))
            if t0 >= t1:
                return 0.0
        return t1 - t0

    def _finish_rubber(self, scene_pt):
        """Convert rubber-band rect (scene coords) to a selection.

        A stitch is selected only when >= SELECT_COVERAGE of its extent
        lies inside the rect; an instance is selected when >= half of its
        resolved stitches qualify.
        """
        a = self._rubber_start
        b = scene_pt
        x0, x1 = sorted([a.x() / CELL, b.x() / CELL])
        y0, y1 = sorted([a.y() / CELL, b.y() / CELL])
        cov = self.SELECT_COVERAGE
        self.selection.stitch_keys = {
            s.key for s in self.pattern.stitches.values()
            if self._stitch_cover(s, x0, y0, x1, y1) >= cov}
        self.selection.instance_uids = set()
        for inst in self.pattern.instances:
            sts = self.resolved_stitches(inst)
            if sts:
                hits = sum(1 for s in sts
                           if self._stitch_cover(s, x0, y0, x1, y1) >= cov)
                if hits / len(sts) >= cov:
                    self.selection.instance_uids.add(inst.uid)
        self.selection_changed.emit()
        self.viewport().update()

    # -- foreground (rubber band, block ghost, backstitch preview) --------
    @staticmethod
    def _dist_to_seg(px, py, a, b) -> float:
        ax, ay = a; bx, by = b
        dx, dy = bx - ax, by - ay
        l2 = dx * dx + dy * dy
        if l2 == 0:
            return ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
        t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / l2))
        return ((px - (ax + t * dx)) ** 2 + (py - (ay + t * dy)) ** 2) ** 0.5

    def _draw_eraser_highlight(self, painter: QPainter):
        """Highlight stitches the eraser would remove at the cursor."""
        sp = self._last_mouse_scene
        gx = sp.x() / CELL
        gy = sp.y() / CELL
        hits = []
        for s in self.pattern.stitches.values():
            if s.kind is StitchKind.X:
                if abs(gx - s.a[0]) < 0.5 and abs(gy - s.a[1]) < 0.5:
                    hits.append(s)
            elif self._dist_to_seg(gx, gy, s.a, s.b) <= 0.6:
                hits.append(s)
        if not hits:
            return
        col = QColor("#ff3333")
        col.setAlpha(170)
        pen = QPen(col, CELL * 0.34)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        for s in hits:
            if s.kind is StitchKind.X:
                cx, cy = s.a[0] * CELL, s.a[1] * CELL
                h = CELL * 0.46
                painter.drawLine(cx - h, cy - h, cx + h, cy + h)
                painter.drawLine(cx + h, cy - h, cx - h, cy + h)
            else:
                painter.drawLine(s.a[0] * CELL, s.a[1] * CELL,
                                 s.b[0] * CELL, s.b[1] * CELL)

    def drawForeground(self, painter: QPainter, rect):
        # snap indicator: dot on the grid intersection a click would hit
        if self.tool not in (Tool.PAN, Tool.BLOCK, Tool.ERASER) and \
                getattr(self, "_last_mouse_scene", None) is not None:
            sp = self._last_mouse_scene
            gx = int(round(sp.x() / CELL))
            gy = int(round(sp.y() / CELL))
            p = self.pattern
            if self.tool is Tool.BACKSTITCH:
                ok = 0 <= gx <= p.width and 0 <= gy <= p.height
            else:
                ok = 0 <= gx < p.width and 0 <= gy < p.height
            if ok:
                col = QColor(self.current_color) if self.tool in (
                    Tool.PENCIL, Tool.XLINE, Tool.BACKSTITCH) else \
                    QColor("#2266ff")
                col.setAlpha(200)
                painter.setPen(QPen(QColor("white"), 1.2))
                painter.setBrush(col)
                painter.drawEllipse(QRectF(gx * CELL - 4, gy * CELL - 4, 8, 8))

        if self._rubber_start is not None:
            end = getattr(self, "_last_mouse_scene", self._rubber_start)
            painter.setPen(QPen(QColor("#2266ff"), 1, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            r = QRectF(self._rubber_start, end).normalized()
            painter.drawRect(r)
        if self.tool is Tool.BLOCK and self.pending_block is not None \
                and getattr(self, "_ghost_cell", None):
            gx, gy = self._ghost_cell
            bb = self.pending_block.bbox()
            painter.setPen(QPen(QColor("#2266ff"), 1.5, Qt.PenStyle.DashLine))
            if bb:
                rbb = self._ghost_bbox(bb)
                ax, ay = self._block_anchor(bb)
                tx, ty = gx - ax, gy - ay
                # rect spans half a cell beyond the outer stitch points so
                # the outline is centered on the stitch lattice
                w = (rbb[2] - rbb[0] + 1) * CELL
                h = (rbb[3] - rbb[1] + 1) * CELL
                painter.drawRect(QRectF((rbb[0] - 0.5 + tx) * CELL,
                                        (rbb[1] - 0.5 + ty) * CELL, w, h))
                # anchor cross at insertion point
                painter.setPen(QPen(QColor("#ff5522"), 1.5))
                painter.drawLine(gx * CELL - 6, gy * CELL, gx * CELL + 6, gy * CELL)
                painter.drawLine(gx * CELL, gy * CELL - 6, gx * CELL, gy * CELL + 6)
        # eraser: highlight the stitch/segment that would be removed
        if self.tool is Tool.ERASER and \
                getattr(self, "_last_mouse_scene", None) is not None:
            self._draw_eraser_highlight(painter)

        # move tool: ghost of selection bbox at drag offset
        if self.tool is Tool.MOVE and self._move_anchor is not None:
            end = self._move_target if self._move_target is not None \
                else self._move_cur
            bb = self._selection_bbox()
            if end is not None and bb:
                dx = (end.x() - self._move_anchor.x()) / CELL
                dy = (end.y() - self._move_anchor.y()) / CELL
                painter.setPen(QPen(QColor("#22aa55"), 1.5,
                                    Qt.PenStyle.DashLine))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(QRectF(
                    (bb[0] - 0.5 + dx) * CELL, (bb[1] - 0.5 + dy) * CELL,
                    (bb[2] - bb[0] + 1) * CELL, (bb[3] - bb[1] + 1) * CELL))
                painter.setBrush(QColor("#22aa55"))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(QRectF(self._move_anchor.x() - 4,
                                           self._move_anchor.y() - 4, 8, 8))

        # rotate tool: center marker + rotated bbox preview
        if self.tool is Tool.ROTATE and self._rot_center is not None:
            cx, cy = self._rot_center
            ccx, ccy = cx * CELL, cy * CELL
            painter.setPen(QPen(QColor("#ff8833"), 1.5))
            painter.drawLine(ccx - 7, ccy, ccx + 7, ccy)
            painter.drawLine(ccx, ccy - 7, ccx, ccy + 7)
            bb = self._selection_bbox()
            if bb:
                corners = [(bb[0], bb[1]), (bb[2], bb[1]),
                           (bb[2], bb[3]), (bb[0], bb[3])]
                pts = []
                for x, y in corners:
                    ddx, ddy = x - cx, y - cy
                    for _ in range(self._rot_q):
                        ddx, ddy = -ddy, ddx
                    pts.append(((cx + ddx) * CELL, (cy + ddy) * CELL))
                painter.setPen(QPen(QColor("#ff8833"), 1.5,
                                    Qt.PenStyle.DashLine))
                for i in range(4):
                    x1, y1 = pts[i]
                    x2, y2 = pts[(i + 1) % 4]
                    painter.drawLine(x1, y1, x2, y2)
                if self._rot_ref is not None:
                    cur = self._last_mouse_scene
                    painter.setPen(QPen(QColor("#ff8833"), 1))
                    painter.drawLine(ccx, ccy, cur.x(), cur.y())

        # backstitch polyline preview
        if self.tool is Tool.BACKSTITCH and self._poly:
            pen = QPen(QColor(self.current_color), 2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            pts = list(self._poly)
            cur = getattr(self, "_last_mouse_scene", None)
            if cur is not None:
                pts.append((round(cur.x() / CELL), round(cur.y() / CELL)))
            for a, b in zip(pts, pts[1:]):
                painter.drawLine(a[0] * CELL, a[1] * CELL,
                                 b[0] * CELL, b[1] * CELL)
            painter.setBrush(QColor(self.current_color))
            painter.setPen(QPen(QColor("white"), 1))
            for v in self._poly:
                painter.drawEllipse(QRectF(v[0] * CELL - 3.5, v[1] * CELL - 3.5,
                                           7, 7))

        # pen-tool anchor preview
        if self._anchor is not None:
            cur = getattr(self, "_last_mouse_scene", None)
            if cur is not None:
                kind, a = self._anchor
                if kind == "back":
                    painter.setPen(QPen(QColor(self.current_color), 2,
                                        Qt.PenStyle.DashLine))
                    painter.drawLine(a[0] * CELL, a[1] * CELL,
                                     cur.x(), cur.y())
                else:
                    # X-line preview: cells along anchor->cursor
                    b_cell = (int(cur.x() // CELL), int(cur.y() // CELL))
                    for c in self._cells_along(a, b_cell):
                        cx, cy = c[0] * CELL, c[1] * CELL
                        h = CELL * 0.42
                        painter.setPen(QPen(QColor(self.current_color), 1.2,
                                            Qt.PenStyle.DashLine))
                        painter.drawLine(cx - h, cy - h, cx + h, cy + h)
                        painter.drawLine(cx + h, cy - h, cx - h, cy + h)
            # anchor marker
            kind, a = self._anchor
            ax, ay = (a[0] * CELL, a[1] * CELL) if kind == "x" else \
                     (a[0] * CELL, a[1] * CELL)
            painter.setPen(QPen(QColor("#2266ff"), 1.5))
            painter.setBrush(QColor(34, 102, 255, 60))
            painter.drawEllipse(QRectF(ax - 4, ay - 4, 8, 8))
