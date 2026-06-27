"""Tests for the GitHub Issues backend — live (mock transport) and fixture mode."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from mbmh.backend.github import GitHubBackend
from mbmh.models import TicketRef

BASE_URL = "https://api.github.com"
Handler = Callable[[httpx.Request], httpx.Response]


def _issue(number: int, title: str, labels: list[str], *, is_pr: bool = False) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "number": number,
        "title": title,
        "labels": [{"name": n} for n in labels],
        "html_url": f"https://github.com/acme/widgets/issues/{number}",
    }
    if is_pr:
        raw["pull_request"] = {"url": "..."}
    return raw


def _backend(handler: Handler) -> GitHubBackend:
    client = httpx.Client(base_url=BASE_URL, transport=httpx.MockTransport(handler))
    return GitHubBackend.from_token(
        base_url=BASE_URL, token="t0ken", issues_project="acme/widgets", client=client
    )


def _default_handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if "/milestones" in url:
        return httpx.Response(200, json=[{"number": 4, "title": "1.4.0", "state": "open"}])
    if url.endswith("/issues/99"):
        return httpx.Response(200, json=_issue(99, "out of scope", ["Other"]))
    if url.endswith("/issues/9999"):
        return httpx.Response(404, json={"message": "Not Found"})
    if "/issues" in url:  # milestone issue listing
        return httpx.Response(
            200,
            json=[
                _issue(10, "ready", ["Ready for Release"]),
                _issue(11, "not ready", []),
                _issue(12, "a PR", ["Ready for Release"], is_pr=True),
            ],
        )
    return httpx.Response(404, json={"message": f"unrouted: {url}"})


def test_marker_is_live() -> None:
    backend = _backend(_default_handler)
    assert backend.marker == "live-api"
    backend.close()


def test_fetch_milestone_tickets_maps_fields_and_filters_prs() -> None:
    backend = _backend(_default_handler)
    tickets = {t.ref.issue: t for t in backend.fetch_milestone_tickets("1.4.0")}
    # PR #12 is filtered out; only issues 10 and 11 remain.
    assert sorted(tickets) == [10, 11]
    assert tickets[10].state_ready is True  # label object -> name read
    assert tickets[11].state_ready is False
    assert tickets[10].ref.project == "acme/widgets"
    assert tickets[10].web_url.endswith("/issues/10")  # html_url mapped
    backend.close()


def test_unknown_milestone_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "/milestones" in str(request.url):
            return httpx.Response(200, json=[{"number": 4, "title": "1.4.0"}])
        return httpx.Response(200, json=[])

    backend = _backend(handler)
    with pytest.raises(KeyError):
        backend.fetch_milestone_tickets("nope")
    backend.close()


def test_fetch_ticket_found_and_not_found() -> None:
    backend = _backend(_default_handler)
    found = backend.fetch_ticket(TicketRef(project="acme/widgets", issue=99))
    assert found is not None
    assert found.ref.issue == 99
    assert found.state_ready is False
    assert backend.fetch_ticket(TicketRef(project="acme/widgets", issue=9999)) is None
    backend.close()


def test_pagination_follows_next_link() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/milestones" in url:
            return httpx.Response(200, json=[{"number": 4, "title": "1.4.0"}])
        if "/issues" in url:
            if "page=2" in url:
                return httpx.Response(200, json=[_issue(11, "page two", [])])
            nxt = f"{BASE_URL}/repos/acme/widgets/issues?page=2"
            return httpx.Response(
                200,
                json=[_issue(10, "page one", ["Ready for Release"])],
                headers={"Link": f'<{nxt}>; rel="next"'},
            )
        return httpx.Response(404, json={"message": "unrouted"})

    backend = _backend(handler)
    iids = sorted(t.ref.issue for t in backend.fetch_milestone_tickets("1.4.0"))
    assert iids == [10, 11]
    backend.close()


def test_fixture_mode(tmp_path: Path) -> None:
    (tmp_path / "milestones.json").write_text(json.dumps([{"number": 4, "title": "1.4.0"}]))
    (tmp_path / "milestone-4-issues.json").write_text(
        json.dumps(
            [
                _issue(10, "ready", ["Ready for Release"]),
                _issue(11, "not ready", []),
                _issue(12, "a PR", ["Ready for Release"], is_pr=True),
            ]
        )
    )
    issues_dir = tmp_path / "issues" / "acme__widgets"
    issues_dir.mkdir(parents=True)
    (issues_dir / "99.json").write_text(json.dumps(_issue(99, "out of scope", ["Other"])))

    backend = GitHubBackend.from_fixture_dir(tmp_path, issues_project="acme/widgets")
    assert backend.marker == "fixture"
    tickets = {t.ref.issue: t for t in backend.fetch_milestone_tickets("1.4.0")}
    assert sorted(tickets) == [10, 11]  # PR filtered out
    assert tickets[10].state_ready is True
    assert backend.fetch_ticket(TicketRef(project="acme/widgets", issue=99)) is not None
    assert backend.fetch_ticket(TicketRef(project="acme/widgets", issue=123)) is None
