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
from pathlib import Path
from typing import Annotated

import typer

from mbmh.backend.gitlab import GitLabBackend
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


@app.command()
def run(
    repo: Annotated[Path, typer.Option(help="Path to the local git working tree.")],
    release_branch: Annotated[str, typer.Option(help="Current release branch name.")],
    milestone: Annotated[str, typer.Option(help="Milestone name (or ID).")],
    issues_project: Annotated[
        str, typer.Option(help="GitLab issues project (path or numeric ID).")
    ],
    previous_branch: Annotated[
        str | None, typer.Option(help="Previous release branch (optional).")
    ] = None,
    base_branch: Annotated[
        str, typer.Option(help="Branch the release forks from (merge-base for commit walks).")
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
    fixture_dir: Annotated[
        Path | None, typer.Option(help="Use recorded JSON fixtures from this directory.")
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
    )

    if fixture_dir is not None:
        backend = GitLabBackend.from_fixture_dir(
            fixture_dir,
            issues_project=issues_project,
            ready_label=ready_label,
        )
    else:
        token = os.environ.get("GITLAB_API_TOKEN")
        if not token:
            typer.echo(
                "GITLAB_API_TOKEN not set and no --fixture-dir provided.",
                err=True,
            )
            raise typer.Exit(code=2)
        base_url = os.environ.get("GITLAB_BASE_URL", "https://gitlab.com")
        backend = GitLabBackend.from_token(
            base_url=base_url,
            token=token,
            issues_project=issues_project,
            ready_label=ready_label,
        )

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
