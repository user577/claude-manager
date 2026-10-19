"""Multi-account GitHub support via the `gh` CLI.

Wraps `gh auth status` (to list logged-in accounts) and `gh auth switch`
(to change the active one). All calls are local and fast, but guarded with
timeouts so a hung keyring never freezes the UI.

gh's active account is one global switch shared by every terminal and
Claude session, and agents flip it to push from the other account. So the
app doesn't rely on it: pin_process_identity() puts the selected
workspace's token in this process's GH_TOKEN, which every git/gh child
inherits (git's credential helper is `gh auth git-credential`, which
honours it), and launched sessions are handed the same identity.
"""
import os
import re
import subprocess

from src.core.logger import log

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# gh usernames are alphanumeric plus hyphens; anything else is never spliced
# into a launch command line.
_USERNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}$")

_pinned_user: str | None = None


def _keyring_env() -> dict:
    """Environment for gh's own account bookkeeping, without GH_TOKEN.

    With GH_TOKEN set, `gh auth status` reports the env token as the active
    account and `gh auth token` just echoes it back, so these calls must see
    the keyring alone.
    """
    env = os.environ.copy()
    env.pop("GH_TOKEN", None)
    env.pop("GITHUB_TOKEN", None)
    return env


def account_token(username: str) -> str | None:
    """The stored gh token for ``username``, or None if gh has none."""
    try:
        r = subprocess.run(
            ["gh", "auth", "token", "--user", username],
            capture_output=True, text=True, timeout=10,
            creationflags=_NO_WINDOW, env=_keyring_env(),
        )
    except Exception as e:
        log.warning("gh auth token failed for %s: %s", username, e)
        return None
    token = r.stdout.strip()
    return token if r.returncode == 0 and token else None


def pin_process_identity(username: str | None) -> bool:
    """Make ``username`` the GitHub identity of everything this app spawns.

    Returns False (and clears any previous pin) when there's no token for
    it, leaving children on gh's global active account.
    """
    global _pinned_user
    token = account_token(username) if username else None
    if token:
        os.environ["GH_TOKEN"] = token
        _pinned_user = username
        return True
    os.environ.pop("GH_TOKEN", None)
    _pinned_user = None
    return False


def pinned_identity() -> str | None:
    """The username pin_process_identity() last pinned, if any."""
    return _pinned_user


def is_valid_username(username: str) -> bool:
    return bool(_USERNAME_RE.match(username))

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
            creationflags=_NO_WINDOW, env=_keyring_env(),
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
            creationflags=_NO_WINDOW, env=_keyring_env(),
        )
    except FileNotFoundError:
        return False, "gh CLI not found"
    except Exception as e:
        return False, str(e)
    msg = (r.stdout + r.stderr).strip()
    return r.returncode == 0, msg
