"""SVG import dialog: accuracy controls + live preview + commit."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImage, QPainter, QColor, QFont, QPixmap
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
                               QComboBox, QSpinBox, QSlider, QLabel,
                               QPushButton, QCheckBox, QFileDialog,
                               QDialogButtonBox, QWidget, QLayout)

from ..core import svg_import, palette
from ..core.model import Pattern, Stitch


class SvgImportDialog(QDialog):
    """Convert an SVG to stitches with adjustable accuracy and preview."""

    def __init__(self, pattern=None, parent=None):
        super().__init__(parent)
        self.pattern = pattern
        self.setWindowTitle("Import SVG")
        self.resize(900, 640)
        self.result = None
        self._svg_path = None
        self._last_result = None

        root = QHBoxLayout(self)

        # ---- controls (fixed width, no scrolling) ----
        left = QVBoxLayout()
        left.setSizeConstraint(QLayout.SizeConstraint.SetFixedSize)
        row = QHBoxLayout()
        self.file_label = QLabel("No file selected")
        row.addWidget(self.file_label, 1)
        pick = QPushButton("Choose…")
        pick.clicked.connect(self._pick_file)
        row.addWidget(pick)
        left.addLayout(row)

        form = QFormLayout()
        self.mode = QComboBox()
        self.mode.addItems(["fill (X-stitches)", "outline (backstitches)",
                            "fill + outline"])
        self.mode.currentIndexChanged.connect(self._update_preview)
        form.addRow("Mode", self.mode)

        self.width_spin = QSpinBox()
        self.width_spin.setRange(1, 2000)
        self.width_spin.setValue(100)
        self.width_spin.editingFinished.connect(self._sync_height)
        form.addRow("Grid width (stitches)", self.width_spin)

        self.height_spin = QSpinBox()
        self.height_spin.setRange(1, 2000)
        self.height_spin.setValue(100)
        self.height_spin.editingFinished.connect(self._update_preview)
        form.addRow("Grid height", self.height_spin)

        self.threshold = QSlider(Qt.Orientation.Horizontal)
        self.threshold.setRange(1, 255)
        self.threshold.setValue(128)
        self.threshold.valueChanged.connect(self._update_preview)
        form.addRow("Threshold", self.threshold)

        self.smooth = QSpinBox()
        self.smooth.setRange(0, 5)
        self.smooth.setValue(0)
        self.smooth.editingFinished.connect(self._update_preview)
        form.addRow("Smoothing passes", self.smooth)

        self.minsize = QSpinBox()
        self.minsize.setRange(0, 8)
        self.minsize.setValue(1)
        self.minsize.editingFinished.connect(self._update_preview)
        form.addRow("Min neighbors (despeckle)", self.minsize)

        self.color_mode = QComboBox()
        self.color_mode.addItems(["single color", "preserve colors"])
        self.color_mode.currentIndexChanged.connect(self._update_preview)
        form.addRow("Color", self.color_mode)

        self.dmc_map = QCheckBox("Map colors to nearest DMC")
        self.dmc_map.stateChanged.connect(self._update_preview)
        form.addRow(self.dmc_map)

        self.as_block = QCheckBox("Import as block (instead of raw stitches)")
        form.addRow(self.as_block)

        self.fit_canvas = QCheckBox(
            "Expand canvas to fit imported size")
        self.fit_canvas.setChecked(True)
        self.fit_canvas.setToolTip(
            "Grow the pattern's width/height if the import is larger")
        form.addRow(self.fit_canvas)

        left.addLayout(form)

        info = QLabel("")
        info.setWordWrap(True)
        self.info_label = info
        left.addWidget(info)
        left.addStretch()

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                   QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        left.addWidget(buttons)
        left.addStretch()

        left_widget = QWidget()
        left_widget.setLayout(left)
        left_widget.setFixedWidth(280)
        root.addWidget(left_widget)

        # ---- preview ----
        self.preview_label = QLabel("Select an SVG file to preview")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumSize(400, 400)
        self.preview_label.setStyleSheet("background:#333; color:#eee;")
        root.addWidget(self.preview_label, 2)

    # -- file ----------------------------------------------------------
    def _pick_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open SVG", "", "SVG files (*.svg);;All files (*)")
        if path:
            self._svg_path = path
            self.file_label.setText(Path(path).name)
            self._update_preview()

    def set_svg_path(self, path: str):
        self._svg_path = path
        self.file_label.setText(Path(path).name)
        self._update_preview()

    # -- params ---------------------------------------------------------
    def _mode_str(self):
        return ("fill", "outline", "both")[self.mode.currentIndex()]

    def _sync_height(self, *_):
        # keep aspect if svg known? just update preview
        self._update_preview()

    def params(self) -> dict:
        return dict(
            mode=self._mode_str(),
            width=self.width_spin.value(),
            height=self.height_spin.value(),
            threshold=self.threshold.value(),
            smooth_passes=self.smooth.value(),
            min_neighbors=self.minsize.value(),
            color_mode="preserve" if self.color_mode.currentIndex() == 1 else "mono",
            default_color="#000000",
            map_to_dmc=self.dmc_map.isChecked(),
        )

    # -- preview ---------------------------------------------------------
    def _update_preview(self, *_):
        if not self._svg_path:
            return
        try:
            self._last_result = svg_import.import_svg(
                self._svg_path, **self.params())
        except Exception as e:
            self.info_label.setText(f"Error: {e}")
            return
        r = self._last_result
        self.info_label.setText(
            f"{r.cell_count} cells → {len(r.stitches)} stitches "
            f"({r.width}×{r.height} grid)")
        self._render_preview(r)

    def _render_preview(self, result):
        from ..core.exporters.chart import build_chart, draw_chart, pattern_bounds
        p = Pattern(width=result.width, height=result.height)
        for s in result.stitches:
            p.add_stitch(s)
        items = build_chart(p)
        if not items:
            self.preview_label.setText("No stitches produced")
            return
        bounds = pattern_bounds(p)
        cell = 16
        w = int((bounds[2] - bounds[0] + 1) * cell) + 20
        h = int((bounds[3] - bounds[1] + 1) * cell) + 20
        img = QImage(max(w, 50), max(h, 50), QImage.Format.Format_ARGB32)
        img.fill(QColor("#F5F0E6"))
        painter = QPainter(img)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        ox = oy = 10.0  # draw_chart X() already offsets by -minx/-miny
        draw_chart(painter, items, cell, ox, oy, realistic=True, bounds=bounds)
        painter.end()
        self.preview_label.setPixmap(QPixmap.fromImage(img.scaled(
            self.preview_label.size() * 0.9,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)))

    # -- accept -----------------------------------------------------------
    def _on_accept(self):
        if not self._last_result:
            self.reject()
            return
        self.result = self._last_result
        self.accept()

    def get_result(self):
        return self.result
