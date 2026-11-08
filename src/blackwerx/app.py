"""Black-Werx main window."""

from __future__ import annotations

import sys
from pathlib import Path

from dataclasses import replace

from PySide6.QtCore import (Qt, QSize, QSettings, QPointF, QEvent,
                            QPoint, QTimer, QRect)
from PySide6.QtGui import (QAction, QKeySequence, QColor, QIcon, QPixmap,
                           QPainter, QPen, QBrush, QPolygonF, QPalette)
from PySide6.QtWidgets import (QMainWindow, QApplication, QWidget,
                               QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
                               QToolBar, QDockWidget, QFileDialog,
                               QMessageBox, QInputDialog, QDialog,
                               QFormLayout, QComboBox, QCheckBox, QSpinBox,
                               QDoubleSpinBox, QDialogButtonBox, QMenu,
                               QSplitter, QToolButton, QPushButton,
                               QSplashScreen)
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QUndoView

from .core.model import Pattern, Stitch, StitchKind, Transform
from .core.block import Block, BlockInstance
from .core.library import Library
from .core import project as project_io
from .core import palette
from .core.exporters import pdf as pdf_exp, image as img_exp, svg as svg_exp, pat as pat_exp
from .gui.canvas import PatternCanvas, Tool, CELL
from .gui.panels import (ColorPanel, LibraryPanel, LayerPanel,
                         make_block_from_stitches, color_icon)
from .gui.commands import (DrawStitchesCommand, EraseStitchesCommand,
                           DeleteSelectionCommand, MoveStitchesCommand,
                           TransformInstancesCommand, RecolorCommand,
                           PlaceBlockCommand, ExplodeCommand,
                           TransformSelectionCommand, CopySelectionCommand,
                           MoveToLayerCommand, SplitStitchCommand,
                           SelectionCommand, ClipBehindCommand)
from .gui.block_editor import BlockEditorDialog
from .gui.svg_import_dialog import SvgImportDialog
from .gui.rulers import Ruler


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Black-Werx")
        self.resize(1200, 800)
        self._settings = QSettings("BlackWerx", "BlackWerx")
        # capture the OS palette before any override so "System" can
        # restore it later
        self._system_palette = QApplication.palette()
        self._apply_palette()

        self.pattern = Pattern()
        self._load_canvas_defaults(self.pattern)
        self.library = Library()
        self.library_blocks = {b.id: b for b in self.library.all()}
        self.undo_stack = QUndoStack(self)
        self._file_path = None
        self._extra_dirty = False   # non-undoable edits (canvas setup)
        self._saved_index = 0       # undo index at last save
        self._mru = []
        # selection tracking for undo + reselect
        self._sel_shadow = (frozenset(), frozenset())
        self._sel_history = []
        self._sym_warn_key = None

        self._build_ui()
        self._build_menus()
        self._wire_canvas()
        self._refresh_all()
        # repaint + status after undo/redo (commands update selection too)
        self.undo_stack.indexChanged.connect(self._on_undo_index_changed)

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        central = QWidget()
        grid = QGridLayout(central)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(0)

        self.canvas = PatternCanvas(self)
        self.canvas.line_width = int(
            self._settings.value("canvas/line_width", 1))
        corner = QLabel("")
        corner.setFixedSize(22, 22)
        self._corner = corner
        _pal = self.palette()
        corner.setStyleSheet(
            f"background:{_pal.color(QPalette.ColorRole.Window).name()};"
            f" border-right:1px solid "
            f"{_pal.color(QPalette.ColorRole.Mid).name()};"
            f" border-bottom:1px solid "
            f"{_pal.color(QPalette.ColorRole.Mid).name()};")
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
        # drag guides out of the rulers onto the canvas
        self.h_ruler.guide_drag.connect(self.canvas.guide_dragging)
        self.h_ruler.guide_drop.connect(self.canvas.guide_dropped)
        self.v_ruler.guide_drag.connect(self.canvas.guide_dragging)
        self.v_ruler.guide_drop.connect(self.canvas.guide_dropped)

        # left tool sidebar
        tb = QToolBar("Tools")
        tb.setObjectName("Tools")
        tb.setIconSize(QSize(28, 28))
        tb.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonIconOnly)
        tb.setMovable(False)
        tb.setStyleSheet(self._bar_qss("Tools", "right"))
        self._tools_bar = tb
        self.addToolBar(Qt.ToolBarArea.LeftToolBarArea, tb)
        self.tool_group = []
        tool_tips = {
            Tool.PENCIL: "X Stitch — click/drag to stitch cells  (X)",
            Tool.XLINE: "X Line — click two points for a stitched line  (L)",
            Tool.BACKSTITCH: "Backstitch — click points for a line; "
                             "right-click finishes  (B)",
            Tool.ERASER: "Eraser — drag over stitches to remove  (E)",
            Tool.SELECT: "Select — click/drag to select stitches "
                         "and blocks  (S)",
            Tool.MOVE: "Move — drag selected stitches/blocks  (M)",
            Tool.ROTATE: "Rotate — pick a center, drag to rotate  (R)",
            Tool.BLOCK: "Place Block — pick a block in the library, "
                        "then click to place",
            Tool.PAN: "Pan — drag to move the view  (P, or Space-drag)",
        }
        for tool, label in [
            (Tool.PENCIL, "X Stitch"), (Tool.XLINE, "X Line"),
            (Tool.BACKSTITCH, "Backstitch"),
            (Tool.ERASER, "Eraser"),
            (Tool.SELECT, "Select"), (Tool.MOVE, "Move"),
            (Tool.ROTATE, "Rotate"),
            (Tool.BLOCK, "Place Block"), (Tool.PAN, "Pan"),
        ]:
            act = QAction(_tool_icon(tool), label, self)
            act.setCheckable(True)
            act.setToolTip(tool_tips[tool])
            act.triggered.connect(lambda _=False, t=tool: self._set_tool(t))
            tb.addAction(act)
            self.tool_group.append((tool, act))
        self._set_tool(Tool.SELECT)

        # symmetry dropdown on the tool bar
        sym_btn = QToolButton(self)
        sym_btn.setIcon(_symmetry_icon())
        sym_btn.setText("Symmetry")
        sym_btn.setToolTip(
            "Symmetry — mirror new stitches and edits across axes")
        sym_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        sym_btn.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonIconOnly)
        sym_menu = QMenu(sym_btn)
        self._sym_btn = sym_btn
        self.sym_on_action = QAction("Enabled", self)
        self.sym_on_action.setCheckable(True)
        self.sym_on_action.setChecked(True)
        self.sym_on_action.triggered.connect(self._set_symmetry_on)
        sym_menu.addAction(self.sym_on_action)
        sym_menu.addSeparator()
        self.sym_actions = {}
        for axis, label in [
                ("h", "Left / right"), ("v", "Top / bottom"),
                ("d", "Diagonal"), ("ad", "Point mirror")]:
            act = QAction(label, self)
            act.setCheckable(True)
            act.triggered.connect(
                lambda _=False, a=axis: self._set_symmetry(a))
            sym_menu.addAction(act)
            self.sym_actions[axis] = act
        sym_btn.setMenu(sym_menu)
        tb.addWidget(sym_btn)

        # edit bar (top): zoom + block/edit commands
        otb = QToolBar("Edit")
        otb.setObjectName("EditBar")
        otb.setMovable(False)
        otb.setIconSize(QSize(20, 20))
        otb.setStyleSheet(self._bar_qss("EditBar", "bottom"))
        self._edit_bar = otb
        self.addToolBar(otb)

        self._edit_btns = []

        def ebtn(icon, text, tip, fn=None, menu=None):
            b = QToolButton(self)
            b.setIcon(_edit_icon(icon))
            self._edit_btns.append((icon, b))
            b.setText(text)
            b.setToolTip(tip)
            b.setToolButtonStyle(
                Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            if menu is not None:
                b.setPopupMode(
                    QToolButton.ToolButtonPopupMode.InstantPopup)
                b.setMenu(menu)
            else:
                b.clicked.connect(fn)
            otb.addWidget(b)
            return b

        # -- zoom -----------------------------------------------------
        ebtn("zoomin", "Zoom In",
             "Zoom in 25%  (Ctrl++)",
             lambda: self.canvas.zoom_centered(1.25))
        ebtn("zoomout", "Zoom Out",
             "Zoom out 20%  (Ctrl+-)",
             lambda: self.canvas.zoom_centered(0.8))
        ebtn("actual", "Actual Size",
             "Zoom so one stitch equals its real-world size "
             "on this display", self.canvas.zoom_actual_size)
        otb.addSeparator()

        # -- blocks ---------------------------------------------------
        ebtn("newblock", "New Block",
             "Create a block from the current selection",
             self.new_block_from_selection)
        ebtn("explode_flat", "Explode",
             "Explode selected block instance(s): flatten to plain "
             "stitches", lambda: self.explode_selected("flatten"))
        ebtn("explode_unlink", "Unlink",
             "Explode selected block instance(s): keep as independent "
             "editable block copies",
             lambda: self.explode_selected("unlink"))
        self.array_btn = QToolButton(self)
        self.array_btn.setIcon(_edit_icon("array"))
        self._edit_btns.append(("array", self.array_btn))
        self.array_btn.setText("Array…")
        self.array_btn.setToolTip(
            "Place blocks in a rows×columns array with edge gaps")
        self.array_btn.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.array_btn.clicked.connect(self._array_dialog)
        self.array_btn.setEnabled(False)
        otb.addWidget(self.array_btn)
        otb.addSeparator()

        # -- selection edits ------------------------------------------
        ebtn("dup", "Duplicate",
             "Duplicate the selection  (Ctrl+D)",
             self.duplicate_selection)
        rot_menu = QMenu(self)
        for deg in (90, 180, 270):
            rot_menu.addAction(
                f"{deg}°",
                lambda _=False, d=deg: self.transform_instances(
                    f"rot{d}"))
        ebtn("rot", "Rotate", "Rotate selection 90/180/270°",
             menu=rot_menu)
        flip_menu = QMenu(self)
        flip_menu.addAction(
            "Horizontal", lambda: self.transform_instances("flipx"))
        flip_menu.addAction(
            "Vertical", lambda: self.transform_instances("flipy"))
        ebtn("flipx", "Flip", "Flip selection horizontally/vertically",
             menu=flip_menu)
        ebtn("split", "Split Stitch",
             "Split the selected stitch(es) in half",
             self.split_selection)
        ebtn("hide", "Hide Behind",
             "Hide selected stitches behind the closed shape "
             "surrounding them", self.clip_behind_selection)
        otb.addSeparator()

        # undo view dock
        self.undo_view = QUndoView(self.undo_stack)
        udock = QDockWidget("History", self)
        udock.setObjectName("HistoryDock")
        udock.setWidget(self.undo_view)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, udock)
        udock.hide()

        # right dock: resizable splitter with color/layers/library panels
        right = QWidget()
        rlay = QVBoxLayout(right)
        rlay.setContentsMargins(0, 0, 0, 0)
        self.color_panel = ColorPanel()
        self.layer_panel = LayerPanel()
        self.library_panel = LibraryPanel()
        self.right_splitter = QSplitter(Qt.Orientation.Vertical)
        self.right_splitter.setHandleWidth(6)
        self.right_splitter.setChildrenCollapsible(False)
        self.right_splitter.addWidget(self.color_panel)
        self.right_splitter.addWidget(self.layer_panel)
        self.right_splitter.addWidget(self.library_panel)
        self.right_splitter.setStretchFactor(0, 0)
        self.right_splitter.setStretchFactor(1, 0)
        self.right_splitter.setStretchFactor(2, 1)
        rlay.addWidget(self.right_splitter)
        rlay.setContentsMargins(5, 5, 5, 5)
        rlay.setSpacing(4)
        rdock = QDockWidget("Palette & Library", self)
        rdock.setObjectName("SideDock")
        rdock.setWidget(right)
        rdock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetClosable |
            QDockWidget.DockWidgetFeature.DockWidgetMovable |
            QDockWidget.DockWidgetFeature.DockWidgetFloatable)
        self.right_dock = rdock
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, rdock)

        # compact, rounded, theme-matched styling for the side panel
        self._side_panel = right
        right.setObjectName("SidePanel")
        right.setStyleSheet(self._side_panel_qss())

        # collapse tab on the panel's left edge (child of main window so
        # it survives the dock being hidden)
        self._central = central
        self._dock_w = None
        self.panel_tab = QToolButton(self)
        self.panel_tab.setFixedSize(12, 72)
        self.panel_tab.setCursor(Qt.CursorShape.PointingHandCursor)
        self.panel_tab.setToolTip(
            "Collapse/expand the palette & library panel")
        self.panel_tab.clicked.connect(self._toggle_right_panel)
        self.panel_tab.setStyleSheet(self._panel_tab_qss())
        central.installEventFilter(self)
        self._position_panel_tab()
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self._position_panel_tab)

        geo = self._settings.value("ui/geometry")
        if geo:
            self.restoreGeometry(geo)
        state = self._settings.value("ui/dock_state")
        if state:
            self.restoreState(state)
        saved_sizes = self._settings.value("ui/right_splitter_sizes")
        if saved_sizes:
            # apply after first layout so sizes aren't overridden
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, lambda: self.right_splitter.setSizes(
                [int(s) for s in saved_sizes]))

        self._refresh_rulers()
        self.status_info = QLabel("0 stitches")
        self.statusBar().addPermanentWidget(self.status_info)

    # -- theme ----------------------------------------------------------
    def _theme_palette(self, mode: str):
        """Build a QPalette for 'light'/'dark'; 'system' restores OS."""
        if mode == "system":
            return self._system_palette
        p = QPalette()
        if mode == "dark":
            win, base, alt = "#2e2b27", "#24211d", "#38342e"
            text, btn, hi = "#ece7dc", "#3a362f", "#4a7ab5"
        else:
            win, base, alt = "#f4f1ea", "#fdfcf8", "#ece8dd"
            text, btn, hi = "#2b261e", "#e7e2d5", "#3d6fb4"
        p.setColor(QPalette.ColorRole.Window, QColor(win))
        p.setColor(QPalette.ColorRole.WindowText, QColor(text))
        p.setColor(QPalette.ColorRole.Base, QColor(base))
        p.setColor(QPalette.ColorRole.AlternateBase, QColor(alt))
        p.setColor(QPalette.ColorRole.Text, QColor(text))
        p.setColor(QPalette.ColorRole.Button, QColor(btn))
        p.setColor(QPalette.ColorRole.ButtonText, QColor(text))
        p.setColor(QPalette.ColorRole.Highlight, QColor(hi))
        p.setColor(QPalette.ColorRole.HighlightedText,
                   QColor("#ffffff"))
        p.setColor(QPalette.ColorRole.Mid, QColor(text).darker(130))
        p.setColor(QPalette.ColorRole.PlaceholderText,
                   QColor(text).darker(140))
        return p

    def _apply_palette(self):
        mode = self._settings.value("ui/theme", "system")
        QApplication.setPalette(self._theme_palette(mode))

    def _set_theme(self, mode: str):
        self._settings.setValue("ui/theme", mode)
        for md, act in getattr(self, "_theme_acts", {}).items():
            act.setChecked(md == mode)
        self._apply_palette()
        # rebuild every stylesheet that baked in palette colors
        if hasattr(self, "_tools_bar"):
            self._tools_bar.setStyleSheet(self._bar_qss("Tools", "right"))
            self._edit_bar.setStyleSheet(self._bar_qss("EditBar", "bottom"))
            _ap = QApplication.palette()
            self._corner.setStyleSheet(
                f"background:{_ap.color(QPalette.ColorRole.Window).name()};"
                f" border-right:1px solid "
                f"{_ap.color(QPalette.ColorRole.Mid).name()};"
                f" border-bottom:1px solid "
                f"{_ap.color(QPalette.ColorRole.Mid).name()};")
            self.panel_tab.setStyleSheet(self._panel_tab_qss())
            self._side_panel.setStyleSheet(self._side_panel_qss())
            # icons bake in a foreground color — regenerate them
            for tool, act in self.tool_group:
                act.setIcon(_tool_icon(tool))
            for kind, b in self._edit_btns:
                b.setIcon(_edit_icon(kind))
            self._sym_btn.setIcon(_symmetry_icon())
            self.layer_panel.refresh(self.pattern)

    def _panel_tab_qss(self) -> str:
        c = self._chrome()
        return f"""
            QToolButton {{ background:{c['btn'].name()};
                          color:{c['txt'].name()};
                          border:1px solid {c['border'].name()};
                          border-top-right-radius:5px;
                          border-bottom-right-radius:5px;
                          font-size:10px; padding:0px; }}
            QToolButton:hover {{ background:{c['hover'].name()}; }}
            QToolButton:pressed {{ background:{c['pressed'].name()}; }}
        """

    def _side_panel_qss(self) -> str:
        c = self._chrome()
        return f"""
            #SidePanel {{ background:{c['btn'].name()};
                          border-radius:10px; font-size:11px; }}
            #SidePanel QPushButton {{
                background:{c['win'].name()};
                color:{c['txt'].name()};
                border:1px solid {c['border'].name()};
                border-radius:6px; padding:1px 8px; font-size:11px; }}
            #SidePanel QPushButton:hover {{
                background:{c['hover'].name()}; }}
            #SidePanel QPushButton:checked {{
                background:{c['hi'].name()};
                color:{c['htxt'].name()};
                border-color:{c['hi'].name()}; }}
            #SidePanel QComboBox, #SidePanel QTreeWidget,
            #SidePanel QListWidget {{
                background:{c['win'].name()};
                border:1px solid {c['border'].name()};
                border-radius:6px; padding:1px 4px; }}
            #SidePanel QTreeWidget::item, #SidePanel QListWidget::item {{
                padding:1px 3px; border-radius:4px; }}
            #SidePanel QLabel {{ color:{c['txt'].name()}; }}
        """

    def _chrome(self):
        """Theme-aware chrome colors (window/button shades + text)."""
        # app palette, not widget palette — some styles freeze widget
        # palettes and would ignore a theme switch
        pal = QApplication.palette()
        win = pal.color(QPalette.ColorRole.Window)
        txt = pal.color(QPalette.ColorRole.ButtonText)
        hi = pal.color(QPalette.ColorRole.Highlight)
        htxt = pal.color(QPalette.ColorRole.HighlightedText)
        lum = (0.299 * win.red() + 0.587 * win.green()
               + 0.114 * win.blue())
        if lum < 140:      # dark theme -> light buttons
            btn = win.lighter(150)
            hover = win.lighter(180)
            pressed = win.lighter(165)
            border = win.lighter(200)
        else:              # light theme -> darker buttons
            btn = win.darker(106)
            hover = win.lighter(102)
            pressed = win.darker(112)
            border = win.darker(118)
        return {"win": win, "btn": btn, "hover": hover,
                "pressed": pressed, "border": border,
                "txt": txt, "hi": hi, "htxt": htxt}

    def _bar_qss(self, name: str, edge: str) -> str:
        """Toolbar chrome styled from the app palette (dark/light safe)."""
        c = self._chrome()
        win, btn = c["win"], c["btn"]
        border, txt = c["border"], c["txt"]
        hover, pressed = c["hover"], c["pressed"]
        hi, htxt = c["hi"], c["htxt"]
        edge_css = (f"border-{edge}: 1px solid {border.name()};"
                    if edge else "")
        return f"""
            QToolBar#{name} {{ background: {win.name()}; {edge_css}
                               spacing: 2px; padding: 5px 7px; }}
            QToolBar#{name}::separator {{ background: {border.name()};
                                          width: 1px; height: 1px;
                                          margin: 4px 3px; }}
            QToolBar#{name} QToolButton {{
                background: {btn.name()};
                color: {txt.name()};
                border: 1px solid {border.name()};
                border-radius: 7px;
                padding: 1px 7px; margin: 2px;
                font-size: 11px; }}
            QToolBar#{name} QToolButton:hover {{
                background: {hover.name()}; }}
            QToolBar#{name} QToolButton:pressed {{
                background: {pressed.name()}; }}
            QToolBar#{name} QToolButton:checked {{
                background: {hi.name()};
                color: {htxt.name()};
                border-color: {hi.name()}; }}
        """

    # -- right panel collapse tab --------------------------------------
    def _toggle_right_panel(self):
        dock = self.right_dock
        if dock.isVisible():
            self._dock_w = dock.width()
            dock.hide()
        else:
            dock.show()
            if self._dock_w:
                dock.resize(self._dock_w, dock.height())
        self._position_panel_tab()

    def _position_panel_tab(self):
        """Pin the collapse tab to the panel's left edge (or the window's
        right edge when the panel is hidden), vertically centered."""
        tab = self.panel_tab
        if self.right_dock.isVisible():
            x = self.right_dock.geometry().left()
        else:
            # park just left of the canvas scrollbar
            right_edge = self._central.mapTo(
                self, QPoint(self._central.width(), 0)).x()
            sb = self.canvas.verticalScrollBar()
            sb_w = sb.width() if sb.isVisible() else 0
            x = right_edge - sb_w - tab.width() - 2
        top = self._central.mapTo(self, QPoint(0, 0)).y()
        y = top + max(0, (self._central.height() - tab.height()) // 2)
        tab.move(x, y)
        tab.raise_()
        tab.setText("❯" if self.right_dock.isVisible() else "❮")

    def eventFilter(self, obj, event):
        if obj is getattr(self, "_central", None) \
                and event.type() == QEvent.Type.Resize:
            self._position_panel_tab()
        return super().eventFilter(obj, event)

    def _refresh_rulers(self, *_):
        self.h_ruler.update()
        self.v_ruler.update()

    def _build_menus(self):
        mb = self.menuBar()
        # File
        m = mb.addMenu("&File")
        self._act(m, "&New", self.new_project, "Ctrl+N")
        self._act(m, "&Open…", self.open_project, "Ctrl+O")
        self.recent_menu = m.addMenu("Open &Recent")
        self._refresh_recent_menu()
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
        self._act(m, "&Reselect Last Selection", self.reselect_last)
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
        self._act(m, "Split stitch in &half", self.split_selection)
        self._act(m, "Hide stitches &behind selection",
                  self.clip_behind_selection)

        # View
        m = mb.addMenu("&View")
        self._act(m, "Zoom &In", lambda: self.canvas.zoom_centered(1.25), "Ctrl++")
        self._act(m, "Zoom &Out", lambda: self.canvas.zoom_centered(0.8), "Ctrl+-")
        self._act(m, "&Reset Zoom", self.canvas.resetTransform, "Ctrl+0")
        self._act(m, "Actual &Size", self.canvas.zoom_actual_size)
        m.addSeparator()
        # theme preference
        tm = m.addMenu("&Theme")
        self._theme_acts = {}
        for mode, label in [("system", "System"), ("light", "Light"),
                            ("dark", "Dark")]:
            act = QAction(label, self)
            act.setCheckable(True)
            act.setChecked(
                self._settings.value("ui/theme", "system") == mode)
            act.triggered.connect(
                lambda _=False, md=mode: self._set_theme(md))
            tm.addAction(act)
            self._theme_acts[mode] = act
        m.addSeparator()
        self.guides_act = QAction("Show &guides", self)
        self.guides_act.setCheckable(True)
        self.guides_act.setChecked(True)
        self.guides_act.triggered.connect(self._toggle_guides)
        m.addAction(self.guides_act)
        self._act(m, "Clear all guides", self.canvas.clear_guides)
        m.addSeparator()
        # panel visibility
        dock_act = QAction("Show side &panel", self)
        dock_act.setCheckable(True)
        dock_act.setChecked(True)
        dock_act.triggered.connect(
            lambda c: self.right_dock.setVisible(c))
        m.addAction(dock_act)
        self.right_dock.visibilityChanged.connect(
            lambda v: dock_act.setChecked(v))
        self._panel_acts = []
        panels = [("Show &colors", self.color_panel),
                  ("Show &layers", self.layer_panel),
                  ("Show &blocks", self.library_panel)]
        for label, w in panels:
            act = QAction(label, self)
            act.setCheckable(True)
            act.setChecked(True)
            act.triggered.connect(lambda c, ww=w: ww.setVisible(c))
            m.addAction(act)
            self._panel_acts.append((act, w))
        saved_vis = self._settings.value("ui/panel_visibility")
        if saved_vis is not None:
            for (act, w), vis in zip(self._panel_acts, saved_vis):
                on = vis if isinstance(vis, bool) else \
                    str(vis).lower() in ("true", "1")
                act.setChecked(on)
                w.setVisible(on)

        # Blocks
        m = mb.addMenu("&Blocks")
        self._act(m, "New block from selection", self.new_block_from_selection)
        self._act(m, "Explode selection (flatten)", lambda: self.explode_selected("flatten"))
        self._act(m, "Explode selection (unlink)", lambda: self.explode_selected("unlink"))
        m.addSeparator()
        self._act(m, "Explode ALL instances (flatten)…",
                  self.explode_all_instances)

        # Help
        m = mb.addMenu("&Help")
        self._act(m, "&User Guide", self.user_guide)
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
        c.erase_keys.connect(self._on_erase_keys)
        c.place_block.connect(self._on_place_block)
        c.move_selection.connect(self._on_move_selection)
        c.rotate_selection.connect(self._on_rotate_selection)
        c.tool_changed.connect(self._on_canvas_tool_changed)
        c.context_menu.connect(self._on_context_menu)
        c.guides_changed.connect(lambda: setattr(self, "_extra_dirty", True))
        c.cursor_cell_changed.connect(
            lambda x, y: self.statusBar().showMessage(f"cell {x}, {y}"))
        c.selection_changed.connect(self._on_selection_changed)
        self.color_panel.color_changed.connect(self._on_color_changed)
        self.library_panel.place_requested.connect(self._on_library_place)
        self.library_panel.new_from_selection.connect(self.new_block_from_selection)
        self.library_panel.edit_requested.connect(self._on_edit_block)
        self.library_panel.delete_requested.connect(self._on_delete_block)
        self.library_panel.promote_requested.connect(self._on_promote_block)
        self.library_panel.folder_requested.connect(self._on_block_folder)
        self.layer_panel.layers_changed.connect(self._on_layers_changed)
        self.layer_panel.active_changed.connect(self._on_active_layer)
        self.layer_panel.guides_toggled.connect(self._on_guides_toggled)
        self.layer_panel.guides_locked_toggled.connect(
            self._on_guides_locked)
        self.layer_panel.move_selection_requested.connect(
            self._on_move_selection_to_layer)
        self.layer_panel.layer_delete_requested.connect(
            self._on_layer_delete_migrate)
        self.layer_panel.merge_requested.connect(self._on_merge_layers)

    def _on_layers_changed(self):
        self._extra_dirty = True
        self.canvas.refresh()
        self._update_status()

    def _on_active_layer(self, _lid):
        self._extra_dirty = True
        self._update_status()

    def _on_guides_toggled(self, visible):
        self.canvas.guides_visible = visible
        self.canvas.viewport().update()
        self.canvas.guides_changed.emit()

    def _on_guides_locked(self, locked):
        self.canvas.guides_locked = locked

    def _on_move_selection_to_layer(self, lid):
        sel = self.canvas.selection
        keys = list(sel.stitch_keys)
        uid_list = list(sel.instance_uids)
        if not keys and not uid_list:
            self.statusBar().showMessage("Select stitches or blocks first.")
            return
        self.undo_stack.push(MoveToLayerCommand(
            self.pattern, keys, uid_list, lid,
            selection=self.canvas.selection, sym_ops=self._sym_ops()))
        self.canvas.refresh()
        self._update_status()

    def _on_layer_delete_migrate(self, deleted_id, target_id):
        keys = [s.key for s in self.pattern.stitches.values()
                if s.layer == deleted_id]
        uid_list = [i.uid for i in self.pattern.instances
                    if i.layer == deleted_id]
        if keys or uid_list:
            self.undo_stack.push(MoveToLayerCommand(
                self.pattern, keys, uid_list, target_id))

    def _on_merge_layers(self, ids):
        """Flatten checked layers into the topmost checked layer."""
        p = self.pattern
        survivor = ids[0]
        for lid in ids[1:]:
            keys = [s.key for s in p.stitches.values() if s.layer == lid]
            uid_list = [i.uid for i in p.instances if i.layer == lid]
            if keys or uid_list:
                self.undo_stack.push(MoveToLayerCommand(
                    p, keys, uid_list, survivor,
                    text=f"Merge layer into {survivor}"))
        drop = set(ids[1:])
        p.layers = [l for l in p.layers if l["id"] not in drop]
        if p.active_layer in drop:
            p.active_layer = survivor
        self.layer_panel.checked_layer_ids -= drop
        self.layer_panel.refresh(p)
        self.canvas.refresh()
        self._extra_dirty = True
        self._update_status()

    def _refresh_all(self):
        # keep canvas registry in sync so promoted global blocks resolve
        self.canvas.library_blocks = {**self.library_blocks,
                                      **self.pattern.blocks}
        self.library_panel.global_blocks = dict(self.library_blocks)
        self.library_panel.project_blocks = dict(self.pattern.blocks)
        self.library_panel.refresh()
        self.layer_panel.refresh(self.pattern)
        self.layer_panel.set_guides_visible(self.canvas.guides_visible)
        self._update_status()

    def _on_undo_index_changed(self, *_):
        try:
            # commands mutate selection silently; resync the shadow so the
            # next user-driven change diffs against the true state
            self._sel_shadow = self._sel_snapshot()
            self._note_selection(self._sel_shadow)
            self.canvas.viewport().update()
            self._update_status()
        except RuntimeError:
            pass  # during interpreter/Qt teardown

    # -- selection tracking -------------------------------------------------
    def _sel_snapshot(self):
        s = self.canvas.selection
        return (frozenset(s.stitch_keys), frozenset(s.instance_uids))

    def _note_selection(self, snap):
        snap = (frozenset(snap[0]), frozenset(snap[1]))
        if not self._sel_history or self._sel_history[-1] != snap:
            self._sel_history.append(snap)
            del self._sel_history[:-50]

    def _on_selection_changed(self):
        new = self._sel_snapshot()
        if new == self._sel_shadow:
            self._update_status()
            return
        before = self._sel_shadow
        self._sel_shadow = new
        self._note_selection(new)
        self._record_selection(before, new)
        self._update_status()

    def _record_selection(self, before, after):
        """Push (or extend) an undoable selection-change command."""
        if after == before:
            return
        sel = self.canvas.selection
        keys, uids = after
        text = "Select" if (keys or uids) else "Deselect"
        self.undo_stack.push(SelectionCommand(
            sel, (set(before[0]), set(before[1])),
            (set(keys), set(uids)), text=text))

    def _apply_selection(self, snap):
        s = self.canvas.selection
        s.stitch_keys = set(snap[0])
        s.instance_uids = set(snap[1])
        self.canvas.selection_changed.emit()
        self.canvas.viewport().update()

    def reselect_last(self):
        """Restore the selection state from before the current one."""
        if len(self._sel_history) < 2:
            self.statusBar().showMessage("No previous selection.")
            return
        self._apply_selection(self._sel_history[-2])

    def _update_status(self):
        n = self.pattern.stitch_count()
        self.status_info.setText(f"{n} stitches")
        dirty = " •" if self._is_dirty() else ""
        name = self.pattern.name
        if name in ("", "Untitled") and self._file_path is not None:
            name = self._file_path.stem
        self.setWindowTitle(
            f"Black-Werx — {name}{dirty}" +
            (f" — {self._file_path.name}" if self._file_path else ""))
        self._refresh_sym_warnings()

    def _refresh_sym_warnings(self):
        """Flag stitches that can't be edited symmetrically (missing orbit
        counterparts) while symmetry axes are active."""
        from .core.symmetry import orphan_stitch_keys
        axes = self.canvas.active_symmetry_axes
        key = (self.undo_stack.index(), frozenset(axes),
               self.pattern.width, self.pattern.height)
        if key == self._sym_warn_key:
            return
        self._sym_warn_key = key
        warn = orphan_stitch_keys(self.pattern, axes) if axes else set()
        if warn != self.canvas.sym_warn_keys:
            self.canvas.sym_warn_keys = warn
            self.canvas.viewport().update()

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
        self.canvas.setFocus()   # canvas keys (Esc, arrows, R/F/V) need it
        self._update_array_btn()
        if tool is Tool.BLOCK and self.canvas.pending_block is None:
            self.statusBar().showMessage(
                "Select a block in the library panel, then click to place.")

    def _update_array_btn(self):
        btn = getattr(self, "array_btn", None)
        if btn is not None:
            btn.setEnabled(self.canvas.tool is Tool.BLOCK
                           and self.canvas.pending_block is not None)

    def _set_symmetry(self, axis):
        act = self.sym_actions[axis]
        if act.isChecked():
            self.canvas.symmetry_axes.add(axis)
        else:
            self.canvas.symmetry_axes.discard(axis)
        self.canvas.viewport().update()
        self._refresh_sym_warnings()

    def _set_symmetry_on(self, checked):
        """Master symmetry switch — axis selections are preserved."""
        self.canvas.symmetry_on = checked
        self._sym_btn.setText("Symmetry" if checked else "Symmetry (off)")
        self.canvas.viewport().update()
        self._refresh_sym_warnings()

    def _toggle_guides(self, checked):
        self.canvas.guides_visible = checked
        self.layer_panel.set_guides_visible(checked)
        self.canvas.viewport().update()

    # -- canvas settings persistence ------------------------------------
    def _load_canvas_defaults(self, pattern):
        """Seed a fresh pattern with the last-used canvas settings."""
        s = self._settings
        pattern.aida_count = int(s.value(
            "canvas/aida", pattern.aida_count))
        pattern.stitch_w_mm = float(s.value(
            "canvas/stitch_w_mm", pattern.stitch_w_mm))
        pattern.stitch_h_mm = float(s.value(
            "canvas/stitch_h_mm", pattern.stitch_h_mm))
        w = int(s.value("canvas/width", pattern.width))
        h = int(s.value("canvas/height", pattern.height))
        pattern.width = w + w % 2      # keep even counts
        pattern.height = h + h % 2

    def _save_canvas_settings(self):
        p = self.pattern
        s = self._settings
        s.setValue("canvas/aida", p.aida_count)
        s.setValue("canvas/stitch_w_mm", p.stitch_w_mm)
        s.setValue("canvas/stitch_h_mm", p.stitch_h_mm)
        s.setValue("canvas/width", p.width)
        s.setValue("canvas/height", p.height)

    def _apply_canvas_values(self, v):
        """Apply accepted CanvasSetupDialog values to self.pattern."""
        self.pattern.aida_count = v["aida"]
        if v["size_mode"] == "inches":
            self.pattern.width = max(1, round(v["size_w"] * v["aida"]))
            self.pattern.height = max(1, round(v["size_h"] * v["aida"]))
        else:
            self.pattern.width = max(1, round(v["size_w"]))
            self.pattern.height = max(1, round(v["size_h"]))
        # even counts only: keeps the symmetry center on a grid dot
        self.pattern.width += self.pattern.width % 2
        self.pattern.height += self.pattern.height % 2
        self.canvas._update_scene_rect()
        self.canvas.centerOn(self.canvas.pattern_center_scene())
        self.canvas.viewport().update()
        self.pattern.stitch_w_mm = v["w"]
        self.pattern.stitch_h_mm = v["h"]
        self._extra_dirty = True
        self.statusBar().showMessage(
            f"Fabric: {v['aida']} ct aida, stitch "
            f"{v['w']}×{v['h']} mm, canvas "
            f"{self.pattern.width}×{self.pattern.height} (even counts)")

    def canvas_setup(self):
        dlg = CanvasSetupDialog(
            self.pattern, self, line_width=self.canvas.line_width)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._apply_canvas_values(dlg.values())
            v = dlg.values()
            self.canvas.line_width = v["line_width"]
            self._settings.setValue("canvas/line_width",
                                    v["line_width"])
            self._save_canvas_settings()

    def _on_color_changed(self, spec):
        self.canvas.current_color = spec
        self.canvas.refresh_cursor()

    # ------------------------------------------------------- canvas events
    def _on_draw_stitches(self, stitches):
        lid = self.pattern.active_layer
        if self.pattern.layer_locked(lid):
            name = (self.pattern.layer_def(lid) or {}).get("name", lid)
            self.statusBar().showMessage(
                f"Cannot draw: layer '{name}' is locked.")
            return
        if any(s.layer != lid for s in stitches):
            stitches = [replace(s, layer=lid) for s in stitches]
        self.undo_stack.push(DrawStitchesCommand(self.pattern, stitches))
        self.canvas.refresh()
        self._update_status()

    def _on_erase_keys(self, keys):
        keys = [k for k in keys
                if k in self.pattern.stitches
                and not self.pattern.layer_locked(
                    self.pattern.stitches[k].layer)
                and self.pattern.layer_visible(
                    self.pattern.stitches[k].layer)]
        if keys:
            self.undo_stack.push(EraseStitchesCommand(
            self.pattern, keys, selection=self.canvas.selection,
            sym_ops=self._sym_ops()))
            self.canvas.refresh()
            self._update_status()

    def _on_place_block(self, block, scope, gx, gy, anchor,
                        rot=0, mx=False, my=False, array=None):
        self._place_block_at(block, scope, gx, gy, anchor, rot, mx, my,
                             array)

    def _on_library_place(self, payload):
        block, scope = payload
        self.canvas.set_pending_block(block, scope)
        self._set_tool(Tool.BLOCK)
        self.canvas.setFocus()   # placement keys (R/F/V/1-9) go to canvas
        arr = ""
        if self.canvas.array_armed and (self.canvas.array_rows > 1
                                        or self.canvas.array_cols > 1):
            arr = (f" Array {self.canvas.array_rows}x"
                   f"{self.canvas.array_cols} gap "
                   f"{self.canvas.array_dx},{self.canvas.array_dy}"
                   " — one placement, then back to single."
                   " (Array… to change.)")
        self.statusBar().showMessage(
            f"Click to place '{block.name}' ({scope}). "
            "1-9 anchor, R rotate, F/V flip, right-click done." + arr)

    def _array_dialog(self):
        """Configure rows/cols/spacing for block array placement."""
        c = self.canvas
        dlg = QDialog(self)
        dlg.setWindowTitle("Block array")
        form = QFormLayout(dlg)
        rows = QSpinBox(); rows.setRange(1, 50)
        cols = QSpinBox(); cols.setRange(1, 50)
        dx = QSpinBox(); dx.setRange(-500, 500)
        dy = QSpinBox(); dy.setRange(-500, 500)
        centered = QCheckBox("Center array on click")
        s = self._settings
        rows.setValue(s.value("block/array_rows", c.array_rows, int))
        cols.setValue(s.value("block/array_cols", c.array_cols, int))
        dx.setValue(s.value("block/array_dx",
                            c.array_dx if c.array_dx else 1, int))
        dy.setValue(s.value("block/array_dy",
                            c.array_dy if c.array_dy else 1, int))
        centered.setChecked(
            s.value("block/array_centered", c.array_centered, bool))
        form.addRow("Rows", rows)
        form.addRow("Columns", cols)
        form.addRow("Gap X (stitches)", dx)
        form.addRow("Gap Y (stitches)", dy)
        form.addRow(centered)
        hint = QLabel("Gap is the empty space between block edges "
                      "(0 = touching, negative = overlap).")
        hint.setWordWrap(True)
        form.addRow(hint)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                               QDialogButtonBox.StandardButton.Cancel)
        box.accepted.connect(dlg.accept)
        box.rejected.connect(dlg.reject)
        form.addRow(box)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        c.array_rows, c.array_cols = rows.value(), cols.value()
        c.array_dx, c.array_dy = dx.value(), dy.value()
        c.array_centered = centered.isChecked()
        # array applies to the next placement only (one-shot)
        c.array_armed = rows.value() > 1 or cols.value() > 1
        for k, v in (("block/array_rows", c.array_rows),
                     ("block/array_cols", c.array_cols),
                     ("block/array_dx", c.array_dx),
                     ("block/array_dy", c.array_dy),
                     ("block/array_centered", c.array_centered)):
            s.setValue(k, v)
        c._update_tool_label()
        c.viewport().update()
        if c.array_armed:
            self.statusBar().showMessage(
                f"Array armed: {c.array_rows}x{c.array_cols} gap "
                f"{c.array_dx},{c.array_dy}" +
                (" centered" if c.array_centered else "") +
                " — next click places it once.")
        else:
            self.statusBar().showMessage("Array cleared (single placement).")

    @staticmethod
    def _array_offsets(rows, cols, centered):
        rows, cols = max(1, rows), max(1, cols)
        if rows == 1 and cols == 1:
            return [(0, 0)]
        c0 = -(cols - 1) // 2 if centered else 0
        r0 = -(rows - 1) // 2 if centered else 0
        return [(c0 + c, r0 + r)
                for r in range(rows) for c in range(cols)]

    def _place_block_at(self, block, scope, gx, gy, anchor=5,
                        rot=0, mx=False, my=False, array=None):
        bb = block.bbox() or (0, 0, 0, 0)
        fx, fy = PatternCanvas.PLACE_ANCHORS.get(anchor, (0.5, 0.5))
        ax = int(round(bb[0] + fx * (bb[2] - bb[0])))
        ay = int(round(bb[1] + fy * (bb[3] - bb[1])))
        # pending rot/mirror about the anchor point, in block-local space
        inner = Transform.from_semantic(0, 0, rot, mx, my)
        local = (Transform.translation(-ax, -ay)
                 .then(inner)
                 .then(Transform.translation(ax, ay)))
        rows, cols, dx, dy, centered = array or (1, 1, 0, 0, False)
        # spacing is the GAP between block edges: step = placed bbox
        # size (after rot/mirror) + gap
        xs, ys = [], []
        for cx in (bb[0], bb[2]):
            for cy in (bb[1], bb[3]):
                px, py = local.apply((cx, cy))
                xs.append(px); ys.append(py)
        step_x = int(round(max(xs) - min(xs))) + dx
        step_y = int(round(max(ys) - min(ys))) + dy
        insts = []
        for dc, dr in self._array_offsets(rows, cols, centered):
            insts.append(BlockInstance(
                uid=self.pattern.next_instance_id(),
                block_id=block.id, scope=scope,
                transform=local.then(Transform.translation(
                    gx - ax + dc * step_x, gy - ay + dr * step_y)),
                linked=True, layer=self.pattern.active_layer))
        # live symmetry: mirror every placed instance into the
        # other quadrant(s)
        from .core.symmetry import symmetry_matrices
        p = self.pattern
        base = list(insts)
        for m in symmetry_matrices(self.canvas.active_symmetry_axes,
                                   p.width, p.height):
            mt = Transform(*m)
            for inst in base:
                insts.append(BlockInstance(
                    uid=p.next_instance_id(), block_id=block.id,
                    scope=scope,
                    transform=inst.transform.then(mt),
                    linked=True, layer=inst.layer))
        self.undo_stack.push(PlaceBlockCommand(self.pattern, insts))
        self.canvas.refresh()
        self._update_status()

    # ------------------------------------------------------------ editing
    def delete_selection(self):
        sel = self.canvas.selection
        if sel.empty:
            return
        self._record("Edit: Delete Selection", self.delete_selection)
        self.undo_stack.push(DeleteSelectionCommand(
            self.pattern, sel.stitch_keys, sel.instance_uids,
            selection=self.canvas.selection, sym_ops=self._sym_ops()))
        self.canvas.refresh()
        self.selection_changed = True
        self._update_status()

    def select_all(self):
        p = self.pattern
        self.canvas.selection.stitch_keys = {
            s.key for s in p.stitches.values()
            if not p.layer_locked(s.layer) and p.layer_visible(s.layer)}
        self.canvas.selection.instance_uids = {
            i.uid for i in p.instances
            if not (i.layer and (p.layer_locked(i.layer)
                                 or not p.layer_visible(i.layer)))}
        self.canvas.selection_changed.emit()
        self.canvas.viewport().update()

    def clear_selection(self):
        self.canvas.selection.clear()
        self.canvas.selection_changed.emit()
        self.canvas.viewport().update()

    def split_selection(self):
        sel = self.canvas.selection
        keys = [k for k in sel.stitch_keys
                if (s := self.pattern.stitches.get(k)) is not None
                and s.kind is StitchKind.BACK and s.b is not None]
        if not keys:
            self.statusBar().showMessage(
                "Select backstitch segments to split.")
            return
        self.undo_stack.push(SplitStitchCommand(
            self.pattern, keys, selection=self.canvas.selection,
            sym_ops=self._sym_ops()))
        self.canvas.refresh()
        self._update_status()

    def clip_behind_selection(self):
        """Clip all non-selected stitches to the outside of the closed
        shape formed by the selected backstitches (raw or inside blocks)."""
        sel = self.canvas.selection
        keys = [k for k in sel.stitch_keys
                if (s := self.pattern.stitches.get(k)) is not None
                and s.kind is StitchKind.BACK and s.b is not None]
        uids = [u for u in sel.instance_uids
                if any(i.uid == u for i in self.pattern.instances)]
        if not keys and not uids:
            self.statusBar().showMessage(
                "Select backstitch(s) or a block forming a closed shape.")
            return
        cmd = ClipBehindCommand(
            self.pattern, keys, boundary_uids=uids,
            library_blocks=self.library_blocks)
        self.undo_stack.push(cmd)
        removed, added = cmd.stats
        if removed == 0:
            self.statusBar().showMessage(
                "Nothing was inside the selected shape — check that the "
                "outline is closed and surrounds the target stitches.")
        else:
            self.statusBar().showMessage(
                f"Clipped {removed} stitch(es) behind the shape "
                f"({added} piece(s) kept).")
        self.canvas.refresh()
        self._update_status()

    def transform_instances(self, op):
        sel = self.canvas.selection
        uids = list(sel.instance_uids)
        keys = list(sel.stitch_keys)
        if not uids and not keys:
            self.statusBar().showMessage(
                "Transform: select stitches or block instances first.")
            return
        stitch_op = None
        if keys:
            # bbox center of selected stitches (cell coords)
            xs, ys = [], []
            for k in keys:
                s = self.pattern.stitches.get(k)
                if s is None:
                    continue
                xs += [s.a[0], s.b[0] if s.b else s.a[0]]
                ys += [s.a[1], s.b[1] if s.b else s.a[1]]
            if xs:
                cx, cy = int(round((min(xs) + max(xs)) / 2)), \
                    int(round((min(ys) + max(ys)) / 2))
                inner = Transform.from_semantic(
                    0, 0, int(op[3:]) if op.startswith("rot") else 0,
                    op == "flipx", op == "flipy")
                stitch_op = (Transform.translation(-cx, -cy)
                             .then(inner)
                             .then(Transform.translation(cx, cy)))
        lib = {**self.library_blocks, **self.pattern.blocks}
        self.undo_stack.push(
            TransformInstancesCommand(self.pattern, uids, op,
                                      library_blocks=lib,
                                      stitch_keys=keys, stitch_op=stitch_op,
                                      selection=sel,
                                      sym_ops=self._sym_ops()))
        self._record(f"Edit: Transform ({op})",
                     lambda o=op: self.transform_instances(o))
        self.canvas.refresh()

    # -- move / rotate / duplicate -----------------------------------------
    def _sel_ids(self):
        return (list(self.canvas.selection.stitch_keys),
                list(self.canvas.selection.instance_uids))

    def _sym_ops(self):
        """Live symmetry transforms ([] when symmetry is off)."""
        if not self.canvas.active_symmetry_axes:
            return []
        from .core.symmetry import symmetry_matrices
        return [Transform(*m) for m in symmetry_matrices(
            self.canvas.active_symmetry_axes, self.pattern.width,
            self.pattern.height)]

    def _on_move_selection(self, dx, dy):
        dlg = TransformOptionsDialog("Move", self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        copies, keep = dlg.values()
        self._apply_transform_op((dx, dy, 0, 0, 0), copies, keep,
                                 "Move")

    def _on_rotate_selection(self, cx, cy, q):
        dlg = TransformOptionsDialog("Rotate", self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        copies, keep = dlg.values()
        self._apply_transform_op((0, 0, cx, cy, q), copies, keep,
                                 "Rotate")

    def _apply_transform_op(self, op, copies, keep, label):
        """op = (dx, dy, cx, cy, q): translate then rotate q quarter-turns
        about (cx, cy). copies/keep drive array duplication."""
        dx, dy, cx, cy, q = op
        keys, uids = self._sel_ids()
        if not keys and not uids:
            return
        sel = self.canvas.selection
        plain = copies <= 0 or (not keep and copies <= 1)
        if plain:
            if q == 0 and (dx or dy):
                self.undo_stack.push(MoveStitchesCommand(
                    self.pattern, keys, uids, dx, dy, selection=sel,
                    sym_ops=self._sym_ops()))
            else:
                self.undo_stack.push(TransformSelectionCommand(
                    self.pattern, keys, uids, cx, cy, q, selection=sel,
                    sym_ops=self._sym_ops()))
        else:
            # keep: N copies at steps 1..N, original untouched
            # !keep: original takes step 1, extras at steps 2..N
            steps = range(1, copies + 1) if keep else range(2, copies + 1)
            specs = [(k * dx, k * dy, cx, cy, (k * q) % 4)
                     for k in steps]
            orig_op = None if keep else op
            self.undo_stack.push(CopySelectionCommand(
                self.pattern, keys, uids, specs,
                text=f"{label} +{len(specs)} copies",
                orig_op=orig_op, selection=sel,
                sym_ops=self._sym_ops()))
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
            self.pattern, keys, uids, [(1, 1, 0, 0, 0)], text="Duplicate",
            selection=sel, sym_ops=self._sym_ops())
        self.undo_stack.push(cmd)
        # command already selected the copies; enter Move to drag them
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
            self.pattern, mapping, sel.stitch_keys, sel.instance_uids,
            sym_ops=self._sym_ops()))
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
                    text=f"Explode ({mode})",
                    selection=self.canvas.selection))
        self.canvas.refresh()
        self._refresh_all()
        self._update_status()

    def explode_all_instances(self):
        """Flatten every placed instance into raw stitches (with confirm)."""
        insts = list(self.pattern.instances)
        if not insts:
            self.statusBar().showMessage("No block instances to explode.")
            return
        r = QMessageBox.question(
            self, "Explode all instances",
            f"Flatten all {len(insts)} block instance(s) into raw "
            "stitches? This cannot be undone selectively.")
        if r != QMessageBox.StandardButton.Yes:
            return
        for inst in insts:
            self.undo_stack.push(ExplodeCommand(
                self.pattern, inst, "flatten", self.library_blocks,
                text="Explode all (flatten)",
                selection=self.canvas.selection))
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

    def _on_block_folder(self, block, scope, folder):
        block.folder = folder
        if scope == "global":
            self.library.save()
        else:
            self._extra_dirty = True
        self._refresh_all()

    # ------------------------------------------------------------- files
    def _confirm_discard(self, action):
        """Prompt to save if dirty. Returns True if it's OK to proceed
        (clean, saved, or user chose Don't save); False on Cancel."""
        import os
        if os.environ.get("QT_QPA_PLATFORM") == "offscreen":
            return True   # headless/test runs: never block on a dialog
        if not self._is_dirty():
            return True
        box = QMessageBox(self)
        box.setWindowTitle("Unsaved changes")
        box.setText(f"Save changes before {action}?")
        save_btn = box.addButton("Save", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Don't save", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked == save_btn:
            if self._file_path is None:
                self.save_project_as()
                return self._file_path is not None
            self.save_project()
            return True
        return box.buttonRole(clicked) == QMessageBox.ButtonRole.DestructiveRole

    def new_project(self):
        if not self._confirm_discard("starting a new project"):
            return
        # build the new pattern from persisted canvas defaults and let
        # the user confirm/adjust before it replaces the current doc
        trial = Pattern()
        self._load_canvas_defaults(trial)
        dlg = CanvasSetupDialog(
            trial, self, line_width=self.canvas.line_width)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self.pattern = trial
        self._apply_canvas_values(dlg.values())
        self._save_canvas_settings()
        self._file_path = None
        self._extra_dirty = False
        self._saved_index = 0
        self.canvas.set_pattern(self.pattern)
        self.undo_stack.clear()
        self._refresh_all()

    # -- recent files ---------------------------------------------------
    _RECENT_KEY = "recentFiles"
    _RECENT_MAX = 10

    def _recent_files(self):
        v = QSettings("BlackWerx", "BlackWerx").value(self._RECENT_KEY) or []
        if isinstance(v, str):
            v = [v]
        return [str(p) for p in v]

    def _refresh_recent_menu(self):
        self.recent_menu.clear()
        files = self._recent_files()
        if not files:
            self.recent_menu.addAction("(empty)").setEnabled(False)
            return
        for p in files:
            act = QAction(p, self)
            act.setToolTip(p)
            act.triggered.connect(lambda _=False, path=p: self._open_path(path))
            self.recent_menu.addAction(act)
        self.recent_menu.addSeparator()
        self.recent_menu.addAction("Clear Recent", self._clear_recent)

    def _add_recent(self, path):
        p = str(path)
        files = [r for r in self._recent_files() if r != p]
        files.insert(0, p)
        QSettings("BlackWerx", "BlackWerx").setValue(
            self._RECENT_KEY, files[:self._RECENT_MAX])
        self._refresh_recent_menu()

    def _clear_recent(self):
        QSettings("BlackWerx", "BlackWerx").setValue(self._RECENT_KEY, [])
        self._refresh_recent_menu()

    def _open_path(self, path):
        self._load_path(path)

    def open_project(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open project", "", "Black-Werx project (*.bwpx)")
        if not path:
            return
        self._load_path(path)

    def _load_path(self, path):
        if not self._confirm_discard("opening a project"):
            return
        try:
            self.pattern = project_io.load_project(path)
        except Exception as e:
            QMessageBox.critical(self, "Open failed", str(e))
            return
        self._file_path = Path(path)
        if self.pattern.name in ("", "Untitled"):
            self.pattern.name = self._file_path.stem
        self._add_recent(path)
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
        if self.pattern.name in ("", "Untitled") \
                and self._file_path is not None:
            self.pattern.name = self._file_path.stem
        self._saved_index = self.undo_stack.index()
        self._extra_dirty = False
        if self._file_path is not None:
            self._add_recent(self._file_path)

    def import_svg(self):
        dlg = SvgImportDialog(self.pattern)
        # Center on the main window, then show as an independent
        # top-level window so dragging it can't move the app window.
        c = self.geometry().center()
        dlg.move(c.x() - dlg.width() // 2, c.y() - dlg.height() // 2)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            r = dlg.get_result()
            if r is None:
                return
            self._record("File: Import SVG", self.import_svg)
            # place at center of current view-ish: offset so result centered
            # on pattern; simple: place at (2,2)
            ox, oy = 2, 2
            if dlg.fit_canvas.isChecked():
                need_w = ox + r.width
                need_h = oy + r.height
                if need_w > self.pattern.width or need_h > self.pattern.height:
                    self.pattern.width = need_w + need_w % 2
                    self.pattern.height = need_h + need_h % 2
                    self.canvas._update_scene_rect()
                    self.canvas.centerOn(self.canvas.pattern_center_scene())
                    self.canvas.viewport().update()
                    self._extra_dirty = True
            stitches = [replace(
                s, a=(s.a[0] + ox, s.a[1] + oy),
                b=((s.b[0] + ox, s.b[1] + oy) if s.b else None),
                layer=self.pattern.active_layer)
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
    def _export_options(self, style):
        """Small options dialog before export: symbol set + full canvas.
        Returns (symbol_style, full_canvas) or None if cancelled."""
        from .core.exporters.chart import SYMBOL_STYLES
        from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QComboBox,
                                       QCheckBox, QFormLayout, QLabel)
        dlg = QDialog(self)
        dlg.setWindowTitle("Export options")
        form = QFormLayout(dlg)
        labels = {"shapes": "Shapes (• ▲ ■ ◆ …)",
                  "letters": "Letters (A B C …)",
                  "numbers": "Numbers (1 2 3 …)",
                  "dmc": "DMC numbers"}
        keys = SYMBOL_STYLES
        combo = QComboBox()
        combo.addItems([labels[k] for k in keys])
        cur = self._settings.value("export/symbol_style", "shapes")
        combo.setCurrentIndex(keys.index(cur) if cur in keys else 0)
        combo.setEnabled(style == "symbol" or style is None)
        form.addRow("Symbol set:", combo)
        full = QCheckBox("Export entire canvas (not just stitches)")
        full.setChecked(bool(self._settings.value("export/full_canvas", False)))
        form.addRow(full)
        if style == "realistic":
            form.addRow(QLabel("(symbol set applies to symbol charts only)"))
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                              | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        form.addRow(bb)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return None
        sym = keys[combo.currentIndex()]
        fc = full.isChecked()
        self._settings.setValue("export/symbol_style", sym)
        self._settings.setValue("export/full_canvas", fc)
        return sym, fc

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
        if fmt == "pat":
            opts = ("shapes", False)
        else:
            opts = self._export_options(style)
            if opts is None:
                return
        sym_style, full_canvas = opts
        try:
            lib = {b.id: b for b in self.library.all()}
            if fmt == "pdf":
                pdf_exp.export_pdf(self.pattern, path, style=style or "symbol",
                                   library_blocks=lib, symbol_style=sym_style,
                                   full_canvas=full_canvas)
            elif fmt == "png":
                img_exp.export_png(self.pattern, path,
                                   style=style or "symbol", library_blocks=lib,
                                   symbol_style=sym_style,
                                   full_canvas=full_canvas)
            elif fmt == "svg":
                svg_exp.export_svg(self.pattern, path,
                                   style=style or "realistic", library_blocks=lib,
                                   symbol_style=sym_style,
                                   full_canvas=full_canvas)
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
        self._settings.setValue("ui/geometry", self.saveGeometry())
        self._settings.setValue("ui/dock_state", self.saveState())
        self._settings.setValue("ui/right_splitter_sizes",
                                self.right_splitter.sizes())
        self._settings.setValue(
            "ui/panel_visibility",
            [act.isChecked() for act, _ in self._panel_acts])
        self._save_canvas_settings()
        if not self._confirm_discard("closing"):
            event.ignore()
            return
        event.accept()

    def user_guide(self):
        from .gui.help_dialog import HelpDialog
        HelpDialog(self).exec()

    def about(self):
        QMessageBox.about(self, "About Black-Werx",
                          "Black-Werx — blackwork embroidery pattern editor\n"
                          "Python + PySide6")


class TransformOptionsDialog(QDialog):
    """LibreCAD-style commit options for Move/Rotate.

    Copies = total displaced items. 'Keep original' leaves the source
    untouched and makes Copies extra copies; unchecked, the original is
    transformed and takes the first step (Copies-1 extras follow).
    Always shown on commit; remembers last used values.
    """

    _memory = {"copies": 1, "keep": False}

    def __init__(self, action, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{action} options")
        form = QFormLayout(self)

        self.copies = QSpinBox()
        self.copies.setRange(0, 50)
        self.copies.setValue(self._memory["copies"])
        form.addRow("Copies:", self.copies)

        self.keep = QCheckBox("Keep original")
        self.keep.setChecked(self._memory["keep"])
        form.addRow(self.keep)

        hint = QLabel(
            "Copies counts displaced items. With 'Keep original' the "
            "source stays put and N copies are made; without it the "
            "original takes the first step and N-1 copies follow. "
            "0 copies just moves/rotates the original.")
        hint.setWordWrap(True)
        form.addRow(hint)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        form.addRow(btns)

    def accept(self):
        self._memory["copies"] = self.copies.value()
        self._memory["keep"] = self.keep.isChecked()
        super().accept()

    def values(self):
        return self.copies.value(), self.keep.isChecked()


class CanvasSetupDialog(QDialog):
    """Fabric / physical stitch settings for the pattern."""

    AIDA_COUNTS = [11, 14, 16, 18, 22, 25, 28, 32, 36, 40]

    def __init__(self, pattern, parent=None, line_width=1):
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

        self.line_w = QSpinBox()
        self.line_w.setRange(1, 12)
        self.line_w.setValue(line_width)
        self.line_w.setToolTip(
            "Thickness of X Line stitches, in cells")
        form.addRow("X Line thickness:", self.line_w)

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
            "afterwards for custom fabrics. Canvas counts are rounded "
            "up to even numbers so the symmetry center stays on a "
            "grid intersection.")
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
                "size_h": self.size_h.value(),
                "line_width": self.line_w.value()}


def QColorDialog_getColor(parent):
    from PySide6.QtWidgets import QColorDialog
    c = QColorDialog.getColor(parent=parent)
    return (c, c.isValid())


def _icon_ink() -> QColor:
    """Icon foreground that contrasts with the themed button face."""
    win = QApplication.palette().color(QPalette.ColorRole.Window)
    lum = (0.299 * win.red() + 0.587 * win.green()
           + 0.114 * win.blue())
    # mirror _bar_qss: dark theme -> light buttons, light -> dark buttons
    btn = win.lighter(150) if lum < 140 else win.darker(106)
    blum = (0.299 * btn.red() + 0.587 * btn.green()
            + 0.114 * btn.blue())
    return QColor("#1c1c1c") if blum > 140 else QColor("#f2f2f2")


def _tool_icon(tool) -> QIcon:
    """Draw a 32px toolbar icon for a canvas tool."""
    size = 32
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    c = size / 2
    ink = _icon_ink()
    blue = QColor("#2266ff")
    red = QColor("#d33")
    amber = QColor("#cc7700")

    def cell_x(x0=7, y0=7, x1=25, y1=25):
        grid = QPen(QColor("#bbbbbb"), 1)
        p.setPen(grid)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(x0, y0, x1 - x0, y1 - y0)
        xp = QPen(ink, 2.4)
        xp.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(xp)
        p.drawLine(x0 + 2, y0 + 2, x1 - 2, y1 - 2)
        p.drawLine(x1 - 2, y0 + 2, x0 + 2, y1 - 2)

    if tool is Tool.PENCIL:
        cell_x()
    elif tool is Tool.XLINE:
        cell_x(4, 4, 15, 15)
        dp = QPen(ink, 1.8, Qt.PenStyle.DashLine)
        dp.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(dp)
        p.drawLine(13, 13, 27, 27)
    elif tool is Tool.BACKSTITCH:
        ln = QPen(ink, 2.2)
        ln.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(ln)
        p.drawLine(6, c, 26, c)
        p.setBrush(QBrush(ink))
        p.setPen(Qt.PenStyle.NoPen)
        for dx in (-8, 0, 8):
            p.drawEllipse(int(c + dx - 2.5), int(c - 2.5), 5, 5)
    elif tool is Tool.ERASER:
        ep = QPen(red, 3)
        ep.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(ep)
        p.drawLine(9, 9, 23, 23)
        p.drawLine(23, 9, 9, 23)
    elif tool is Tool.SELECT:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(ink))
        p.drawPolygon(QPolygonF([
            QPointF(9, 4), QPointF(9, 21), QPointF(13, 17),
            QPointF(15.5, 25), QPointF(18.5, 23.5), QPointF(16, 16),
            QPointF(21, 16)]))
    elif tool is Tool.MOVE:
        mp = QPen(ink, 2.4)
        mp.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(mp)
        p.drawLine(6, c, 26, c)
        p.drawLine(c, 6, c, 26)
        for ang in (0, 90, 180, 270):
            import math
            a = math.radians(ang)
            tipx = c + 10 * math.cos(a)
            tipy = c + 10 * math.sin(a)
            bx = c + 5 * math.cos(a)
            by = c + 5 * math.sin(a)
            px, py = -math.sin(a), math.cos(a)
            p.drawLine(QPointF(tipx, tipy),
                       QPointF(bx + 3.5 * px, by + 3.5 * py))
            p.drawLine(QPointF(tipx, tipy),
                       QPointF(bx - 3.5 * px, by - 3.5 * py))
    elif tool is Tool.ROTATE:
        import math
        r = 10.0
        pts = [QPointF(c + r * math.cos(math.radians(a)),
                       c + r * math.sin(math.radians(a)))
               for a in range(80, 391, 8)]
        rp = QPen(amber, 2.6)
        rp.setCapStyle(Qt.PenCapStyle.RoundCap)
        rp.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(rp)
        p.drawPolyline(pts)

        def arc_pt(deg):
            a = math.radians(deg)
            return QPointF(c + r * math.cos(a), c + r * math.sin(a))
        tip = arc_pt(30)
        p.drawLine(tip, arc_pt(8))
        p.drawLine(tip, arc_pt(-12))
        p.setBrush(QBrush(amber))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(int(c - 2), int(c - 2), 4, 4)
    elif tool is Tool.BLOCK:
        bp = QPen(blue, 1.6, Qt.PenStyle.DashLine)
        p.setPen(bp)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(5, 5, 22, 22)
        p.setBrush(QBrush(blue))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRect(int(c - 4), int(c - 4), 8, 8)
    elif tool is Tool.PAN:
        # open hand: palm + fingers
        hp = QPen(ink, 2)
        hp.setCapStyle(Qt.PenCapStyle.RoundCap)
        hp.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(hp)
        p.setBrush(QBrush(ink))
        p.drawRoundedRect(10, 14, 12, 13, 3, 3)
        p.setPen(Qt.PenStyle.NoPen)
        for fx in (11.5, 15.5, 19.5):
            p.drawRoundedRect(int(fx), 7, 3, 9, 1.5, 1.5)
        p.drawRoundedRect(9, 13, 4, 8, 2, 2)   # thumb
    p.end()
    return QIcon(pm)


def _edit_icon(kind: str) -> QIcon:
    """Draw a 32px icon for an edit-bar command."""
    size = 32
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    c = size / 2
    ink = _icon_ink()
    blue = QColor("#2266ff")
    gray = QColor("#888888")

    def magnifier():
        mg = QPen(ink, 2.2)
        mg.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(mg)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(5, 5, 14, 14)
        p.drawLine(16, 16, 25, 25)

    if kind in ("zoomin", "zoomout"):
        magnifier()
        zp = QPen(ink, 2.4)
        zp.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(zp)
        p.drawLine(9, 12, 15, 12)
        if kind == "zoomin":
            p.drawLine(12, 9, 12, 15)
    elif kind == "actual":
        # ruler: blade with ticks
        rp = QPen(ink, 1.8)
        rp.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(rp)
        p.setBrush(QBrush(QColor("#f0f0f0")))
        p.drawRoundedRect(4, 12, 24, 9, 2, 2)
        for x in range(7, 25, 4):
            p.drawLine(x, 12, x, 16)
    elif kind == "newblock":
        bp = QPen(blue, 1.8, Qt.PenStyle.DashLine)
        p.setPen(bp)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(6, 6, 20, 20)
        pp = QPen(blue, 2.4)
        pp.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pp)
        p.drawLine(16, 10, 16, 22)
        p.drawLine(10, 16, 22, 16)
    elif kind == "explode_flat":
        # block outline breaking into loose stitches
        ep = QPen(gray, 1.6, Qt.PenStyle.DashLine)
        p.setPen(ep)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(5, 5, 22, 22)
        xp = QPen(ink, 2)
        xp.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(xp)
        for x0, y0 in ((4, 4), (24, 5), (5, 25), (25, 24)):
            p.drawLine(x0 - 2, y0 - 2, x0 + 2, y0 + 2)
            p.drawLine(x0 - 2, y0 + 2, x0 + 2, y0 - 2)
    elif kind == "explode_unlink":
        # two interlocking squares pulled apart
        lp = QPen(ink, 2)
        lp.setCapStyle(Qt.PenCapStyle.RoundCap)
        lp.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(lp)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(4, 9, 11, 11, 2, 2)
        p.drawRoundedRect(17, 12, 11, 11, 2, 2)
    elif kind == "dup":
        dp = QPen(ink, 2)
        dp.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(dp)
        p.setBrush(QBrush(QColor("#e8e8e8")))
        p.drawRoundedRect(5, 9, 16, 16, 2, 2)
        p.setBrush(QBrush(blue))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(11, 5, 16, 16, 2, 2)
    elif kind in ("rot", "flipx", "flipy"):
        if kind == "rot":
            import math
            r = 10.0
            pts = [QPointF(c + r * math.cos(math.radians(a)),
                           c + r * math.sin(math.radians(a)))
                   for a in range(80, 391, 8)]
            rp = QPen(ink, 2.6)
            rp.setCapStyle(Qt.PenCapStyle.RoundCap)
            rp.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(rp)
            p.drawPolyline(pts)

            def arc_pt(deg):
                a = math.radians(deg)
                return QPointF(c + r * math.cos(a), c + r * math.sin(a))
            tip = arc_pt(30)
            p.drawLine(tip, arc_pt(8))
            p.drawLine(tip, arc_pt(-12))
        else:
            # double-headed arrow: horizontal or vertical
            ap = QPen(ink, 2.4)
            ap.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(ap)
            if kind == "flipx":
                p.drawLine(9, c, 23, c)
                p.drawLine(9, c, 15, c - 5)
                p.drawLine(9, c, 15, c + 5)
                p.drawLine(23, c, 17, c - 5)
                p.drawLine(23, c, 17, c + 5)
            else:
                p.drawLine(c, 9, c, 23)
                p.drawLine(c, 9, c - 5, 15)
                p.drawLine(c, 9, c + 5, 15)
                p.drawLine(c, 23, c - 5, 17)
                p.drawLine(c, 23, c + 5, 17)
    elif kind == "array":
        # 3x3 grid of squares = block array
        ap = QPen(blue, 1.6)
        ap.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(ap)
        p.setBrush(QBrush(QColor("#d4e4ff")))
        for r in range(3):
            for col in range(3):
                p.drawRect(5 + col * 8, 5 + r * 8, 6, 6)
    elif kind == "split":
        # stitched line with a gap in the middle = split in half
        sp = QPen(ink, 2.2)
        sp.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(sp)
        p.drawLine(5, c, 12, c)
        p.drawLine(20, c, 27, c)
        p.setBrush(QBrush(ink))
        p.setPen(Qt.PenStyle.NoPen)
        for dx in (5, 27):
            p.drawEllipse(int(dx - 2), int(c - 2), 4, 4)
    elif kind == "hide":
        # eye with a slash = hide behind
        ep = QPen(ink, 2)
        ep.setCapStyle(Qt.PenCapStyle.RoundCap)
        ep.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(ep)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(7, 10, 18, 12)
        p.drawEllipse(int(c - 3), int(c - 3), 6, 6)
        p.drawLine(5, 5, 27, 27)
    p.end()
    return QIcon(pm)


def _symmetry_icon() -> QIcon:
    """Mirror-pair arrows around a dashed axis = symmetry."""
    size = 32
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    c = size / 2
    blue = QColor("#2266ff")
    # dashed vertical axis
    ax = QPen(QColor("#999999"), 1.4, Qt.PenStyle.DashLine)
    p.setPen(ax)
    p.drawLine(int(c), 5, int(c), 27)
    # two arrows facing each other across the axis
    ap = QPen(blue, 2.4)
    ap.setCapStyle(Qt.PenCapStyle.RoundCap)
    ap.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(ap)
    for y, d in ((11, 1), (21, -1)):
        # shaft
        p.drawLine(int(c - 9 * d), y, int(c - 3 * d), y)
        # head: two wings back from the tip at the axis
        tipx, tipy = c - 2 * d, y
        for s in (-1, 1):
            p.drawLine(QPointF(tipx, tipy),
                       QPointF(tipx + 5 * d, tipy + s * 4))
    p.end()
    return QIcon(pm)


def _asset(name: str):
    """Path to a repo asset (Images/), or None when not present."""
    here = Path(__file__).resolve()
    candidates = [
        here.parents[2] / "Images",          # source checkout
        here.parents[1] / "Images",          # PyInstaller _internal/
        Path(sys.executable).resolve().parent / "Images",
    ]
    for d in candidates:
        p = d / name
        if p.exists():
            return p
    return None


def _splash_pixmap():
    """Splash image with version/author overlaid at the bottom."""
    from . import __version__, __author__
    src = _asset("blackwerx-splash.png")
    if src is None:
        return None
    base = QPixmap(str(src))
    if base.isNull():
        return None
    pm = QPixmap(base.size())
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.drawPixmap(0, 0, base)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    f = p.font()
    f.setPointSize(20)
    f.setBold(True)
    p.setFont(f)
    # the splash artwork has a rounded info panel at
    # (120, 540, 1040, 110) — center the text inside it
    panel = QRect(120, 540, 1040, 110)
    text = f"v{__version__}  ·  {__author__}"
    p.setPen(QColor(0, 0, 0, 140))
    p.drawText(panel.translated(0, 1), Qt.AlignmentFlag.AlignCenter, text)
    p.setPen(QColor("#ffffff"))
    p.drawText(panel, Qt.AlignmentFlag.AlignCenter, text)
    p.end()
    return pm


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Black-Werx")

    # PNG first: some WMs/taskbars don't rasterize SVG window icons
    icon_src = (_asset("blackwerx-icon-1024.png")
                or _asset("blackwerx-icon.svg")
                or _asset("blackwerx-icon.ico"))
    if icon_src is not None:
        app.setWindowIcon(QIcon(str(icon_src)))

    splash = None
    spm = _splash_pixmap()
    if spm is not None:
        # half size, then keep it within ~80% of the available screen
        spm = spm.scaled(spm.width() // 2, spm.height() // 2,
                         Qt.AspectRatioMode.IgnoreAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
        scr = app.primaryScreen()
        if scr is not None:
            avail = scr.availableGeometry().size()
            mw, mh = int(avail.width() * 0.8), int(avail.height() * 0.8)
            if spm.width() > mw or spm.height() > mh:
                spm = spm.scaled(
                    mw, mh, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation)
        splash = QSplashScreen(spm)
        splash.show()
        app.processEvents()

    win = MainWindow()
    if not app.windowIcon().isNull():
        win.setWindowIcon(app.windowIcon())
    if splash is not None:
        # keep the splash on top for its ~3s, then reveal the window
        def _reveal():
            splash.finish(win)
            win.show()
        QTimer.singleShot(3000, _reveal)
    else:
        win.show()
    sys.exit(app.exec())
