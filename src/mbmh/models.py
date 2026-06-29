"""Domain models: vendor-free. The validator core operates on these."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


@dataclass(frozen=True)
class TicketRef:
    """A reference to a ticket parsed from a commit message.

    `project` is the resolved project path/ID (after defaulting to the
    configured issues project if the regex match had no project).
    """

    project: str
    issue: int

    def __str__(self) -> str:
        return f"{self.project}#{self.issue}"


@dataclass(frozen=True)
class Ticket:
    """A ticket as fetched from the issue-tracker backend."""

    ref: TicketRef
    title: str
    state_ready: bool
    web_url: str
    description: str = ""
    kind: str = ""  # issue type, e.g. "epic", "story"
    parent: TicketRef | None = None  # parent epic/ticket, when the tracker links it


@dataclass(frozen=True)
class Commit:
    """A commit on the release branch."""

    sha: str
    subject: str
    message: str
    is_merge: bool
    patch_id: str | None
    change_id: str | None
    ticket_refs: tuple[TicketRef, ...]
    # full sha this commit reverts, parsed from the default `git revert`
    # message; None if the commit is not a recognised revert
    reverts: str | None = None


class ErrorCategory(StrEnum):
    UNAUTHORIZED = "unauthorized"
    NOT_READY = "not-ready"
    MISSING = "missing"
    DROPPED = "dropped"
    ORPHAN = "orphan"
    AMBIGUOUS_EQUIVALENCE = "ambiguous-equivalence"
    POOR_DESCRIPTION = "poor-description"
    MISSING_EPIC = "missing-epic"
    EPIC_NOT_READY = "epic-not-ready"


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


CATEGORY_SEVERITY: dict[ErrorCategory, Severity] = {
    ErrorCategory.UNAUTHORIZED: Severity.ERROR,
    ErrorCategory.NOT_READY: Severity.ERROR,
    ErrorCategory.MISSING: Severity.ERROR,
    ErrorCategory.DROPPED: Severity.ERROR,
    ErrorCategory.ORPHAN: Severity.ERROR,
    ErrorCategory.AMBIGUOUS_EQUIVALENCE: Severity.WARNING,
    ErrorCategory.POOR_DESCRIPTION: Severity.WARNING,
    ErrorCategory.MISSING_EPIC: Severity.ERROR,
    ErrorCategory.EPIC_NOT_READY: Severity.ERROR,
}


@dataclass(frozen=True)
class Finding:
    """A single error/warning attributed to a commit or a ticket."""

    category: ErrorCategory
    message: str
    commit_sha: str | None = None
    ticket: TicketRef | None = None
    detail: str = ""

    @property
    def severity(self) -> Severity:
        return CATEGORY_SEVERITY[self.category]


@dataclass
class ValidationResult:
    """Output of the validator core: findings + the scope tree data."""

    release_name: str
    milestone_name: str
    release_branch: str
    previous_branch: str | None
    commits: list[Commit] = field(default_factory=list[Commit])
    milestone_tickets: list[Ticket] = field(default_factory=list[Ticket])
    findings: list[Finding] = field(default_factory=list[Finding])
    # ticket_ref str -> list of commits that reference it
    commits_by_ticket: dict[str, list[Commit]] = field(default_factory=dict[str, list[Commit]])
    # commits that are on previous-branch and have no patch-equivalent on current
    dropped_previous_commits: list[Commit] = field(default_factory=list[Commit])
    fixture_marker: str = "live-api"
    # (revert_commit, reverted_target) pairs cancelled out of the scope
    reverted_pairs: list[tuple[Commit, Commit]] = field(default_factory=list[tuple[Commit, Commit]])

    @property
    def has_errors(self) -> bool:
        return any(f.severity is Severity.ERROR for f in self.findings)

    @property
    def error_counts(self) -> dict[ErrorCategory, int]:
        out: dict[ErrorCategory, int] = {}
        for f in self.findings:
            out[f.category] = out.get(f.category, 0) + 1
        return out
