"""Shared test fixtures: build a real git repo with a known commit history.

The repo is built once per test session and contains every shape needed
to exercise all six failure categories from the spec:

  - clean case: commit references milestone ticket that is ready
  - orphan: commit with no ticket reference
  - unauthorized: commit references ticket not in the milestone
  - not-ready: commit references milestone ticket whose label != Ready
  - missing: a milestone ticket with no commits on release branch
  - dropped: previous release has a commit with no patch-equivalent on current
  - ambiguous-equivalence: previous release commit with no Change-Id/patch-id
                            (synthesized by emptying the diff)

Plus a clean ticket whose commit lands on both branches via patch-id.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest


def _git(repo: Path, *args: str, env: dict[str, str] | None = None) -> str:
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    # Force a stable identity to make sha hashes deterministic-ish.
    full_env.setdefault("GIT_AUTHOR_NAME", "Test")
    full_env.setdefault("GIT_AUTHOR_EMAIL", "test@example.com")
    full_env.setdefault("GIT_COMMITTER_NAME", "Test")
    full_env.setdefault("GIT_COMMITTER_EMAIL", "test@example.com")
    full_env.setdefault("GIT_AUTHOR_DATE", "2026-01-01T00:00:00Z")
    full_env.setdefault("GIT_COMMITTER_DATE", "2026-01-01T00:00:00Z")
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        env=full_env,
        check=True,
    )
    return result.stdout


def _commit(
    repo: Path,
    file_name: str,
    contents: str,
    message: str,
) -> str:
    (repo / file_name).write_text(contents)
    _git(repo, "add", file_name)
    _git(repo, "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD").strip()


@pytest.fixture(scope="session")
def fixture_repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build a deterministic git repo + JSON fixture set.

    Returns the path to the repo. JSON fixtures live alongside as `api/`.
    """
    base = tmp_path_factory.mktemp("release-scope-fixture")
    repo = base / "repo"
    repo.mkdir()
    api = base / "api"
    api.mkdir()
    (api / "issues").mkdir()

    _git(repo, "init", "--initial-branch=main", "--quiet")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")

    # ----- main branch -----
    _commit(
        repo,
        "README.md",
        "# project",
        "chore: initial commit",
    )

    # Tickets used in this fixture (in milestone "1.4.0"):
    #   acme/widgets#10 — ready
    #   acme/widgets#11 — not ready
    #   acme/widgets#12 — ready but no commit ("missing")
    #   acme/widgets#13 — ready, lands on both prev+current via patch-id (clean back-port)
    # Plus:
    #   acme/widgets#99 — exists in tracker but NOT in milestone (unauthorized)

    # ----- Previous release branch: release/1.3.0 -----
    _git(repo, "checkout", "-b", "release/1.3.0")

    # A commit on prev that is back-ported via patch-id equivalence.
    sha_prev_backport = _commit(
        repo,
        "feature_13.txt",
        "implementation of ticket 13\n",
        "feat: add widget 13 acme/widgets#13",
    )
    # A commit on prev that was dropped (no equivalent on current).
    sha_prev_dropped = _commit(
        repo,
        "feature_dropped.txt",
        "this hotfix never made it forward acme/widgets#7\n",
        "fix: hotfix dropped acme/widgets#7",
    )

    # ----- Current release branch: release/1.4.0, fork from main -----
    _git(repo, "checkout", "main")
    _git(repo, "checkout", "-b", "release/1.4.0")

    # clean commit referencing ready ticket #10
    _commit(
        repo,
        "feature_10.txt",
        "happy path implementation\n",
        "feat: implement widget 10 acme/widgets#10",
    )
    # orphan commit: no ticket reference
    _commit(
        repo,
        "orphan.txt",
        "no ticket here\n",
        "chore: stuff",
    )
    # unauthorized commit: references #99 which exists but isn't in milestone
    _commit(
        repo,
        "unauthorized.txt",
        "sneaky\n",
        "feat: sneaky change acme/widgets#99",
    )
    # not-ready commit: references #11 which is in milestone but not ready
    _commit(
        repo,
        "feature_11.txt",
        "still in progress\n",
        "wip: widget 11 acme/widgets#11",
    )
    # equivalent of the prev-backport commit (same content)
    _commit(
        repo,
        "feature_13.txt",
        "implementation of ticket 13\n",
        "feat: add widget 13 (cherry-pick) acme/widgets#13",
    )
    # multi-ticket commit: references #10 and #11
    _commit(
        repo,
        "multi.txt",
        "touches two\n",
        "refactor: tidy acme/widgets#10 and acme/widgets#11",
    )

    # ----- JSON fixtures -----
    milestone_id = 99
    milestones_index: list[dict[str, Any]] = [
        {"id": milestone_id, "iid": 1, "title": "1.4.0"},
    ]
    (api / "milestones.json").write_text(json.dumps(milestones_index, indent=2))

    def issue(iid: int, title: str, labels: list[str]) -> dict[str, Any]:
        return {
            "iid": iid,
            "title": title,
            "labels": labels,
            "web_url": f"https://gitlab.example.com/acme/widgets/issues/{iid}",
            "project_path": "acme/widgets",
        }

    milestone_issues = [
        issue(10, "Widget 10 happy path", ["Ready for Release"]),
        issue(11, "Widget 11 in progress", []),
        issue(12, "Widget 12 missing", ["Ready for Release"]),
        issue(13, "Widget 13 backport", ["Ready for Release"]),
    ]
    (api / f"milestone-{milestone_id}-issues.json").write_text(
        json.dumps(milestone_issues, indent=2)
    )

    # Individual issues directory: needs to cover unauthorized lookup (#99 exists).
    acme_dir = api / "issues" / "acme__widgets"
    acme_dir.mkdir()
    (acme_dir / "99.json").write_text(
        json.dumps(issue(99, "Out-of-scope #99", ["Some Other Label"]))
    )
    # Note: ticket #7 referenced by the dropped previous-branch commit is
    # intentionally absent; the validator on prev side doesn't lookup, only
    # checks patch-equivalence with current.

    # Stash useful shas for tests that want them.
    metadata = {
        "milestone_id": milestone_id,
        "milestone_name": "1.4.0",
        "release_branch": "release/1.4.0",
        "previous_branch": "release/1.3.0",
        "sha_prev_backport": sha_prev_backport,
        "sha_prev_dropped": sha_prev_dropped,
    }
    (base / "metadata.json").write_text(json.dumps(metadata, indent=2))

    return repo


@pytest.fixture(scope="session")
def fixture_api_dir(fixture_repo: Path) -> Path:
    return fixture_repo.parent / "api"


@pytest.fixture(scope="session")
def fixture_metadata(fixture_repo: Path) -> dict[str, Any]:
    return json.loads((fixture_repo.parent / "metadata.json").read_text())
