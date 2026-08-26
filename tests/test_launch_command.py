"""Guards on the wt.exe command construction shared by every launch path."""

from src.core.process_launcher import (
    _SESSION_MARKERS, build_wt_command, escape_prompt,
)


def test_semicolons_are_escaped_for_wt():
    # wt.exe splits on ";" even inside quoted args and runs the tail as a
    # separate subcommand (0x80070002). This is the bug LaunchWorker shipped
    # with while the git panel's own spawner had already fixed it.
    cmd = build_wt_command("Claude-x", r"C:\repo", 'claude "do a; then b"')
    assert cmd[-1].endswith('claude "do a\\; then b"')
    assert ";" not in cmd[-1].replace("\\;", "")


def test_command_shape():
    cmd = build_wt_command("Claude-x", r"C:\repo", "claude")
    assert cmd[:3] == ["wt.exe", "--window", "new"]
    assert cmd[3:5] == ["--title", "Claude-x"]
    assert cmd[5:7] == ["-d", r"C:\repo"]
    assert cmd[7:9] == ["cmd.exe", "/k"]


def test_escape_prompt_flattens_newlines():
    # cmd.exe /k treats an embedded newline as a command terminator, which
    # would truncate the prompt mid-sentence.
    assert escape_prompt("line one\nline two\n\tindented") == \
        "line one line two indented"


def test_escape_prompt_escapes_quotes():
    assert escape_prompt('say "hi"') == 'say \\"hi\\"'


def test_escape_prompt_survives_round_trip_into_wt():
    prompt = 'Review; commit "everything"\nthen stop'
    cmd = build_wt_command("t", "c:\\r", f'claude "{escape_prompt(prompt)}"')
    assert cmd[-1].endswith(
        'claude "Review\\; commit \\"everything\\" then stop"'
    )


# --- Inherited-session scrubbing -------------------------------------------


def test_every_session_marker_is_cleared():
    """A launched instance must not inherit the parent session's identity.

    Without this, an app started from inside a Claude Code session passes
    CLAUDE_CODE_CHILD_SESSION down and every instance it opens silently stops
    saving its transcript.
    """
    cmd = build_wt_command("t", r"C:\repo", "claude")
    for marker in _SESSION_MARKERS:
        assert f"set {marker}=&&" in cmd[-1], marker


def test_scrub_runs_before_the_command():
    cmd = build_wt_command("t", r"C:\repo", "claude --model opus")
    for marker in _SESSION_MARKERS:
        assert cmd[-1].index(f"set {marker}=") < cmd[-1].index("claude")


def test_scrub_leaves_no_space_before_the_separator():
    """`set FOO= && x` defines FOO as a space; `set FOO=&& x` removes it."""
    cmd = build_wt_command("t", r"C:\repo", "claude")
    for marker in _SESSION_MARKERS:
        assert f"set {marker}= &&" not in cmd[-1], marker


def test_installation_level_vars_are_left_alone():
    """These describe the install, not a session — clearing them would break
    the child's ability to find its own executable."""
    cmd = build_wt_command("t", r"C:\repo", "claude")
    assert "set CLAUDE_CODE_EXECPATH=" not in cmd[-1]
    assert "set CLAUDE_CODE_ENTRYPOINT=" not in cmd[-1]


def test_scrub_does_not_disturb_an_existing_env_prefix():
    """The agent-teams gate is set the same way; both must survive together."""
    inner = 'set CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1&& claude "go"'
    cmd = build_wt_command("t", r"C:\repo", inner)
    assert cmd[-1].endswith(inner)
    assert "set CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1&&" in cmd[-1]
    assert "set CLAUDE_CODE_CHILD_SESSION=&&" in cmd[-1]
