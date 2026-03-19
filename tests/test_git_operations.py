import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.core.git_operations import pyc_cleanup, _run_git


def test_pyc_cleanup(tmp_path):
    # Create __pycache__ dirs and .pyc files
    cache = tmp_path / "src" / "__pycache__"
    cache.mkdir(parents=True)
    (cache / "foo.cpython-310.pyc").write_bytes(b"fake")
    (cache / "bar.cpython-310.pyc").write_bytes(b"fake")

    stray = tmp_path / "stray.pyc"
    stray.write_bytes(b"fake")

    removed = pyc_cleanup(str(tmp_path))
    assert removed >= 2  # __pycache__ dir + stray .pyc
    assert not cache.exists()
    assert not stray.exists()


def test_pyc_cleanup_skips_venv(tmp_path):
    venv_cache = tmp_path / ".venv" / "lib" / "__pycache__"
    venv_cache.mkdir(parents=True)
    (venv_cache / "mod.pyc").write_bytes(b"fake")

    removed = pyc_cleanup(str(tmp_path))
    assert removed == 0
    assert venv_cache.exists()


def test_pyc_cleanup_skips_node_modules(tmp_path):
    nm = tmp_path / "node_modules" / "__pycache__"
    nm.mkdir(parents=True)
    (nm / "x.pyc").write_bytes(b"fake")

    removed = pyc_cleanup(str(tmp_path))
    assert removed == 0


def test_pyc_cleanup_empty_dir(tmp_path):
    removed = pyc_cleanup(str(tmp_path))
    assert removed == 0


def test_run_git_success():
    with patch("src.core.git_operations.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0, stdout="ok\n", stderr=""
        )
        ok, out = _run_git("/fake", "status")
        assert ok
        assert out == "ok"


def test_run_git_failure():
    with patch("src.core.git_operations.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="error msg"
        )
        ok, out = _run_git("/fake", "push")
        assert not ok
        assert "error msg" in out


def test_run_git_timeout():
    import subprocess
    with patch("src.core.git_operations.subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="git", timeout=30)
        ok, out = _run_git("/fake", "fetch")
        assert not ok
        assert "Timed out" in out
