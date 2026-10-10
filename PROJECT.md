# Claude Manager

Launch, tile, and git-manage multiple Claude Code instances from a single Windows-native GUI.

## What It Does

Claude Manager is a PySide6 desktop app for multi-project development workflows. It monitors git status across all your repos, performs batch git operations, launches Claude Code scoped to any project, and gives you a browsable view of what each project is and what's planned next — all from one window.

Two tabs: **Git** (status, batch operations, launching) and **Projects** (descriptions, plans, history).

## Features

- **Git status dashboard** — dirty, ahead/behind, diverged, stash count for every repo
- **One read-only Refresh** — rescans every repo, fetches remotes, and checks GitHub for uncloned repos; changes nothing
- **Batch git operations** — commit, Pull (ff-only), Push (ahead-only), Clone, each labelled with how many repos it would touch; the counts follow the ticked repos, or cover all repos when none are ticked
- **Per-repo Claude launch** — Launch, Launch Auto, Agent Heavy (subagent ladder), and Agent Team on every repo card
- **Remote-sync gate on every launch** — each launch (card buttons, Launch Tiled, Auto Commit, Generate Plan) fetches first; if a repo is behind or diverged, a prompt offers Pull & Launch (ff-only), Launch Anyway, or Cancel
- **New Project interview** — the New Project button creates a blank repo and opens Claude there to interview you (AskUserQuestion rounds: goal, users, first-version scope, stack, constraints, GitHub repo), confirm a brief, then name it, write README.md + PLAN.md, scaffold, and commit; optionally `gh repo create`. The folder takes its chosen name on the next Refresh after the window closes
- **Tiled multi-launch** — tick any set of repos and open them all at once, auto-tiled (2x2 grid, vertical, horizontal, single)
- **Auto Commit** — spawn a Sonnet instance per dirty repo to review changes and commit autonomously
- **Projects tab** — browse every repo's auto-derived description, its PLAN/NEXT/ROADMAP/TODO docs, and its commit history
- **Live usage meters** — 5-hour / 7-day limit windows plus a daily commit counter in the toolbar
- **Multi-account** — switch GitHub accounts (via `gh`), each with its own repo folder plus a `· shared` workspace for repos shared with you
- **Tag-based filtering** — organize repos with custom tags, filter in both tabs
- **Single-instance enforcement** — Windows mutex prevents duplicate app windows
- **VS Code Dark+ theme** — conventional charcoal/blue color scheme

A local-LLM (Ollama) backend exists in `src/core/process_launcher.py` with no UI attached. It is retained for reuse on machines that run local models, and carries a documented defect — see the comment at the top of the Ollama section before wiring a front end onto it.

## Requirements

- Windows 10/11
- Python 3.10+
- [Git](https://git-scm.com/) on PATH
- [Windows Terminal](https://aka.ms/terminal) (`wt.exe`) on PATH
- [Claude CLI](https://docs.anthropic.com/en/docs/claude-code) (`claude`) on PATH
- [GitHub CLI](https://cli.github.com/) (`gh`), signed in — accounts, Clone, commit counter
- Optional: [Ollama](https://ollama.com/) for local LLM backend

## Running from Source

```bash
uv sync
uv run python main.py
```

## Building the Installer

```bash
uv sync --python 3.12 --python-preference only-managed
uv run python build_installer.py
```

Build under a uv-managed Python. The spec refuses to freeze unless the OpenSSL DLLs come
from the building interpreter; a system Python can trip that check and stop the build.

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
│   │   └── settings.py            # RepoInfo, GitHubAccount, Settings (JSON)
│   ├── core/
│   │   ├── logger.py              # Rotating file log (1MB, 2 backups)
│   │   ├── repo_scanner.py        # Git status scanning (QThread)
│   │   ├── git_operations.py      # Batch commit/push/pull, .pyc cleanup
│   │   ├── project_info.py        # Descriptions, plan docs, commit history
│   │   ├── agent_ladder.py        # Haiku->Sonnet->Opus->Fable subagent defs
│   │   ├── commit_counter.py      # Daily commits (GitHub contribution graph)
│   │   ├── new_project.py         # Blank repo, interview prompt, deferred rename
│   │   ├── usage_tracker.py       # Live 5h/7d usage limits
│   │   ├── github_accounts.py     # gh CLI account listing / switching
│   │   ├── process_launcher.py    # Claude launch, wt.exe argv, Ollama framework
│   │   └── window_manager.py      # Window tiling via Win32 API (ctypes)
│   └── gui/
│       ├── main_window.py         # Tab container, toolbar, meters, Ollama dot
│       ├── git_status_panel.py    # Status cards, batch ops, launches, tiling
│       ├── project_panel.py       # Projects tab: description / plans / history
│       ├── settings_dialog.py     # Repo management, tag editor
│       ├── commit_confirm_dialog.py  # Diff preview before commit
│       ├── styles.py              # VS Code Dark+ stylesheet + status colors
│       └── widgets/
│           ├── log_output.py      # Timestamped colored log
│           ├── usage_meter.py     # Toolbar usage + commit meters
│           └── repo_status_card.py  # Checkbox, dot, details, launch buttons
├── tests/                         # 157 tests
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
- **`GitHubAccount`** — a gh username paired with the one folder that defines its workspace, plus that folder's repos
- **`Settings`** — full app state as a dataclass. Loads/saves JSON at `%LOCALAPPDATA%/ClaudeManager/settings.json`
- `discover_repos()` scans the GitHub directory for git repos and registers them
- `get_all_tags()` collects unique tags across all repos for the filter bar

**Folder scoping** — an account's folder is the single source of truth for what it
shows. `prune_foreign_repos()` drops anything outside it, `sync_repos()` prunes,
discovers, and drops entries whose folder is gone, and `prune_all_accounts()` scopes
every account (run on `load()`, so an old config is cleaned once and saved). This is
what keeps personal and work repos on separate drives from bleeding into each other on
an account switch.

**Renames made outside the app.** Each `RepoInfo` remembers its root commit (`root`)
while its folder exists. When a folder disappears and exactly one newly discovered
folder has the same root, `sync_repos()` moves the entry to the new path and keeps its
tags, instead of dropping it and rediscovering a fresh one. This covers a folder
renamed in Explorer or by a Claude session. Two clones of one history are ambiguous,
so in that case the old entry is just dropped. A New Project placeholder that never
got a commit has no root and is simply dropped.

Two deliberate exceptions, both to avoid destroying a repo list by accident: an
account with **no folder set** is never pruned, and neither is one whose folder is
**currently unreachable** — an unplugged drive or offline sync root must not be read
as "none of these repos belong here".

### Project Info (`src/core/project_info.py`)

- **`describe()`** — one-line description from PROJECT.md / README.md prose, falling back to `package.json` / `pyproject.toml`, then CLAUDE.md
- **`find_plans()`** — discovers PLAN/NEXT/ROADMAP/TODO-style docs in the repo root and `docs/`, newest-modified first
- **`sanitize_markdown()`** — strips images and raw HTML (outside code fences) so image-heavy READMEs render cleanly offline
- **`ProjectLoadThread`** / **`DescriptionScanThread`** — per-repo detail and bulk description scans, both off the UI thread

### Repo Scanner (`src/core/repo_scanner.py`)

- **`RepoStatus`** — branch, dirty flag, modified/untracked counts, ahead/behind, diverged, stash count, last commit
- **`scan_one()`** runs 5 git commands per repo: `branch --show-current`, `status --porcelain`, `rev-list --left-right --count`, `stash list`, `log -1`
- **`RepoScannerThread`** — scans all repos on a QThread, emits per-repo updates for live card refresh
- **`verify_remote_sync()`** / **`SyncCheckThread`** / **`classify_sync()`** — the pre-launch remote check: a ~1.5s TCP probe of the remote host (once per host per batch) so offline fails fast, then fetch (failures surface as `error`, not a silent "in sync"), rescan, and sort into behind / diverged / unchecked

### Git Operations (`src/core/git_operations.py`)

- `pyc_cleanup()` — recursively deletes `__pycache__` and `.pyc`, skipping `.venv`, `node_modules`, `vendor`, `.git`, `dist`, `build`
- `commit_repo()` — cleans .pyc, stages all (`git add -A`), commits
- `push_repo()` — standard `git push` (rejects non-fast-forward automatically)
- `pull_repo()` — `git pull --ff-only` (never creates merge commits)
- `fetch_and_pull_repo()` — `git fetch --all --prune` then `pull --ff-only`
- **`GitWorker`** — QThread that runs any operation across a list of repos sequentially, with cancel support

### Process Launcher (`src/core/process_launcher.py`)

- **`build_wt_command()`** — the single place `wt.exe` argv is built. Escapes `;` as `\;`, because wt splits on semicolons even inside quoted arguments and runs the tail as a subcommand (0x80070002). Every launch path goes through it
- **Inherited-session scrub** — `build_wt_command()` prefixes `set CLAUDE_CODE_CHILD_SESSION=&& …` to clear the parent's session markers (`CHILD_SESSION`, `SESSION_ID`, `MESSAGING_SOCKET`, `MESSAGING_TOKEN`). If the app is started from inside a Claude Code session it inherits those, and every instance it launches then believes it is a continuation of that session — silently skipping transcript saving and pointing at another session's IPC pipe. Cleared *inside the shell*, not via `Popen(env=...)`, because wt.exe may hand the tab to an existing terminal broker that drops the passed environment. `EXECPATH`/`ENTRYPOINT` are left alone: they describe the install, not a session
- **`escape_prompt()`** — flattens newlines and escapes quotes for a `cmd.exe /k` argument
- **`LaunchWorker`** — launches Claude Code instances in Windows Terminal:
  - Builds command with flags: `--permission-mode`, `--model`, `--worktree`, `--continue`/`--name`, initial prompt
  - Each instance gets a unique window title (`Claude-{label}-{uid}`)
  - After launching, finds windows by title and tiles them using `window_manager`
- **Ollama framework** (no UI): `get_ollama_models()`, `get_ollama_status()`, health/test/pull workers, and `LaunchWorker`'s `backend="local"` branch. Retained for reuse elsewhere — see the KNOWN DEFECT comment in the file; the local launch path does not currently work

### Window Manager (`src/core/window_manager.py`)

- Pure Win32 API via ctypes — no pywin32 dependency
- `get_work_area()` — primary monitor bounds excluding taskbar
- `compute_layout()` — calculates positions for grid_2x2, vertical, horizontal, single layouts
- `find_windows_by_title()` — `EnumWindows` callback matching title substring
- `tile_windows()` — `MoveWindow` + `SetForegroundWindow`

### GUI — Git Tab (`src/gui/git_status_panel.py`)

- Status cards for every repo with a select checkbox, colored dot, branch, change summary, last commit hash
- **Per-card launches** — Launch, Launch Auto, Agent Heavy, Agent Team, each scoped to that repo with a guardrail prompt
- **Quick-select** — Select Dirty / Ahead / Behind tick the matching cards; Clear unticks everything; Out of Sync filters to ahead, behind, diverged or dirty repos
- **Sort** — Name, Recently Modified (last commit or uncommitted change, whichever is newer), or Status (urgent first: error → diverged → behind+modified → behind → modified → ahead → untracked → clean → unscanned)
- **Refresh** — the one read-only sync action: rescan, fetch remotes so ahead/behind is current, and check GitHub for repos not cloned here
- **Pull (n) / Push (n) / Clone (n)** — the counts are what each button would act on right now: the ticked repos if any are ticked, otherwise all. They stay disabled mid-scan so a half-updated count can't drive an action
  - **Pull** — fetch and fast-forward repos that are behind; diverged repos are skipped
  - **Push** — push repos that are strictly ahead; diverged repos are skipped
  - **Clone** — clone the account's repos (or, in a `· shared` workspace, repos shared with you) that aren't in the folder yet
- **Launch Tiled** — opens Claude in every ticked repo and tiles the windows (layout + model persist to settings)
- **Auto Commit** — one Sonnet instance per dirty repo, reviews and commits autonomously
- Batch commit with confirmation dialog (shows `git diff --stat` per repo)
- Cancel button for long-running operations
- Auto-rescans after every operation

### GUI — Projects Tab (`src/gui/project_panel.py`)

- Repo list with each project's auto-derived description and a plan-doc count badge; filters on name *and* description
- **Overview** — README / PROJECT prose rendered as markdown
- **What's Next** — picker over the repo's PLAN/NEXT/ROADMAP/TODO docs, newest first
- **History** — recent commits as a sha / subject / age table
- **Generate Plan** — opens Claude in plan mode to write or refresh the plan doc
- List and scan are built lazily on first open to keep startup fast

### GUI — Settings Dialog (`src/gui/settings_dialog.py`)

- One folder row per GitHub account
- Repo list for the active account, with Add Folder / Remove / Auto-Discover
- Add Folder refuses a repo outside the active account's folder — it would only be pruned again on the next scan
- Per-repo tag editor (comma-separated)
- Daily commit goal

### Commit Counter (`src/core/commit_counter.py`)

Reads *today* from the active account's GitHub contribution graph via `gh api graphql`,
rather than counting local git — unpushed work, feature branches, squash-merges and
stale remote-tracking refs make a local count diverge from the graph by 100+/day.

**`read:user` is required.** Without it the API still answers 200 but returns only the
*public* graph, so an account whose repos are all private reads a flat `0` every day.
`missing_contribution_scope()` detects this and the meter shows an amber `!` with the
fix (`gh auth refresh -h github.com -s read:user`) instead of a misleading zero.

## Safety Guarantees

- **Pull is always `--ff-only`** — never creates merge commits, fails gracefully on diverged repos
- **Push is never forced** — standard `git push` rejects non-fast-forward
- **Push skips diverged repos** — only pushes repos that are strictly ahead with no remote changes
- **Refresh changes nothing** — it scans and fetches only; every write is its own button
- **Commit shows diff preview** — confirmation dialog with `git diff --stat` before committing
- **Single instance** — mutex prevents accidentally running two managers

## Configuration Files

| File | Location | Purpose |
|------|----------|---------|
| `settings.json` | `%LOCALAPPDATA%/ClaudeManager/` | Repos, layout, mode, geometry |
| `claude_manager.log` | `%LOCALAPPDATA%/ClaudeManager/` | Rolling log (1MB, 2 backups) |

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| Ctrl+L | Launch selected repos tiled |
| Ctrl+1 | Switch to Git tab |
| Ctrl+2 | Switch to Projects tab |
| Ctrl+R | Refresh (rescan, fetch, check GitHub) |
| Ctrl+Enter | Commit all dirty repos |

## Tests

```bash
uv run pytest
```

157 tests covering settings (save/load, discovery, dedup, per-account folder scoping, missing-folder cleanup and rename following), project info (description sources, fallbacks), launch commands (wt.exe argv, semicolon escaping, session-marker scrub), git operations (.pyc cleanup, run_git wrapper), window manager (layout calculations, edge cases), urgency and recent-activity sorts, card selection, the sync controls (Pull/Push/Clone targeting and counts, the single Refresh), GitHub clone discovery, ahead/behind inference for branches pushed without an upstream, commit-counter scope detection, and the pre-launch sync gate (classification, prompt text, remote-URL parsing, the offline fast path, and a real-git fetch → pull → launch run), and new-project kickoff (cmd-safe prompt, folder naming, deferred rename, the button end to end).

## Dependencies

- **PySide6** >= 6.6 — Qt GUI framework
- **PyInstaller** — bundling (dev only)
- **Inno Setup 6** — Windows installer (build only)

## Git History

Milestones only; `git log` has the full history.

| Commit | Description |
|--------|-------------|
| `2f18deb` | Initial commit — launch, tile, git-manage |
| `ac11e91` | Search filter, diff preview, shortcuts, first tests |
| `a8b3e7e` | Stash count and divergence detection |
| `fac2d5d` | Repo tagging with pill-shaped filters |
| `5202dd8` | Single-instance lock, per-repo Launch, safe push |
| `9a29fc0` | VS Code Dark+ color scheme |
| `ffde672` | GitHub sync and clone missing repos |
| `c4b5c3b` | Status sort by urgency |
| `71c9005` | Per-account GitHub folders |
| `26e557f` | Live 5h / 7d usage meters |
| `177138b` | Commit meter fed from the GitHub contribution graph |
| `8f66fc5` | Agent Heavy rework and Agent Team mode |
| `5989884` | Projects tab replaces the Launch tab |
| `47206d6` | Per-account repo scoping, contribution-scope warning, session scrub |
| `084df04` | Remote-sync check before every launch |
| `d4c2e5e` | New Project interview and kickoff |
| `6ec0913` | Shared-with-me workspace per account |
| `c4504e2` | Ahead/behind for branches pushed without an upstream |
| `b0827a2` | Refresh, Fetch and Check GitHub folded into one Refresh |

## License

[MIT](LICENSE)
