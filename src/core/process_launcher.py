import os
import subprocess
import time
import uuid

from PySide6.QtCore import QThread, Signal

from src.config.settings import RepoInfo
from src.core.window_manager import (
    get_work_area, compute_layout, find_windows_by_title, tile_windows,
)


_ollama_model_cache: list[str] | None = None

# --- Ollama / local-backend framework ---------------------------------------
#
# Retained with no UI on this install: the machinery below (model listing,
# health, test, pull, and LaunchWorker's backend="local" branch) is kept so a
# machine that actually runs local models can wire a front end back onto it.
#
# KNOWN DEFECT — the local launch path does not work as written. LaunchWorker
# exports ANTHROPIC_BASE_URL=http://localhost:11434, but Claude Code speaks the
# Anthropic Messages API (/v1/messages) and Ollama serves only its native
# /api/* plus an OpenAI-compatible /v1/chat/completions. The first request 404s.
# OllamaTestWorker below probes /v1/chat/completions, which *does* exist, so
# "Test" reports success while an actual launch fails — do not read a passing
# test as proof the backend works. Making this real needs a translation shim
# (or an Ollama build that serves /v1/messages), not a config tweak.


def stop_worker(thread, wait_ms: int = 3000) -> bool:
    """Stop a background :class:`QThread` cleanly for shutdown.

    Signals cancellation if the worker supports it, then waits up to
    ``wait_ms`` for ``run()`` to return. Returns ``True`` if the thread
    finished, ``False`` if it was still running when the timeout elapsed.

    We deliberately do NOT call ``QThread.terminate()`` on a stuck thread:
    these workers run pure-Python bodies (urllib / subprocess), and force-
    killing one mid-execution corrupts the interpreter and aborts the process.
    A thread stuck on a slow network/subprocess call is instead abandoned; it
    holds no shared state and the process is exiting anyway. In practice these
    calls return in well under a second, so the wait almost always succeeds.
    """
    if thread is None:
        return True
    try:
        if not thread.isRunning():
            return True
    except RuntimeError:
        # Underlying C++ object already deleted — nothing to do.
        return True
    if hasattr(thread, "cancel"):
        try:
            thread.cancel()
        except Exception:
            pass
    thread.quit()  # no-op for run()-loop workers, harmless
    return thread.wait(wait_ms)


def get_ollama_models(force_refresh: bool = False) -> list[str]:
    """Query ollama for available models. Cached until force_refresh."""
    global _ollama_model_cache
    if _ollama_model_cache is not None and not force_refresh:
        return _ollama_model_cache

    try:
        result = subprocess.run(
            ["ollama", "list"],
            capture_output=True, text=True, timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode != 0:
            _ollama_model_cache = []
            return []
        models = []
        for line in result.stdout.strip().splitlines()[1:]:  # skip header
            parts = line.split()
            if parts:
                models.append(parts[0])  # model name is first column
        _ollama_model_cache = models
        return models
    except Exception:
        _ollama_model_cache = []
        return []


def get_ollama_status() -> dict:
    """Check ollama health. Returns {"running": bool, "version": str, "models": list}."""
    info: dict = {"running": False, "version": "", "models": []}
    try:
        result = subprocess.run(
            ["ollama", "--version"],
            capture_output=True, text=True, timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode == 0:
            info["version"] = result.stdout.strip()
    except Exception:
        return info

    # Check if the server is actually responding
    try:
        import urllib.request
        req = urllib.request.Request("http://localhost:11434/api/version", method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            if resp.status == 200:
                import json
                data = json.loads(resp.read())
                info["running"] = True
                info["version"] = data.get("version", info["version"])
    except Exception:
        # ollama installed but server not running
        return info

    info["models"] = get_ollama_models(force_refresh=True)
    return info


class OllamaHealthWorker(QThread):
    """Check ollama status in a background thread to avoid blocking the UI."""
    result = Signal(dict)

    def run(self):
        self.result.emit(get_ollama_status())


class OllamaTestWorker(QThread):
    """Send a minimal prompt to verify the local model responds."""
    result = Signal(bool, str)  # (success, message)

    def __init__(self, model: str, parent=None):
        super().__init__(parent)
        self.model = model

    def run(self):
        try:
            import urllib.request
            import json
            payload = json.dumps({
                "model": self.model,
                "messages": [{"role": "user", "content": "Say OK"}],
                "max_tokens": 8,
                "stream": False,
            }).encode()
            req = urllib.request.Request(
                "http://localhost:11434/v1/chat/completions",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
                reply = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                self.result.emit(True, reply.strip()[:80] or "(empty)")
        except Exception as e:
            self.result.emit(False, str(e))


class OllamaPullWorker(QThread):
    """Pull an ollama model, emitting progress lines."""
    progress = Signal(str)
    finished = Signal(bool, str)  # (success, final_message)

    def __init__(self, model_name: str, parent=None):
        super().__init__(parent)
        self.model_name = model_name

    def run(self):
        try:
            proc = subprocess.Popen(
                ["ollama", "pull", self.model_name],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            for line in proc.stdout:
                stripped = line.strip()
                if stripped:
                    self.progress.emit(stripped)
            proc.wait()
            if proc.returncode == 0:
                # Invalidate the model cache so refresh picks it up
                global _ollama_model_cache
                _ollama_model_cache = None
                self.finished.emit(True, f"Successfully pulled {self.model_name}")
            else:
                self.finished.emit(False, f"ollama pull exited with code {proc.returncode}")
        except Exception as e:
            self.finished.emit(False, str(e))


def escape_prompt(text: str) -> str:
    """Make prompt text safe to embed in a double-quoted cmd.exe argument.

    Flattened to one line — cmd.exe /k treats embedded newlines in the argument
    as command terminators, which would truncate the prompt.
    """
    return " ".join(text.split()).replace('"', '\\"')


def build_wt_command(title: str, cwd: str, shell_cmd: str) -> list[str]:
    """Build the wt.exe argv that opens `shell_cmd` in a new titled window.

    wt.exe splits its command line on ";" even inside quoted arguments, then
    tries to run the tail as a separate subcommand (0x80070002), so semicolons
    are escaped ("\\;") to pass through literally.

    Every launch path goes through here. Hand-rolling the argv is how the
    semicolon bug survived in LaunchWorker long after the git panel fixed it.
    """
    return [
        "wt.exe", "--window", "new",
        "--title", title,
        "-d", cwd,
        "cmd.exe", "/k", shell_cmd.replace(";", "\\;"),
    ]


def _make_title(label: str, uid: str) -> str:
    return f"Claude-{label}-{uid}"


class LaunchWorker(QThread):
    """Launch Claude instances in Windows Terminal and tile them."""
    status = Signal(str)  # progress messages
    finished_ok = Signal()
    finished_err = Signal(str)

    def __init__(self, repos: list[RepoInfo], layout: str, count: int,
                 permission_mode: str = "default",
                 model: str = "default",
                 backend: str = "cloud",
                 local_model: str = "",
                 initial_prompt: str = "",
                 use_worktree: bool = False,
                 session_mode: str = "new",
                 parent=None):
        super().__init__(parent)
        self.repos = repos[:count]
        self.layout = layout
        self.count = min(count, len(repos))
        self.permission_mode = permission_mode
        self.model = model
        self.backend = backend
        self.local_model = local_model
        self.initial_prompt = initial_prompt
        self.use_worktree = use_worktree
        self.session_mode = session_mode

    def run(self):
        if self.count == 0:
            self.finished_err.emit("No repos selected")
            return

        uid = uuid.uuid4().hex[:8]
        titles = []

        # Launch each instance
        for i, repo in enumerate(self.repos):
            title = _make_title(repo.label, uid)
            titles.append(title)
            claude_cmd = "claude"
            if self.permission_mode == "bypassPermissions":
                claude_cmd += " --dangerously-skip-permissions"
            elif self.permission_mode != "default":
                claude_cmd += f" --permission-mode {self.permission_mode}"

            if self.backend == "local" and self.local_model:
                # Local ollama — model flag uses the ollama model name
                claude_cmd += f" --model {self.local_model}"
            elif self.model != "default":
                claude_cmd += f" --model {self.model}"

            if self.use_worktree:
                claude_cmd += " --worktree"

            if self.session_mode == "continue":
                claude_cmd += " --continue"
            elif self.session_mode == "named":
                claude_cmd += f" --name {repo.label}"

            if self.initial_prompt.strip():
                claude_cmd += f' "{escape_prompt(self.initial_prompt)}"'

            # Build the shell command — prepend env vars for local backend
            if self.backend == "local":
                shell_cmd = (
                    f"set ANTHROPIC_BASE_URL=http://localhost:11434"
                    f" && set ANTHROPIC_API_KEY=ollama"
                    f" && {claude_cmd}"
                )
            else:
                shell_cmd = claude_cmd

            cmd = build_wt_command(title, repo.path, shell_cmd)
            try:
                subprocess.Popen(cmd)
                backend_label = f" [local:{self.local_model}]" if self.backend == "local" else ""
                self.status.emit(f"Launched [{i+1}/{self.count}] {repo.label}{backend_label}")
            except Exception as e:
                self.finished_err.emit(f"Failed to launch {repo.label}: {e}")
                return
            time.sleep(0.8)

        # Wait for windows to render
        self.status.emit("Waiting for windows to appear...")
        time.sleep(2.5)

        # Find and tile windows
        work = get_work_area()
        positions = compute_layout(work, self.layout, self.count)

        hwnds = []
        for title in titles:
            found = find_windows_by_title(title)
            if found:
                hwnds.append(found[0])
            else:
                self.status.emit(f"Warning: could not find window '{title}'")

        if hwnds:
            tile_windows(hwnds, positions[:len(hwnds)])
            self.status.emit(f"Tiled {len(hwnds)} windows ({self.layout})")

        self.finished_ok.emit()
