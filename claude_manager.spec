# -*- mode: python ; coding: utf-8 -*-
import os
from pathlib import Path


def _discover_src_modules():
    """Auto-discover all .py modules under src/ for hidden imports."""
    src = Path("src")
    modules = []
    for py in src.rglob("*.py"):
        if py.name == "__init__.py":
            mod = str(py.parent).replace(os.sep, ".")
        else:
            mod = str(py.with_suffix("")).replace(os.sep, ".")
        if mod and mod not in modules:
            modules.append(mod)
    return modules


block_cipher = None

a = Analysis(
    ["src/app.py"],
    pathex=[],
    binaries=[
        (".venv/Lib/site-packages/PySide6/msvcp140.dll", "."),
    ],
    datas=[
        ("app_icon.ico", "."),
    ],
    hiddenimports=_discover_src_modules(),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=["hooks/rthook_dll_dirs.py"],
    excludes=["tkinter", "unittest", "pytest"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ClaudeManager",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon="app_icon.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="ClaudeManager",
)
