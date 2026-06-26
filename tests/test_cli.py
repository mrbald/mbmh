"""Smoke tests for the Typer CLI."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from mbmh.cli import app


def test_cli_help_exits_zero() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    # Help is rich-formatted; just check it ran cleanly.
    assert result.stdout, "expected non-empty help output"


def test_cli_run_with_fixture_dir_exits_nonzero_on_findings(
    fixture_repo: Path,
    fixture_api_dir: Path,
    fixture_metadata: dict[str, Any],
    tmp_path: Path,
) -> None:
    runner = CliRunner()
    out = tmp_path / "report.md"
    result = runner.invoke(
        app,
        [
            "--repo",
            str(fixture_repo),
            "--release-branch",
            fixture_metadata["release_branch"],
            "--milestone",
            fixture_metadata["milestone_name"],
            "--issues-project",
            "acme/widgets",
            "--previous-branch",
            fixture_metadata["previous_branch"],
            "--fixture-dir",
            str(fixture_api_dir),
            "--output",
            str(out),
        ],
    )
    # exit code 1 means findings present.
    assert result.exit_code == 1
    text = out.read_text()
    assert "# Release scope report" in text
    assert "`unauthorized`" in text


def test_cli_missing_token_and_no_fixture_dir_errors_out(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "--repo",
            str(tmp_path),
            "--release-branch",
            "release/x",
            "--milestone",
            "X",
            "--issues-project",
            "p",
        ],
        env={"GITLAB_API_TOKEN": ""},
    )
    assert result.exit_code == 2
    assert "GITLAB_API_TOKEN" in result.stderr or "GITLAB_API_TOKEN" in result.stdout
