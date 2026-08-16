from src.core.project_info import (
    describe, find_plans, first_paragraph, is_plan_file,
    sanitize_markdown, strip_inline_markdown,
)


def test_sanitize_markdown_removes_badges_and_screenshots():
    md = (
        "# Tool\n\n"
        "[![CI](https://img.shields.io/ci.svg)](https://ci.example)\n"
        "![screenshot](docs/shot.png)\n\n"
        "<img src=\"https://x/logo.png\" width=\"120\">\n\n"
        "Real prose survives.\n\n"
        "- \n- A real bullet\n"
    )
    out = sanitize_markdown(md)
    assert "img.shields.io" not in out
    assert "shot.png" not in out
    assert "<img" not in out
    assert "Real prose survives." in out
    assert "A real bullet" in out
    # The badge-only list item leaves no stray bullet behind.
    assert "\n- \n" not in out


def test_sanitize_markdown_keeps_plain_links():
    assert "https://example.com" in sanitize_markdown("See [docs](https://example.com).")


def test_strip_inline_markdown():
    assert strip_inline_markdown(
        "Parametric **climbing hold** generator for `blender`"
    ) == "Parametric climbing hold generator for blender"
    assert strip_inline_markdown(
        "Built on [FullControl](https://x.com/fc) and _fast_"
    ) == "Built on FullControl and fast"
    assert strip_inline_markdown("![badge](x.svg) A tool") == "A tool"
    # snake_case must survive the italic rule
    assert strip_inline_markdown("Runs geo_event_trader daily") == \
        "Runs geo_event_trader daily"


def test_is_plan_file_matches_real_conventions():
    for name in ("PLAN.md", "NEXT_STEPS.md", "ROADMAP.md", "TODO.md",
                 "NEXT.md", "CAM_NEXT_SESSION_PLAN.md",
                 "independent_rnd_sprint_plan.md", "PLAN-AI-SORT.md"):
        assert is_plan_file(name), name


def test_is_plan_file_rejects_non_plans():
    for name in ("README.md", "README_AI_OPTIMIZATION.md", "PROJECT.md",
                 "plan.py", "notes.md", "STATUS.md"):
        assert not is_plan_file(name), name


def test_first_paragraph_skips_headings_and_badges():
    text = (
        "# Claude Manager\n\n"
        "![build](https://img.shields.io/badge.svg)\n\n"
        "Launch, tile, and git-manage multiple Claude Code instances\n"
        "from a single Windows-native GUI.\n\n"
        "## What It Does\n\nSomething else entirely.\n"
    )
    assert first_paragraph(text) == (
        "Launch, tile, and git-manage multiple Claude Code instances "
        "from a single Windows-native GUI."
    )


def test_first_paragraph_stops_at_next_block():
    assert first_paragraph("Intro line.\n- a bullet\n") == "Intro line."


def test_first_paragraph_empty_for_headings_only():
    assert first_paragraph("# Title\n\n## Sub\n") == ""


def test_find_plans_covers_root_and_docs_newest_first(tmp_path):
    (tmp_path / "docs").mkdir()
    old = tmp_path / "PLAN.md"
    old.write_text("old plan", encoding="utf-8")
    new = tmp_path / "docs" / "ROADMAP.md"
    new.write_text("new plan", encoding="utf-8")
    (tmp_path / "README.md").write_text("not a plan", encoding="utf-8")

    import os
    os.utime(old, (1_000_000, 1_000_000))
    os.utime(new, (2_000_000, 2_000_000))

    plans = find_plans(str(tmp_path))
    assert [p.title for p in plans] == ["docs/ROADMAP.md", "PLAN.md"]


def test_describe_prefers_project_md_over_readme(tmp_path):
    (tmp_path / "README.md").write_text("# R\n\nFrom the readme.\n", encoding="utf-8")
    (tmp_path / "PROJECT.md").write_text("# P\n\nFrom project.\n", encoding="utf-8")
    desc, src, text, tsrc = describe(str(tmp_path))
    assert desc == "From project."
    assert src == "PROJECT.md"
    assert tsrc == "PROJECT.md"
    assert "From project." in text


def test_describe_falls_back_to_manifest(tmp_path):
    (tmp_path / "package.json").write_text(
        '{"name": "x", "description": "A packaged thing"}', encoding="utf-8")
    desc, src, _text, _tsrc = describe(str(tmp_path))
    assert desc == "A packaged thing"
    assert src == "package.json"


def test_describe_uses_manifest_when_readme_has_no_prose(tmp_path):
    (tmp_path / "README.md").write_text("# Only a heading\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\ndescription = "Toml described"\n', encoding="utf-8")
    desc, src, text, tsrc = describe(str(tmp_path))
    assert desc == "Toml described"
    assert src == "pyproject.toml"
    # The README still feeds the Overview pane even with no prose paragraph.
    assert tsrc == "README.md"
    assert "Only a heading" in text


def test_describe_empty_repo(tmp_path):
    assert describe(str(tmp_path)) == ("", "", "", "")
