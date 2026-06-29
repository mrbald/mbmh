"""CLI entrypoint.

Pyright is asked to relax `reportUnknownMemberType` only on this file:
`typer.Option`'s overload returns `Any`, which pyright-strict flags as
unknown. The behavior is correct; the type signature is just incomplete
upstream. The validator core and backend modules stay fully typed.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from __future__ import annotations

import os
import sys
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from mbmh.backend import IssueTrackerBackend
from mbmh.backend.github import GitHubBackend
from mbmh.backend.gitlab import GitLabBackend
from mbmh.backend.jira import JiraBackend
from mbmh.backend.local import LocalBackend
from mbmh.config import (
    DEFAULT_READY_LABEL,
    DEFAULT_TICKET_REGEX,
    ValidatorConfig,
)
from mbmh.report import render_report
from mbmh.validator import validate

app = typer.Typer(
    help="Validate the scope of a release against its milestone.",
    no_args_is_help=True,
)


class Tracker(StrEnum):
    gitlab = "gitlab"
    github = "github"
    jira = "jira"
    local = "local"


def _resolve_backend(
    tracker: Tracker,
    fixture_dir: Path | None,
    issues_project: str,
    ready_label: str,
    repo: Path,
    todo_file: Path | None,
) -> IssueTrackerBackend:
    """Build the chosen backend in fixture mode or live (token) mode."""
    if tracker is Tracker.local:
        path = todo_file if todo_file is not None else repo / "todo.txt"
        if not path.exists():
            typer.echo(f"todo file not found: {path}", err=True)
            raise typer.Exit(code=2)
        return LocalBackend.from_file(path, issues_project=issues_project, ready_label=ready_label)
    if tracker is Tracker.jira:
        if fixture_dir is not None:
            return JiraBackend.from_fixture_dir(
                fixture_dir, issues_project=issues_project, ready_label=ready_label
            )
        email = os.environ.get("JIRA_EMAIL")
        token = os.environ.get("JIRA_API_TOKEN")
        base_url = os.environ.get("JIRA_BASE_URL")
        if not (email and token and base_url):
            typer.echo(
                "set JIRA_EMAIL, JIRA_API_TOKEN, and JIRA_BASE_URL (or use --fixture-dir).",
                err=True,
            )
            raise typer.Exit(code=2)
        return JiraBackend.from_token(
            base_url=base_url,
            email=email,
            token=token,
            issues_project=issues_project,
            ready_label=ready_label,
        )
    if tracker is Tracker.github:
        if fixture_dir is not None:
            return GitHubBackend.from_fixture_dir(
                fixture_dir, issues_project=issues_project, ready_label=ready_label
            )
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            typer.echo("GITHUB_TOKEN not set and no --fixture-dir provided.", err=True)
            raise typer.Exit(code=2)
        base_url = os.environ.get("GITHUB_API_URL", "https://api.github.com")
        return GitHubBackend.from_token(
            base_url=base_url, token=token, issues_project=issues_project, ready_label=ready_label
        )
    if fixture_dir is not None:
        return GitLabBackend.from_fixture_dir(
            fixture_dir, issues_project=issues_project, ready_label=ready_label
        )
    token = os.environ.get("GITLAB_API_TOKEN")
    if not token:
        typer.echo("GITLAB_API_TOKEN not set and no --fixture-dir provided.", err=True)
        raise typer.Exit(code=2)
    base_url = os.environ.get("GITLAB_BASE_URL", "https://gitlab.com")
    return GitLabBackend.from_token(
        base_url=base_url, token=token, issues_project=issues_project, ready_label=ready_label
    )


@app.command()
def run(
    repo: Annotated[Path, typer.Option(help="Path to the local git working tree.")],
    release_branch: Annotated[
        str,
        typer.Option(
            "--to", "--release-branch", help="Newer ref to validate — branch, tag, or commit."
        ),
    ],
    milestone: Annotated[str, typer.Option(help="Milestone name (or ID).")],
    issues_project: Annotated[
        str,
        typer.Option(help="Issues project — GitLab path/ID, or GitHub 'owner/repo'."),
    ],
    tracker: Annotated[Tracker, typer.Option(help="Issue tracker backend.")] = Tracker.gitlab,
    previous_branch: Annotated[
        str | None,
        typer.Option(
            "--previous",
            "--previous-branch",
            help="Optional prior release ref for the dropped-commit check.",
        ),
    ] = None,
    base_branch: Annotated[
        str,
        typer.Option(
            "--from",
            "--base-branch",
            help="Older ref to diff from — the merge-base anchor (branch, tag, or commit).",
        ),
    ] = "main",
    ticket_regex: Annotated[
        str, typer.Option(help="Ticket extraction regex.")
    ] = DEFAULT_TICKET_REGEX,
    ready_label: Annotated[
        str, typer.Option(help="Issue label that marks 'ready for release'.")
    ] = DEFAULT_READY_LABEL,
    include_merges: Annotated[
        bool,
        typer.Option(
            "--include-merges/--no-include-merges",
            help="Include merge commits in per-commit checks.",
        ),
    ] = False,
    check_descriptions: Annotated[
        bool,
        typer.Option(
            "--check-descriptions/--no-check-descriptions",
            help="Flag milestone tickets with thin or missing descriptions.",
        ),
    ] = False,
    min_description_words: Annotated[
        int,
        typer.Option(help="Minimum words for a description (with --check-descriptions)."),
    ] = 5,
    require_epic: Annotated[
        bool,
        typer.Option(
            "--require-epic/--no-require-epic",
            help="Require each milestone ticket to have a parent epic that is ready.",
        ),
    ] = False,
    epic_kind: Annotated[
        str, typer.Option(help="Ticket kind that identifies an epic (with --require-epic).")
    ] = "epic",
    fixture_dir: Annotated[
        Path | None, typer.Option(help="Use recorded JSON fixtures from this directory.")
    ] = None,
    todo_file: Annotated[
        Path | None,
        typer.Option(
            "--todo-file",
            help="Path to a todo.txt for --tracker local (default: <repo>/todo.txt).",
        ),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Write the report to this file (default: stdout)."),
    ] = None,
) -> None:
    """Run the validator and produce a markdown report.

    Exit code is non-zero if any error-severity finding is present.
    """
    config = ValidatorConfig(
        repo_path=str(repo),
        release_branch=release_branch,
        previous_branch=previous_branch,
        milestone=milestone,
        issues_project=issues_project,
        base_branch=base_branch,
        ticket_regex=ticket_regex,
        ready_label=ready_label,
        include_merges=include_merges,
        check_descriptions=check_descriptions,
        min_description_words=min_description_words,
        require_epic=require_epic,
        epic_kind=epic_kind,
    )

    backend = _resolve_backend(tracker, fixture_dir, issues_project, ready_label, repo, todo_file)

    try:
        result = validate(config, backend)
    finally:
        backend.close()
    report = render_report(result)

    if output is not None:
        output.write_text(report)
    else:
        sys.stdout.write(report)

    if result.has_errors:
        raise typer.Exit(code=1)


if __name__ == "__main__":  # pragma: no cover
    app()
