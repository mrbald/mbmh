"""Tests for the markdown report renderer."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mbmh.backend.gitlab import GitLabBackend
from mbmh.config import ValidatorConfig
from mbmh.report import render_report
from mbmh.validator import validate


def _make_result(fixture_repo: Path, fixture_api_dir: Path, fixture_metadata: dict[str, Any]):
    backend = GitLabBackend.from_fixture_dir(fixture_api_dir, issues_project="acme/widgets")
    cfg = ValidatorConfig(
        repo_path=str(fixture_repo),
        release_branch=fixture_metadata["release_branch"],
        previous_branch=fixture_metadata["previous_branch"],
        milestone=fixture_metadata["milestone_name"],
        issues_project="acme/widgets",
    )
    return validate(cfg, backend)


def test_report_has_five_sections(
    fixture_repo: Path,
    fixture_api_dir: Path,
    fixture_metadata: dict[str, Any],
) -> None:
    result = _make_result(fixture_repo, fixture_api_dir, fixture_metadata)
    md = render_report(result, now=datetime(2026, 5, 25, tzinfo=UTC))
    # Header is the H1; the other four are H2.
    assert md.startswith("# Release scope report")
    for heading in ("## Errors", "## Scope tree", "## Reconciliation", "## Footer"):
        assert heading in md, f"missing section: {heading}"


def test_report_lists_every_error_category_present(
    fixture_repo: Path,
    fixture_api_dir: Path,
    fixture_metadata: dict[str, Any],
) -> None:
    result = _make_result(fixture_repo, fixture_api_dir, fixture_metadata)
    md = render_report(result, now=datetime(2026, 5, 25, tzinfo=UTC))
    for cat in ("unauthorized", "not-ready", "missing", "dropped", "orphan"):
        assert f"`{cat}`" in md, f"missing category in report: {cat}"


def test_report_footer_has_fixture_marker(
    fixture_repo: Path,
    fixture_api_dir: Path,
    fixture_metadata: dict[str, Any],
) -> None:
    result = _make_result(fixture_repo, fixture_api_dir, fixture_metadata)
    md = render_report(result, now=datetime(2026, 5, 25, tzinfo=UTC))
    assert "Data source: `fixture`" in md


def test_report_links_milestone_tickets(
    fixture_repo: Path,
    fixture_api_dir: Path,
    fixture_metadata: dict[str, Any],
) -> None:
    result = _make_result(fixture_repo, fixture_api_dir, fixture_metadata)
    md = render_report(result, now=datetime(2026, 5, 25, tzinfo=UTC))
    # Should contain a markdown link with the gitlab.example.com URL.
    assert re.search(
        r"\[acme/widgets#10\]\(https://gitlab\.example\.com/acme/widgets/issues/10\)",
        md,
    )


def test_report_is_idempotent_at_fixed_now(
    fixture_repo: Path,
    fixture_api_dir: Path,
    fixture_metadata: dict[str, Any],
) -> None:
    result1 = _make_result(fixture_repo, fixture_api_dir, fixture_metadata)
    result2 = _make_result(fixture_repo, fixture_api_dir, fixture_metadata)
    fixed = datetime(2026, 5, 25, tzinfo=UTC)
    a = render_report(result1, now=fixed)
    b = render_report(result2, now=fixed)
    assert a == b
