"""Revert handling: an apply+revert pair (default git revert message) cancels out."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from mbmh.git_ops import collapse_reverts, list_commits
from mbmh.models import Commit

REGEX = r"(?:(?P<project>[\w./-]+))?#(?P<issue>\d+)"


def _commit_obj(sha: str, message: str, reverts: str | None = None) -> Commit:
    return Commit(
        sha=sha,
        subject=message.splitlines()[0],
        message=message,
        is_merge=False,
        patch_id=None,
        change_id=None,
        ticket_refs=(),
        reverts=reverts,
    )


def test_apply_then_revert_cancels() -> None:
    a = "a" * 40
    commits = [
        _commit_obj(a, "feat: thing acme/widgets#1"),
        _commit_obj("b" * 40, f'Revert "feat: thing"\n\nThis reverts commit {a}.', reverts=a),
    ]
    assert collapse_reverts(commits) == []


def test_unreverted_commit_survives() -> None:
    a, c = "a" * 40, "c" * 40
    commits = [
        _commit_obj(a, "feat: a acme/widgets#1"),
        _commit_obj(c, "feat: c acme/widgets#2"),
        _commit_obj("b" * 40, f"Revert a\n\nThis reverts commit {a}.", reverts=a),
    ]
    assert [x.sha for x in collapse_reverts(commits)] == [c]


def test_revert_of_out_of_range_target_is_kept() -> None:
    b = "b" * 40
    commits = [_commit_obj(b, f"Revert\n\nThis reverts commit {'z' * 40}.", reverts="z" * 40)]
    assert [x.sha for x in collapse_reverts(commits)] == [b]


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


def test_real_git_revert_is_parsed_and_collapsed(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "--initial-branch=main")
    _git(repo, "config", "user.email", "t@e.com")
    _git(repo, "config", "user.name", "T")
    (repo / "base.txt").write_text("base\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "chore: init")
    _git(repo, "checkout", "-q", "-b", "release/1")
    (repo / "f.txt").write_text("feature\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "feat: f acme/widgets#1")
    feat_sha = _git(repo, "rev-parse", "HEAD").strip()
    _git(repo, "revert", "--no-edit", feat_sha)

    commits = list_commits(
        repo_path=repo,
        release_branch="release/1",
        base_ref="main",
        ticket_regex=REGEX,
        default_project="acme/widgets",
    )
    assert any(c.reverts == feat_sha for c in commits), "default revert message should be parsed"
    assert collapse_reverts(commits) == [], "feat and its revert should cancel out"
