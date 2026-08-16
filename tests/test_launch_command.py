"""Guards on the wt.exe command construction shared by every launch path."""

from src.core.process_launcher import build_wt_command, escape_prompt


def test_semicolons_are_escaped_for_wt():
    # wt.exe splits on ";" even inside quoted args and runs the tail as a
    # separate subcommand (0x80070002). This is the bug LaunchWorker shipped
    # with while the git panel's own spawner had already fixed it.
    cmd = build_wt_command("Claude-x", r"C:\repo", 'claude "do a; then b"')
    assert cmd[-1] == 'claude "do a\\; then b"'
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
    assert cmd[-1] == 'claude "Review\\; commit \\"everything\\" then stop"'
