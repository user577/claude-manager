# -*- mode: python ; coding: utf-8 -*-
import os
import sys
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


def _without_icu_binaries(toc):
    """Use Windows' ICU DLLs instead of bundling incompatible conda builds."""
    return [
        entry for entry in toc
        if not Path(entry[0]).name.lower().startswith("icu")
    ]


def _with_correct_openssl(toc):
    """Force the OpenSSL that ships with this Python, not whatever is on PATH.

    _ssl.pyd (Python 3.12) imports X509_STORE_get1_objects, added in OpenSSL
    3.4. PyInstaller's dependency scan can resolve libcrypto-3-x64.dll from an
    OLDER OpenSSL earlier on PATH (e.g. Git's mingw64 build) that lacks that
    export. Bundling that shadow makes `import ssl` fail at runtime with
    "DLL load failed ... procedure could not be found", which silently strips
    HTTPS from urllib — every usage-meter fetch then dies as "Offline" while
    everything network-free (the gh-backed commit meter) keeps working.

    Repoint the OpenSSL DLLs at the copies next to this interpreter's _ssl.pyd
    (base_prefix/DLLs), which are guaranteed to match it.
    """
    dlls = Path(sys.base_prefix) / "DLLs"
    targets = {"libcrypto-3-x64.dll", "libssl-3-x64.dll"}
    seen = set()
    fixed = []
    for dest, src, kind in toc:
        name = Path(dest).name
        if name.lower() in targets:
            correct = dlls / name
            if correct.is_file():
                src = str(correct)
            seen.add(name.lower())
        fixed.append((dest, src, kind))
    for name in targets - seen:
        correct = dlls / name
        if correct.is_file():
            fixed.append((name, str(correct), "BINARY"))
    return fixed


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
a.binaries = _without_icu_binaries(a.binaries)
a.binaries = _with_correct_openssl(a.binaries)

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
