"""Configuration for a validator run. Vendor-free shape; backend choice is separate."""

from __future__ import annotations

from dataclasses import dataclass

# Default regex per the spec. Named captures: project, issue.
# Examples it matches:
#   group/project#123
#   project#42
#   #7  (resolves against the configured default issues project)
DEFAULT_TICKET_REGEX = r"(?:(?P<project>[\w./-]+))?#(?P<issue>\d+)"

DEFAULT_READY_LABEL = "Ready for Release"


@dataclass(frozen=True)
class ValidatorConfig:
    repo_path: str
    release_branch: str
    previous_branch: str | None
    milestone: str
    # The "issues project" the backend will query; also the default project
    # for bare `#N` ticket refs.
    issues_project: str
    # Branch the release branches fork from; the merge-base for commit walks.
    # Override if your default branch is not "main".
    base_branch: str = "main"
    ticket_regex: str = DEFAULT_TICKET_REGEX
    ready_label: str = DEFAULT_READY_LABEL
    include_merges: bool = False
    # Ticket-structure rules (opt-in).
    check_descriptions: bool = False
    min_description_words: int = 5
    require_epic: bool = False
    epic_kind: str = "epic"
