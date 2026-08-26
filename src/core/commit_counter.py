"""Fetch today's GitHub contribution count for the active account.

Feeds the toolbar's daily commit meter. This mirrors the number GitHub shows
on your profile's contribution graph (the green squares) for *today*, read from
the contributions calendar via the ``gh`` CLI.

We query GitHub rather than counting local git because the two diverge badly:
local feature-branch work, unpushed commits, squash-merges, and stale
``origin`` remote-tracking refs all throw a local count off — sometimes by
100+ commits/day. GitHub's calendar is the source of truth the user actually
compares against.

``gh api graphql`` runs as the **active** ``gh`` account (the app keeps that in
sync with its own active account), so the count reflects that profile's graph.
Private-repo contributions are included only when the account's token carries
the ``read:user`` scope — without it GitHub returns just the public graph
(``gh auth refresh -h github.com -s read:user`` grants it).
"""

from __future__ import annotations

import datetime as _dt
import json
import re
import subprocess

from PySide6.QtCore import QThread, Signal

# subprocess.CREATE_NO_WINDOW is Windows-only; keep the app from flashing a
# console window when it shells out to gh.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Sentinels emitted by CommitCountWorker in place of a real count.
FETCH_FAILED = -1
SCOPE_MISSING = -2

# The scope GitHub requires before the contributions calendar includes private
# repositories. Without it the API still answers 200 — it just returns the
# public graph, which reads as a flat 0 for an all-private account.
CONTRIB_SCOPE = "read:user"

_ACTIVE_RE = re.compile(r"Active account:\s*true", re.IGNORECASE)
_SCOPES_RE = re.compile(r"Token scopes:\s*(.+)")

# The contributions calendar buckets days in the account's own timezone, so we
# ask for a small window around "now" and then pick the day whose date matches
# the local calendar date (with the latest returned day as a fallback).
_GRAPHQL = """
query($from: DateTime!, $to: DateTime!) {
  viewer {
    contributionsCollection(from: $from, to: $to) {
      contributionCalendar {
        weeks { contributionDays { date contributionCount } }
      }
    }
  }
}
"""


def active_token_scopes() -> set[str] | None:
    """Scopes carried by the active ``gh`` token, or None if unreadable."""
    try:
        r = subprocess.run(
            ["gh", "auth", "status"],
            capture_output=True, text=True, timeout=10,
            creationflags=_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    out = r.stdout + "\n" + r.stderr
    # gh prints one block per logged-in account; pick the active one.
    blocks = re.split(r"(?=Logged in to )", out)
    block = next((b for b in blocks if _ACTIVE_RE.search(b)), None)
    if block is None:
        return None
    m = _SCOPES_RE.search(block)
    if not m:
        return None
    return {s.strip().strip("'\"") for s in m.group(1).split(",") if s.strip()}


def missing_contribution_scope() -> bool:
    """True when the active token can only see the *public* contribution graph.

    An account whose repos are all private then reads a flat 0 every day, which
    looks like "no commits" rather than "can't see them". Returns False when the
    scopes can't be determined — better to show a count than to cry wolf.
    """
    scopes = active_token_scopes()
    if scopes is None:
        return False
    return CONTRIB_SCOPE not in scopes


def github_contributions_today() -> int | None:
    """Today's contribution count for the active ``gh`` account.

    Returns the integer count, or ``None`` on any failure (gh missing, not
    authenticated, network error, malformed response) so the caller can keep
    the last good reading rather than blanking the meter.
    """
    now = _dt.datetime.now(_dt.timezone.utc)
    frm = (now - _dt.timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    to = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        r = subprocess.run(
            ["gh", "api", "graphql",
             "-f", f"query={_GRAPHQL}",
             "-f", f"from={frm}",
             "-f", f"to={to}"],
            capture_output=True, text=True, timeout=20,
            creationflags=_NO_WINDOW,
        )
        if r.returncode != 0:
            return None
        data = json.loads(r.stdout)
        weeks = (data["data"]["viewer"]["contributionsCollection"]
                 ["contributionCalendar"]["weeks"])
        days = [d for w in weeks for d in w["contributionDays"]]
        if not days:
            return None
        today_iso = _dt.date.today().isoformat()
        for d in days:
            if d["date"] == today_iso:
                return int(d["contributionCount"])
        # No exact match (timezone edge, or GitHub hasn't opened today's bucket
        # yet) — fall back to the most recent day the calendar reports.
        return int(max(days, key=lambda d: d["date"])["contributionCount"])
    except (OSError, subprocess.SubprocessError, ValueError, KeyError,
            TypeError, json.JSONDecodeError):
        return None


class CommitCountWorker(QThread):
    """Fetches today's GitHub contribution count off the UI thread.

    Emits ``result`` with the count, ``FETCH_FAILED`` when the fetch fails (so
    the meter keeps its last good value instead of dropping to zero), or
    ``SCOPE_MISSING`` when the token can't see private contributions at all.
    """

    result = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        # Check the scope first: without it the query still succeeds and
        # returns 0, which would silently overwrite a good reading.
        if missing_contribution_scope():
            if not self._cancelled:
                self.result.emit(SCOPE_MISSING)
            return
        count = github_contributions_today()
        if self._cancelled:
            return
        self.result.emit(count if count is not None else FETCH_FAILED)
