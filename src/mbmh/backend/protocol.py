"""The issue-tracker backend Protocol.

This is the boundary that lets the validator core stay vendor-free.
A backend exposes only what the validator needs:

  - the set of tickets a milestone declares as in-scope,
  - whether a ticket is in the *ready for release* state.

Backend implementations decide how those concepts map onto their data model
(GitLab issue labels, GitHub project columns, Jira workflow states, etc.).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from mbmh.models import Ticket, TicketRef


@runtime_checkable
class IssueTrackerBackend(Protocol):
    """Issue tracker as seen by the validator core."""

    def fetch_milestone_tickets(self, milestone: str) -> list[Ticket]:
        """Return all tickets the named/identified milestone declares as scope."""
        ...

    def fetch_ticket(self, ref: TicketRef) -> Ticket | None:
        """Return a ticket by reference, or None if it doesn't exist."""
        ...

    @property
    def marker(self) -> str:
        """Free-form short string for the report footer (e.g. 'fixture'/'live-api')."""
        ...
