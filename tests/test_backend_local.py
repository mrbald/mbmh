"""Local todo.txt backend — parsing/lookup, plus a full offline end-to-end run."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from typer.testing import CliRunner

from mbmh.backend.local import LocalBackend
from mbmh.cli import app
from mbmh.models import TicketRef


def test_parsing_lookup_and_ready(tmp_path: Path) -> None:
    todo = tmp_path / "todo.txt"
    todo.write_text(
        "(A) Fix login redirect loop id:42 milestone:1.4.0 @ready\n"
        "Add signup form id:43 milestone:1.4.0\n"
        "x 2026-06-20 Footer links id:44 milestone:1.4.0 @ready\n"
        "A note with no id milestone:1.4.0\n"
        "Other release id:50 milestone:2.0.0 @ready\n"
        "\n"
        "# a comment\n"
    )
    backend = LocalBackend.from_file(todo, issues_project="mbmh", ready_label="ready")

    assert backend.marker == "todo.txt"
    tickets = {t.ref.issue: t for t in backend.fetch_milestone_tickets("1.4.0")}
    # id:50 is a different milestone; the no-id line is not a ticket.
    assert sorted(tickets) == [42, 43, 44]
    assert tickets[42].state_ready is True
    assert tickets[43].state_ready is False
    assert tickets[44].state_ready is True
    # priority, completion/date markers and metadata stripped from the title.
    assert tickets[42].title == "Fix login redirect loop"
    assert tickets[44].title == "Footer links"
    assert tickets[42].web_url == ""


def test_fetch_ticket(tmp_path: Path) -> None:
    todo = tmp_path / "todo.txt"
    todo.write_text("Thing id:50 milestone:2.0.0 @ready\n")
    backend = LocalBackend.from_file(todo, issues_project="mbmh", ready_label="ready")
    assert backend.fetch_ticket(TicketRef(project="mbmh", issue=50)) is not None
    assert backend.fetch_ticket(TicketRef(project="mbmh", issue=999)) is None
    # a foreign project is not in this local tracker
    assert backend.fetch_ticket(TicketRef(project="other", issue=50)) is None


def _git(repo: Path, *args: str) -> str:
    env = dict(os.environ)
    env.update(
        GIT_AUTHOR_NAME="T",
        GIT_AUTHOR_EMAIL="t@e.com",
        GIT_COMMITTER_NAME="T",
        GIT_COMMITTER_EMAIL="t@e.com",
        GIT_AUTHOR_DATE="2026-01-01T00:00:00Z",
        GIT_COMMITTER_DATE="2026-01-01T00:00:00Z",
    )
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True, env=env
    ).stdout


def test_end_to_end_offline(tmp_path: Path) -> None:
    """Validate a real release branch against an in-repo todo.txt — no network."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "--initial-branch=main")
    _git(repo, "config", "user.email", "t@e.com")
    _git(repo, "config", "user.name", "T")
    (repo / "base.txt").write_text("base\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "chore: init")
    _git(repo, "checkout", "-q", "-b", "release/1.4.0")
    (repo / "f.txt").write_text("x\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "feat: login fix #42")
    (repo / "todo.txt").write_text(
        "Fix login id:42 milestone:1.4.0 @ready\n"
        "Add signup form id:43 milestone:1.4.0 @ready\n"  # ready but no commit -> missing
    )

    out = tmp_path / "report.md"
    result = CliRunner().invoke(
        app,
        [
            "--tracker",
            "local",
            "--repo",
            str(repo),
            "--to",
            "release/1.4.0",
            "--from",
            "main",
            "--milestone",
            "1.4.0",
            "--issues-project",
            "mbmh",
            "--ready-label",
            "ready",
            "--output",
            str(out),
        ],
    )

    assert result.exit_code == 1  # ticket #43 promised by the milestone has no commit
    text = out.read_text()
    assert "# Release scope report" in text
    assert "`missing`" in text
    assert "Data source: `todo.txt`" in text
