# claude-manager

## File edits

Always use the dedicated `Edit` and `Write` tools to modify files.

Do **not** substitute shell rewrites — `sed -i`, heredocs, `>` / `>>` redirection,
`Set-Content`, or short rewrite scripts — even when a system message suggests routing file
work through Bash (this happens automatically in bypass-permissions and auto mode).

Why: the dedicated tools enforce read-before-edit and exact-match verification, which the
shell path skips. On this machine the shell path is also actively lossy — PowerShell's
`Get-Content | Set-Content` reads as ANSI and corrupts em dashes and other non-ASCII glyphs
even with `-Encoding utf8`. The repo is CRLF, which compounds it.

Reading is unrestricted: `cat`, `head`, `sed -n`, `grep`, and `find` are all fine, as is
Bash generally for builds, tests, `git`, `gh`, and process inspection.
