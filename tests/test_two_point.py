"""Diffing two points (tags) on the same branch, and cherry-pick equivalence."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from mbmh.git_ops import list_commits, patch_equivalence_set

REGEX = r"(?:(?P<project>[\w./-]+))?#(?P<issue>\d+)"


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


def _init(repo: Path) -> None:
    repo.mkdir()
    _git(repo, "init", "-q", "--initial-branch=main")
    _git(repo, "config", "user.email", "t@e.com")
    _git(repo, "config", "user.name", "T")
    (repo / "base.txt").write_text("base\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "chore: init")


def test_diff_two_tags_on_same_branch(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init(repo)
    _git(repo, "checkout", "-q", "-b", "release/1")
    (repo / "a.txt").write_text("a\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "feat: a acme/widgets#1")
    _git(repo, "tag", "v1")
    (repo / "b.txt").write_text("b\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "feat: b acme/widgets#2")
    _git(repo, "tag", "v2")

    # Two points on one branch: from the older tag to the newer tag.
    commits = list_commits(
        repo_path=repo,
        release_branch="v2",
        base_ref="v1",
        ticket_regex=REGEX,
        default_project="acme/widgets",
    )
    issues = [r.issue for c in commits for r in c.ticket_refs]
    assert issues == [2], "v1..v2 should contain only the commit added after v1"


def test_cherry_pick_is_patch_equivalent(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init(repo)
    _git(repo, "checkout", "-q", "-b", "release/prev")
    (repo / "x.txt").write_text("payload\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "feat: x acme/widgets#1")
    prev_sha = _git(repo, "rev-parse", "HEAD").strip()
    _git(repo, "checkout", "-q", "main")
    _git(repo, "checkout", "-q", "-b", "release/cur")
    _git(repo, "cherry-pick", prev_sha)

    prev = list_commits(
        repo_path=repo,
        release_branch="release/prev",
        base_ref="main",
        ticket_regex=REGEX,
        default_project="acme/widgets",
    )
    cur = list_commits(
        repo_path=repo,
        release_branch="release/cur",
        base_ref="main",
        ticket_regex=REGEX,
        default_project="acme/widgets",
    )
    _, prev_patch = patch_equivalence_set(prev)
    _, cur_patch = patch_equivalence_set(cur)
    assert prev_patch and prev_patch == cur_patch, "cherry-pick should be patch-id equivalent"
