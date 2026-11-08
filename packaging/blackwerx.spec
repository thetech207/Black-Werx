# PyInstaller spec for Black-Werx (onedir)
# Build: .venv/bin/pip install pyinstaller && .venv/bin/pyinstaller packaging/blackwerx.spec

import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(SPEC)))

a = Analysis(
    [os.path.join(ROOT, "packaging/run.py")],
    pathex=[os.path.join(ROOT, "src")],
    binaries=[],
    datas=[(os.path.join(ROOT, "src/blackwerx/resources"),
            "blackwerx/resources"),
           (os.path.join(ROOT, "Images"), "Images")],
    hiddenimports=["blackwerx.core.exporters.chart"],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="blackwerx",
    console=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="blackwerx",
)
