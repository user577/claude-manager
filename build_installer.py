"""One-click build: clean .pyc -> PyInstaller -> Inno Setup."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
VERSION = "1.0.0"

# Sentinel so a venv python that reports an unexpected sys.executable can't
# send us into an endless re-exec loop.
_REEXEC_FLAG = "CLAUDE_MANAGER_BUILD_REEXEC"


def venv_python():
    if os.name == "nt":
        return ROOT / ".venv" / "Scripts" / "python.exe"
    return ROOT / ".venv" / "bin" / "python"


def ensure_project_venv():
    """Re-run under the project venv if invoked with a different interpreter.

    The interpreter that runs PyInstaller decides what gets frozen — the spec
    pins OpenSSL to *its* base_prefix/DLLs, and PySide6 comes from its
    site-packages. A stray `python build_installer.py` picking up some other
    Python on PATH produces a bundle that builds clean and is broken at
    runtime, so re-exec instead of trusting whatever was used.
    """
    py = venv_python()
    if not py.is_file():
        sys.exit(f"Project venv not found at {py}\nCreate it first:  uv sync")

    try:
        already_venv = Path(sys.executable).resolve() == py.resolve()
    except OSError:
        already_venv = False
    if already_venv or os.environ.get(_REEXEC_FLAG) == "1":
        return

    print(f"=== Wrong interpreter ({sys.executable}) ===")
    print(f"=== Re-running under project venv: {py} ===")
    env = {**os.environ, _REEXEC_FLAG: "1"}
    r = subprocess.run([str(py), str(Path(__file__).resolve()), *sys.argv[1:]],
                       cwd=ROOT, env=env)
    sys.exit(r.returncode)

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

    ensure_project_venv()
    print(f"=== Python {sys.version.split()[0]} ({sys.executable}) ===")

    clean_pyc()
    clean_build()
    build_pyinstaller()
    if not args.skip_inno:
        build_inno()

    print("\n=== Done ===")


if __name__ == "__main__":
    main()
