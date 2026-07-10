"""Agent Heavy mode — a graded ladder of Claude Code subagents plus a sizing
policy, used to launch an auto-scaling multi-agent session against a repo.

The ladder spans Haiku -> Sonnet -> Opus so the orchestrator can size each
task and delegate to the cheapest tier that fits, escalating only when needed.
Subagents run in isolated contexts and return summaries, so exploration/tool
noise never bloats the orchestrator's window.

The ladder is materialized as markdown subagent files under the app's config
dir (not the user's repos), and loaded into a launched session via
`claude --add-dir <ladder root>` — Claude Code scans `.claude/agents/` inside
any added directory. Session-scoped effect, zero writes to the target repo.

This materializes real named subagents with pinned models + effort, so the
model routing per tier is enforced rather than merely suggested in a prompt.
"""

from pathlib import Path

from src.constants import CONFIG_DIR


# Root passed to `claude --add-dir`; the agents live in its .claude/agents/.
LADDER_ROOT = CONFIG_DIR / "agent-ladder"
_AGENTS_DIR = LADDER_ROOT / ".claude" / "agents"


# Each entry: (filename, markdown content with YAML frontmatter).
_AGENTS: list[tuple[str, str]] = [
    ("scout.md", """\
---
name: scout
description: Locates files, symbols, and call sites. Use for any "where is X",
  broad search, or codebase-orientation question before acting. Read-only.
tools: Glob, Grep, Read
model: haiku
effort: low
---

You locate code. Return file:line references plus a one-line note for each hit.
Do not review, refactor, edit, or explain broadly. Be terse — the orchestrator
only needs pointers, not prose.
"""),
    ("runner.md", """\
---
name: runner
description: Runs tests, linters, builds, and git status, then reports the
  outcome. Use to verify or gather command output without flooding main context.
tools: Bash, Read, Glob, Grep
model: haiku
effort: low
---

You run commands and report results. Lead with the verdict (PASS / FAIL), then
include only the lines that matter (failing tests, error messages). Never fix
anything — diagnosing and reporting is your whole job.
"""),
    ("implementer.md", """\
---
name: implementer
description: Implements a single well-scoped change in one area of the codebase.
  Use for routine coding tasks that have clear acceptance criteria.
model: sonnet
effort: medium
---

You implement one scoped change. Match the surrounding code's conventions and
idioms. Run the relevant tests before returning. Summarize what changed in two
or three lines — do not paste large diffs back to the orchestrator.
"""),
    ("deep-worker.md", """\
---
name: deep-worker
description: Handles hard sub-tasks needing cross-file reasoning, tricky
  debugging, architecture decisions, or correctness-critical work. Use ONLY
  when a task genuinely exceeds implementer's scope — this is the expensive tier.
model: opus
effort: high
---

You take the hard problems. Think through cross-cutting implications before
acting. State your assumptions explicitly. Verify your work end-to-end (run it,
test it) rather than assuming it is correct. Return a clear summary of what you
did and any residual risk.
"""),
]


# Appended to the launch prompt so the orchestrator knows the ladder exists and
# how to size work against it. Kept free of double quotes to stay shell-safe.
SIZING_POLICY = (
    "You are running in Agent Heavy mode: an auto-scaling multi-agent setup. "
    "Four subagents are available (via the Agent tool) and you should size every "
    "non-trivial task and delegate to the cheapest tier that fits, escalating "
    "only when a cheaper tier returns uncertainty or fails:\n"
    "- scout (Haiku): find files, symbols, call sites; any search or orientation.\n"
    "- runner (Haiku): run tests, lint, build, git status; report pass/fail.\n"
    "- implementer (Sonnet): one scoped change with clear acceptance criteria.\n"
    "- deep-worker (Opus): cross-file reasoning, hard debugging, architecture, "
    "correctness-critical work. Reserve it for genuinely hard sub-tasks.\n"
    "Fan out independent subtasks in parallel. For a single sequential edit you "
    "can already see, just do it directly rather than delegating. Keep your own "
    "context lean by letting subagents absorb search and tool-output noise."
)


def ensure_ladder() -> Path:
    """Write (or refresh) the ladder subagent files and return the root path
    to pass to `claude --add-dir`. Idempotent — safe to call on every launch."""
    _AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    for filename, content in _AGENTS:
        (_AGENTS_DIR / filename).write_text(content, encoding="utf-8")
    return LADDER_ROOT
