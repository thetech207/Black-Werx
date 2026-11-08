"""In-app user guide (Help → User Guide)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QTextBrowser,
                               QDialogButtonBox)

GUIDE_HTML = """
<h2>Black-Werx User Guide</h2>
<p><b>Black-Werx</b> is a vector-style editor for blackwork (cross-stitch)
embroidery. Stitches snap to an Aida grid: <b>X stitches</b> live in cell
centers, <b>backstitches</b> run dot-to-dot on grid intersections.</p>

<h3>Projects</h3>
<ul>
<li><b>File → New</b> (Ctrl+N) opens Canvas setup first — pick Aida count,
stitched size (stitches or inches), stitch pitch, and X-line thickness.
Settings persist between sessions.</li>
<li>Canvas counts are always <b>even</b> so the symmetry center lands on a
grid dot.</li>
<li>A <b>•</b> in the title bar means unsaved changes. New/Open prompt
to save first.</li>
<li><b>Canvas setup…</b> (Edit menu) changes fabric size, Aida count, and
physical stitch size later.</li>
<li><b>View → Theme</b>: System / Light / Dark.</li>
</ul>

<h3>The canvas</h3>
<ul>
<li>The <b>fabric</b> is the printable area; the shaded <b>workspace</b>
border around it (100 stitches) is for staging blocks and elements.
Exports only include the fabric region.</li>
<li><b>Rulers</b> show coordinates (negative in the workspace). Drag from
a ruler onto the canvas to drop a <b>guide</b>; guides are non-printing
and live on their own layer.</li>
<li><b>Zoom</b>: Ctrl++ / Ctrl+- , Ctrl+0 reset, or View → Actual Size
for true on-fabric scale.</li>
<li>The pink marker is the canvas center — a grid dot, matching the
symmetry point.</li>
</ul>

<h3>Tools</h3>
<p>Click a tool button on the left (or press its key):</p>
<table border="1" cellspacing="0" cellpadding="4">
<tr><th>Tool</th><th>Key</th><th>How it works</th></tr>
<tr><td>X Stitch</td><td>X</td><td>Click or drag to fill cells with X
stitches in the current thread color.</td></tr>
<tr><td>X Line</td><td>L</td><td>Click two points; fills a stitched line
between them. Thickness set in Canvas setup.</td></tr>
<tr><td>Backstitch</td><td>B</td><td>Click points to chain backstitches
dot-to-dot. Right-click finishes a run and keeps the tool; right-click
again returns to Select.</td></tr>
<tr><td>Eraser</td><td>E</td><td>Drag over stitches to delete exactly
what highlights.</td></tr>
<tr><td>Select</td><td>S</td><td>Click items or drag a rubber band
(stitches need ~50% inside). Shift-click toggles. Right-click opens a
context menu; left-click empty space deselects.</td></tr>
<tr><td>Move</td><td>M</td><td>Drag the selection; a live ghost shows the
result. Right-click cancels the drag.</td></tr>
<tr><td>Rotate</td><td>R</td><td>Click to set the center, drag to rotate;
commits in 90° steps. Shift+R rotates the other way.</td></tr>
<tr><td>Place Block</td><td>—</td><td>Arm a block in the library, then
click to place. <b>1–9</b> sets the anchor, <b>R</b> rotates 90°
(Shift+R = 270°), <b>F</b>/<b>V</b> flip. The ghost shows exactly what
will be placed.</td></tr>
<tr><td>Pan</td><td>P</td><td>Drag to move the view. Space-drag or
middle-drag pans from any tool.</td></tr>
</table>
<p><b>Esc</b> cancels the current operation; a second Esc/right-click
returns to Select.</p>

<h3>Colors</h3>
<ul>
<li>The color panel lists the <b>DMC palette</b> (filterable) plus a
Custom picker. New stitches use the selected color.</li>
<li>Stitches keep their own colors — recolor a selection via
Edit → Recolor selection.</li>
<li>Layers can have a display color (view-only override).</li>
</ul>

<h3>Blocks</h3>
<ul>
<li><b>New Block</b> (Edit bar or Blocks menu) turns the selection into a
reusable block, normalized to its bounding box.</li>
<li>The <b>library</b> (right panel) has Global and Project sections.
Double-click or Place to arm a block; Edit opens the block editor;
Delete removes; Promote copies a project block to the global library.</li>
<li><b>Folders</b>: Folder… files a block under a named folder (pick an
existing one or type a new name; blank unfiles).</li>
<li><b>Array…</b> (Edit bar) arms a one-shot rows×columns placement with
edge-to-edge gap spacing — the ghost previews the whole array, one
click places it all in a single undo step.</li>
<li><b>Explode</b> breaks instances back into editable content:
Flatten makes plain stitches; Unlink keeps independent block copies.</li>
<li>Blocks can contain other blocks (nested); linked instances update
together when the source block is edited.</li>
</ul>

<h3>Symmetry</h3>
<p>The Symmetry button (bottom of the tool strip) mirrors new stitches,
edits, and block placements across axes: Left/right, Top/bottom,
Diagonal, or Point mirror — combinable. <b>Enabled</b> toggles
application without losing your axis choices. Stitches missing their
mirrored counterparts are flagged while symmetry is active.</p>

<h3>Layers &amp; guides</h3>
<ul>
<li>New stitches go to the <b>active layer</b> (red dot). Each layer can
be hidden, locked, recolored for display, reordered, merged, or deleted
(with migration).</li>
<li>Selections can be moved to another layer.</li>
<li><b>Guides</b> are non-printing reference lines dragged from the
rulers; they live on a dedicated layer that can be shown/locked.</li>
</ul>

<h3>Editing selections</h3>
<p>Select stitches/instances, then use the Edit bar: Duplicate,
Rotate (90/180/270°), Flip (H/V), Split Stitch (halve a stitch),
Hide Behind (mask stitches behind a closed shape), Delete. Right-click
a selection for the MRU context menu — recently used actions float to
the top.</p>

<h3>Import &amp; export</h3>
<ul>
<li><b>Import SVG</b> converts vector art to stitches: fill (X),
outline (backstitch), or both; optional color preservation, grid size,
and canvas expansion. Preview updates when you leave a field.</li>
<li><b>Export</b>: PDF or PNG in symbol-chart or realistic style, SVG,
or Tajima .pat stitch file. Exports clip to the fabric — workspace
content never prints.</li>
</ul>

<h3>Undo</h3>
<p>Everything is undoable (Ctrl+Z / Ctrl+Y), including symmetry-mirrored
edits, block placement, transforms, and layer operations. The History
dock (View menu) lists the stack.</p>
"""


class HelpDialog(QDialog):
    """Scrollable user guide."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Black-Werx User Guide")
        self.resize(720, 640)
        lay = QVBoxLayout(self)
        view = QTextBrowser()
        view.setOpenExternalLinks(False)
        view.setHtml(GUIDE_HTML)
        lay.addWidget(view, 1)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btns.rejected.connect(self.reject)
        btns.accepted.connect(self.accept)
        lay.addWidget(btns)
