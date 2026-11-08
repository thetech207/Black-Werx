"""Grid-snapped pattern canvas (QGraphicsView + custom item)."""

from __future__ import annotations

import math
from enum import Enum

from PySide6.QtCore import Qt, Signal, QRectF, QPointF, QPoint
from PySide6.QtGui import (QColor, QPen, QPainter, QPainterPath, QFont,
                           QWheelEvent, QMouseEvent, QCursor, QPixmap,
                           QImage, QBrush)
from PySide6.QtWidgets import (QGraphicsView, QGraphicsScene,
                               QGraphicsItem, QAbstractScrollArea, QLabel)

from ..core.model import (Pattern, Stitch, StitchKind, Transform,
                          WORKSPACE)
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
        self._pens: dict = {}   # (hexcol, alpha) -> QPen cache

    def boundingRect(self) -> QRectF:
        c = self.canvas
        ws = WORKSPACE + 2
        return QRectF(-ws * CELL, -ws * CELL,
                      (c.pattern.width + 2 * ws) * CELL,
                      (c.pattern.height + 2 * ws) * CELL)

    def _grid_bounds(self):
        """Dot-grid intersection range: fabric is 0..w/0..h, the
        non-printing workspace extends WORKSPACE cells beyond it."""
        c = self.canvas
        ws = WORKSPACE
        return (-ws, -ws,
                c.pattern.width + ws - 1,
                c.pattern.height + ws - 1)

    def paint(self, painter: QPainter, option, widget=None):
        c = self.canvas
        p = c.pattern
        minx, miny, maxx, maxy = self._grid_bounds()

        # visible region in cell units — cull dots/stitches to the
        # viewport so repaints don't redraw the whole workspace
        vp = c.viewport().rect()
        tl = c.mapToScene(vp.topLeft())
        br = c.mapToScene(vp.bottomRight())
        x0, x1 = tl.x() / CELL - 1, br.x() / CELL + 1
        y0, y1 = tl.y() / CELL - 1, br.y() / CELL + 1

        def stitch_visible(s):
            if s.kind is StitchKind.X:
                return not (s.a[0] + 1 < x0 or s.a[0] > x1
                            or s.a[1] + 1 < y0 or s.a[1] > y1)
            pa, pb = s.endpoints()
            return not (max(pa[0], pb[0]) < x0 or min(pa[0], pb[0]) > x1
                        or max(pa[1], pb[1]) < y0 or min(pa[1], pb[1]) > y1)

        # workspace background (non-printing margin around the fabric)
        ws = WORKSPACE
        painter.fillRect(
            QRectF(-ws * CELL, -ws * CELL,
                   (p.width + 2 * ws) * CELL,
                   (p.height + 2 * ws) * CELL),
            QColor("#e8e4da"))

        # fabric background: intersections run 0..w, so the fabric
        # spans -0.5..w+0.5 cells (half a cell beyond the outer dots)
        painter.fillRect(
            QRectF(-0.5 * CELL, -0.5 * CELL,
                   (p.width + 1) * CELL, (p.height + 1) * CELL),
            QColor(c.fabric_color))

        # workspace outer boundary: dots run -ws..w+ws, so it spans
        # -ws-0.5 .. w+ws+0.5 cells
        painter.setPen(QPen(QColor("#a89f8a"), 1.2, Qt.PenStyle.DashLine))
        painter.drawRect(QRectF(-(ws + 0.5) * CELL, -(ws + 0.5) * CELL,
                                (p.width + 2 * ws + 1) * CELL,
                                (p.height + 2 * ws + 1) * CELL))
        painter.setPen(QColor("#8a7f6a"))
        painter.drawText(-ws * CELL + 6, -(ws + 0.4) * CELL - 4,
                         "workspace (non-printing)")

        # fabric outline
        painter.setPen(QPen(QColor("#8a7f6a"), 1.5, Qt.PenStyle.DashLine))
        painter.drawRect(QRectF(-0.5 * CELL, -0.5 * CELL,
                                (p.width + 1) * CELL,
                                (p.height + 1) * CELL))

        # dot grid: intersections are holes; darker every GRID_MAJOR.
        # Only draw dots inside the exposed region.
        gx_lo = max(minx, math.floor(x0))
        gx_hi = min(maxx + 1, math.ceil(x1))
        gy_lo = max(miny, math.floor(y0))
        gy_hi = min(maxy + 1, math.ceil(y1))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#c9bfa9"))
        for gx in range(gx_lo, gx_hi + 1):
            for gy in range(gy_lo, gy_hi + 1):
                painter.drawEllipse(QRectF(gx * CELL - 1.4,
                                            gy * CELL - 1.4, 2.8, 2.8))
        painter.setBrush(QColor("#6f6046"))
        for gx in range(gx_lo - (gx_lo % GRID_MAJOR), gx_hi + 1,
                        GRID_MAJOR):
            for gy in range(gy_lo - (gy_lo % GRID_MAJOR), gy_hi + 1,
                            GRID_MAJOR):
                painter.drawEllipse(QRectF(gx * CELL - 2.4,
                                            gy * CELL - 2.4, 4.8, 4.8))

        # stitches (raw pattern), honoring layer visibility + display color
        warn = c.sym_warn_keys
        for s in p.stitches.values():
            if not p.layer_visible(s.layer) or not stitch_visible(s):
                continue
            override = p.layer_color(s.layer)
            self._draw_stitch(painter, s,
                              override or palette.resolve(s.color))
            if warn and s.key in warn:
                # orange ring: editing this stitch can't stay symmetric
                pa, pb = s.endpoints()
                mx = (pa[0] + (pb[0] if pb else pa[0])) / 2
                my = (pa[1] + (pb[1] if pb else pa[1])) / 2
                painter.setPen(QPen(QColor("#ff8800"), 1.6))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(QRectF((mx - 0.32) * CELL,
                                            (my - 0.32) * CELL,
                                            0.64 * CELL, 0.64 * CELL))

        # guides (non-printing, view-only)
        if c.guides_visible or c._guide_drag is not None \
                or c._guide_move is not None:
            br = self.boundingRect()
            x0, x1 = br.left() / CELL, br.right() / CELL
            y0, y1 = br.top() / CELL, br.bottom() / CELL

            def seg_h(gy):
                return (br.left(), gy * CELL, br.right(), gy * CELL)

            def seg_v(gx):
                return (gx * CELL, br.top(), gx * CELL, br.bottom())

            def seg_d1(cc):   # y = x + c
                xa, xb = max(x0, y0 - cc), min(x1, y1 - cc)
                if xa >= xb:
                    return None
                return (xa * CELL, (xa + cc) * CELL,
                        xb * CELL, (xb + cc) * CELL)

            def seg_d2(cc):   # y = -x + c
                xa, xb = max(x0, cc - y1), min(x1, cc - y0)
                if xa >= xb:
                    return None
                return (xa * CELL, (-xa + cc) * CELL,
                        xb * CELL, (-xb + cc) * CELL)

            painter.setPen(QPen(QColor("#00aaaa"), 1,
                                Qt.PenStyle.DashLine))
            for gy in c.guides_h:
                painter.drawLine(*seg_h(gy))
            for gx in c.guides_v:
                painter.drawLine(*seg_v(gx))
            for cc in c.guides_d1:
                s = seg_d1(cc)
                if s:
                    painter.drawLine(*s)
            for cc in c.guides_d2:
                s = seg_d2(cc)
                if s:
                    painter.drawLine(*s)
            # guide being dragged out of a ruler
            if c._guide_drag is not None:
                kind, val = c._guide_drag
                painter.setPen(QPen(QColor("#ffaa00"), 1.5))
                seg = {"h": seg_h, "v": seg_v,
                       "d1": seg_d1, "d2": seg_d2}[kind](val)
                if seg:
                    painter.drawLine(*seg)
            # guide being repositioned
            if c._guide_move is not None:
                kind = c._guide_move["kind"]
                val = c._guide_move["cur"]
                painter.setPen(QPen(QColor("#ff5500"), 2.5))
                seg = {"h": seg_h, "v": seg_v,
                       "d1": seg_d1, "d2": seg_d2}[kind](val)
                if seg:
                    painter.drawLine(*seg)

        # canvas center marker (always visible) — on a grid intersection
        # (dot), matching the symmetry axes at width/2, height/2
        ccx = p.width / 2 * CELL
        ccy = p.height / 2 * CELL
        painter.setPen(QPen(QColor("#cc2266"), 1.2))
        painter.drawLine(ccx - 7, ccy, ccx + 7, ccy)
        painter.drawLine(ccx, ccy - 7, ccx, ccy + 7)
        painter.drawEllipse(QRectF(ccx - 2.5, ccy - 2.5, 5, 5))

        # resolved block instances (cached), honoring layer visibility
        for inst in p.instances:
            for s in c.resolved_stitches(inst):
                if not p.layer_visible(s.layer) or not stitch_visible(s):
                    continue
                override = p.layer_color(s.layer)
                col = override or palette.resolve(
                    c.instance_color(inst, s.color))
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
        a = int(alpha * 255) if alpha <= 1.0 else int(alpha)
        pkey = (hexcol, a)
        pen = self._pens.get(pkey)
        if pen is None:
            col = QColor(hexcol)
            col.setAlpha(a)
            pen = QPen(col, max(1.2, CELL * 0.16))
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            self._pens[pkey] = pen
        painter.setPen(pen)
        if s.kind is StitchKind.X:
            cx, cy = (s.a[0] + 0.5) * CELL, (s.a[1] + 0.5) * CELL
            h = CELL * 0.5
            painter.drawLine(cx - h, cy - h, cx + h, cy + h)
            painter.drawLine(cx + h, cy - h, cx - h, cy + h)
        else:
            pa, pb = s.endpoints()
            painter.drawLine(pa[0] * CELL, pa[1] * CELL,
                             pb[0] * CELL, pb[1] * CELL)

    def _draw_stitch_outline(self, painter, s: Stitch):
        pen = QPen(QColor("#2266ff"), 2.5)
        painter.setPen(pen)
        if s.kind is StitchKind.X:
            cx, cy = (s.a[0] + 0.5) * CELL, (s.a[1] + 0.5) * CELL
            h = CELL * 0.5
            painter.drawLine(cx - h, cy - h, cx + h, cy + h)
            painter.drawLine(cx + h, cy - h, cx - h, cy + h)
        else:
            pa, pb = s.endpoints()
            painter.drawLine(pa[0] * CELL, pa[1] * CELL,
                             pb[0] * CELL, pb[1] * CELL)


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

    # single-key tool shortcuts
    _TOOL_KEYS = {
        Qt.Key.Key_X: Tool.PENCIL,       # X Stitch
        Qt.Key.Key_L: Tool.XLINE,        # X Line
        Qt.Key.Key_B: Tool.BACKSTITCH,   # Backstitch
        Qt.Key.Key_E: Tool.ERASER,       # Eraser
        Qt.Key.Key_S: Tool.SELECT,       # Select
        Qt.Key.Key_M: Tool.MOVE,         # Move
        Qt.Key.Key_R: Tool.ROTATE,       # Rotate
        Qt.Key.Key_P: Tool.PAN,          # Pan
    }

    # signals
    cursor_cell_changed = Signal(int, int)
    draw_stitches = Signal(list)          # list[Stitch] already symmetry-expanded
    erase_keys = Signal(list)           # list of stitch keys under eraser
    place_block = Signal(object, str, int, int, int, int, bool, bool,
                         tuple)             # + (rows,cols,dx,dy,centered)
    # Block, scope, gx, gy, anchor, rot, mirror_x, mirror_y
    tool_changed = Signal(object)
    context_menu = Signal(object)   # viewport pos for right-click menu
    move_selection = Signal(int, int)               # dx, dy
    rotate_selection = Signal(int, int, int)        # cx, cy, quarters
    view_changed = Signal()                          # zoom/resize for rulers
    guides_changed = Signal()                        # guides edited (dirty)
    selection_changed = Signal()
    status_message = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pattern = Pattern()
        self.library_blocks: dict = {}
        self.tool = Tool.SELECT
        self.current_color = "#000000"
        self.fabric_color = "#F5F0E6"
        self.symmetry_axes: set = set()   # selected axes (persist when off)
        self.symmetry_on = True           # master symmetry switch
        self.sym_warn_keys: set = set()   # stitches w/o full symmetry orbit
        self.selection = Selection()
        self.selection_changed.connect(self._clear_ghost_cache)
        self.pending_block = None  # Block to place
        self.pending_scope = "project"
        self.place_anchor = 5      # 3x3 anchor key (numpad layout, 5=center)
        self.place_rot = 0         # pending placement rotation (deg)
        self.place_mx = False      # pending placement mirror X
        self.place_my = False      # pending placement mirror Y
        # array placement: rows x cols grid, dx/dy gap in stitches.
        # Values persist for the Array dialog, but only apply while
        # array_armed (set by the dialog, consumed by one placement).
        self.array_rows = 1
        self.array_cols = 1
        self.array_dx = 0
        self.array_dy = 0
        self.array_centered = False
        self.array_armed = False
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
        self._ghost_cache: dict = {}      # ghost stroke lists per params
        self._ghost_base_cache = {}       # resolved block-local stitches
        self._last_mouse_scene = QPointF(0, 0)
        self._ghost_cell = None
        self._back_current = None
        # guides (view-only, snapped to grid lines)
        self.guides_h: set = set()   # horizontal guide row (cell y)
        self.guides_v: set = set()   # vertical guide col (cell x)
        self.guides_d1: set = set()  # "/" diag: y = x + c
        self.guides_d2: set = set()  # "\" diag: y = -x + c
        self.guides_visible = True
        self.guides_locked = False   # locked guides can't be grabbed/moved
        self._guide_drag = None      # (kind_str, value) preview while dragging
        self._guide_move = None      # dict while editing a placed guide
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
        # high-contrast scrollbars: light track, dark chunky handle
        self.setStyleSheet("""
            QScrollBar:vertical { background:#e7e0d0; width:14px;
                                  margin:0px; border-left:1px solid #cfc6b0; }
            QScrollBar::handle:vertical { background:#5a5a5a;
                                          min-height:28px; border-radius:4px;
                                          margin:2px; }
            QScrollBar::handle:vertical:hover { background:#333; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height:0px; }
            QScrollBar:horizontal { background:#e7e0d0; height:14px;
                                    margin:0px; border-top:1px solid #cfc6b0; }
            QScrollBar::handle:horizontal { background:#5a5a5a;
                                            min-width:28px;
                                            border-radius:4px; margin:2px; }
            QScrollBar::handle:horizontal:hover { background:#333; }
            QScrollBar::add-line:horizontal,
            QScrollBar::sub-line:horizontal { width:0px; }
        """)
        # scrollbars are siblings of the viewport — give them an explicit
        # arrow cursor so they never inherit the tool cursor
        self.horizontalScrollBar().setCursor(Qt.CursorShape.ArrowCursor)
        self.verticalScrollBar().setCursor(Qt.CursorShape.ArrowCursor)
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
        if tool is not Tool.BLOCK:
            self.array_armed = False   # leaving block placement disarms
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
            if self.array_armed and (self.array_rows > 1
                                     or self.array_cols > 1):
                text += (f"  ·array {self.array_rows}x{self.array_cols}"
                         f" gap {self.array_dx},{self.array_dy}")
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
        """Tool-specific cursor: pencil for X tools, glyph per tool."""
        if self._panning:
            return
        if self.tool is Tool.MOVE:
            self.viewport().setCursor(Qt.CursorShape.SizeAllCursor)
            return
        if self.tool is Tool.SELECT:
            self.viewport().unsetCursor()   # standard arrow
            return
        if self.tool is Tool.PAN:
            self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
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

        if self.tool is Tool.PENCIL:
            draw_pencil(col)
            # tiny X at the tip: this tool fills stitch cells
            tx, ty = int(m - 1), int(m - 1)
            xp = QPen(col, 2)
            xp.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(xp)
            p.drawLine(tx - 3, ty - 3, tx + 3, ty + 3)
            p.drawLine(tx - 3, ty + 3, tx + 3, ty - 3)
        elif self.tool is Tool.XLINE:
            draw_pencil(col)
            # dashed line trailing from the tip: this tool draws lines
            dp = QPen(col, 1.5, Qt.PenStyle.DashLine)
            p.setPen(dp)
            p.drawLine(int(m - 1), int(m - 1), int(m + 12), int(m + 12))
        elif self.tool is Tool.BACKSTITCH:
            # minimal crosshair on the snap dot
            white = QPen(QColor("#ffffff"), 3.5)
            white.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(white)
            p.drawLine(int(c - 8), int(c), int(c + 8), int(c))
            p.drawLine(int(c), int(c - 8), int(c), int(c + 8))
            sp = QPen(col, 1.8)
            sp.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(sp)
            p.drawLine(int(c - 8), int(c), int(c + 8), int(c))
            p.drawLine(int(c), int(c - 8), int(c), int(c + 8))
            p.setBrush(QBrush(col))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(int(c - 1), int(c - 1), 3, 3)
        elif self.tool is Tool.ERASER:
            # compact red X — smaller than the stitch glyphs
            em = 12
            pen = QPen(QColor("#d33"), 3)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawLine(em, em, size - em, size - em)
            p.drawLine(size - em, em, em, size - em)
            p.setPen(QPen(QColor("#ffffff"), 1.2))
            p.drawLine(em, em, size - em, size - em)
            p.drawLine(size - em, em, em, size - em)
        elif self.tool is Tool.ROTATE:
            # near-full circular arrow = rotation, gap at upper right
            import math
            r = 12.0
            pts = [QPointF(c + r * math.cos(math.radians(a)),
                           c + r * math.sin(math.radians(a)))
                   for a in range(80, 391, 5)]
            rp = QPen(QColor("#cc7700"), 3)
            rp.setCapStyle(Qt.PenCapStyle.RoundCap)
            rp.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(rp)
            p.drawPolyline(pts)
            # arrowhead: tip at 30°, wings back along the arc
            def arc_pt(deg):
                a = math.radians(deg)
                return QPointF(c + r * math.cos(a), c + r * math.sin(a))
            tip = arc_pt(30)
            p.drawLine(tip, arc_pt(8))
            p.drawLine(tip, arc_pt(-12))
            p.setBrush(QBrush(QColor("#cc7700")))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(int(c - 2), int(c - 2), 4, 4)
        elif self.tool is Tool.BLOCK:
            # dashed frame + solid inner square = a block being stamped
            bp = QPen(QColor("#2266ff"), 1.8, Qt.PenStyle.DashLine)
            p.setPen(bp)
            p.drawRect(int(m), int(m), int(size - 2 * m),
                       int(size - 2 * m))
            p.setBrush(QBrush(QColor("#2266ff")))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRect(int(c - 5), int(c - 5), 10, 10)
        # PAN uses OpenHandCursor above; no custom pixmap needed
        p.end()

        if self.tool in (Tool.PENCIL, Tool.XLINE):
            # hotspot at the pencil tip
            hx = hy = int(m - 1)
        else:
            hx = hy = int(size / 2)
        self.viewport().setCursor(QCursor(QPixmap.fromImage(img), hx, hy))

    # -- scene management ---------------------------------------------
    def _update_scene_rect(self):
        # center the scene rect on the pattern so scrollbar centering and
        # zoom-out land on the fabric, not the scene origin
        cx = self.pattern.width / 2 * CELL
        cy = self.pattern.height / 2 * CELL
        m = (max(self.pattern.width, self.pattern.height) / 2
             + WORKSPACE + 2 * MARGIN) * CELL
        self.scene.setSceneRect(cx - m, cy - m, 2 * m, 2 * m)

    def pattern_center_scene(self):
        return QPointF(self.pattern.width / 2 * CELL,
                       self.pattern.height / 2 * CELL)

    @property
    def active_symmetry_axes(self):
        """Axes actually applied right now (empty when symmetry is off)."""
        return self.symmetry_axes if self.symmetry_on else set()

    def set_pattern(self, pattern: Pattern):
        self.pattern = pattern
        self.selection.clear()
        self._resolve_cache.clear()
        self._ghost_cache.clear()
        self._ghost_base_cache.clear()
        g = pattern.guides
        self.guides_h = set(g.get("h", []))
        self.guides_v = set(g.get("v", []))
        self.guides_d1 = set(g.get("d1", []))
        self.guides_d2 = set(g.get("d2", []))
        self._update_scene_rect()
        self.centerOn(self.pattern_center_scene())
        self.viewport().update()

    def refresh(self):
        self._resolve_cache.clear()
        self._ghost_cache.clear()
        self._ghost_base_cache.clear()
        self.viewport().update()

    # -- coordinate helpers --------------------------------------------
    def cell_from_scene(self, pos) -> tuple[int, int] | None:
        """Nearest grid intersection to the scene position.

        Intersections run -WORKSPACE..width+WORKSPACE — the fabric is
        0..width/0..height, the rest is non-printing workspace."""
        p = self.mapToScene(pos)
        gx = int(round(p.x() / CELL))
        gy = int(round(p.y() / CELL))
        ws = WORKSPACE
        if -ws <= gx <= self.pattern.width + ws \
                and -ws <= gy <= self.pattern.height + ws:
            return (gx, gy)
        return None

    def _clamped_intersection(self, scene_pt) -> tuple[int, int]:
        """Nearest grid intersection, clamped to fabric+workspace."""
        gx = int(round(scene_pt.x() / CELL))
        gy = int(round(scene_pt.y() / CELL))
        w, h = self.pattern.width, self.pattern.height
        ws = WORKSPACE
        return (min(max(gx, -ws), w + ws),
                min(max(gy, -ws), h + ws))

    def cell_index_from_scene(self, pos) -> tuple[int, int] | None:
        """Cell (floor) containing the scene position — for X stitches,
        whose a coords are cell indices centered at a+0.5. Cells run
        -WORKSPACE..width+WORKSPACE-1 (between the edge dots)."""
        p = self.mapToScene(pos)
        gx = math.floor(p.x() / CELL)
        gy = math.floor(p.y() / CELL)
        ws = WORKSPACE
        if -ws <= gx < self.pattern.width + ws \
                and -ws <= gy < self.pattern.height + ws:
            return (gx, gy)
        return None

    def point_from_scene(self, pos) -> tuple[float, float]:
        p = self.mapToScene(pos)
        return (p.x() / CELL, p.y() / CELL)

    # -- block resolution cache ----------------------------------------
    def _clear_ghost_cache(self):
        self._ghost_cache.clear()

    def resolved_stitches(self, inst) -> list[Stitch]:
        key = (inst.uid, inst.block_id, inst.scope, inst.layer,
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
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
            self.zoom_at(event.position().toPoint(), factor)
            event.accept()
            return
        # plain wheel scrolls the view
        d = event.pixelDelta()
        if d.isNull():
            a = event.angleDelta()
            d = QPoint(int(a.x() / 3), int(a.y() / 3))
        self.horizontalScrollBar().setValue(
            self.horizontalScrollBar().value() - d.x())
        self.verticalScrollBar().setValue(
            self.verticalScrollBar().value() - d.y())
        event.accept()

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

    def zoom_actual_size(self):
        """Zoom so one grid cell equals its real-world stitch pitch.

        Approximate: pitch = 25.4/aida mm per cell, converted to pixels
        via the screen's logical DPI."""
        pitch_mm = 25.4 / max(1, self.pattern.aida_count)
        dpi = 96.0
        if self.screen() is not None:
            dpi = self.screen().logicalDotsPerInch()
        px_per_cell = pitch_mm * dpi / 25.4
        target = px_per_cell / CELL
        self.resetTransform()
        self.scale(target, target)
        self.centerOn(self.pattern_center_scene())
        pct = target * 100
        self.status_message.emit(
            f"Actual size ({self.pattern.aida_count} ct, ~{dpi:.0f} dpi): "
            f"{pct:.0f}%")

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
            if self._guide_move is not None:
                self._guide_move = None
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
                self.status_message.emit(f"placement rotation: {self.place_rot}°")
                event.accept()
                return
            if key == Qt.Key.Key_F:
                self.place_mx = not self.place_mx
                self._update_tool_label()
                self.viewport().update()
                self.status_message.emit(
                    f"placement flip horizontal: {'on' if self.place_mx else 'off'}")
                event.accept()
                return
            if key == Qt.Key.Key_V:
                self.place_my = not self.place_my
                self._update_tool_label()
                self.viewport().update()
                self.status_message.emit(
                    f"placement flip vertical: {'on' if self.place_my else 'off'}")
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
        # single-key tool shortcuts (plain keys, no modifiers)
        tool = self._TOOL_KEYS.get(event.key())
        if tool is not None \
                and event.modifiers() == Qt.KeyboardModifier.NoModifier:
            self.set_tool(tool)
            event.accept()
            return
        if event.key() == Qt.Key.Key_Space:
            self._panning = True
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key.Key_Space:
            self._panning = False
            self.viewport().unsetCursor()
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
                self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            self._pan_start = event.position().toPoint()
            event.accept()
            return
        if event.button() == Qt.MouseButton.RightButton:
            # in-progress action -> commit/cancel it, keep tool active
            committing = (
                (self.tool is Tool.BACKSTITCH and self._poly is not None) or
                self._anchor is not None or
                self._guide_move is not None or
                self._move_anchor is not None or
                self._rot_center is not None)
            if committing:
                if self.tool is Tool.BACKSTITCH and self._poly is not None:
                    self._finish_poly(commit=len(self._poly) >= 2)
                self._clear_anchor()
                self._guide_move = None
                self._move_anchor = self._move_cur = self._move_target = None
                self._rot_center = self._rot_ref = None
                self._rot_q = 0
                self.viewport().update()
            elif self.tool is not Tool.SELECT:
                # nothing in progress -> second right-click exits to Select
                if self.tool is Tool.BLOCK \
                        and self.pending_block is not None:
                    self.status_message.emit("block placement ended")
                self.set_tool(Tool.SELECT)
            else:
                # right-click on an item -> MRU menu; on empty -> deselect
                scene_pt = self.mapToScene(event.position().toPoint())
                keys, uids = self._items_at_point(scene_pt)
                if keys or uids:
                    self.context_menu.emit(event.position().toPoint())
                elif not self.selection.empty:
                    self.selection.clear()
                    self.selection_changed.emit()
                    self.viewport().update()
            event.accept()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return

        cell = self.cell_from_scene(event.position().toPoint())
        xcell = self.cell_index_from_scene(event.position().toPoint())
        scene_pt = self.mapToScene(event.position().toPoint())
        self._press_scene = scene_pt
        self._press_moved = False

        if self.tool is Tool.PENCIL:
            if xcell:
                self._drag_start_cell = xcell
                self._drag_last_cell = xcell
        elif self.tool is Tool.BACKSTITCH:
            gp = self._clamped_intersection(scene_pt)
            self._back_start = gp
            self._press_point = gp
        elif self.tool is Tool.XLINE:
            if xcell:
                self._press_point = xcell
        elif self.tool is Tool.ERASER:
            keys = self._eraser_keys_at(scene_pt)
            self._erase_last = scene_pt
            if keys:
                self.erase_keys.emit(keys)
        elif self.tool is Tool.SELECT:
            hit = None if self.guides_locked else self._guide_at(scene_pt)
            if hit is not None:
                # grab a guide to reposition it
                self._guide_move = {"kind": hit[0], "key": hit[1],
                                    "cur": hit[1]}
                self.viewport().update()
            else:
                self._rubber_start = scene_pt
        elif self.tool is Tool.BLOCK and self.pending_block is not None:
            if cell:
                self.place_block.emit(self.pending_block, self.pending_scope,
                                      cell[0], cell[1], self.place_anchor,
                                      self.place_rot, self.place_mx,
                                      self.place_my, self._array_tuple())
                # array is one-shot: consumed by this placement
                if self.array_armed:
                    self.array_armed = False
                    self._update_tool_label()
                    self.viewport().update()
        elif self.tool is Tool.MOVE:
            if self.selection.empty:
                self.status_message.emit("Move: select stitches or blocks first.")
            elif self._move_anchor is None:
                self._move_anchor = scene_pt
                self._move_cur = scene_pt
                self._move_target = None
                self.status_message.emit("move: drag or click target")
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
                self.status_message.emit(
                    "rotate: press-drag from a point to set the angle")
                self.viewport().update()
            elif self._rot_ref is None:
                self._rot_ref = scene_pt
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        cell_i = self.cell_from_scene(event.position().toPoint())
        cell_x = self.cell_index_from_scene(event.position().toPoint())
        # X-stitch tools and the eraser work in cell-index space
        cell = cell_x if self.tool in (
            Tool.PENCIL, Tool.XLINE, Tool.ERASER) else cell_i
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
            if self.tool is Tool.XLINE:
                self._back_current = (
                    math.floor(self._last_mouse_scene.x() / CELL),
                    math.floor(self._last_mouse_scene.y() / CELL))
            else:
                self._back_current = self._clamped_intersection(
                    self._last_mouse_scene)

        if self._guide_move is not None:
            px = self._last_mouse_scene.x() / CELL
            py = self._last_mouse_scene.y() / CELL
            self._guide_move["cur"] = self._guide_snapped(
                self._guide_move["kind"], px, py)
            self.viewport().update()
            super().mouseMoveEvent(event)
            return

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
        elif self.tool is Tool.ERASER \
                and (event.buttons() & Qt.MouseButton.LeftButton):
            cur = self._last_mouse_scene
            last = getattr(self, "_erase_last", cur)
            # sample along the drag path so fast moves don't skip stitches
            dx, dy = cur.x() - last.x(), cur.y() - last.y()
            dist = (dx * dx + dy * dy) ** 0.5
            steps = max(1, int(dist / (0.3 * CELL)))
            keys = []
            for i in range(steps + 1):
                t = i / steps
                pt = QPointF(last.x() + dx * t, last.y() + dy * t)
                keys.extend(self._eraser_keys_at(pt))
            self._erase_last = cur
            keys = list(dict.fromkeys(keys))
            if keys:
                self.erase_keys.emit(keys)
        elif self.tool is Tool.BLOCK and self.pending_block is not None:
            self.viewport().update()
        elif self.tool is Tool.MOVE and self._move_anchor is not None:
            dx, dy = self._move_delta_clamped(self._last_mouse_scene)
            self._move_cur = QPointF(
                self._move_anchor.x() + dx * CELL,
                self._move_anchor.y() + dy * CELL)
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
        if self._guide_move is not None \
                and event.button() == Qt.MouseButton.LeftButton:
            gm = self._guide_move
            self._guide_move = None
            store = {"h": self.guides_h, "v": self.guides_v,
                     "d1": self.guides_d1,
                     "d2": self.guides_d2}[gm["kind"]]
            store.discard(gm["key"])
            store.add(gm["cur"])
            self._sync_guides()
            self.viewport().update()
            event.accept()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            super().mouseReleaseEvent(event)
            return

        scene_pt = self.mapToScene(event.position().toPoint())
        cell_i = self.cell_from_scene(event.position().toPoint())
        cell_x = self.cell_index_from_scene(event.position().toPoint())
        cell = cell_x if self.tool in (
            Tool.PENCIL, Tool.XLINE, Tool.ERASER) else cell_i
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
            gp = self._clamped_intersection(scene_pt)
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
            if not moved:
                self._click_select(
                    scene_pt, additive=bool(
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

    def _array_tuple(self):
        """Effective array spec — (1,1,...) unless armed."""
        if not self.array_armed:
            return (1, 1, 0, 0, False)
        return (self.array_rows, self.array_cols,
                self.array_dx, self.array_dy, self.array_centered)

    def _array_offsets(self):
        """(dc, dr) cell offsets for each array element."""
        if not self.array_armed:
            return [(0, 0)]
        rows = max(1, self.array_rows)
        cols = max(1, self.array_cols)
        if rows == 1 and cols == 1:
            return [(0, 0)]
        c0 = -(cols - 1) // 2 if self.array_centered else 0
        r0 = -(rows - 1) // 2 if self.array_centered else 0
        return [(c0 + c, r0 + r)
                for r in range(rows) for c in range(cols)]

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

    # -- guides ------------------------------------------------------------
    @staticmethod
    def _guide_key(orient, gx, gy, kind):
        """Map a ruler drag to (storage kind, snapped value)."""
        if kind == 1:    # "/" family: y = x + c  ->  c = y - x
            return "d1", gy - gx
        if kind == 2:    # "\" family: y = -x + c ->  c = y + x
            return "d2", gy + gx
        if orient is Qt.Orientation.Horizontal:
            return "h", gy
        return "v", gx

    def guide_dragging(self, orient, gx, gy, kind):
        self._guide_drag = self._guide_key(orient, gx, gy, kind)
        self.viewport().update()

    def guide_dropped(self, orient, gx, gy, kind):
        self._guide_drag = None
        gkind, val = self._guide_key(orient, gx, gy, kind)
        store = {"h": self.guides_h, "v": self.guides_v,
                 "d1": self.guides_d1, "d2": self.guides_d2}[gkind]
        store.add(val)
        self._sync_guides()
        self.viewport().update()

    def _sync_guides(self):
        """Write guide sets back to pattern.guides for persistence."""
        g = self.pattern.guides
        g["h"] = sorted(self.guides_h)
        g["v"] = sorted(self.guides_v)
        g["d1"] = sorted(self.guides_d1)
        g["d2"] = sorted(self.guides_d2)
        self.guides_changed.emit()

    def clear_guides(self):
        self.guides_h.clear()
        self.guides_v.clear()
        self.guides_d1.clear()
        self.guides_d2.clear()
        self._sync_guides()
        self.viewport().update()

    # -- guide hit-testing / editing ---------------------------------------
    def _guide_at(self, scene_pt):
        """Nearest guide within ~6px of the scene point, or None."""
        px, py = scene_pt.x() / CELL, scene_pt.y() / CELL
        best = None
        best_d = 0.3  # cell units (~6px)
        for gy in self.guides_h:
            d = abs(py - gy)
            if d < best_d:
                best, best_d = ("h", gy), d
        for gx in self.guides_v:
            d = abs(px - gx)
            if d < best_d:
                best, best_d = ("v", gx), d
        import math
        for cc in self.guides_d1:
            d = abs(py - px - cc) / math.sqrt(2)
            if d < best_d:
                best, best_d = ("d1", cc), d
        for cc in self.guides_d2:
            d = abs(py + px - cc) / math.sqrt(2)
            if d < best_d:
                best, best_d = ("d2", cc), d
        return best

    def _guide_snapped(self, kind, px, py):
        if kind == "h":
            return int(round(py))
        if kind == "v":
            return int(round(px))
        if kind == "d1":
            return int(round(py - px))
        return int(round(py + px))  # d2

    # -- move / rotate tools ----------------------------------------------
    def _selection_bbox(self):
        """Cell-space bbox of selected stitches + instances, or None."""
        xs, ys = [], []
        for k in self.selection.stitch_keys:
            s = self.pattern.stitches.get(k)
            if s:
                for px, py in s.extent_points():
                    xs.append(px); ys.append(py)
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

    def _move_delta_clamped(self, scene_pt):
        """Move delta in cells, clamped so the selection bbox stays
        inside fabric + workspace."""
        if self._move_anchor is None:
            return 0, 0
        bb = self._selection_bbox()
        if bb is None:
            return 0, 0
        dx = int(round((scene_pt.x() - self._move_anchor.x()) / CELL))
        dy = int(round((scene_pt.y() - self._move_anchor.y()) / CELL))
        ws = WORKSPACE
        x0, y0, x1, y1 = bb
        w, h = self.pattern.width, self.pattern.height
        dx = min(max(dx, math.ceil(-ws - x0)), math.floor(w + ws - x1))
        dy = min(max(dy, math.ceil(-ws - y0)), math.floor(h + ws - y1))
        return dx, dy

    def _commit_move(self):
        if self._move_anchor is None:
            return
        end = self._move_target if self._move_target is not None \
            else self._move_cur
        if end is None:
            self._move_anchor = self._move_cur = self._move_target = None
            return
        dx, dy = self._move_delta_clamped(end)
        self._move_anchor = self._move_cur = self._move_target = None
        if dx == 0 and dy == 0:
            self.viewport().update()
            return
        self.move_selection.emit(dx, dy)
        self.viewport().update()

    def _commit_rotate(self):
        if self._rot_center is None:
            return
        if self._rot_ref is not None and self._rot_q:
            cx, cy = self._rot_center
            self.rotate_selection.emit(cx, cy, self._rot_q)
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
                        a_cell[0] + 0.5 + nx * off, a_cell[1] + 0.5 + ny * off,
                        b_cell[0] + 0.5 + nx * off, b_cell[1] + 0.5 + ny * off)
        stitches = [Stitch(StitchKind.X, c, None, self.current_color)
                    for c in sorted(cells)]
        stitches = apply_symmetry(stitches, self.active_symmetry_axes,
                                  self.pattern.width, self.pattern.height)
        self._emit_with_layer(stitches)

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
        stitches = apply_symmetry(stitches, self.active_symmetry_axes,
                                  self.pattern.width, self.pattern.height)
        self._emit_with_layer(stitches)

    def _finish_poly(self, commit: bool):
        """Right-click on backstitch tool: commit (>=2 pts) or cancel."""
        if commit and self._poly and len(self._poly) >= 2:
            from ..core.symmetry import apply_symmetry
            stitches = []
            for a, b in zip(self._poly, self._poly[1:]):
                if a != b:
                    stitches.extend(
                        self._backline_stitches(a, b, self.current_color))
            stitches = apply_symmetry(stitches, self.active_symmetry_axes,
                                      self.pattern.width, self.pattern.height)
            self._emit_with_layer(stitches)
            self.status_message.emit(f"polyline committed ({len(self._poly)} points)")
        else:
            self.status_message.emit("polyline cancelled")
        self._poly = None
        self.viewport().update()

    def _emit_pencil(self, cell):
        from ..core.symmetry import apply_symmetry
        s = Stitch(StitchKind.X, cell, None, self.current_color)
        stitches = apply_symmetry([s], self.active_symmetry_axes,
                                  self.pattern.width, self.pattern.height)
        self._emit_with_layer(stitches)

    def _emit_with_layer(self, stitches):
        """Tag new stitches with the pattern's active layer, then emit."""
        lyr = self.pattern.active_layer
        if any(s.layer != lyr for s in stitches):
            from dataclasses import replace
            stitches = [replace(s, layer=lyr) for s in stitches]
        self.draw_stitches.emit(stitches)

    def _cells_along(self, a, b) -> set:
        """Cells on the line between cell indices a and b.

        Samples in center space (index + 0.5) so floor() yields the
        cells the drawn line actually passes through."""
        return self._cells_along_float(a[0] + 0.5, a[1] + 0.5,
                                       b[0] + 0.5, b[1] + 0.5)

    @staticmethod
    def _cells_along_float(x0, y0, x1, y1, step=0.5) -> set:
        """Cell indices sampled along a (possibly fractional) line."""
        cells = set()
        dist = max(abs(x1 - x0), abs(y1 - y0), step)
        n = max(int(dist / step) + 1, 2)
        for i in range(n + 1):
            t = i / n
            cells.add((math.floor(x0 + (x1 - x0) * t),
                       math.floor(y0 + (y1 - y0) * t)))
        return cells

    def _stitch_hit_dist(self, s: Stitch, px, py):
        """Distance in cells from point to stitch extent, or None.

        X stitches hit within ~0.6 cells of their intersection (covers
        the arms); backstitches hit within ~0.4 cells of the segment.
        """
        if s.kind is StitchKind.X:
            # X occupies cell [a, a+1] centered at a+0.5
            cx, cy = s.a[0] + 0.5, s.a[1] + 0.5
            d = max(abs(px - cx), abs(py - cy))
            return d if d <= 0.6 else None
        pa, pb = s.endpoints()
        d = self._dist_to_seg(px, py, pa, pb)
        return d if d <= 0.4 else None

    def _items_at_point(self, scene_pt):
        """Nearest (stitch key | instance uid) under the scene point."""
        px, py = scene_pt.x() / CELL, scene_pt.y() / CELL
        p = self.pattern
        best = None
        best_d = 1e9
        for s in p.stitches.values():
            if p.layer_locked(s.layer) or not p.layer_visible(s.layer):
                continue
            d = self._stitch_hit_dist(s, px, py)
            if d is not None and d < best_d:
                best, best_d = ("s", s.key), d
        for inst in p.instances:
            if inst.layer and (p.layer_locked(inst.layer)
                               or not p.layer_visible(inst.layer)):
                continue
            for s in self.resolved_stitches(inst):
                if not p.layer_visible(s.layer) \
                        or p.layer_locked(s.layer):
                    continue
                d = self._stitch_hit_dist(s, px, py)
                if d is not None and d < best_d:
                    best, best_d = ("i", inst.uid), d
                    break
        if best is None:
            return set(), set()
        if best[0] == "s":
            return {best[1]}, set()
        return set(), {best[1]}

    def _click_select(self, scene_pt, additive=False):
        """Click-select nearest segment: plain replaces, Shift toggles."""
        keys, uids = self._items_at_point(scene_pt)
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
            # X occupies the unit cell [a, a+1] x [a1, a1+1]
            return (self._frac_inside_1d(s.a[0], s.a[0] + 1, x0, x1)
                    * self._frac_inside_1d(s.a[1], s.a[1] + 1, y0, y1))
        # backstitch: parametric fraction of the drawn (trimmed) segment
        # inside the rect; t runs along full a->b, clipped to [ta, tb]
        ax, ay = s.a
        bx, by = s.b
        dx, dy = bx - ax, by - ay
        t0, t1 = s.ta, s.tb
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
        return (t1 - t0) / (s.tb - s.ta)

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
        p = self.pattern
        self.selection.stitch_keys = {
            s.key for s in p.stitches.values()
            if not p.layer_locked(s.layer)
            and p.layer_visible(s.layer)
            and self._stitch_cover(s, x0, y0, x1, y1) >= cov}
        self.selection.instance_uids = set()
        for inst in p.instances:
            if inst.layer and (p.layer_locked(inst.layer)
                               or not p.layer_visible(inst.layer)):
                continue
            sts = [s for s in self.resolved_stitches(inst)
                   if not p.layer_locked(s.layer)
                   and p.layer_visible(s.layer)]
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

    def _ghost_strokes(self):
        """Selected stitches transformed by the pending move/rotate.

        Returns list of (kind, a, b, color_spec) in cell coords, or [].
        """
        dx = dy = 0
        rot = None  # (cx, cy, q)
        if self.tool is Tool.MOVE and self._move_anchor is not None:
            end = self._move_target if self._move_target is not None \
                else self._move_cur
            if end is None:
                return []
            dx = int(round((end.x() - self._move_anchor.x()) / CELL))
            dy = int(round((end.y() - self._move_anchor.y()) / CELL))
            if dx == 0 and dy == 0:
                return []
        elif self.tool is Tool.ROTATE and self._rot_center is not None \
                and self._rot_q:
            rot = (self._rot_center[0], self._rot_center[1], self._rot_q)
        else:
            return []

        def xf(p):
            x, y = p[0] + dx, p[1] + dy
            if rot:
                cx, cy, q = rot
                ddx, ddy = x - cx, y - cy
                for _ in range(q):
                    ddx, ddy = -ddy, ddx
                x, y = cx + ddx, cy + ddy
            return (x, y)

        # cache per quantized transform — mouse moves within the same
        # cell delta reuse the stroke list instead of recomputing
        gkey = ("m", dx, dy) if rot is None else ("r",) + rot
        hit = self._ghost_cache.get(gkey)
        if hit is not None:
            return hit

        out = []
        for k in self.selection.stitch_keys:
            s = self.pattern.stitches.get(k)
            if s:
                out.append((s.kind, xf(s.a),
                            xf(s.b) if s.b else None, s.color,
                            s.ta, s.tb))
        for inst in self.pattern.instances:
            if inst.uid not in self.selection.instance_uids:
                continue
            for s in self.resolved_stitches(inst):
                out.append((s.kind, xf(s.a),
                            xf(s.b) if s.b else None,
                            self.instance_color(inst, s.color),
                            s.ta, s.tb))
        self._ghost_cache[gkey] = out
        return out

    def _draw_ghost_strokes(self, painter: QPainter, strokes):
        pens = {}
        for kind, a, b, color, ta, tb in strokes:
            pen = pens.get(color)
            if pen is None:
                col = QColor(palette.resolve(color))
                col.setAlpha(80)
                pen = QPen(col, max(1.2, CELL * 0.16))
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                pens[color] = pen
            painter.setPen(pen)
            if kind is StitchKind.X:
                cx, cy = (a[0] + 0.5) * CELL, (a[1] + 0.5) * CELL
                h = CELL * 0.5
                painter.drawLine(cx - h, cy - h, cx + h, cy + h)
                painter.drawLine(cx + h, cy - h, cx - h, cy + h)
            else:
                pa = (a[0] + (b[0] - a[0]) * ta, a[1] + (b[1] - a[1]) * ta)
                pb = (a[0] + (b[0] - a[0]) * tb, a[1] + (b[1] - a[1]) * tb)
                painter.drawLine(pa[0] * CELL, pa[1] * CELL,
                                 pb[0] * CELL, pb[1] * CELL)

    def _draw_transform_ghost(self, painter: QPainter):
        """Paint selected stitches ghosted at their pending transform."""
        self._draw_ghost_strokes(painter, self._ghost_strokes())

    def _block_ghost_stitches(self):
        """Pending block's resolved stitches at the ghost position,
        expanded over the placement array."""
        if self.pending_block is None or self._ghost_cell is None:
            return []
        bb = self.pending_block.bbox()
        if not bb:
            return []
        gx, gy = self._ghost_cell
        # cache key covers every input to the ghost computation
        b = self.pending_block
        fp = (len(b.stitches), len(b.instances),
              id(b.stitches), id(b.instances))
        gkey = (id(b), gx, gy, self.place_anchor, self.place_rot,
                self.place_mx, self.place_my, self._array_tuple(), fp)
        hit = self._ghost_cache.get(("block",) + gkey)
        if hit is not None:
            return hit
        ax, ay = self._block_anchor(bb)
        ax, ay = int(round(ax)), int(round(ay))
        inner = Transform.from_semantic(0, 0, self.place_rot,
                                        self.place_mx, self.place_my)
        local = (Transform.translation(-ax, -ay)
                 .then(inner)
                 .then(Transform.translation(ax, ay)))
        reg = {**self.pattern.blocks, **self.library_blocks}
        # resolve once in block-local space, then transform per cell —
        # much cheaper than re-resolving for every array element
        from ..core.model import transform_stitch
        base = self._ghost_base(b, reg)
        # spacing is the GAP between block edges: step = placed bbox
        # size + gap (bbox after pending rot/mirror, before placement)
        gbb = self._ghost_bbox(bb)
        step_x = int(round(gbb[2] - gbb[0])) + self.array_dx
        step_y = int(round(gbb[3] - gbb[1])) + self.array_dy
        out = []
        for dc, dr in self._array_offsets():
            t = local.then(Transform.translation(
                gx - ax + dc * step_x,
                gy - ay + dr * step_y))
            for s in base:
                ts = transform_stitch(s, t)
                out.append((ts.kind, ts.a, ts.b, ts.color,
                            ts.ta, ts.tb))
        self._ghost_cache[("block",) + gkey] = out
        return out

    def _ghost_base(self, block, registry):
        """Block-local resolved stitches, cached per block content."""
        fp = (len(block.stitches), len(block.instances),
              id(block.stitches), id(block.instances))
        key = (id(block), fp)
        if key not in self._ghost_base_cache:
            self._ghost_base_cache[key] = block.resolved_stitches(
                Transform.IDENTITY, registry=registry)
        return self._ghost_base_cache[key]

    def _block_ghost_strokes(self):
        return self._block_ghost_stitches()

    def _eraser_keys_at(self, scene_pt) -> list:
        """Stitch keys the eraser would remove at a scene point.

        Single source of truth for both the erase action and the
        highlight, so they always agree.
        """
        gx = scene_pt.x() / CELL
        gy = scene_pt.y() / CELL
        keys = []
        for s in self.pattern.stitches.values():
            if self.pattern.layer_locked(s.layer) \
                    or not self.pattern.layer_visible(s.layer):
                continue
            if s.kind is StitchKind.X:
                # X occupies cell [a, a+1]; center at a+0.5
                if abs(gx - (s.a[0] + 0.5)) <= 0.55 \
                        and abs(gy - (s.a[1] + 0.5)) <= 0.55:
                    keys.append(s.key)
            elif self._dist_to_seg(gx, gy, *s.endpoints()) <= 0.6:
                keys.append(s.key)
        return keys

    def _draw_eraser_highlight(self, painter: QPainter):
        """Highlight stitches the eraser would remove at the cursor."""
        keys = self._eraser_keys_at(self._last_mouse_scene)
        hits = [self.pattern.stitches[k] for k in keys
                if k in self.pattern.stitches]
        if not hits:
            return
        col = QColor("#ff3333")
        col.setAlpha(170)
        pen = QPen(col, CELL * 0.34)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        for s in hits:
            if s.kind is StitchKind.X:
                cx, cy = (s.a[0] + 0.5) * CELL, (s.a[1] + 0.5) * CELL
                h = CELL * 0.46
                painter.drawLine(cx - h, cy - h, cx + h, cy + h)
                painter.drawLine(cx + h, cy - h, cx - h, cy + h)
            else:
                pa, pb = s.endpoints()
                painter.drawLine(pa[0] * CELL, pa[1] * CELL,
                                 pb[0] * CELL, pb[1] * CELL)

    def _draw_symmetry_axes(self, painter: QPainter):
        """Overlay showing active symmetry modes and their axes."""
        axes = self.active_symmetry_axes
        if not axes:
            return
        p = self.pattern
        w, h = p.width, p.height
        ws = WORKSPACE
        col = QColor("#9944ff")
        col.setAlpha(140)
        pen = QPen(col, 1.4, Qt.PenStyle.DashLine)
        painter.setPen(pen)
        # axes span the whole design area (fabric + workspace)
        x0, y0 = -ws * CELL, -ws * CELL
        x1, y1 = (w + ws) * CELL, (h + ws) * CELL
        if "h" in axes:
            xm = w * CELL / 2
            painter.drawLine(xm, y0, xm, y1)
            painter.drawText(xm + 4, y0 + 12, "H")
        if "v" in axes:
            ym = h * CELL / 2
            painter.drawLine(x0, ym, x1, ym)
            painter.drawText(x0 + 4, ym - 4, "V")
        if "d" in axes:
            m = (min(w, h) + ws) * CELL
            painter.drawLine(x0, y0, m, m)
            painter.drawText(m - 14, m - 6, "D")
        if "ad" in axes:
            # point mirror: mark the center
            cx, cy = w * CELL / 2, h * CELL / 2
            painter.drawLine(cx - 8, cy, cx + 8, cy)
            painter.drawLine(cx, cy - 8, cx, cy + 8)
            painter.drawText(cx + 8, cy - 6, "180")

    def drawForeground(self, painter: QPainter, rect):
        self._draw_symmetry_axes(painter)
        # snap indicator: dot on the grid intersection a click would hit
        if self.tool not in (Tool.PAN, Tool.BLOCK, Tool.ERASER) and \
                getattr(self, "_last_mouse_scene", None) is not None:
            sp = self._last_mouse_scene
            p = self.pattern
            ws = WORKSPACE
            if self.tool in (Tool.PENCIL, Tool.XLINE):
                # X tools snap to cell centers
                gx = math.floor(sp.x() / CELL)
                gy = math.floor(sp.y() / CELL)
                ok = (-ws <= gx < p.width + ws
                      and -ws <= gy < p.height + ws)
                px, py = (gx + 0.5) * CELL, (gy + 0.5) * CELL
            else:
                gx = int(round(sp.x() / CELL))
                gy = int(round(sp.y() / CELL))
                if self.tool is Tool.BACKSTITCH:
                    ok = (-ws <= gx <= p.width + ws
                          and -ws <= gy <= p.height + ws)
                else:
                    ok = (-ws <= gx < p.width + ws
                          and -ws <= gy < p.height + ws)
                px, py = gx * CELL, gy * CELL
            if ok:
                col = QColor(self.current_color) if self.tool in (
                    Tool.PENCIL, Tool.XLINE, Tool.BACKSTITCH) else \
                    QColor("#2266ff")
                col.setAlpha(200)
                painter.setPen(QPen(QColor("white"), 1.2))
                painter.setBrush(col)
                painter.drawEllipse(QRectF(px - 4, py - 4, 8, 8))

        if self._rubber_start is not None:
            end = getattr(self, "_last_mouse_scene", self._rubber_start)
            painter.setPen(QPen(QColor("#2266ff"), 1, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            r = QRectF(self._rubber_start, end).normalized()
            painter.drawRect(r)
        if self.tool is Tool.BLOCK and self.pending_block is not None \
                and getattr(self, "_ghost_cell", None):
            gx, gy = self._ghost_cell
            # ghosted block stitches at the exact pending transform
            self._draw_ghost_strokes(painter, self._block_ghost_strokes())
            # anchor cross at insertion point
            painter.setPen(QPen(QColor("#ff5522"), 1.5))
            painter.drawLine(gx * CELL - 6, gy * CELL, gx * CELL + 6, gy * CELL)
            painter.drawLine(gx * CELL, gy * CELL - 6, gx * CELL, gy * CELL + 6)
        # eraser: highlight the stitch/segment that would be removed
        if self.tool is Tool.ERASER and \
                getattr(self, "_last_mouse_scene", None) is not None:
            self._draw_eraser_highlight(painter)

        # move/rotate ghost: actual selected stitches at pending transform
        self._draw_transform_ghost(painter)
        # move tool: anchor marker
        if self.tool is Tool.MOVE and self._move_anchor is not None:
            painter.setBrush(QColor("#22aa55"))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QRectF(self._move_anchor.x() - 4,
                                       self._move_anchor.y() - 4, 8, 8))

        # rotate tool: center marker + sweep line
        if self.tool is Tool.ROTATE and self._rot_center is not None:
            cx, cy = self._rot_center
            ccx, ccy = cx * CELL, cy * CELL
            painter.setPen(QPen(QColor("#ff8833"), 1.5))
            painter.drawLine(ccx - 7, ccy, ccx + 7, ccy)
            painter.drawLine(ccx, ccy - 7, ccx, ccy + 7)
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
                        cx, cy = (c[0] + 0.5) * CELL, (c[1] + 0.5) * CELL
                        h = CELL * 0.42
                        painter.setPen(QPen(QColor(self.current_color), 1.2,
                                            Qt.PenStyle.DashLine))
                        painter.drawLine(cx - h, cy - h, cx + h, cy + h)
                        painter.drawLine(cx + h, cy - h, cx - h, cy + h)
            # anchor marker
            kind, a = self._anchor
            ax = (a[0] + 0.5) * CELL if kind == "x" else a[0] * CELL
            ay = (a[1] + 0.5) * CELL if kind == "x" else a[1] * CELL
            painter.setPen(QPen(QColor("#2266ff"), 1.5))
            painter.setBrush(QColor(34, 102, 255, 60))
            painter.drawEllipse(QRectF(ax - 4, ay - 4, 8, 8))
