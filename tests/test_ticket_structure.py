"""Ticket-structure rules: description quality and parent-epic state (end-to-end)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from typer.testing import CliRunner

from mbmh.backend.local import LocalBackend
from mbmh.cli import app
from mbmh.models import TicketRef


def test_local_parses_type_and_parent(tmp_path: Path) -> None:
    todo = tmp_path / "todo.txt"
    todo.write_text(
        "Build authentication subsystem end to end id:100 type:epic @ready\n"
        "Login form id:42 milestone:1.4.0 parent:100 @ready\n"
    )
    backend = LocalBackend.from_file(todo, issues_project="repo", ready_label="ready")
    epic = backend.fetch_ticket(TicketRef(project="repo", issue=100))
    assert epic is not None
    assert epic.kind == "epic"
    assert epic.state_ready is True
    child = backend.fetch_ticket(TicketRef(project="repo", issue=42))
    assert child is not None
    assert child.parent == TicketRef(project="repo", issue=100)


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


def _make_repo(tmp_path: Path, todo: str) -> Path:
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
    _git(repo, "commit", "-qm", "feat: login work #42")
    (repo / "todo.txt").write_text(todo)
    return repo


def _run(repo: Path, out: Path, *extra: str):  # returns Typer's Result (not importable to annotate)
    return CliRunner().invoke(
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
            "repo",
            "--ready-label",
            "ready",
            "--output",
            str(out),
            *extra,
        ],
    )


def test_epic_not_ready_is_flagged(tmp_path: Path) -> None:
    # epic #100 is NOT @ready; child #42 (in the milestone) references it.
    todo = (
        "Build authentication subsystem end to end id:100 type:epic\n"
        "Implement the login form fully id:42 milestone:1.4.0 parent:100 @ready\n"
    )
    out = tmp_path / "r.md"
    result = _run(_make_repo(tmp_path, todo), out, "--require-epic")
    assert result.exit_code == 1
    assert "`epic-not-ready`" in out.read_text()


def test_missing_epic_is_flagged(tmp_path: Path) -> None:
    todo = "Implement the login form fully id:42 milestone:1.4.0 @ready\n"  # no parent
    out = tmp_path / "r.md"
    result = _run(_make_repo(tmp_path, todo), out, "--require-epic")
    assert result.exit_code == 1
    assert "`missing-epic`" in out.read_text()


def test_thin_description_is_a_warning(tmp_path: Path) -> None:
    todo = "Login id:42 milestone:1.4.0 @ready\n"  # 1-word description
    out = tmp_path / "r.md"
    result = _run(
        _make_repo(tmp_path, todo), out, "--check-descriptions", "--min-description-words", "5"
    )
    assert "`poor-description`" in out.read_text()
    assert result.exit_code == 0  # warning only; the ticket is shipped and ready


def test_clean_with_ready_epic_and_full_description(tmp_path: Path) -> None:
    todo = (
        "Build authentication subsystem end to end id:100 type:epic @ready\n"
        "Implement the login form fully now id:42 milestone:1.4.0 parent:100 @ready\n"
    )
    out = tmp_path / "r.md"
    result = _run(_make_repo(tmp_path, todo), out, "--require-epic", "--check-descriptions")
    assert result.exit_code == 0
    text = out.read_text()
    for category in ("missing-epic", "epic-not-ready", "poor-description"):
        assert f"`{category}`" not in text
