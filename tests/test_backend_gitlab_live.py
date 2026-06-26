"""Tests for the GitLab live-API backend, using a mock httpx transport.

No network: every request is served by an in-process handler.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest

from mbmh.backend.gitlab import GitLabBackend
from mbmh.models import TicketRef

BASE_URL = "https://gitlab.example.com"

Handler = Callable[[httpx.Request], httpx.Response]


def _issue(iid: int, title: str, labels: list[str]) -> dict[str, Any]:
    return {
        "iid": iid,
        "title": title,
        "labels": labels,
        "web_url": f"{BASE_URL}/acme/widgets/-/issues/{iid}",
    }


def _backend(handler: Handler) -> GitLabBackend:
    client = httpx.Client(base_url=BASE_URL, transport=httpx.MockTransport(handler))
    return GitLabBackend.from_token(
        base_url=BASE_URL,
        token="t0ken",
        issues_project="acme/widgets",
        client=client,
    )


def _default_handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if "/milestones/99/issues" in url:
        return httpx.Response(
            200,
            json=[
                _issue(10, "ready one", ["Ready for Release"]),
                _issue(11, "not ready", []),
            ],
        )
    if "/milestones" in url:  # resolution by title
        return httpx.Response(200, json=[{"id": 99, "iid": 1, "title": "1.4.0"}])
    if url.endswith("/issues/99"):
        return httpx.Response(200, json=_issue(99, "out of scope", ["Other"]))
    if url.endswith("/issues/9999"):
        return httpx.Response(404, json={"message": "404 Not Found"})
    return httpx.Response(404, json={"message": f"unrouted: {url}"})


def test_marker_is_live() -> None:
    backend = _backend(_default_handler)
    assert backend.marker == "live-api"
    backend.close()


def test_fetch_milestone_tickets_live() -> None:
    backend = _backend(_default_handler)
    tickets = {t.ref.issue: t for t in backend.fetch_milestone_tickets("1.4.0")}
    assert sorted(tickets) == [10, 11]
    assert tickets[10].state_ready is True
    assert tickets[11].state_ready is False
    # Milestone issues default to the configured issues project.
    assert tickets[10].ref.project == "acme/widgets"
    backend.close()


def test_unknown_milestone_raises() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    backend = _backend(handler)
    with pytest.raises(KeyError):
        backend.fetch_milestone_tickets("nope")
    backend.close()


def test_fetch_ticket_found_live() -> None:
    backend = _backend(_default_handler)
    t = backend.fetch_ticket(TicketRef(project="acme/widgets", issue=99))
    assert t is not None
    assert t.ref.issue == 99
    assert t.state_ready is False
    backend.close()


def test_fetch_ticket_not_found_returns_none() -> None:
    backend = _backend(_default_handler)
    assert backend.fetch_ticket(TicketRef(project="acme/widgets", issue=9999)) is None
    backend.close()


def test_pagination_follows_next_link() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/milestones/99/issues" in url:
            if "page=2" in url:
                return httpx.Response(200, json=[_issue(11, "page two", [])])
            next_url = f"{BASE_URL}/api/v4/projects/acme%2Fwidgets/milestones/99/issues?page=2"
            return httpx.Response(
                200,
                json=[_issue(10, "page one", ["Ready for Release"])],
                headers={"Link": f'<{next_url}>; rel="next"'},
            )
        if "/milestones" in url:
            return httpx.Response(200, json=[{"id": 99, "title": "1.4.0"}])
        return httpx.Response(404, json={"message": "unrouted"})

    backend = _backend(handler)
    iids = sorted(t.ref.issue for t in backend.fetch_milestone_tickets("1.4.0"))
    assert iids == [10, 11]
    backend.close()
