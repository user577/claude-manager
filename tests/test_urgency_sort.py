from src.core.repo_scanner import RepoStatus
from src.gui.git_status_panel import (
    URGENCY_TIERS, URGENCY_TOOLTIP, UNSCANNED_RANK, _urgency_rank,
)


def status(**kw) -> RepoStatus:
    kw.setdefault("path", "C:/repos/x")
    kw.setdefault("label", "x")
    return RepoStatus(**kw)


def rank(**kw) -> int:
    return _urgency_rank(status(**kw))


def test_full_ladder_is_strictly_ordered():
    ranks = [
        rank(error="Path not found"),
        rank(diverged=True),
        rank(behind=1, modified_count=1),
        rank(behind=1),
        rank(modified_count=1),
        rank(ahead=1),
        rank(untracked_count=1),
        rank(),  # clean
    ]
    assert ranks == sorted(ranks)
    assert len(set(ranks)) == len(ranks), "every tier must be distinct"
    assert ranks == list(range(len(URGENCY_TIERS)))


def test_errored_repo_outranks_clean():
    # The bug this replaced: error and clean both returned 6, so a repo with a
    # vanished path sorted alphabetically among the healthy ones.
    assert rank(error="Path not found") < rank()


def test_errored_repo_is_most_urgent():
    assert rank(error="boom") < rank(diverged=True)


def test_unscanned_sorts_below_every_scanned_tier():
    assert UNSCANNED_RANK == len(URGENCY_TIERS)
    assert UNSCANNED_RANK > rank()  # below clean
    assert UNSCANNED_RANK > rank(error="boom")


def test_behind_and_modified_outranks_plain_behind():
    assert rank(behind=1, modified_count=1) < rank(behind=1)


def test_first_match_wins_for_combined_states():
    # Modified is more urgent than ahead, so a repo that is both ranks modified.
    assert rank(ahead=3, modified_count=1) == rank(modified_count=1)
    # Error short-circuits everything, even a diverged repo.
    assert rank(error="boom", diverged=True) == rank(error="boom")


def test_error_wins_over_stale_counts():
    # _build_cards constructs errored statuses with all counts at their
    # defaults, but a scan that fails partway can leave counts populated.
    assert rank(error="boom", behind=5, modified_count=5) == 0


def test_tooltip_lists_every_tier_in_order():
    names = [name for name, _ in URGENCY_TIERS]
    assert names == [p.strip() for p in URGENCY_TOOLTIP.split("→")][:len(names)]
    assert URGENCY_TOOLTIP.endswith("unscanned")
