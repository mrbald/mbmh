"""Validator core.

Pure function. Takes already-fetched commits + already-fetched tickets, and
produces a `ValidationResult` carrying all findings + the scope tree data.

This module knows nothing about GitLab, HTTP, or markdown.
"""

from __future__ import annotations

from mbmh.backend import IssueTrackerBackend
from mbmh.config import ValidatorConfig
from mbmh.git_ops import list_commits, patch_equivalence_set
from mbmh.models import (
    Commit,
    ErrorCategory,
    Finding,
    Ticket,
    TicketRef,
    ValidationResult,
)


def validate(
    config: ValidatorConfig,
    backend: IssueTrackerBackend,
) -> ValidationResult:
    """Run all checks. Returns the populated ValidationResult."""

    current_commits = list_commits(
        repo_path=config.repo_path,
        release_branch=config.release_branch,
        ticket_regex=config.ticket_regex,
        default_project=config.issues_project,
        include_merges=config.include_merges,
    )

    milestone_tickets = backend.fetch_milestone_tickets(config.milestone)
    milestone_refs: dict[TicketRef, Ticket] = {t.ref: t for t in milestone_tickets}

    result = ValidationResult(
        release_name=config.release_branch.split("/", 1)[-1],
        milestone_name=config.milestone,
        release_branch=config.release_branch,
        previous_branch=config.previous_branch,
        commits=current_commits,
        milestone_tickets=list(milestone_tickets),
        fixture_marker=backend.marker,
    )

    _check_per_commit(result, current_commits, milestone_refs, backend)
    _check_missing(result, current_commits, milestone_tickets)

    if config.previous_branch is not None:
        previous_commits = list_commits(
            repo_path=config.repo_path,
            release_branch=config.previous_branch,
            ticket_regex=config.ticket_regex,
            default_project=config.issues_project,
            include_merges=config.include_merges,
        )
        _check_regressions(result, current_commits, previous_commits)

    return result


def _commit_short_id(commit: Commit) -> str:
    return commit.sha[:12]


def _check_per_commit(
    result: ValidationResult,
    commits: list[Commit],
    milestone_refs: dict[TicketRef, Ticket],
    backend: IssueTrackerBackend,
) -> None:
    """Per-commit checks: orphan, unauthorized, not-ready."""
    by_ticket: dict[str, list[Commit]] = {}

    for c in commits:
        if not c.ticket_refs:
            result.findings.append(
                Finding(
                    category=ErrorCategory.ORPHAN,
                    message=f"commit {_commit_short_id(c)} has no parseable ticket reference",
                    commit_sha=c.sha,
                    detail=c.subject,
                )
            )
            continue

        for ref in c.ticket_refs:
            by_ticket.setdefault(str(ref), []).append(c)

            milestone_ticket = milestone_refs.get(ref)
            if milestone_ticket is None:
                # Either the ticket exists but isn't in the milestone, or
                # the reference is to a non-existent ticket. Either way the
                # commit is *unauthorized* with respect to this release.
                existing = backend.fetch_ticket(ref)
                detail = (
                    "ticket exists but is not in this milestone"
                    if existing is not None
                    else "ticket does not exist in tracker"
                )
                result.findings.append(
                    Finding(
                        category=ErrorCategory.UNAUTHORIZED,
                        message=(
                            f"commit {_commit_short_id(c)} references {ref} "
                            f"which is not in milestone"
                        ),
                        commit_sha=c.sha,
                        ticket=ref,
                        detail=detail,
                    )
                )
                continue

            if not milestone_ticket.state_ready:
                result.findings.append(
                    Finding(
                        category=ErrorCategory.NOT_READY,
                        message=(
                            f"commit {_commit_short_id(c)} references {ref} "
                            f"which is not Ready for Release"
                        ),
                        commit_sha=c.sha,
                        ticket=ref,
                        detail=milestone_ticket.title,
                    )
                )

    result.commits_by_ticket = by_ticket


def _check_missing(
    result: ValidationResult,
    commits: list[Commit],
    milestone_tickets: list[Ticket],
) -> None:
    """Milestone tickets that have zero commits on the release branch."""
    refs_with_commits: set[str] = set()
    for c in commits:
        for ref in c.ticket_refs:
            refs_with_commits.add(str(ref))
    for t in milestone_tickets:
        if str(t.ref) not in refs_with_commits:
            result.findings.append(
                Finding(
                    category=ErrorCategory.MISSING,
                    message=f"milestone ticket {t.ref} has no commits on release branch",
                    ticket=t.ref,
                    detail=t.title,
                )
            )


def _check_regressions(
    result: ValidationResult,
    current_commits: list[Commit],
    previous_commits: list[Commit],
) -> None:
    """`dropped`: previous-branch commit with no patch-equivalent on current.

    Equivalence rule (per spec):
      1. `Change-Id` trailer match (Gerrit-style).
      2. Otherwise `git patch-id --stable` match.
      3. Otherwise flag the *current* match attempt as ambiguous if we found
         a partial fingerprint but couldn't confirm. We're conservative here:
         a commit with neither change-id nor patch-id on the previous branch
         can't be reasoned about — flag it as ambiguous-equivalence rather
         than dropping silently.
    """
    cur_change_ids, cur_patch_ids = patch_equivalence_set(current_commits)

    for c in previous_commits:
        # Change-Id wins.
        if c.change_id and c.change_id in cur_change_ids:
            continue
        # Else patch-id.
        if c.patch_id and c.patch_id in cur_patch_ids:
            continue
        # If we have *something* to match on but no match was found, it's
        # dropped.
        if c.change_id or c.patch_id:
            result.dropped_previous_commits.append(c)
            result.findings.append(
                Finding(
                    category=ErrorCategory.DROPPED,
                    message=(
                        f"previous-branch commit {_commit_short_id(c)} has no "
                        f"patch-equivalent on current branch"
                    ),
                    commit_sha=c.sha,
                    detail=c.subject,
                )
            )
        else:
            # No fingerprint at all → can't decide.
            result.findings.append(
                Finding(
                    category=ErrorCategory.AMBIGUOUS_EQUIVALENCE,
                    message=(
                        f"previous-branch commit {_commit_short_id(c)} has no "
                        f"Change-Id or patch-id; manual review wanted"
                    ),
                    commit_sha=c.sha,
                    detail=c.subject,
                )
            )
