"""Scope detection for the toolbar commit meter.

Without ``read:user`` the contributions API still answers 200 — it just omits
private repositories. For an all-private account that reads as a flat 0 every
day, which looks like "you committed nothing" rather than "I can't see it".
These cover the parsing that tells the two apart.
"""
from types import SimpleNamespace
from unittest.mock import patch

from src.core.commit_counter import (
    CONTRIB_SCOPE, active_token_scopes, missing_contribution_scope,
)

# Two accounts logged in, the active one lacking read:user — the real shape of
# `gh auth status` output for the case this guards against.
_TWO_ACCOUNTS = """github.com
  ✓ Logged in to github.com account user577 (keyring)
  - Active account: true
  - Git operations protocol: https
  - Token: gho_************************************
  - Token scopes: 'gist', 'read:org', 'repo'

  ✓ Logged in to github.com account work-account (keyring)
  - Active account: false
  - Git operations protocol: https
  - Token: gho_************************************
  - Token scopes: 'gist', 'read:org', 'repo', 'read:user', 'workflow'
"""


def _gh(stdout: str = "", stderr: str = "", returncode: int = 0):
    """Patch subprocess.run inside commit_counter with a canned gh result."""
    return patch(
        "src.core.commit_counter.subprocess.run",
        return_value=SimpleNamespace(
            stdout=stdout, stderr=stderr, returncode=returncode
        ),
    )


def test_reads_scopes_from_the_active_account_only():
    with _gh(stdout=_TWO_ACCOUNTS):
        assert active_token_scopes() == {"gist", "read:org", "repo"}


def test_flags_the_active_account_missing_read_user():
    with _gh(stdout=_TWO_ACCOUNTS):
        assert missing_contribution_scope() is True


def test_does_not_flag_when_the_active_account_has_the_scope():
    # Same output with the active flag on the account that *does* have it.
    swapped = _TWO_ACCOUNTS.replace(
        "- Active account: true", "- Active account: TEMP"
    ).replace(
        "- Active account: false", "- Active account: true"
    ).replace("- Active account: TEMP", "- Active account: false")
    with _gh(stdout=swapped):
        scopes = active_token_scopes()
        assert CONTRIB_SCOPE in scopes
        assert missing_contribution_scope() is False


def test_reads_status_from_stderr_too():
    """gh writes the status table to stderr in some versions."""
    with _gh(stderr=_TWO_ACCOUNTS):
        assert active_token_scopes() == {"gist", "read:org", "repo"}


def test_unknown_scopes_do_not_cry_wolf():
    """gh missing, or output we can't parse — show the count, not a warning."""
    with patch("src.core.commit_counter.subprocess.run",
               side_effect=FileNotFoundError):
        assert active_token_scopes() is None
        assert missing_contribution_scope() is False

    with _gh(stdout="not logged in to any hosts"):
        assert active_token_scopes() is None
        assert missing_contribution_scope() is False
