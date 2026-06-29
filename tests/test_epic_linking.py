"""Built-in epic linking: GitHub native sub-issue parent + GitLab group-epic resolver."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from mbmh.backend.github import GitHubBackend
from mbmh.backend.gitlab import GitLabBackend, GitLabEpicResolver
from mbmh.models import Ticket, TicketRef

Handler = Callable[[httpx.Request], httpx.Response]


def _gh_issue(
    number: int, title: str, labels: list[str], *, parent: int | None = None
) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "number": number,
        "title": title,
        "labels": [{"name": n} for n in labels],
        "html_url": f"https://github.com/acme/widgets/issues/{number}",
    }
    if parent is not None:
        raw["parent"] = {"number": parent, "repository": {"full_name": "acme/widgets"}}
    return raw


def test_github_maps_sub_issue_parent(tmp_path: Path) -> None:
    issues_dir = tmp_path / "issues" / "acme__widgets"
    issues_dir.mkdir(parents=True)
    (issues_dir / "42.json").write_text(
        json.dumps(_gh_issue(42, "child", ["Ready for Release"], parent=100))
    )
    backend = GitHubBackend.from_fixture_dir(tmp_path, issues_project="acme/widgets")
    child = backend.fetch_ticket(TicketRef(project="acme/widgets", issue=42))
    assert child is not None
    assert child.parent == TicketRef(project="acme/widgets", issue=100)


def test_github_no_parent_stays_none(tmp_path: Path) -> None:
    issues_dir = tmp_path / "issues" / "acme__widgets"
    issues_dir.mkdir(parents=True)
    (issues_dir / "42.json").write_text(json.dumps(_gh_issue(42, "child", [])))
    backend = GitHubBackend.from_fixture_dir(tmp_path, issues_project="acme/widgets")
    child = backend.fetch_ticket(TicketRef(project="acme/widgets", issue=42))
    assert child is not None
    assert child.parent is None


def _gitlab_resolver(handler: Handler) -> GitLabEpicResolver:
    client = httpx.Client(
        base_url="https://gitlab.example.com", transport=httpx.MockTransport(handler)
    )
    return GitLabEpicResolver.from_token(
        base_url="https://gitlab.example.com",
        token="t0ken",
        ready_label="Ready for Release",
        client=client,
    )


def _dummy_backend(tmp_path: Path) -> GitLabBackend:
    return GitLabBackend.from_fixture_dir(tmp_path, issues_project="acme/widgets")


def test_gitlab_epic_resolver_resolves_group_epic(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/issues/42"):
            return httpx.Response(200, json={"iid": 42, "epic": {"iid": 9, "group_id": 7}})
        if path.endswith("/groups/7/epics/9"):
            return httpx.Response(
                200,
                json={
                    "iid": 9,
                    "title": "the auth epic",
                    "labels": ["Ready for Release"],
                    "web_url": "https://gitlab.example.com/groups/acme/-/epics/9",
                },
            )
        return httpx.Response(404, json={})

    resolver = _gitlab_resolver(handler)
    ticket = Ticket(
        ref=TicketRef(project="acme/widgets", issue=42), title="child", state_ready=True, web_url=""
    )
    epic = resolver.resolve(ticket, _dummy_backend(tmp_path))
    assert epic is not None
    assert epic.ref == TicketRef(project="acme/widgets", issue=9)
    assert epic.kind == "epic"
    assert epic.state_ready is True
    resolver.close()


def test_gitlab_epic_resolver_no_epic_returns_none(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/issues/42"):
            return httpx.Response(200, json={"iid": 42})  # no epic field
        return httpx.Response(404, json={})

    resolver = _gitlab_resolver(handler)
    ticket = Ticket(
        ref=TicketRef(project="acme/widgets", issue=42), title="c", state_ready=True, web_url=""
    )
    assert resolver.resolve(ticket, _dummy_backend(tmp_path)) is None
    resolver.close()
