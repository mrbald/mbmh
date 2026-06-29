"""GitLab implementation of `IssueTrackerBackend`.

Two constructors:
  - `from_fixture_dir(...)` — reads recorded JSON responses from a directory
    (offline; for tests and CI without a token).
  - `from_token(...)` — queries the live GitLab REST API with a personal or CI
    job token.

GitLab JSON shape (relevant subset):

  Milestone resolution by name: GET /projects/:id/milestones?title=...
    [{"id": 123, "iid": 4, "title": "1.4.0"}, ...]

  Milestone issues:    GET /projects/:id/milestones/:id/issues
    [{"iid": 7, "title": "...", "labels": ["Ready for Release"], "web_url": "..."}, ...]

  Single issue:        GET /projects/:id/issues/:iid
    {"iid": 7, "title": "...", "labels": [...], "web_url": "..."}

The fixture layout mirrors this:
  <dir>/milestones.json              # list of milestones
  <dir>/milestone-<id>-issues.json   # issues for milestone
  <dir>/issues/<project>/<iid>.json  # individual issues (for unauthorized lookup)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from urllib.parse import quote

import httpx

from mbmh.backend._http import paginate
from mbmh.backend.protocol import IssueTrackerBackend
from mbmh.config import DEFAULT_READY_LABEL
from mbmh.models import Ticket, TicketRef


@dataclass
class GitLabBackend:
    """GitLab issue-tracker backend.

    Concrete class (not the Protocol); structural typing makes any instance
    satisfy `IssueTrackerBackend`. It runs in one of two modes: fixture (data
    loaded from disk) or live (HTTP through an `httpx.Client`).
    """

    issues_project: str
    ready_label: str = DEFAULT_READY_LABEL
    # Fixture mode: milestone-name-or-id -> issues JSON list.
    _milestones: dict[str, list[dict[str, Any]]] | None = None
    # Fixture mode: (project, iid) -> single-issue JSON (for `fetch_ticket`).
    _issues: dict[tuple[str, int], dict[str, Any]] | None = None
    # Live mode: an httpx client carrying base_url + auth header.
    _client: httpx.Client | None = None
    _marker: str = "live-api"

    @classmethod
    def from_fixture_dir(
        cls,
        path: str | Path,
        *,
        issues_project: str,
        ready_label: str = DEFAULT_READY_LABEL,
    ) -> GitLabBackend:
        root = Path(path)
        milestones_index_path = root / "milestones.json"
        milestones_index: list[dict[str, Any]] = (
            json.loads(milestones_index_path.read_text()) if milestones_index_path.exists() else []
        )

        milestones: dict[str, list[dict[str, Any]]] = {}
        for m in milestones_index:
            mid = str(m["id"])
            mname = str(m["title"])
            issues_path = root / f"milestone-{mid}-issues.json"
            if not issues_path.exists():
                continue
            data = json.loads(issues_path.read_text())
            milestones[mid] = data
            milestones[mname] = data

        issues: dict[tuple[str, int], dict[str, Any]] = {}
        issues_dir = root / "issues"
        if issues_dir.exists():
            for proj_dir in issues_dir.iterdir():
                if not proj_dir.is_dir():
                    continue
                proj = proj_dir.name.replace("__", "/")
                for issue_file in proj_dir.glob("*.json"):
                    iid = int(issue_file.stem)
                    issues[proj, iid] = json.loads(issue_file.read_text())

        # Also index milestone-issue data by (project, iid) for direct lookup.
        for issue_list in milestones.values():
            for raw in issue_list:
                proj = raw.get("project_path") or issues_project
                issues.setdefault((proj, int(raw["iid"])), raw)

        return cls(
            issues_project=issues_project,
            ready_label=ready_label,
            _milestones=milestones,
            _issues=issues,
            _marker="fixture",
        )

    @classmethod
    def from_token(
        cls,
        *,
        base_url: str,
        token: str,
        issues_project: str,
        ready_label: str = DEFAULT_READY_LABEL,
        client: httpx.Client | None = None,
    ) -> GitLabBackend:
        """Connect to the live GitLab REST API.

        `token` needs at least `read_api` scope on `issues_project`. Pass a
        pre-built `client` (e.g. one with a mock transport) for testing;
        otherwise one is built from `base_url` + `token`.
        """
        http = (
            client
            if client is not None
            else httpx.Client(
                base_url=base_url.rstrip("/"),
                headers={"PRIVATE-TOKEN": token, "Accept": "application/json"},
                timeout=httpx.Timeout(30.0),
            )
        )
        return cls(
            issues_project=issues_project,
            ready_label=ready_label,
            _client=http,
            _marker="live-api",
        )

    # ----- IssueTrackerBackend protocol surface -----

    @property
    def marker(self) -> str:
        return self._marker

    def fetch_milestone_tickets(self, milestone: str) -> list[Ticket]:
        if self._client is not None:
            return self._live_milestone_tickets(milestone)
        if self._milestones is None:
            raise RuntimeError("backend not loaded; use from_fixture_dir or from_token")
        if milestone not in self._milestones:
            raise KeyError(f"unknown milestone: {milestone}")
        return [self._to_ticket(raw) for raw in self._milestones[milestone]]

    def fetch_ticket(self, ref: TicketRef) -> Ticket | None:
        if self._client is not None:
            return self._live_fetch_ticket(ref)
        if self._issues is None:
            raise RuntimeError("backend not loaded; use from_fixture_dir or from_token")
        raw = self._issues.get((ref.project, ref.issue))
        if raw is None:
            return None
        return self._to_ticket(raw, ref=ref)

    def close(self) -> None:
        """Close the live HTTP client, if any. A no-op in fixture mode."""
        if self._client is not None:
            self._client.close()

    # ----- live API internals -----

    def _live_milestone_tickets(self, milestone: str) -> list[Ticket]:
        assert self._client is not None
        enc = quote(self.issues_project, safe="")
        found = paginate(self._client, f"/api/v4/projects/{enc}/milestones", {"title": milestone})
        if not found:
            raise KeyError(f"unknown milestone: {milestone}")
        milestone_id = int(found[0]["id"])
        issues = paginate(
            self._client,
            f"/api/v4/projects/{enc}/milestones/{milestone_id}/issues",
            {"per_page": 100},
        )
        return [self._to_ticket(raw) for raw in issues]

    def _live_fetch_ticket(self, ref: TicketRef) -> Ticket | None:
        assert self._client is not None
        enc = quote(ref.project, safe="")
        resp = self._client.get(f"/api/v4/projects/{enc}/issues/{ref.issue}")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return self._to_ticket(resp.json(), ref=ref)

    # ----- shared helpers -----

    def _to_ticket(self, raw: dict[str, Any], *, ref: TicketRef | None = None) -> Ticket:
        project = raw.get("project_path") or self.issues_project
        iid = int(raw["iid"])
        labels = raw.get("labels", [])
        ready = self.ready_label in labels
        web_url = str(raw.get("web_url", ""))
        # `parent` is left unset: GitLab epics are premium/group-level and aren't
        # issues. GitLabEpicResolver (below) fetches the epic via the group epics
        # API; the CLI wires it in for --require-epic.
        return Ticket(
            ref=ref or TicketRef(project=str(project), issue=iid),
            title=str(raw.get("title", "")),
            state_ready=ready,
            web_url=web_url,
            description=str(raw.get("description") or ""),
            kind=str(raw.get("issue_type") or ""),
        )


@dataclass
class GitLabEpicResolver:
    """Best-effort epic resolution for GitLab (premium, group-level epics).

    Reads the issue's `epic` (iid + group_id), fetches the epic from the group
    epics API, and maps its labels to the ready state. Unverified against a live
    instance — confirm on yours. The CLI uses it for live GitLab + --require-epic.
    """

    _client: httpx.Client
    ready_label: str = DEFAULT_READY_LABEL

    @classmethod
    def from_token(
        cls,
        *,
        base_url: str,
        token: str,
        ready_label: str = DEFAULT_READY_LABEL,
        client: httpx.Client | None = None,
    ) -> GitLabEpicResolver:
        http = client or httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"PRIVATE-TOKEN": token, "Accept": "application/json"},
            timeout=httpx.Timeout(30.0),
        )
        return cls(_client=http, ready_label=ready_label)

    def resolve(self, ticket: Ticket, backend: IssueTrackerBackend) -> Ticket | None:
        enc = quote(ticket.ref.project, safe="")
        issue = self._client.get(f"/api/v4/projects/{enc}/issues/{ticket.ref.issue}")
        if issue.status_code == 404:
            return None
        issue.raise_for_status()
        epic = issue.json().get("epic")
        if not isinstance(epic, dict):
            return None
        epic_obj = cast("dict[str, Any]", epic)
        group_id = epic_obj.get("group_id")
        epic_iid = epic_obj.get("iid")
        if group_id is None or epic_iid is None:
            return None
        resp = self._client.get(f"/api/v4/groups/{group_id}/epics/{epic_iid}")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        raw: dict[str, Any] = resp.json()
        labels = raw.get("labels", [])
        return Ticket(
            ref=TicketRef(project=ticket.ref.project, issue=int(epic_iid)),
            title=str(raw.get("title", "")),
            state_ready=self.ready_label in labels,
            web_url=str(raw.get("web_url", "")),
            kind="epic",
        )

    def close(self) -> None:
        self._client.close()
