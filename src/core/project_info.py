"""Read the human-facing story of a repo: what it is, what's planned, what happened.

The git panel answers "is this repo dirty?". This answers "what is this repo?" —
pulled from the files the repos already carry (README/PROJECT prose, the
PLAN/NEXT/ROADMAP/TODO docs that get generated per project) plus git log.

Everything here is plain functions over a path so it can be tested without a
QApplication; the QThread wrapper at the bottom is the only Qt dependency.
"""

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

# Filenames whose *stem* marks a doc as a forward-looking plan. Matched
# case-insensitively against the whole stem or a hyphen/underscore-delimited
# word inside it, so both NEXT_STEPS.md and CAM_NEXT_SESSION_PLAN.md qualify
# while README_AI_OPTIMIZATION.md does not.
PLAN_WORDS = ("next", "plan", "plans", "roadmap", "todo", "steps", "sprint")

# Where plan docs live in practice across the repo collection: the root and a
# docs/ folder. Deeper recursion would drag in vendored/node_modules noise for
# no real gain.
PLAN_DIRS = ("", "docs")

# Files consulted for the one-line description, best source first.
DESCRIPTION_FILES = ("PROJECT.md", "README.md", "readme.md", "Readme.md")

MAX_COMMITS = 60

# Skipped when hunting for the description paragraph: badge images, HTML
# wrappers, blockquote callouts, and list items are decoration, not prose.
_SKIP_PREFIXES = ("#", ">", "!", "<", "-", "*", "+", "|", "=", "```", "[!")


@dataclass
class Commit:
    sha: str
    author: str
    when: str  # relative, e.g. "3 days ago"
    subject: str


@dataclass
class PlanDoc:
    """A forward-looking doc (PLAN/NEXT/ROADMAP/TODO) found in the repo."""
    path: str
    title: str  # display name, e.g. "docs/ROADMAP.md"
    body: str = ""
    mtime: float = 0.0


@dataclass
class ProjectInfo:
    path: str
    label: str
    branch: str = ""
    description: str = ""
    description_source: str = ""  # which file the description came from
    readme: str = ""              # full README/PROJECT text for the Overview pane
    readme_source: str = ""
    plans: list[PlanDoc] = field(default_factory=list)
    commits: list[Commit] = field(default_factory=list)
    error: str = ""


def _read_text(p: Path, limit: int = 400_000) -> str:
    """Read a text file defensively — encoding, size, and permissions all vary."""
    try:
        if p.stat().st_size > limit:
            return p.read_text(encoding="utf-8", errors="replace")[:limit] + \
                "\n\n… (truncated)"
        return p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def is_plan_file(name: str) -> bool:
    """True if `name` looks like a generated plan/next-steps doc."""
    if not name.lower().endswith((".md", ".txt")):
        return False
    stem = Path(name).stem.lower()
    if stem.startswith("readme"):
        return False
    words = re.split(r"[-_. ]+", stem)
    return any(w in PLAN_WORDS for w in words)


def find_plans(repo_path: str) -> list[PlanDoc]:
    """Discover plan docs in the repo root and docs/, newest first.

    Sorted by mtime rather than name because the useful one is almost always
    the most recently regenerated, not the alphabetically first.
    """
    root = Path(repo_path)
    found: list[PlanDoc] = []
    for sub in PLAN_DIRS:
        d = root / sub if sub else root
        try:
            if not d.is_dir():
                continue
            entries = sorted(d.iterdir())
        except Exception:
            continue
        for f in entries:
            if not f.is_file() or not is_plan_file(f.name):
                continue
            try:
                mtime = f.stat().st_mtime
            except Exception:
                mtime = 0.0
            title = f"{sub}/{f.name}" if sub else f.name
            found.append(PlanDoc(path=str(f), title=title, mtime=mtime))
    found.sort(key=lambda p: p.mtime, reverse=True)
    return found


_FENCE_RE = re.compile(r"(^```.*?^```|^~~~.*?^~~~)", re.DOTALL | re.MULTILINE)


def _sanitize_prose(md: str) -> str:
    """Strip images and raw HTML from one non-code segment of markdown."""
    md = re.sub(r"<!--.*?-->", "", md, flags=re.DOTALL)
    md = re.sub(r"<picture\b.*?</picture>", "", md, flags=re.DOTALL | re.IGNORECASE)
    # A linked image ("[![badge](img)](href)") must go before bare images, or
    # the leftover empty link renders as a stray bullet.
    md = re.sub(r"\[!\[[^\]]*\]\([^)]*\)\]\([^)]*\)", "", md)
    md = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", md)
    # Remaining raw HTML tags: keep the text between them, drop the markup.
    # Qt's markdown parser ignores most of it but still reserves vertical space
    # for the blocks, which reads as a large blank gap at the top of the pane.
    md = re.sub(r"<[^>\n]{1,200}>", "", md)
    # Drop list items and lines left empty by the removals above.
    md = re.sub(r"^[ \t]*[-*+][ \t]*$", "", md, flags=re.MULTILINE)
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md


def sanitize_markdown(md: str) -> str:
    """Make a repo's markdown safe and legible in the doc pane.

    READMEs lead with badge rows, screenshots hosted remotely, and HTML layout
    wrappers. The doc view deliberately refuses network fetches, so images
    would paint as broken icons, and the HTML blocks render as blank space.
    Fenced code blocks are passed through untouched — HTML inside them is
    content, not markup.
    """
    parts = _FENCE_RE.split(md)
    # split() with one capture group alternates: prose, fence, prose, fence…
    out = [p if _FENCE_RE.fullmatch(p) else _sanitize_prose(p)
           for p in parts]
    return "".join(out).strip()


def strip_inline_markdown(text: str) -> str:
    """Flatten a prose line to plain text for the one-line description.

    The description is shown in a QLabel, which renders no markdown, so
    leaving the source markers in turns "a **fast** slicer" into literal
    asterisks. Links keep their label and drop the target.
    """
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)      # images
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)  # links → label
    text = re.sub(r"`+([^`]*)`+", r"\1", text)            # inline code
    text = re.sub(r"(\*\*|__)(.+?)\1", r"\2", text)       # bold
    text = re.sub(r"(?<!\w)([*_])(?!\s)(.+?)(?<!\s)\1(?!\w)", r"\2", text)  # italic
    text = text.replace("<br>", " ").replace("<br/>", " ")
    return " ".join(text.split()).strip()


def first_paragraph(text: str) -> str:
    """First real prose paragraph of a markdown doc, collapsed to one line.

    Headings, badges, HTML, and lists are skipped so the result is the sentence
    a human would give if asked "what is this project?".
    """
    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            if lines:
                break
            continue
        if line.startswith(_SKIP_PREFIXES):
            if lines:
                break  # prose ended and a new block started
            continue
        lines.append(line)
    return strip_inline_markdown(" ".join(lines))


def _manifest_description(root: Path) -> tuple[str, str]:
    """Fall back to a package manifest's description field."""
    pkg = root / "package.json"
    if pkg.is_file():
        try:
            desc = json.loads(pkg.read_text(encoding="utf-8")).get("description")
            if desc:
                return str(desc).strip(), "package.json"
        except Exception:
            pass
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        m = re.search(
            r'^\s*description\s*=\s*["\'](.+?)["\']\s*$',
            _read_text(pyproject), re.MULTILINE,
        )
        if m:
            return m.group(1).strip(), "pyproject.toml"
    return "", ""


def describe(repo_path: str) -> tuple[str, str, str, str]:
    """Return (description, description_source, readme_text, readme_source)."""
    root = Path(repo_path)
    for name in DESCRIPTION_FILES:
        f = root / name
        if not f.is_file():
            continue
        text = _read_text(f)
        if not text.strip():
            continue
        desc = first_paragraph(text)
        if desc:
            return desc, name, text, name
        # A doc with no prose paragraph still belongs in the Overview pane;
        # keep looking for a description elsewhere.
        fallback_desc, fallback_src = _manifest_description(root)
        return fallback_desc, fallback_src, text, name

    desc, src = _manifest_description(root)

    # Last resort: CLAUDE.md. It's instructions rather than a description, but
    # in repos with no README at all its opening paragraph is usually still a
    # plain statement of what the project is — better than a blank row.
    claude_md = root / "CLAUDE.md"
    if claude_md.is_file():
        text = _read_text(claude_md)
        if text.strip():
            return desc or first_paragraph(text), src or "CLAUDE.md", text, "CLAUDE.md"

    return desc, src, "", ""


def read_commits(repo_path: str, limit: int = MAX_COMMITS) -> list[Commit]:
    try:
        r = subprocess.run(
            ["git", "-C", repo_path, "log", f"-{limit}",
             "--format=%h%x1f%an%x1f%ar%x1f%s"],
            capture_output=True, text=True, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if r.returncode != 0:
            return []
        commits = []
        for line in r.stdout.splitlines():
            parts = line.split("\x1f")
            if len(parts) == 4:
                commits.append(Commit(*parts))
        return commits
    except Exception:
        return []


def _branch(repo_path: str) -> str:
    try:
        r = subprocess.run(
            ["git", "-C", repo_path, "branch", "--show-current"],
            capture_output=True, text=True, timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return r.stdout.strip() or "HEAD"
    except Exception:
        return ""


def load_project(repo_path: str, label: str) -> ProjectInfo:
    """Gather everything the Projects tab shows for one repo. Blocking."""
    info = ProjectInfo(path=repo_path, label=label)
    if not Path(repo_path).is_dir():
        info.error = "Path not found"
        return info
    try:
        info.branch = _branch(repo_path)
        (info.description, info.description_source,
         info.readme, info.readme_source) = describe(repo_path)
        info.plans = find_plans(repo_path)
        for plan in info.plans:
            plan.body = _read_text(Path(plan.path))
        info.commits = read_commits(repo_path)
    except Exception as e:
        info.error = str(e)
    return info


# --- Qt wrapper -------------------------------------------------------------

from PySide6.QtCore import QThread, Signal  # noqa: E402


class ProjectLoadThread(QThread):
    """Loads one repo's project info off the UI thread.

    Disk reads over 100+ repos on OneDrive-backed paths are slow enough to
    stutter the UI, and plan docs can be large, so even a single repo's load
    goes through here.
    """
    loaded = Signal(object)  # ProjectInfo

    def __init__(self, repo_path: str, label: str, parent=None):
        super().__init__(parent)
        self.repo_path = repo_path
        self.label = label

    def run(self):
        self.loaded.emit(load_project(self.repo_path, self.label))


class DescriptionScanThread(QThread):
    """Bulk-loads just the one-line descriptions for the repo list.

    Separate from ProjectLoadThread because the list only needs the subtitle —
    reading every repo's plan docs and git log up front would be wasteful.
    """
    described = Signal(str, str, int)  # path, description, plan_count
    scan_complete = Signal()

    def __init__(self, repos, parent=None):
        super().__init__(parent)
        # (path, label) tuples, snapshotted so settings can mutate underneath.
        self.repos = [(r.path, r.label) for r in repos]
        self._stop = False

    def cancel(self):
        self._stop = True

    def run(self):
        for path, _label in self.repos:
            if self._stop:
                return
            if not Path(path).is_dir():
                self.described.emit(path, "", 0)
                continue
            try:
                desc, _src, _text, _tsrc = describe(path)
                plan_count = len(find_plans(path))
            except Exception:
                desc, plan_count = "", 0
            self.described.emit(path, desc, plan_count)
        self.scan_complete.emit()
