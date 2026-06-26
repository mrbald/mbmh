"""Unit tests for ticket-reference extraction from commit messages."""

from __future__ import annotations

from mbmh.config import DEFAULT_TICKET_REGEX
from mbmh.git_ops import extract_ticket_refs
from mbmh.models import TicketRef


def _extract(msg: str, default: str = "acme/widgets") -> list[TicketRef]:
    return list(extract_ticket_refs(msg, regex=DEFAULT_TICKET_REGEX, default_project=default))


def test_bare_ref_resolves_to_default_project() -> None:
    refs = _extract("fix #42")
    assert refs == [TicketRef(project="acme/widgets", issue=42)]


def test_project_qualified_ref() -> None:
    refs = _extract("fix project-x#7")
    assert refs == [TicketRef(project="project-x", issue=7)]


def test_group_project_qualified_ref() -> None:
    refs = _extract("fix acme/widgets#15")
    assert refs == [TicketRef(project="acme/widgets", issue=15)]


def test_multiple_refs_preserve_order_and_dedupe() -> None:
    msg = "refactor: tidy acme/widgets#10 and acme/widgets#11 and #10 again"
    refs = _extract(msg)
    assert refs == [
        TicketRef(project="acme/widgets", issue=10),
        TicketRef(project="acme/widgets", issue=11),
    ]


def test_no_refs_returns_empty_tuple() -> None:
    assert _extract("chore: no tickets here") == []


def test_dotted_project_in_path() -> None:
    refs = _extract("feat: acme.dotted/foo#3")
    assert refs == [TicketRef(project="acme.dotted/foo", issue=3)]
