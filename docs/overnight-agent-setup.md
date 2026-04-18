# Setting Up Overnight Autonomous Agents

A reusable recipe for scheduling a remote Claude Code agent to work through
a project's TODO backlog overnight. Derived from the 2026-04-17 run on
`3dp-sales-site`.

## What this is

A **remote trigger** (scheduled via `RemoteTrigger` / `/schedule`) spins up an
isolated Claude Code session in Anthropic's cloud at a cron time. The session
clones a GitHub repo, executes tools autonomously (no permission prompts),
commits branches, and opens draft PRs back to the repo. When the session
ends, the sandbox is destroyed. Your local machine plays no role once the
trigger exists.

## Prerequisites (one-time per account)

- GitHub repo, pushed to `origin`.
- Anthropic GitHub app authorized for that repo (visit
  https://claude.ai/code/scheduled once — it'll prompt for access if needed).
- Claude Code installed locally for the setup conversation.

## Per-project setup (~30 min)

### 1. Write `TODO.md` with an Execution Guide

This is the single most important artifact. The overnight agent starts with
zero context from your setup conversation — whatever isn't in the repo at
trigger-fire time is invisible to it.

`TODO.md` must include, **before the task list**, an "Execution Guide"
section with:

- **Repo conventions** — match what's already in the codebase; don't
  invent. Package manager (pip? uv? poetry?), test runner, web framework,
  models library, settings pattern, DB migration style, HTML/frontend stack,
  auth pattern, logging, import style.
- **Default decisions** for ambiguous choices — pick one library or provider
  per category so the agent doesn't wheel-spin. Example:
  `Shipping API: EasyPost (simpler auth). PDF: reportlab (pure Python).
  Frontend JS: htmx + Alpine via CDN (no build step).`
- **Stubbing policy for missing credentials** — degrade with a `WARNING`
  log and a `# TODO(operator): set <VAR>` comment; never fake success;
  test the degraded path.
- **What NOT to touch** — production-critical code, existing enums,
  payment webhooks, pricing math, lifespan handlers.
- **Branch / PR policy** — one branch per task ID, draft PRs only, never
  merge to master, commit author identity from the sandbox (don't change
  global git config).
- **Orchestration strategy** — which tasks parallelize, which serialize,
  the dependency graph.
- **Tasks already done** — prevents re-implementation of shipped features.
- **Final deliverable** — require a `RUN_REPORT.md` summarizing what
  shipped, what's partial, what's blocked.

Tasks themselves should have explicit **acceptance criteria** per task,
not just a description. Vague tasks produce vague PRs.

### 2. Commit and push `TODO.md`

```bash
git add TODO.md && git commit -m "Add overnight roadmap" && git push
```

The remote agent clones `origin/master` at fire-time; only what's there
is visible.

### 3. Add a `/eval-overnight-run` slash command

Create `.claude/commands/eval-overnight-run.md` at the repo root. Commit
and push. Tomorrow, typing `/eval-overnight-run` in Claude Code will drive
the review. It should contain:

- Context (which trigger ran, model, fire time, expected artifacts).
- Orientation commands (`git fetch`, `gh pr list`, read `RUN_REPORT.md`).
- Triage order (foundational PRs first, then dependents).
- **Per-PR rubric**: scope, conventions, tests, violated rules, stubbing.
- **Verdict vocabulary**: MERGE / EDIT / CLOSE / REDO with rationale.
- Cross-cutting analysis (merge conflicts, schema ordering).
- Recommended merge sequence.
- House rules (don't merge yourself, run `pytest` before declaring
  mergeable, check for accidental secrets).

### 4. Enable branch protection on `master`

In GitHub repo settings → Branches → add rule for `master`:
- Require a pull request before merging.
- Dismiss stale reviews on new commits.
- Include administrators.

This is the **hard guardrail**. The agent's "never merge to master"
instruction is a soft rule — branch protection physically prevents a
rogue push.

### 5. Create the scheduled trigger

In Claude Code, invoke `/schedule`. Provide:

- **Repo URL** — `https://github.com/<user>/<repo>`.
- **Cron expression** — UTC. Minimum interval is 1 hour. For a "one-shot":
  pick a specific date like `0 10 17 4 *` (10:00 UTC on April 17), then
  disable the trigger after it fires so it doesn't recur next year.
- **Model** — `claude-opus-4-7` for heavy/complex work, `claude-sonnet-4-6`
  for lighter or cost-sensitive runs.
- **Allowed tools** — broad set: `Bash, Read, Write, Edit, Glob, Grep,
  Task, TodoWrite, WebSearch, WebFetch`. Add `NotebookEdit` if the project
  uses Jupyter.
- **Prompt** — see template below.

### 6. After the run: disable the trigger

Visit `https://claude.ai/code/scheduled/<trigger_id>` and toggle off.
Cron doesn't support year-aware one-shots; an annual fire on the same
date is the closest approximation. Disable once you've got what you
wanted.

## Trigger prompt template

The prompt must be self-contained — the scheduled agent has no memory of
your setup conversation. Adapt this:

```
You are running autonomously overnight in a sandboxed cloud environment
with a fresh clone of <REPO_URL>. Your job is to push through as much of
TODO.md as you can in the time you have. This is real work intended for
use, not a test.

## Orient yourself first (in parallel)

1. Read TODO.md — your spec. The Execution Guide section at the top is
   authoritative: conventions, defaults, stubbing policy, orchestration,
   what-NOT-to-touch, PR policy.
2. Read any historical planning docs (SHIP_PLAN.md, ROADMAP.md).
3. Map the existing code: list key dirs, read main entry points, models,
   database layer, config.
4. git log --oneline -10
5. Install deps and run the test baseline. Must pass before you touch
   anything. If it doesn't, fixing that is the first task.

## Execution strategy

- Fan out with the Task tool. Independent tasks → parallel subagents.
- One branch per task ID, starting from origin/master.
- Draft PR per branch. Never merge to master.
- Commit incrementally; every commit must have passing tests.
- Respect the dependency graph in the Execution Guide.
- Stubbing policy: degrade + warn when credentials are missing.
- Default decisions table: if you're about to ask a clarifying question
  about tooling, check the table first and proceed with the default.
- Do NOT touch: <list from Execution Guide>.
- PR body template: what shipped, what's stubbed, pytest output snippet,
  follow-up TODOs.

## Budget management

If a subagent is low on budget: commit WIP with `WIP:` prefix, push, note
in RUN_REPORT.md, move on. Do NOT block the whole run on one stuck task.
Partial is better than nothing; mark TODO items [~] with a reason.

If the TOP-level is low: finalize RUN_REPORT.md and TODO.md updates
FIRST, then stop. The report matters more than the last 10% of code.

## Final deliverables

1. RUN_REPORT.md at repo root: summary (branches, PRs, tests passing),
   per-phase status ([x]/[~]/[ ]/[-]), blockers and resolution, review
   order.
2. TODO.md updated — checkboxes reflect actual state.
3. Commit both to `chore/overnight-run-report` and open a draft PR.
4. Push all branches.

## Orchestration

You are the top-level orchestrator. Use Task for subagents. Track progress
with TodoWrite. Many small focused subagents > few giant ones. After each
subagent returns, verify its branch has green pytest and an open PR
before moving on.

Begin by reading TODO.md — especially the Execution Guide.
```

## Why two triggers beats two projects per trigger

It's tempting to combine two projects into one trigger to "save a slot."
Don't. Each trigger run has a fixed token budget. Splitting a run across
two codebases:

- **Dilutes the prompt** — each project needs its own conventions.
  Accidental crossover is likely.
- **Halves effective depth per project.**
- **Single point of failure** — if it gets stuck on project A, project B
  gets nothing.

Create a separate trigger at a different fire time. The documented limit
is the cron minimum interval (1 hour), not a per-day cap.

## Gotchas

- **No true one-shot cron** — pick a specific-date expression and disable
  the trigger after it fires.
- **TODO.md must be pushed** before fire-time. Local edits are invisible.
- **No permission gate** in the remote session. The agent runs whatever
  is in `allowed_tools` without prompts. Structural safety = sandbox
  isolation + branch protection + draft-PR-only policy.
- **Prompt is the product.** Vague prompts produce vague output.
  Acceptance criteria per task are a force-multiplier.
- **Subagents have their own budgets.** Tell the top-level orchestrator
  to commit WIP and keep going rather than block on a single stuck task.
- **Sandbox git identity** comes from the CCR environment. Don't instruct
  the agent to `git config --global` anything.
- **GitHub push auth** uses the Anthropic GitHub app; no tokens to manage
  manually.

## Signals of a good run

- Many small draft PRs, each with a green `pytest` snippet in the body.
- Branch names that match task IDs from `TODO.md`.
- A `RUN_REPORT.md` that honestly uses `[~]` and `[ ]` for partial or
  skipped work — not a wall of `[x]`.
- Zero commits on `master`.
- `TODO.md` updated with status flips matching what's in the PRs.

## Signals of a bad run

- Commits pushed directly to `master` — branch protection should prevent
  this; if they exist, the branch protection wasn't enabled.
- PRs that touch the "do not touch" list.
- PRs that refactor unrelated code (scope creep).
- Tests marked `@pytest.mark.skip` without explanation — skipped tests
  are not passing tests.
- `RUN_REPORT.md` missing or claiming 100% completion — usually means the
  agent ran out of time and didn't self-report honestly.

## Recovery if it goes wrong

- **Rogue branches**: `git push origin --delete <branch>` or close PRs
  on GitHub.
- **Accidentally merged to master**: `git revert <sha>` — don't force-push.
- **Trigger keeps firing**: disable at `https://claude.ai/code/scheduled/<id>`.
- **Secrets leaked in a commit**: rotate the secret immediately, then
  rewrite history only if truly necessary.

## Per-project checklist

Copy this for each new project:

- [ ] `TODO.md` written with Execution Guide at the top
- [ ] Execution Guide covers: conventions, defaults, stubbing, don't-touch, branching, orchestration, done-already
- [ ] Each task has explicit acceptance criteria
- [ ] `TODO.md` committed and pushed
- [ ] `.claude/commands/eval-overnight-run.md` added with per-PR rubric
- [ ] Branch protection enabled on `master`
- [ ] GitHub app authorized for the repo
- [ ] Trigger created via `/schedule` with self-contained prompt
- [ ] Fire time confirmed (UTC)
- [ ] Calendar reminder to disable the trigger after the run
