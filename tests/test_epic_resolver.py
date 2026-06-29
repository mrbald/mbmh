"""The EpicResolver seam: default + no-op resolvers, and a custom override."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from mbmh.backend import IssueTrackerBackend
from mbmh.backend.local import LocalBackend
from mbmh.config import ValidatorConfig
from mbmh.models import ErrorCategory, Ticket, TicketRef
from mbmh.validator import DefaultEpicResolver, NoOpEpicResolver, validate


def test_default_resolver_uses_parent(tmp_path: Path) -> None:
    todo = tmp_path / "todo.txt"
    todo.write_text(
        "The auth epic id:100 type:epic @ready\n"
        "Login form id:42 milestone:1.4.0 parent:100 @ready\n"
    )
    backend = LocalBackend.from_file(todo, issues_project="repo", ready_label="ready")
    child = backend.fetch_ticket(TicketRef(project="repo", issue=42))
    assert child is not None
    epic = DefaultEpicResolver().resolve(child, backend)
    assert epic is not None
    assert epic.ref == TicketRef(project="repo", issue=100)


def test_noop_resolver_returns_none(tmp_path: Path) -> None:
    todo = tmp_path / "todo.txt"
    todo.write_text("Login form id:42 milestone:1.4.0 parent:100 @ready\n")
    backend = LocalBackend.from_file(todo, issues_project="repo", ready_label="ready")
    child = backend.fetch_ticket(TicketRef(project="repo", issue=42))
    assert child is not None
    assert NoOpEpicResolver().resolve(child, backend) is None


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


def test_custom_resolver_overrides_epic_linking(tmp_path: Path) -> None:
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
    # #42 (in the milestone) has NO parent; #100 is a ready epic.
    (repo / "todo.txt").write_text(
        "The auth epic id:100 type:epic @ready\n"
        "Implement the login form fully id:42 milestone:1.4.0 @ready\n"
    )
    backend = LocalBackend.from_file(repo / "todo.txt", issues_project="repo", ready_label="ready")
    config = ValidatorConfig(
        repo_path=str(repo),
        release_branch="release/1.4.0",
        previous_branch=None,
        milestone="1.4.0",
        issues_project="repo",
        base_branch="main",
        ready_label="ready",
        require_epic=True,
    )

    # Default resolver: #42 has no parent -> missing-epic.
    default_result = validate(config, backend)
    assert any(f.category is ErrorCategory.MISSING_EPIC for f in default_result.findings)

    # Custom resolver: link every ticket to epic #100 -> no missing-epic.
    class FixedResolver:
        def resolve(self, ticket: Ticket, backend: IssueTrackerBackend) -> Ticket | None:
            return backend.fetch_ticket(TicketRef(project=ticket.ref.project, issue=100))

    custom_result = validate(config, backend, epic_resolver=FixedResolver())
    assert not any(f.category is ErrorCategory.MISSING_EPIC for f in custom_result.findings)
    assert not any(f.category is ErrorCategory.EPIC_NOT_READY for f in custom_result.findings)
