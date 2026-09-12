"""One-click build: clean .pyc -> PyInstaller -> Inno Setup."""
import os
import shutil
import stat
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


def _clear_readonly(func, path, _exc_info):
    """rmtree error handler: drop the read-only bit and retry.

    Windows refuses to unlink a read-only file, and DLLs copied out of a Qt or
    system directory keep that bit. One such leftover in dist/ is enough to
    abort every later build, so clear it rather than fail the clean.
    """
    os.chmod(path, stat.S_IWRITE)
    func(path)


def clean_build():
    print("=== Cleaning build artifacts ===")
    for d in ["build", "dist", "Output"]:
        p = ROOT / d
        if p.exists():
            shutil.rmtree(p, onerror=_clear_readonly)
            print(f"  Removed {d}/")


def _is_openssl_dll(name):
    n = name.lower()
    return n.startswith(("libcrypto-", "libssl-")) and n.endswith(".dll")


def openssl_clean_env():
    """Drop PATH entries carrying an OpenSSL that is not this interpreter's.

    PyInstaller resolves libcrypto/libssl by walking PATH, so a stray copy gets
    bundled ahead of the pair sitting next to _ssl.pyd, and the spec's fixup
    then hard-fails the build. Two such copies show up routinely here: Git's
    mingw64 build (on PATH in any Git Bash shell) and — self-inflicted — a
    previously installed ClaudeManager, whose _internal directory is added to
    the user PATH and still holds whatever a past build bundled. That second
    one makes the failure loop: ship a bad OpenSSL once and every later build
    picks it back up.

    Filtering here rather than relying on whoever invokes the build to have a
    clean shell. The spec still hard-fails if anything slips through.
    """
    dlls = (Path(sys.base_prefix) / "DLLs").resolve()
    kept, dropped = [], []
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if not entry:
            continue
        try:
            shadows = Path(entry).resolve() != dlls and any(
                _is_openssl_dll(p.name) for p in Path(entry).glob("*.dll")
            )
        except OSError:
            shadows = False
        (dropped if shadows else kept).append(entry)

    if dropped:
        print("  Dropped from PATH (shadowing OpenSSL):")
        for entry in dropped:
            print(f"    {entry}")
    return {**os.environ, "PATH": os.pathsep.join(kept)}


def build_pyinstaller():
    print("=== Building with PyInstaller ===")
    r = subprocess.run(
        [sys.executable, "-m", "PyInstaller", "claude_manager.spec", "-y"],
        cwd=ROOT,
        env=openssl_clean_env(),
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
