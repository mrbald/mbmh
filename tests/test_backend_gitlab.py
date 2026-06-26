"""Tests for the GitLab fixture-mode backend."""

from __future__ import annotations

from pathlib import Path

from mbmh.backend.gitlab import GitLabBackend
from mbmh.models import TicketRef


def test_marker_is_fixture_when_loaded_from_dir(fixture_api_dir: Path) -> None:
    backend = GitLabBackend.from_fixture_dir(fixture_api_dir, issues_project="acme/widgets")
    assert backend.marker == "fixture"


def test_fetch_milestone_tickets_by_name(fixture_api_dir: Path) -> None:
    backend = GitLabBackend.from_fixture_dir(fixture_api_dir, issues_project="acme/widgets")
    tickets = backend.fetch_milestone_tickets("1.4.0")
    iids = sorted(t.ref.issue for t in tickets)
    assert iids == [10, 11, 12, 13]


def test_fetch_milestone_tickets_by_id(fixture_api_dir: Path) -> None:
    backend = GitLabBackend.from_fixture_dir(fixture_api_dir, issues_project="acme/widgets")
    tickets = backend.fetch_milestone_tickets("99")
    assert len(tickets) == 4


def test_ready_label_drives_state(fixture_api_dir: Path) -> None:
    backend = GitLabBackend.from_fixture_dir(fixture_api_dir, issues_project="acme/widgets")
    tickets = {t.ref.issue: t for t in backend.fetch_milestone_tickets("1.4.0")}
    assert tickets[10].state_ready is True
    assert tickets[11].state_ready is False
    assert tickets[12].state_ready is True
    assert tickets[13].state_ready is True


def test_fetch_ticket_found_outside_milestone(fixture_api_dir: Path) -> None:
    backend = GitLabBackend.from_fixture_dir(fixture_api_dir, issues_project="acme/widgets")
    t = backend.fetch_ticket(TicketRef(project="acme/widgets", issue=99))
    assert t is not None
    assert t.ref.issue == 99
    assert t.state_ready is False


def test_fetch_ticket_not_found(fixture_api_dir: Path) -> None:
    backend = GitLabBackend.from_fixture_dir(fixture_api_dir, issues_project="acme/widgets")
    t = backend.fetch_ticket(TicketRef(project="acme/widgets", issue=9999))
    assert t is None
