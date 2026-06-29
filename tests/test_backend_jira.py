"""Tests for the Jira backend — live (mock transport), fixtures, and parsers."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from mbmh.backend.jira import JiraBackend
from mbmh.models import TicketRef

BASE_URL = "https://acme.atlassian.net"
Handler = Callable[[httpx.Request], httpx.Response]


def _issue(
    key: str,
    summary: str,
    status: str,
    *,
    issuetype: str = "Story",
    parent: str | None = None,
    description: Any = "a perfectly adequate description here",
) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "summary": summary,
        "status": {"name": status},
        "issuetype": {"name": issuetype},
        "description": description,
    }
    if parent is not None:
        fields["parent"] = {"key": parent}
    return {"key": key, "fields": fields}


def _backend(handler: Handler) -> JiraBackend:
    client = httpx.Client(base_url=BASE_URL, transport=httpx.MockTransport(handler))
    return JiraBackend.from_token(
        base_url=BASE_URL, email="e@x.com", token="t0ken", issues_project="PROJ", client=client
    )


def _default_handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path.endswith("/search"):
        return httpx.Response(
            200,
            json={
                "issues": [
                    _issue("PROJ-10", "ready one", "Ready for Release"),
                    _issue("PROJ-11", "not ready", "In Progress", parent="PROJ-99"),
                ],
                "total": 2,
                "startAt": 0,
                "maxResults": 100,
            },
        )
    if path.endswith("/issue/PROJ-99"):
        return httpx.Response(
            200, json=_issue("PROJ-99", "the epic", "Ready for Release", issuetype="Epic")
        )
    if path.endswith("/issue/PROJ-9999"):
        return httpx.Response(404, json={"errorMessages": ["does not exist"]})
    return httpx.Response(404, json={"errorMessages": [f"unrouted: {path}"]})


def test_adf_description_via_fixture(tmp_path: Path) -> None:
    issues_dir = tmp_path / "issues"
    issues_dir.mkdir()
    adf = {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "Hello world here"}]}
        ],
    }
    (issues_dir / "PROJ-50.json").write_text(
        json.dumps(_issue("PROJ-50", "x", "Done", description=adf))
    )
    backend = JiraBackend.from_fixture_dir(tmp_path, issues_project="PROJ")
    ticket = backend.fetch_ticket(TicketRef(project="PROJ", issue=50))
    assert ticket is not None
    assert ticket.description == "Hello world here"


def test_marker_is_live() -> None:
    backend = _backend(_default_handler)
    assert backend.marker == "live-api"
    backend.close()


def test_fetch_milestone_tickets_maps_fields() -> None:
    backend = _backend(_default_handler)
    tickets = {t.ref.issue: t for t in backend.fetch_milestone_tickets("1.4.0")}
    assert sorted(tickets) == [10, 11]
    assert tickets[10].ref.project == "PROJ"
    assert tickets[10].state_ready is True  # status == ready label
    assert tickets[11].state_ready is False
    assert tickets[10].kind == "story"
    assert tickets[11].parent == TicketRef(project="PROJ", issue=99)
    assert tickets[10].web_url == f"{BASE_URL}/browse/PROJ-10"
    backend.close()


def test_fetch_ticket_epic_and_missing() -> None:
    backend = _backend(_default_handler)
    epic = backend.fetch_ticket(TicketRef(project="PROJ", issue=99))
    assert epic is not None
    assert epic.kind == "epic"
    assert epic.state_ready is True
    assert backend.fetch_ticket(TicketRef(project="PROJ", issue=9999)) is None
    backend.close()


def test_unknown_milestone_search_empty() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"issues": [], "total": 0, "startAt": 0, "maxResults": 100})

    backend = _backend(handler)
    assert backend.fetch_milestone_tickets("nope") == []
    backend.close()


def test_search_pagination() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        start = int(request.url.params.get("startAt", "0"))
        page = (
            [_issue("PROJ-11", "page two", "In Progress")]
            if start
            else [_issue("PROJ-10", "page one", "Ready for Release")]
        )
        return httpx.Response(
            200, json={"issues": page, "total": 2, "startAt": start, "maxResults": 1}
        )

    backend = _backend(handler)
    iids = sorted(t.ref.issue for t in backend.fetch_milestone_tickets("1.4.0"))
    assert iids == [10, 11]
    backend.close()


def test_fixture_mode(tmp_path: Path) -> None:
    (tmp_path / "milestones.json").write_text(
        json.dumps(
            {
                "1.4.0": [
                    _issue("PROJ-10", "ready", "Ready for Release"),
                    _issue("PROJ-11", "not ready", "In Progress", parent="PROJ-99"),
                ]
            }
        )
    )
    issues_dir = tmp_path / "issues"
    issues_dir.mkdir()
    (issues_dir / "PROJ-99.json").write_text(
        json.dumps(_issue("PROJ-99", "the epic", "Ready for Release", issuetype="Epic"))
    )

    backend = JiraBackend.from_fixture_dir(tmp_path, issues_project="PROJ")
    assert backend.marker == "fixture"
    tickets = {t.ref.issue: t for t in backend.fetch_milestone_tickets("1.4.0")}
    assert sorted(tickets) == [10, 11]
    assert tickets[10].state_ready is True
    epic = backend.fetch_ticket(TicketRef(project="PROJ", issue=99))
    assert epic is not None
    assert epic.kind == "epic"
    with pytest.raises(KeyError):
        backend.fetch_milestone_tickets("unknown")
