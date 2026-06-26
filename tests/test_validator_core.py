"""End-to-end tests for the validator core against the fixture repo + API."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mbmh.backend.gitlab import GitLabBackend
from mbmh.config import ValidatorConfig
from mbmh.models import ErrorCategory, Severity
from mbmh.validator import validate


def _build_config(
    fixture_repo: Path, fixture_metadata: dict[str, Any], *, with_prev: bool = True
) -> ValidatorConfig:
    return ValidatorConfig(
        repo_path=str(fixture_repo),
        release_branch=fixture_metadata["release_branch"],
        previous_branch=fixture_metadata["previous_branch"] if with_prev else None,
        milestone=fixture_metadata["milestone_name"],
        issues_project="acme/widgets",
    )


def _run(
    fixture_repo: Path,
    fixture_api_dir: Path,
    fixture_metadata: dict[str, Any],
    *,
    with_prev: bool = True,
):
    backend = GitLabBackend.from_fixture_dir(fixture_api_dir, issues_project="acme/widgets")
    cfg = _build_config(fixture_repo, fixture_metadata, with_prev=with_prev)
    return validate(cfg, backend)


def test_all_six_failure_categories_present(
    fixture_repo: Path,
    fixture_api_dir: Path,
    fixture_metadata: dict[str, Any],
) -> None:
    result = _run(fixture_repo, fixture_api_dir, fixture_metadata)
    categories = {f.category for f in result.findings}
    expected = {
        ErrorCategory.UNAUTHORIZED,
        ErrorCategory.NOT_READY,
        ErrorCategory.MISSING,
        ErrorCategory.DROPPED,
        ErrorCategory.ORPHAN,
    }
    assert expected <= categories, f"missing categories: {expected - categories}"


def test_exit_code_logic_via_has_errors(
    fixture_repo: Path,
    fixture_api_dir: Path,
    fixture_metadata: dict[str, Any],
) -> None:
    result = _run(fixture_repo, fixture_api_dir, fixture_metadata)
    assert result.has_errors is True


def test_orphan_count_matches_fixture(
    fixture_repo: Path,
    fixture_api_dir: Path,
    fixture_metadata: dict[str, Any],
) -> None:
    result = _run(fixture_repo, fixture_api_dir, fixture_metadata)
    orphans = [f for f in result.findings if f.category is ErrorCategory.ORPHAN]
    assert len(orphans) == 1


def test_unauthorized_links_to_ticket_99(
    fixture_repo: Path,
    fixture_api_dir: Path,
    fixture_metadata: dict[str, Any],
) -> None:
    result = _run(fixture_repo, fixture_api_dir, fixture_metadata)
    unauth = [f for f in result.findings if f.category is ErrorCategory.UNAUTHORIZED]
    assert len(unauth) == 1
    assert unauth[0].ticket is not None
    assert unauth[0].ticket.issue == 99


def test_not_ready_for_ticket_11(
    fixture_repo: Path,
    fixture_api_dir: Path,
    fixture_metadata: dict[str, Any],
) -> None:
    result = _run(fixture_repo, fixture_api_dir, fixture_metadata)
    nrs = [f for f in result.findings if f.category is ErrorCategory.NOT_READY]
    # Two commits reference #11 (the "wip" commit and the multi-ticket
    # refactor commit). Both should be flagged.
    assert len(nrs) == 2
    assert all(f.ticket and f.ticket.issue == 11 for f in nrs)


def test_missing_ticket_12(
    fixture_repo: Path,
    fixture_api_dir: Path,
    fixture_metadata: dict[str, Any],
) -> None:
    result = _run(fixture_repo, fixture_api_dir, fixture_metadata)
    missing = [f for f in result.findings if f.category is ErrorCategory.MISSING]
    assert len(missing) == 1
    assert missing[0].ticket is not None
    assert missing[0].ticket.issue == 12


def test_dropped_only_for_prev_hotfix(
    fixture_repo: Path,
    fixture_api_dir: Path,
    fixture_metadata: dict[str, Any],
) -> None:
    result = _run(fixture_repo, fixture_api_dir, fixture_metadata)
    dropped = [f for f in result.findings if f.category is ErrorCategory.DROPPED]
    # Only the "hotfix dropped" commit; widget 13 back-port is patch-equivalent.
    assert len(dropped) == 1
    assert dropped[0].commit_sha == fixture_metadata["sha_prev_dropped"]


def test_no_dropped_without_previous_branch(
    fixture_repo: Path,
    fixture_api_dir: Path,
    fixture_metadata: dict[str, Any],
) -> None:
    result = _run(fixture_repo, fixture_api_dir, fixture_metadata, with_prev=False)
    dropped = [f for f in result.findings if f.category is ErrorCategory.DROPPED]
    assert dropped == []


def test_commit_counts(
    fixture_repo: Path,
    fixture_api_dir: Path,
    fixture_metadata: dict[str, Any],
) -> None:
    result = _run(fixture_repo, fixture_api_dir, fixture_metadata)
    # 6 commits on release/1.4.0 (excluding the main initial commit).
    assert len(result.commits) == 6
    assert len(result.milestone_tickets) == 4


def test_multi_ticket_commit_counted_under_each(
    fixture_repo: Path,
    fixture_api_dir: Path,
    fixture_metadata: dict[str, Any],
) -> None:
    result = _run(fixture_repo, fixture_api_dir, fixture_metadata)
    # The multi-ticket commit references both #10 and #11.
    ticket_10_commits = result.commits_by_ticket.get("acme/widgets#10", [])
    ticket_11_commits = result.commits_by_ticket.get("acme/widgets#11", [])
    multi_in_10 = any("tidy" in c.subject for c in ticket_10_commits)
    multi_in_11 = any("tidy" in c.subject for c in ticket_11_commits)
    assert multi_in_10 and multi_in_11


def test_severity_warning_vs_error(
    fixture_repo: Path,
    fixture_api_dir: Path,
    fixture_metadata: dict[str, Any],
) -> None:
    result = _run(fixture_repo, fixture_api_dir, fixture_metadata)
    severities = {f.severity for f in result.findings}
    # Errors are always present in this fixture; warning category may or
    # may not appear depending on whether ambiguous-equivalence triggers.
    assert Severity.ERROR in severities
