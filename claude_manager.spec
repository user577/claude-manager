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


def _is_openssl_dll(name):
    n = name.lower()
    return n.startswith(("libcrypto-", "libssl-")) and n.endswith(".dll")


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

    Matched by prefix rather than by literal filename: CPython ships these as
    libcrypto-3-x64.dll on some builds and libcrypto-3.dll on others (the
    Windows Store build), and an exact-name check silently no-ops on the
    spelling it doesn't know — quietly shipping the broken DLL. Anything left
    pointing outside base_prefix/DLLs is a hard build error instead.
    """
    dlls = Path(sys.base_prefix) / "DLLs"
    authoritative = {
        p.name.lower(): p for p in dlls.glob("*.dll") if _is_openssl_dll(p.name)
    }

    seen = set()
    fixed = []
    for dest, src, kind in toc:
        name = Path(dest).name
        if _is_openssl_dll(name):
            correct = authoritative.get(name.lower())
            if correct is not None:
                src = str(correct)
            seen.add(name.lower())
        fixed.append((dest, src, kind))

    # Pull in any that the dependency scan missed entirely.
    for name, correct in authoritative.items():
        if name not in seen:
            fixed.append((correct.name, str(correct), "BINARY"))

    _assert_openssl_correct(fixed, dlls)
    return fixed


def _assert_openssl_correct(toc, dlls):
    """Fail the build rather than ship an app whose HTTPS is dead on arrival."""
    bundled = [
        (Path(dest).name, src)
        for dest, src, _ in toc
        if _is_openssl_dll(Path(dest).name)
    ]
    if not bundled:
        raise SystemExit(
            f"\nOpenSSL fixup: nothing bundled, and none found in {dlls}\n"
            "The frozen app would have no working HTTPS (usage meters would\n"
            "read 'Offline'). Build with the project venv: uv sync && "
            "uv run python build_installer.py\n"
        )
    wrong = [
        (name, src) for name, src in bundled
        if Path(src).resolve().parent != dlls.resolve()
    ]
    if wrong:
        detail = "\n".join(f"    {name}  <-  {src}" for name, src in wrong)
        raise SystemExit(
            "\nOpenSSL fixup could not repoint these at the copies belonging\n"
            f"to the interpreter running this build ({sys.version.split()[0]}):\n"
            f"{detail}\n"
            f"Expected them in: {dlls}\n"
            "Usually means the build ran under the wrong Python. Use the\n"
            "project venv: uv sync && uv run python build_installer.py\n"
        )


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
