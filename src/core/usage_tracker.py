"""Live Claude Code usage/limit tracker.

Reads the OAuth token that Claude Code stores locally and queries the same
authenticated endpoint the in-session ``/usage`` meter uses. Returns the
rolling 5-hour session window and 7-day weekly window utilisation.

This is the real limit data (not a local consumption estimate). The token is
refreshed by Claude Code itself; we only read it, so as long as ``claude`` has
authenticated on this machine the call succeeds. An expired token surfaces as
an auth error rather than a crash.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QThread, Signal

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
OAUTH_BETA = "oauth-2025-04-20"
CREDENTIALS_PATH = Path.home() / ".claude" / ".credentials.json"


@dataclass
class Window:
    """A single rolling limit window."""

    percent: float          # 0-100 utilisation
    resets_at: datetime | None
    severity: str = "normal"  # normal | warning | critical


@dataclass
class UsageData:
    ok: bool
    five_hour: Window | None = None
    seven_day: Window | None = None
    error: str = ""


def _read_token() -> str | None:
    try:
        with open(CREDENTIALS_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
        return data.get("claudeAiOauth", {}).get("accessToken")
    except (OSError, json.JSONDecodeError, KeyError):
        return None


def _parse_ts(value) -> datetime | None:
    if not value:
        return None
    try:
        # API returns e.g. "2026-07-09T08:20:00.482241+00:00"
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def _window(block: dict) -> Window | None:
    if not isinstance(block, dict):
        return None
    pct = block.get("utilization")
    if pct is None:
        return None
    return Window(
        percent=float(pct),
        resets_at=_parse_ts(block.get("resets_at")),
    )


def _severity_for(percent: float) -> str:
    if percent >= 90:
        return "critical"
    if percent >= 75:
        return "warning"
    return "normal"


def fetch_usage(timeout: float = 15.0) -> UsageData:
    """Blocking fetch. Run off the UI thread via :class:`UsageWorker`."""
    token = _read_token()
    if not token:
        return UsageData(ok=False, error="Not authenticated (run `claude`)")

    req = urllib.request.Request(
        USAGE_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "anthropic-beta": OAUTH_BETA,
            "Content-Type": "application/json",
            "User-Agent": "claude-manager-usage",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.load(resp)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return UsageData(ok=False, error="Auth expired (run `claude`)")
        return UsageData(ok=False, error=f"HTTP {e.code}")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return UsageData(ok=False, error="Offline")
    except json.JSONDecodeError:
        return UsageData(ok=False, error="Bad response")

    five = _window(payload.get("five_hour"))
    seven = _window(payload.get("seven_day"))

    # Prefer server-supplied severity from the richer `limits` array when present.
    for lim in payload.get("limits") or []:
        grp = lim.get("group")
        sev = lim.get("severity")
        if grp == "session" and five and sev:
            five.severity = sev
        elif grp == "weekly" and lim.get("kind") == "weekly_all" and seven and sev:
            seven.severity = sev

    if five and five.severity == "normal":
        five.severity = _severity_for(five.percent)
    if seven and seven.severity == "normal":
        seven.severity = _severity_for(seven.percent)

    if five is None and seven is None:
        return UsageData(ok=False, error="No usage data")
    return UsageData(ok=True, five_hour=five, seven_day=seven)


def humanize_reset_short(resets_at: datetime | None) -> str:
    """Return just the remaining time — '4h 12m', '2d 3h', '45m', 'now', ''."""
    if resets_at is None:
        return ""
    secs = int((resets_at - datetime.now(timezone.utc)).total_seconds())
    if secs <= 0:
        return "now"
    days, rem = divmod(secs, 86400)
    hours, rem = divmod(rem, 3600)
    mins = rem // 60
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {mins}m"
    return f"{mins}m"


def humanize_reset(resets_at: datetime | None) -> str:
    """Return a short 'resets in 4h 12m' style string."""
    short = humanize_reset_short(resets_at)
    if not short:
        return ""
    return "resets now" if short == "now" else f"resets in {short}"


class UsageWorker(QThread):
    """Fetches usage off the UI thread and emits the result."""

    result = Signal(object)  # UsageData

    def run(self):
        self.result.emit(fetch_usage())
