"""One-click build: clean .pyc -> PyInstaller -> Inno Setup."""
import shutil
import subprocess
import sys
from pathlib import Path
import os

ROOT = Path(__file__).parent
VERSION = "1.0.0"

ISCC_PATHS = [
    Path.home() / r"AppData\Local\Programs\Inno Setup 6\ISCC.exe",
    Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
    Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
]


def clean_pyc():
    print("=== Cleaning .pyc / __pycache__ ===")
    removed = 0
    for d in ROOT.rglob("__pycache__"):
        shutil.rmtree(d, ignore_errors=True)
        removed += 1
    for f in ROOT.rglob("*.pyc"):
        f.unlink(missing_ok=True)
        removed += 1
    print(f"  Removed {removed} items")


def clean_build():
    print("=== Cleaning build artifacts ===")
    for d in ["build", "dist", "Output"]:
        p = ROOT / d
        if p.exists():
            shutil.rmtree(p)
            print(f"  Removed {d}/")


def bundle_icu_dlls():
    """Copy icuuc.dll + icudt*.dll into the exe root so they are always found
    via LOAD_LIBRARY_SEARCH_APPLICATION_DIR, even when Miniconda is absent
    from the shortcut's PATH."""
    exe_root = ROOT / "dist" / "ClaudeManager"
    if not exe_root.exists():
        print("  dist/ClaudeManager not found, skipping ICU bundle")
        return

    # Search PATH directories and common conda locations for icuuc.dll
    search_dirs = []
    for p in os.environ.get("PATH", "").split(os.pathsep):
        if p:
            search_dirs.append(Path(p))

    icu_src = None
    for d in search_dirs:
        candidate = d / "icuuc.dll"
        if candidate.exists():
            icu_src = d
            break

    if icu_src is None:
        print("  icuuc.dll not found on PATH – ICU DLLs not bundled")
        return

    print(f"=== Bundling ICU DLLs from {icu_src} ===")
    for dll in icu_src.glob("icu*.dll"):
        dest = exe_root / dll.name
        shutil.copy2(dll, dest)
        print(f"  Copied {dll.name}")


def build_pyinstaller():
    print("=== Building with PyInstaller ===")
    r = subprocess.run(
        [sys.executable, "-m", "PyInstaller", "claude_manager.spec", "-y"],
        cwd=ROOT,
    )
    if r.returncode != 0:
        print("PyInstaller FAILED")
        sys.exit(1)
    print("  PyInstaller OK")


def build_inno():
    iscc = None
    for p in ISCC_PATHS:
        if p.exists():
            iscc = p
            break
    if not iscc:
        print("=== Inno Setup not found, skipping installer ===")
        return

    print(f"=== Building installer with {iscc} ===")
    r = subprocess.run(
        [str(iscc), f"/DMyAppVersion={VERSION}", "installer.iss"],
        cwd=ROOT,
    )
    if r.returncode != 0:
        print("Inno Setup FAILED")
        sys.exit(1)
    print("  Installer OK")

    out = ROOT / "Output" / f"ClaudeManager-Setup-{VERSION}.exe"
    if out.exists():
        print(f"  Output: {out} ({out.stat().st_size / 1024 / 1024:.1f} MB)")


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-inno", action="store_true")
    args = parser.parse_args()

    clean_pyc()
    clean_build()
    build_pyinstaller()
    bundle_icu_dlls()
    if not args.skip_inno:
        build_inno()

    print("\n=== Done ===")


if __name__ == "__main__":
    main()
