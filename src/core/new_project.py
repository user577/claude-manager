"""Create a blank repo under the active account's folder and let the Claude
session that opens in it choose the real name.

Why the two-step rename: the app starts Claude inside the new folder, and on
Windows a directory cannot be renamed while any process has it as its working
directory. Both the Claude process and its cmd.exe host sit there, so Claude
cannot rename its own repo. Instead it writes the chosen name to a marker
file; the git panel picks that up on the next Refresh and does the rename
once the window is closed.
"""

import os
import re
import subprocess
from datetime import datetime
from pathlib import Path

from src.config.settings import RepoInfo

PLACEHOLDER_PREFIX = "new-project-"

# Repo-root file holding the folder name Claude settled on. Excluded from
# the repo via .git/info/exclude at init so it never lands in a commit.
RENAME_MARKER = ".claude-manager-rename"

# Characters Windows refuses in a file name, plus path separators.
_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# Passed as the first user turn on a cmd.exe command line, so it must stay
# free of the characters cmd treats specially even inside quotes (see
# CMD_UNSAFE). The test suite enforces that.
NEW_PROJECT_PROMPT = (
    "This is a brand-new, empty git repository that claude-manager just "
    "created with the placeholder folder name {name}. {idea}Your job is to "
    "interview the user about what they want to build, then kick the "
    "project off. "
    "INTERVIEW: Before writing any file, interview the user in short rounds. "
    "Use the AskUserQuestion tool whenever a question has natural options "
    "(language, platform, scope tiers, repo visibility), listing your "
    "recommended option first; ask open-ended questions in plain text. Ask "
    "at most four questions per round and adapt each round to the previous "
    "answers. Cover: what it is and the problem it solves; who uses it and "
    "where it runs; the must-haves for a first usable version versus later "
    "ideas; language, framework and key dependencies (recommend a stack if "
    "they have no preference); constraints such as integrations, data, "
    "deadlines or budget; and whether to create a GitHub repo for it "
    "(private, public, or not yet). Skip anything already answered and stop "
    "as soon as you could write the plan; three rounds is usually plenty. "
    "Then show a short brief of what you heard and ask the user to confirm "
    "or correct it. "
    "KICKOFF, once the brief is confirmed: (1) Pick a short kebab-case "
    "folder name, or use the one they gave, and confirm it in one line. "
    "(2) Write that name, and nothing else, as the single line of a file "
    "called " + RENAME_MARKER + " in the repo root. It is already excluded "
    "via .git/info/exclude, so never stage or commit it. (3) Write README.md "
    "titled with the chosen name; PLAN.md recording the brief (goal, users, "
    "first-version scope, later ideas, stack, constraints, open questions) "
    "followed by a prioritized list of next concrete steps, each with enough "
    "context that a fresh session could pick it up; and the starter "
    "structure for the chosen stack, including a .gitignore. Keep the "
    "scaffold minimal: it should build or run, not implement features yet. "
    "(4) Make an initial commit. (5) Only if the user asked for a GitHub "
    "repo: run gh auth status, tell the user which account is active and "
    "confirm it is the right one, then run gh repo create with the chosen "
    "name and visibility, --source . and --push. Otherwise do not push. "
    "(6) Finish by telling the user that claude-manager renames the folder "
    "to the chosen name on the next Refresh, and that they must close this "
    "Claude window first because Windows locks a folder while a process "
    "runs inside it. Never rename or move the folder yourself, and never "
    "run git init again."
)

# cmd.exe acts on these even inside a quoted argument once a stray quote
# flips its quoting state, and expands %VAR% regardless of quotes.
CMD_UNSAFE = re.compile(r'["&|<>^%]')


def new_project_prompt(name: str, idea: str = "") -> str:
    """The kickoff prompt for placeholder folder ``name``.

    ``idea`` is the user's optional one-liner from the New Project dialog. It
    rides on the cmd.exe command line, so shell-significant characters are
    replaced with spaces (and "&" with "and") rather than escaped — cmd has
    no escaping that survives every quoting state.
    """
    idea = " ".join(idea.replace("&", " and ").split())
    idea = " ".join(CMD_UNSAFE.sub(" ", idea).split())
    seed = (f"The user's starting idea, in their words: {idea}. Use it to "
            "skip questions it already answers. ") if idea else ""
    return NEW_PROJECT_PROMPT.format(name=name, idea=seed)


def sanitize_name(raw: str) -> str | None:
    """Return a safe folder name, or None if ``raw`` can't be one.

    Rejects anything that would escape the account folder (separators,
    ``..``), Windows-illegal characters, and empty/whitespace-only input.
    Case and hyphens are left as written so the name matches what Claude
    told the user.
    """
    name = raw.strip().strip(".")
    if not name or _BAD_CHARS.search(name):
        return None
    if name in {".", ".."}:
        return None
    return name


def create_blank_repo(folder: str) -> str:
    """Make ``<folder>/new-project-<stamp>``, ``git init`` it, and return the path.

    The marker is added to ``.git/info/exclude`` right away so the Claude
    session can write it without it ever showing up in ``git status``.
    """
    root = Path(folder)
    if not root.is_dir():
        raise FileNotFoundError(f"Account folder not found: {folder}")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = root / f"{PLACEHOLDER_PREFIX}{stamp}"
    n = 1
    while target.exists():
        n += 1
        target = root / f"{PLACEHOLDER_PREFIX}{stamp}-{n}"
    target.mkdir()

    proc = subprocess.run(
        ["git", "init"], cwd=str(target),
        capture_output=True, text=True, timeout=30,
        # The frozen GUI has no console; without this git flashes one.
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git init failed: {proc.stderr.strip()}")

    info = target / ".git" / "info"
    info.mkdir(parents=True, exist_ok=True)
    with (info / "exclude").open("a", encoding="utf-8") as fh:
        fh.write(f"\n/{RENAME_MARKER}\n")
    return str(target)


def pending_rename(repo_path: str) -> str | None:
    """The sanitized name from the repo's marker file, or None if absent."""
    marker = Path(repo_path) / RENAME_MARKER
    if not marker.is_file():
        return None
    try:
        first = marker.read_text(encoding="utf-8").strip().splitlines()
    except OSError:
        return None
    return sanitize_name(first[0]) if first else None


def apply_pending_renames(
    repos: list[RepoInfo],
) -> tuple[list[tuple[str, str]], list[str]]:
    """Rename every repo that has a marker file, updating its RepoInfo in place.

    Returns ``(renamed, problems)``: ``renamed`` is ``(old_path, new_path)``
    pairs; ``problems`` are human-readable reasons a rename was skipped. A
    locked folder (the Claude window is still open) is reported, not raised,
    so a Refresh never fails because of it.
    """
    renamed: list[tuple[str, str]] = []
    problems: list[str] = []
    for repo in repos:
        marker = Path(repo.path) / RENAME_MARKER
        if not marker.is_file():
            continue
        name = pending_rename(repo.path)
        if name is None:
            problems.append(
                f"{repo.label}: rename marker holds an invalid folder name"
            )
            continue
        old = Path(repo.path)
        new = old.parent / name
        if os.path.normcase(str(new)) == os.path.normcase(str(old)):
            # Already called that; nothing to do but clear the marker.
            try:
                marker.unlink()
            except OSError:
                pass
            continue
        if new.exists():
            problems.append(
                f"{repo.label}: can't rename to {name}, that folder already exists"
            )
            continue
        try:
            old.rename(new)
        except PermissionError:
            problems.append(
                f"{repo.label}: folder is in use, close its Claude window and "
                f"Refresh again to rename it to {name}"
            )
            continue
        except OSError as e:
            problems.append(f"{repo.label}: rename failed ({e})")
            continue
        try:
            (new / RENAME_MARKER).unlink()
        except OSError:
            pass
        repo.path = str(new)
        repo.label = name
        renamed.append((str(old), str(new)))
    return renamed, problems
