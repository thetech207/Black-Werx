# Black-Werx

A desktop editor for **blackwork / cross-stitch embroidery patterns**,
built with Python + PySide6 (Qt6). Runs natively on Debian Linux; designed
to stay portable to Windows.

## Features

- **Grid-snapped canvas** — drawing is restricted to grid intersections
  (the holes in Aida cloth). X-stitches and backstitches.
- **CAD-style block library** — reusable, nestable pattern fragments.
  Place, move, rotate, flip, and recolor instances; double-click blocks in
  the library to place them.
- **Explode blocks** — flatten an instance into raw stitches, or unlink it
  from the library definition so it becomes an editable snapshot.
- **Block editor** — edit a block definition standalone.
- **Thread colors** — built-in DMC palette plus custom colors.
- **Symmetry tools** — live mirror across vertical/horizontal/diagonal
  axes while drawing.
- **Undo/redo** for all edits.
- **SVG import** — convert vector artwork to stitches with adjustable
  accuracy (grid size, threshold, smoothing, despeckle) in fill or outline
  mode, with live preview before committing.
- **Export** — symbol chart or realistic preview as PDF, PNG, or SVG;
  Tajima `.pat` stitch files; `.bwpx` project files.

## Running

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/python -m blackwerx
# or after install:
.venv/bin/blackwerx
```

## Project files

`.bwpx` files are versioned JSON (`{"format": "bwpx", "version": 1, ...}`).

The global block library lives at
`~/.local/share/blackwerx/library.json` (XDG path).

## Layout

```
src/blackwerx/
  core/         GUI-free model, blocks, palette, symmetry, svg import, exporters
  gui/          canvas, tools, panels, commands, dialogs
  app.py        main window
tests/          pytest core tests + pytest-qt GUI tests
packaging/      .desktop file, icon, PyInstaller spec
```

## Testing

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ -q
```

## Packaging (Debian)

See `packaging/` — a `.desktop` file and PyInstaller spec are provided.
PySide6 pulls in Qt6; on Debian install `libgl1` and `libegl1` if the
binary complains about OpenGL.
