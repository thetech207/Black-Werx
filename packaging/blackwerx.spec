# PyInstaller spec for Black-Werx (onedir)
# Build: .venv/bin/pip install pyinstaller && .venv/bin/pyinstaller packaging/blackwerx.spec

a = Analysis(
    ["src/blackwerx/__main__.py"],
    pathex=["src"],
    binaries=[],
    datas=[("src/blackwerx/resources", "blackwerx/resources")],
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
