"""Multi-account GitHub support via the `gh` CLI.

Wraps `gh auth status` (to list logged-in accounts) and `gh auth switch`
(to change the active one). All calls are local and fast, but guarded with
timeouts so a hung keyring never freezes the UI.
"""
import re
import subprocess

from src.core.logger import log

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Matches: "✓ Logged in to github.com account user577 (keyring)"
_ACCOUNT_RE = re.compile(r"Logged in to \S+ account (\S+)")
_ACTIVE_RE = re.compile(r"Active account:\s*true", re.IGNORECASE)


def list_accounts() -> tuple[list[str], str | None]:
    """Return (usernames, active_username) parsed from `gh auth status`.

    Returns ([], None) when gh is missing or no account is logged in.
    """
    try:
        r = subprocess.run(
            ["gh", "auth", "status"],
            capture_output=True, text=True, timeout=10,
            creationflags=_NO_WINDOW,
        )
    except FileNotFoundError:
        log.warning("gh CLI not found; account switcher disabled")
        return [], None
    except Exception as e:
        log.warning("gh auth status failed: %s", e)
        return [], None

    # gh writes the status table to stderr in some versions, stdout in others.
    out = r.stdout + "\n" + r.stderr
    accounts: list[str] = []
    active: str | None = None
    current: str | None = None
    for line in out.splitlines():
        m = _ACCOUNT_RE.search(line)
        if m:
            current = m.group(1)
            if current not in accounts:
                accounts.append(current)
            continue
        if current and _ACTIVE_RE.search(line):
            active = current

    if active is None and accounts:
        active = accounts[0]
    return accounts, active


def switch_account(username: str) -> tuple[bool, str]:
    """Switch the active gh account. Returns (success, message)."""
    try:
        r = subprocess.run(
            ["gh", "auth", "switch", "--user", username],
            capture_output=True, text=True, timeout=15,
            creationflags=_NO_WINDOW,
        )
    except FileNotFoundError:
        return False, "gh CLI not found"
    except Exception as e:
        return False, str(e)
    msg = (r.stdout + r.stderr).strip()
    return r.returncode == 0, msg
