"""Ruler widgets synced to a PatternCanvas view transform."""

from __future__ import annotations

from PySide6.QtCore import Qt, QRectF, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QFont
from PySide6.QtWidgets import QWidget

from .canvas import CELL, GRID_MAJOR


class Ruler(QWidget):
    """Horizontal or vertical ruler showing grid cell coordinates.

    Ticks are drawn in scene units so they stay glued to the grid under
    pan/zoom. Major ticks + labels every GRID_MAJOR cells.

    Dragging outward from a ruler creates a guide line snapped to the
    nearest grid line: guide_drag fires continuously while dragging,
    guide_drop fires on release.
    """

    guide_drag = Signal(object, int, int, int)  # orient, gx, gy, kind
    guide_drop = Signal(object, int, int, int)
    # kind: 0 = straight guide, 1 = "/" diagonal (Shift), 2 = "\" (Ctrl)

    def __init__(self, view, orientation=Qt.Orientation.Horizontal,
                 parent=None):
        super().__init__(parent)
        self.view = view
        self.orientation = orientation
        self._dragging = False
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(self.backgroundRole(), QColor("#f3eee1"))
        self.setPalette(pal)
        if orientation is Qt.Orientation.Horizontal:
            self.setFixedHeight(22)
            self.setSizePolicy(self.sizePolicy().horizontalPolicy(),
                               self.sizePolicy().verticalPolicy())
        else:
            self.setFixedWidth(22)

    def _visible_cell_range(self):
        """(lo, hi) cell indices visible along the ruler axis."""
        vp = self.view.viewport()
        if self.orientation is Qt.Orientation.Horizontal:
            tl = self.view.mapToScene(0, 0)
            br = self.view.mapToScene(vp.width(), vp.height())
            lo = int(tl.x() // CELL) - 1
            hi = int(br.x() // CELL) + 2
        else:
            tl = self.view.mapToScene(0, 0)
            br = self.view.mapToScene(vp.width(), vp.height())
            lo = int(tl.y() // CELL) - 1
            hi = int(br.y() // CELL) + 2
        return lo, hi

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor("#f3eee1"))
        p.setFont(QFont("Sans", 7))

        lo, hi = self._visible_cell_range()
        major_pen = QPen(QColor("#666666"))
        minor_pen = QPen(QColor("#aaaaaa"))
        p.setPen(minor_pen)
        for i in range(lo, hi + 1):
            major = i % GRID_MAJOR == 0
            if major:
                p.setPen(major_pen)
            # scene coordinate of this grid line
            if self.orientation is Qt.Orientation.Horizontal:
                sx = self.view.mapFromScene(i * CELL, 0).x()
                if sx < -20 or sx > w + 20:
                    if major:
                        p.setPen(minor_pen)
                    continue
                tl = 12 if major else 6
                p.drawLine(sx, h - tl, sx, h)
                if major:
                    p.drawText(sx + 2, 10, str(i))
            else:
                sy = self.view.mapFromScene(0, i * CELL).y()
                if sy < -20 or sy > h + 20:
                    if major:
                        p.setPen(minor_pen)
                    continue
                tl = 12 if major else 6
                p.drawLine(w - tl, sy, w, sy)
                if major:
                    p.save()
                    p.translate(10, sy + 3)
                    p.rotate(-90)
                    p.drawText(0, 0, str(i))
                    p.restore()
            if major:
                p.setPen(minor_pen)
        # border
        p.setPen(QPen(QColor("#bbbbbb")))
        if self.orientation is Qt.Orientation.Horizontal:
            p.drawLine(0, h - 1, w, h - 1)
        else:
            p.drawLine(w - 1, 0, w - 1, h)
        p.end()

    # -- guide dragging ---------------------------------------------------
    def _point_at(self, event):
        """Grid cell coords (gx, gy) under the cursor."""
        vp = self.view.viewport()
        gp = event.globalPosition().toPoint()
        vp_pos = vp.mapFromGlobal(gp)
        scene = self.view.mapToScene(vp_pos)
        return (int(round(scene.x() / CELL)),
                int(round(scene.y() / CELL)))

    @staticmethod
    def _kind(event) -> int:
        mods = event.modifiers()
        if mods & Qt.KeyboardModifier.ControlModifier:
            return 2
        if mods & Qt.KeyboardModifier.ShiftModifier:
            return 1
        return 0

    def _emit(self, signal, event):
        gx, gy = self._point_at(event)
        signal.emit(self.orientation, gx, gy, self._kind(event))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self.grabMouse()
            self._emit(self.guide_drag, event)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging:
            self._emit(self.guide_drag, event)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._dragging and event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            self.releaseMouse()
            self._emit(self.guide_drop, event)
            event.accept()
            return
        super().mouseReleaseEvent(event)
