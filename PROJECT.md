# Claude Manager

Launch, tile, and git-manage multiple Claude Code instances from a single Windows-native GUI.

## What It Does

Claude Manager is a PySide6 desktop app for multi-project development workflows. It lets you launch up to 4 Claude Code instances in parallel, auto-tile them across your screen, monitor git status across all your repos, and perform batch git operations — all from one window.

## Features

- **Multi-instance launching** with automatic window tiling (2x2 grid, vertical, horizontal, single)
- **Git status dashboard** — dirty, ahead/behind, diverged, stash count for every repo
- **Batch git operations** — commit, push (ahead-only), fetch+pull (ff-only) with .pyc cleanup
- **Per-repo Claude launch** — click Launch on any repo card to open Claude scoped to that project
- **Preset system** — save/load named configurations (repos, layout, mode, model, backend)
- **Local LLM support** via Ollama (model pulling, testing, health monitoring)
- **Permission modes** — Default, Accept Edits, Auto, Bypass Permissions, Plan
- **Session management** — New, Continue last, Named (per-repo)
- **Tag-based filtering** — organize repos with custom tags, filter in both tabs
- **Single-instance enforcement** — Windows mutex prevents duplicate app windows
- **VS Code Dark+ theme** — conventional charcoal/blue color scheme

## Requirements

- Windows 10/11
- Python 3.10+
- [Git](https://git-scm.com/) on PATH
- [Windows Terminal](https://aka.ms/terminal) (`wt.exe`) on PATH
- [Claude CLI](https://docs.anthropic.com/en/docs/claude-code) (`claude`) on PATH
- Optional: [Ollama](https://ollama.com/) for local LLM backend

## Running from Source

```bash
uv sync
uv run python main.py
```

## Building the Installer

```bash
uv run python build_installer.py
```

This cleans all `.pyc` / `__pycache__`, runs PyInstaller, then compiles the Inno Setup installer. Output: `Output/ClaudeManager-Setup-1.0.0.exe` (~32 MB).

Requires [Inno Setup 6](https://jrsoftware.org/isinfo.php) installed. Use `--skip-inno` to build just the PyInstaller bundle without the installer.

## Installation

Run `ClaudeManager-Setup-1.0.0.exe`. Installs per-user to `%LOCALAPPDATA%\Programs\ClaudeManager\` — no admin required. Creates Start Menu and optional desktop shortcut.

## Architecture

```
claude-manager/
├── main.py                        # Dev entry point
├── src/
│   ├── app.py                     # Init, single-instance mutex, prerequisites check
│   ├── constants.py               # App name, paths, skip dirs
│   ├── config/
│   │   ├── settings.py            # RepoInfo, Settings (JSON persistence)
│   │   └── presets.py             # Preset, PresetManager (JSON persistence)
│   ├── core/
│   │   ├── logger.py              # Rotating file log (1MB, 2 backups)
│   │   ├── repo_scanner.py        # Git status scanning (QThread)
│   │   ├── git_operations.py      # Batch commit/push/pull, .pyc cleanup
│   │   ├── process_launcher.py    # Claude instance launch, Ollama integration
│   │   └── window_manager.py      # Window tiling via Win32 API (ctypes)
│   └── gui/
│       ├── main_window.py         # Tab container, toolbar, Ollama health dot
│       ├── launcher_panel.py      # Repo selection, controls, presets, launch
│       ├── git_status_panel.py    # Status cards, batch ops, per-repo launch
│       ├── settings_dialog.py     # Repo management, tag editor
│       ├── commit_confirm_dialog.py  # Diff preview before commit
│       ├── presets_panel.py       # Preset combo bar widget
│       ├── styles.py              # VS Code Dark+ stylesheet + status colors
│       └── widgets/
│           ├── log_output.py      # Timestamped colored log
│           └── repo_status_card.py  # Status dot + details + launch button
├── tests/                         # 24 tests (git ops, settings, window manager)
├── docs/
│   └── ollama-setup-guide.html    # Local LLM setup guide
├── claude_manager.spec            # PyInstaller config (auto-discovers src modules)
├── installer.iss                  # Inno Setup config
├── build_installer.py             # One-click build script
└── generate_icon.py               # Icon generator (2x2 terminal grid)
```

## Module Details

### Entry & Init (`src/app.py`)

- Acquires a Windows named mutex (`Global\ClaudeManager_SingleInstance`) — if already held, finds and focuses the existing window via `EnumWindows`, then exits
- Checks that `git`, `wt.exe`, and `claude` are on PATH before launching
- Sets up rotating file log at `%LOCALAPPDATA%/ClaudeManager/claude_manager.log`

### Settings (`src/config/settings.py`)

- **`RepoInfo`** — path, label, enabled, tags list. `exists()` checks for `.git` dir
- **`Settings`** — full app state as a dataclass. Loads/saves JSON at `%LOCALAPPDATA%/ClaudeManager/settings.json`
- `discover_repos()` scans the GitHub directory for git repos and registers them
- `get_all_tags()` collects unique tags across all repos for the filter bar

### Presets (`src/config/presets.py`)

- **`Preset`** — named snapshot of launch configuration (enabled repos, layout, mode, model, backend, session, prompt, worktree)
- **`PresetManager`** — CRUD for presets, persists to `%LOCALAPPDATA%/ClaudeManager/presets.json`

### Repo Scanner (`src/core/repo_scanner.py`)

- **`RepoStatus`** — branch, dirty flag, modified/untracked counts, ahead/behind, diverged, stash count, last commit
- **`scan_one()`** runs 5 git commands per repo: `branch --show-current`, `status --porcelain`, `rev-list --left-right --count`, `stash list`, `log -1`
- **`RepoScannerThread`** — scans all repos on a QThread, emits per-repo updates for live card refresh

### Git Operations (`src/core/git_operations.py`)

- `pyc_cleanup()` — recursively deletes `__pycache__` and `.pyc`, skipping `.venv`, `node_modules`, `vendor`, `.git`, `dist`, `build`
- `commit_repo()` — cleans .pyc, stages all (`git add -A`), commits
- `push_repo()` — standard `git push` (rejects non-fast-forward automatically)
- `pull_repo()` — `git pull --ff-only` (never creates merge commits)
- `fetch_and_pull_repo()` — `git fetch --all --prune` then `pull --ff-only`
- **`GitWorker`** — QThread that runs any operation across a list of repos sequentially, with cancel support

### Process Launcher (`src/core/process_launcher.py`)

- **Ollama integration**: `get_ollama_models()`, `get_ollama_status()`, health/test/pull workers
- **`LaunchWorker`** — launches Claude Code instances in Windows Terminal:
  - Builds command with flags: `--permission-mode`, `--model`, `--worktree`, `--continue`/`--name`, initial prompt
  - For local backend: prepends `ANTHROPIC_BASE_URL` and `ANTHROPIC_API_KEY` env vars
  - Each instance gets a unique window title (`Claude-{label}-{uid}`)
  - After launching, finds windows by title and tiles them using `window_manager`

### Window Manager (`src/core/window_manager.py`)

- Pure Win32 API via ctypes — no pywin32 dependency
- `get_work_area()` — primary monitor bounds excluding taskbar
- `compute_layout()` — calculates positions for grid_2x2, vertical, horizontal, single layouts
- `find_windows_by_title()` — `EnumWindows` callback matching title substring
- `tile_windows()` — `MoveWindow` + `SetForegroundWindow`

### GUI — Launch Tab (`src/gui/launcher_panel.py`)

- Repo checklist with search filter and tag pills
- All/None select buttons
- Controls: instance count (1-4), layout, permission mode, backend (cloud/local), model, session mode, initial prompt, worktree toggle
- Preset management bar (save/load/delete named configs)
- Launch button kicks off `LaunchWorker`, progress bar shows status

### GUI — Git Tab (`src/gui/git_status_panel.py`)

- Status cards for every repo with colored dot, branch, change summary, last commit hash
- **Launch button** on each card — opens Claude scoped to that repo with guardrail prompt
- Quick-select: Select Dirty, Select Ahead
- Batch commit with confirmation dialog (shows `git diff --stat` per repo)
- **Push Ahead** — only pushes repos strictly ahead of remote, skips diverged/behind
- **Fetch & Pull All** — safe sync (ff-only), never overwrites remote
- Cancel button for long-running operations
- Auto-rescans after every operation

### GUI — Settings Dialog (`src/gui/settings_dialog.py`)

- GitHub directory path selector
- Repo list with Add Folder / Remove / Auto-Discover
- Per-repo tag editor (comma-separated)

## Safety Guarantees

- **Pull is always `--ff-only`** — never creates merge commits, fails gracefully on diverged repos
- **Push is never forced** — standard `git push` rejects non-fast-forward
- **Push Ahead skips diverged repos** — only pushes repos that are strictly ahead with no remote changes
- **Commit shows diff preview** — confirmation dialog with `git diff --stat` before committing
- **Single instance** — mutex prevents accidentally running two managers

## Configuration Files

| File | Location | Purpose |
|------|----------|---------|
| `settings.json` | `%LOCALAPPDATA%/ClaudeManager/` | Repos, layout, mode, geometry |
| `presets.json` | `%LOCALAPPDATA%/ClaudeManager/` | Named launch configurations |
| `claude_manager.log` | `%LOCALAPPDATA%/ClaudeManager/` | Rolling log (1MB, 2 backups) |

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| Ctrl+L | Launch Claude instances |
| Ctrl+1 | Switch to Launch tab |
| Ctrl+2 | Switch to Git tab |
| Ctrl+R | Refresh git status |
| Ctrl+Enter | Commit all dirty repos |

## Tests

```bash
uv run pytest
```

24 tests covering git operations (.pyc cleanup, run_git wrapper), settings (save/load, discovery, dedup), and window manager (layout calculations, edge cases).

## Dependencies

- **PySide6** >= 6.6 — Qt GUI framework
- **PyInstaller** — bundling (dev only)
- **Inno Setup 6** — Windows installer (build only)

## Git History

| Commit | Description |
|--------|-------------|
| `ed5d6d5` | Initial commit — launch, tile, git-manage |
| `e511c31` | Permission mode selector |
| `8954d1a` | Harden reliability, UX polish |
| `2d88b74` | Search filter, diff preview, shortcuts, 22 tests |
| `a5cdfcd` | Model selection, initial prompt, worktree, session resume |
| `399bfa4` | Workspace presets — save, load, delete |
| `5d6fe53` | Stash count and divergence detection |
| `50d6ca8` | Repo tagging system with pill-shaped filters |
| `2747911` | Local Ollama backend toggle |
| `15729ae` | Ollama setup guide (HTML) |
| `400cd7e` | Ollama UX: background health, test button, pull from UI |
| `fd45e68` | Single-instance lock, per-repo Launch, safe push, suppress CMD flash |
| `39b1602` | VS Code Dark+ color scheme |
