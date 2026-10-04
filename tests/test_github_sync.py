from src.core.repo_scanner import collaborator_repos_cmd, parse_collaborator_repos


def test_collaborator_query_asks_for_shared_repos_only_and_pages():
    cmd = collaborator_repos_cmd()
    assert cmd[:3] == ["gh", "api", "--paginate"]
    assert "affiliation=collaborator" in cmd[3]


def test_parse_collaborator_repos_reads_one_object_per_line():
    out = (
        '{"name":"energy-monitor","url":"https://github.com/jovantperic/energy-monitor",'
        '"description":null,"isPrivate":false}\n'
        "\n"
        '{"name":"other","url":"https://github.com/x/other",'
        '"description":"d","isPrivate":true}\n'
    )
    repos = parse_collaborator_repos(out)
    assert [r["name"] for r in repos] == ["energy-monitor", "other"]
    assert repos[1]["isPrivate"] is True


def test_parse_collaborator_repos_empty_output():
    assert parse_collaborator_repos("") == []
