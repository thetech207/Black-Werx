"""Ruler widgets synced to a PatternCanvas view transform."""

from __future__ import annotations

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QPainter, QPen, QFont
from PySide6.QtWidgets import QWidget

from .canvas import CELL, GRID_MAJOR


class Ruler(QWidget):
    """Horizontal or vertical ruler showing grid cell coordinates.

    Ticks are drawn in scene units so they stay glued to the grid under
    pan/zoom. Major ticks + labels every GRID_MAJOR cells.
    """

    def __init__(self, view, orientation=Qt.Orientation.Horizontal,
                 parent=None):
        super().__init__(parent)
        self.view = view
        self.orientation = orientation
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(self.backgroundRole(), QColor("#ececec"))
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
        p.fillRect(0, 0, w, h, QColor("#ececec"))
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
