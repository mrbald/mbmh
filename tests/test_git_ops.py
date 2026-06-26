"""Tests for the git-operations module against the fixture repo."""

from __future__ import annotations

from pathlib import Path

from mbmh.config import DEFAULT_TICKET_REGEX
from mbmh.git_ops import list_commits, patch_equivalence_set


def test_list_commits_walks_only_release_branch_commits(fixture_repo: Path) -> None:
    commits = list_commits(
        repo_path=fixture_repo,
        release_branch="release/1.4.0",
        ticket_regex=DEFAULT_TICKET_REGEX,
        default_project="acme/widgets",
    )
    subjects = [c.subject for c in commits]
    # Should NOT include the initial main commit; should include all six
    # release-branch commits.
    assert "chore: initial commit" not in subjects
    assert len(commits) == 6


def test_list_commits_ticket_refs_parsed(fixture_repo: Path) -> None:
    commits = list_commits(
        repo_path=fixture_repo,
        release_branch="release/1.4.0",
        ticket_regex=DEFAULT_TICKET_REGEX,
        default_project="acme/widgets",
    )
    by_subject = {c.subject: c for c in commits}
    assert by_subject["feat: implement widget 10 acme/widgets#10"].ticket_refs == (
        __import__("mbmh.models", fromlist=["TicketRef"]).TicketRef(
            project="acme/widgets", issue=10
        ),
    )
    orphan = by_subject["chore: stuff"]
    assert orphan.ticket_refs == ()


def test_patch_equivalence_back_port(fixture_repo: Path) -> None:
    current = list_commits(
        repo_path=fixture_repo,
        release_branch="release/1.4.0",
        ticket_regex=DEFAULT_TICKET_REGEX,
        default_project="acme/widgets",
    )
    previous = list_commits(
        repo_path=fixture_repo,
        release_branch="release/1.3.0",
        ticket_regex=DEFAULT_TICKET_REGEX,
        default_project="acme/widgets",
    )
    cur_cids, cur_pids = patch_equivalence_set(current)

    # On the prev branch, the back-ported ticket-13 commit must match
    # by patch-id (same diff) against the current branch.
    backport = next(c for c in previous if "widget 13" in c.subject)
    assert backport.patch_id is not None
    assert backport.patch_id in cur_pids

    # The dropped commit on prev has a unique diff — should NOT be in
    # current's patch_ids.
    dropped = next(c for c in previous if "hotfix dropped" in c.subject)
    assert dropped.patch_id is not None
    assert dropped.patch_id not in cur_pids
    _ = cur_cids
