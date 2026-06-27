"""Git porcelain wrappers and parsing.

All operations are local — we never network out. The caller is expected
to have already fetched both release branches into the working tree.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from mbmh.models import Commit, TicketRef

# Match a "Change-Id: I<hex>" trailer Gerrit-style.
_CHANGE_ID_RE = re.compile(r"^Change-Id:\s*(I[0-9a-fA-F]+)\s*$", re.MULTILINE)

# Match the default `git revert` body line: "This reverts commit <sha>."
_REVERT_RE = re.compile(r"^This reverts commit ([0-9a-f]{7,40})\b", re.MULTILINE)


@dataclass(frozen=True)
class GitError(Exception):
    """Raised when a git command fails or returns unexpected output."""

    message: str

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.message


def _run_git(repo: Path, *args: str) -> str:
    """Run a git command and return stdout, raising GitError on failure."""
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise GitError(message=f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def merge_base(repo: Path, a: str, b: str) -> str:
    out = _run_git(repo, "merge-base", a, b).strip()
    if not out:
        raise GitError(message=f"no merge-base between {a} and {b}")
    return out


def _commit_subject_and_body(repo: Path, sha: str) -> tuple[str, str]:
    # %B is the raw body including subject.
    body = _run_git(repo, "show", "-s", "--format=%B", sha)
    body = body.rstrip("\n")
    first_nl = body.find("\n")
    if first_nl == -1:
        return body, body
    return body[:first_nl], body


def _is_merge(repo: Path, sha: str) -> bool:
    parents = _run_git(repo, "rev-list", "--parents", "-n", "1", sha).strip().split()
    # First field is the commit itself; remaining are parents.
    return len(parents) > 2


def _patch_id(repo: Path, sha: str) -> str | None:
    """Return git patch-id --stable for a commit, or None for empty diff."""
    diff = _run_git(repo, "show", "--patch", "--no-color", sha)
    if not diff.strip():
        return None
    result = subprocess.run(
        ["git", "-C", str(repo), "patch-id", "--stable"],
        input=diff,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    line = result.stdout.strip()
    if not line:
        return None
    return line.split()[0]


def _extract_change_id(message: str) -> str | None:
    m = _CHANGE_ID_RE.search(message)
    return m.group(1) if m else None


def _extract_reverted_sha(message: str) -> str | None:
    m = _REVERT_RE.search(message)
    return m.group(1) if m else None


def extract_ticket_refs(
    message: str,
    *,
    regex: str,
    default_project: str,
) -> tuple[TicketRef, ...]:
    """Extract all ticket references from a commit message.

    Bare `#N` resolves to `default_project`. Order-preserving, deduplicated.
    """
    compiled = re.compile(regex)
    seen: set[tuple[str, int]] = set()
    out: list[TicketRef] = []
    for m in compiled.finditer(message):
        proj_raw = m.groupdict().get("project")
        proj = (proj_raw or default_project).strip()
        iid = int(m.group("issue"))
        key = (proj, iid)
        if key in seen:
            continue
        seen.add(key)
        out.append(TicketRef(project=proj, issue=iid))
    return tuple(out)


def list_commits(
    *,
    repo_path: str | Path,
    release_branch: str,
    base_ref: str = "main",
    ticket_regex: str,
    default_project: str,
    include_merges: bool = False,
) -> list[Commit]:
    """List commits on `release_branch` since its merge-base with `base_ref`.

    By default walks `--first-parent` and skips merge commits per the spec.
    """
    repo = Path(repo_path)
    base = merge_base(repo, release_branch, base_ref)
    args = ["rev-list", "--reverse"]
    if not include_merges:
        args += ["--first-parent", "--no-merges"]
    args += [f"{base}..{release_branch}"]
    raw = _run_git(repo, *args)
    shas = [line.strip() for line in raw.splitlines() if line.strip()]

    out: list[Commit] = []
    for sha in shas:
        subject, message = _commit_subject_and_body(repo, sha)
        is_merge = _is_merge(repo, sha)
        if is_merge and not include_merges:
            continue
        out.append(
            Commit(
                sha=sha,
                subject=subject,
                message=message,
                is_merge=is_merge,
                patch_id=_patch_id(repo, sha),
                change_id=_extract_change_id(message),
                ticket_refs=extract_ticket_refs(
                    message,
                    regex=ticket_regex,
                    default_project=default_project,
                ),
                reverts=_extract_reverted_sha(message),
            )
        )
    return out


def patch_equivalence_set(commits: list[Commit]) -> tuple[set[str], set[str]]:
    """Return (change_ids, patch_ids) seen across the given commit list.

    Empty/None values are ignored. Used to detect when a previous-branch
    commit is patch-equivalent to a current-branch commit (back-port).
    """
    change_ids = {c.change_id for c in commits if c.change_id}
    patch_ids = {c.patch_id for c in commits if c.patch_id}
    return change_ids, patch_ids


def _resolve_sha(ref: str, by_sha: dict[str, Commit]) -> str | None:
    """Resolve a possibly-abbreviated sha to a full sha present in `by_sha`."""
    if ref in by_sha:
        return ref
    matches = [s for s in by_sha if s.startswith(ref)]
    return matches[0] if len(matches) == 1 else None


@dataclass(frozen=True)
class RevertCollapse:
    """Result of collapsing reverts: surviving commits + the cancelled pairs."""

    kept: list[Commit]
    # (revert_commit, reverted_target) pairs that cancelled out
    pairs: list[tuple[Commit, Commit]]


def collapse_reverts_detailed(commits: list[Commit]) -> RevertCollapse:
    """Collapse apply+revert pairs; return survivors and the cancelled pairs.

    A commit carrying the default `This reverts commit <sha>.` message cancels
    the commit it names, when that commit is also in the list: both are removed,
    so a change that was applied and then reverted counts as *not present*.

    Revert-of-revert chains are best-effort only: the simple apply+revert case
    is guaranteed; re-applying a change via a double revert is not un-cancelled.
    """
    by_sha = {c.sha: c for c in commits}
    cancelled: set[str] = set()
    pairs: list[tuple[Commit, Commit]] = []
    for c in commits:
        if c.reverts is None or c.sha in cancelled:
            continue
        target = _resolve_sha(c.reverts, by_sha)
        if target is not None and target not in cancelled:
            cancelled.add(c.sha)
            cancelled.add(target)
            pairs.append((c, by_sha[target]))
    kept = [c for c in commits if c.sha not in cancelled]
    return RevertCollapse(kept=kept, pairs=pairs)


def collapse_reverts(commits: list[Commit]) -> list[Commit]:
    """Return only the commits that survive `collapse_reverts_detailed`."""
    return collapse_reverts_detailed(commits).kept
