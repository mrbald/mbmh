"""Epic resolution — how the validator finds a ticket's parent epic.

`--require-epic` needs to know each ticket's parent epic. The default resolver
reads `Ticket.parent`, which the local `todo.txt` and Jira backends populate.
GitLab and GitHub don't expose epic links to mbmh (premium / awkward), so this
is the seam where you supply your own logic.

Using mbmh as a library, implement `EpicResolver` (or subclass
`NoOpEpicResolver`) and pass it to `validate(..., epic_resolver=...)`:

    from mbmh.validator import validate, NoOpEpicResolver
    from mbmh.models import Ticket, TicketRef

    class MyResolver(NoOpEpicResolver):
        def resolve(self, ticket: Ticket, backend) -> Ticket | None:
            epic_id = ...  # e.g. parse a GitLab epic id from a label
            return backend.fetch_ticket(TicketRef(ticket.ref.project, epic_id))

    validate(config, backend, epic_resolver=MyResolver())
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from mbmh.backend import IssueTrackerBackend
from mbmh.models import Ticket


@runtime_checkable
class EpicResolver(Protocol):
    """Finds the parent epic of a ticket (or None if it has none)."""

    def resolve(self, ticket: Ticket, backend: IssueTrackerBackend) -> Ticket | None: ...


class DefaultEpicResolver:
    """Resolve the epic from `Ticket.parent` via the backend.

    Works whenever the backend populates `parent` (local `todo.txt`, Jira).
    """

    def resolve(self, ticket: Ticket, backend: IssueTrackerBackend) -> Ticket | None:
        if ticket.parent is None:
            return None
        return backend.fetch_ticket(ticket.parent)


class NoOpEpicResolver:
    """A stub that resolves no epics — every ticket reads as `missing-epic`.

    Copy it and fill in `resolve` with your tracker's epic-linking logic when
    `Ticket.parent` isn't populated for your backend.
    """

    def resolve(self, ticket: Ticket, backend: IssueTrackerBackend) -> Ticket | None:
        return None
