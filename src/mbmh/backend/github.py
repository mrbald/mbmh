"""GitHub Issues implementation of `IssueTrackerBackend`.

Two constructors:
  - `from_fixture_dir(...)` — reads recorded JSON responses from a directory
    (offline; for tests and CI without a token).
  - `from_token(...)` — queries the live GitHub REST API with a token.

GitHub JSON shape (relevant subset):

  Milestones:        GET /repos/:owner/:repo/milestones?state=all
    [{"number": 4, "title": "1.4.0", "state": "open"}, ...]

  Milestone issues:  GET /repos/:owner/:repo/issues?milestone=:number&state=all
    [{"number": 7, "title": "...", "labels": [{"name": "Ready for Release"}],
      "html_url": "..."}, ...]            # pull requests appear here too

  Single issue:      GET /repos/:owner/:repo/issues/:number

Differences from GitLab: the issue id is `number` (not `iid`), the web link is
`html_url` (not `web_url`), labels are objects with a `name`, milestones are
addressed by number, and the issues endpoint also returns pull requests
(filtered out via the `pull_request` key).

The fixture layout mirrors the API:
  <dir>/milestones.json                     # list of milestones
  <dir>/milestone-<number>-issues.json      # issues for milestone
  <dir>/issues/<owner__repo>/<number>.json  # individual issues
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import httpx

from mbmh.backend._http import paginate
from mbmh.config import DEFAULT_READY_LABEL
from mbmh.models import Ticket, TicketRef


def _split_project(project: str) -> tuple[str, str] | None:
    """Split an `owner/repo` project string, or None if it is not that shape."""
    parts = project.split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return None
    return parts[0], parts[1]


def _label_names(raw: dict[str, Any]) -> list[str]:
    """GitHub labels are objects with a `name`; tolerate bare strings too."""
    names: list[str] = []
    for lbl in raw.get("labels", []):
        if isinstance(lbl, dict):
            names.append(str(cast("dict[str, Any]", lbl).get("name", "")))
        else:
            names.append(str(lbl))
    return names


@dataclass
class GitHubBackend:
    """GitHub Issues issue-tracker backend.

    Structural typing makes any instance satisfy `IssueTrackerBackend`. Runs in
    fixture mode (data from disk) or live mode (HTTP through an `httpx.Client`).
    `issues_project` is `owner/repo`.
    """

    issues_project: str
    ready_label: str = DEFAULT_READY_LABEL
    _milestones: dict[str, list[dict[str, Any]]] | None = None
    _issues: dict[tuple[str, int], dict[str, Any]] | None = None
    _client: httpx.Client | None = None
    _marker: str = "live-api"

    @classmethod
    def from_fixture_dir(
        cls,
        path: str | Path,
        *,
        issues_project: str,
        ready_label: str = DEFAULT_READY_LABEL,
    ) -> GitHubBackend:
        root = Path(path)
        index_path = root / "milestones.json"
        index: list[dict[str, Any]] = (
            json.loads(index_path.read_text()) if index_path.exists() else []
        )

        milestones: dict[str, list[dict[str, Any]]] = {}
        for m in index:
            number = str(m["number"])
            title = str(m["title"])
            issues_path = root / f"milestone-{number}-issues.json"
            if not issues_path.exists():
                continue
            data = json.loads(issues_path.read_text())
            milestones[number] = data
            milestones[title] = data

        issues: dict[tuple[str, int], dict[str, Any]] = {}
        issues_dir = root / "issues"
        if issues_dir.exists():
            for proj_dir in issues_dir.iterdir():
                if not proj_dir.is_dir():
                    continue
                proj = proj_dir.name.replace("__", "/")
                for issue_file in proj_dir.glob("*.json"):
                    issue_number = int(issue_file.stem)
                    issues[proj, issue_number] = json.loads(issue_file.read_text())

        for issue_list in milestones.values():
            for raw in issue_list:
                if "pull_request" in raw:
                    continue
                issues.setdefault((issues_project, int(raw["number"])), raw)

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
    ) -> GitHubBackend:
        """Connect to the live GitHub REST API.

        `token` needs read access to issues on `issues_project`. Pass a
        pre-built `client` (e.g. one with a mock transport) for testing;
        otherwise one is built from `base_url` + `token`. For GitHub Enterprise,
        set `base_url` to `https://HOST/api/v3`.
        """
        http = (
            client
            if client is not None
            else httpx.Client(
                base_url=base_url.rstrip("/"),
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
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
        return [
            self._to_ticket(raw) for raw in self._milestones[milestone] if "pull_request" not in raw
        ]

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
        owner_repo = _split_project(self.issues_project)
        if owner_repo is None:
            raise ValueError(f"issues_project must be 'owner/repo', got {self.issues_project!r}")
        owner, repo = owner_repo
        milestones = paginate(self._client, f"/repos/{owner}/{repo}/milestones", {"state": "all"})
        match = next(
            (
                m
                for m in milestones
                if str(m.get("title")) == milestone or str(m.get("number")) == milestone
            ),
            None,
        )
        if match is None:
            raise KeyError(f"unknown milestone: {milestone}")
        number = int(match["number"])
        issues = paginate(
            self._client,
            f"/repos/{owner}/{repo}/issues",
            {"milestone": number, "state": "all", "per_page": 100},
        )
        return [self._to_ticket(raw) for raw in issues if "pull_request" not in raw]

    def _live_fetch_ticket(self, ref: TicketRef) -> Ticket | None:
        assert self._client is not None
        owner_repo = _split_project(ref.project)
        if owner_repo is None:
            return None
        owner, repo = owner_repo
        resp = self._client.get(f"/repos/{owner}/{repo}/issues/{ref.issue}")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        raw: dict[str, Any] = resp.json()
        if "pull_request" in raw:
            return None
        return self._to_ticket(raw, ref=ref)

    # ----- shared helpers -----

    def _to_ticket(self, raw: dict[str, Any], *, ref: TicketRef | None = None) -> Ticket:
        number = int(raw["number"])
        ready = self.ready_label in _label_names(raw)
        type_obj = raw.get("type")
        kind = (
            str(cast("dict[str, Any]", type_obj).get("name", ""))
            if isinstance(type_obj, dict)
            else ""
        )
        # `parent` is intentionally unset: GitHub exposes sub-issue parents via
        # the sub-issues API, not this payload. Wire it up by hand with an
        # EpicResolver (see mbmh.validator.epics, README "Extending").
        return Ticket(
            ref=ref or TicketRef(project=self.issues_project, issue=number),
            title=str(raw.get("title", "")),
            state_ready=ready,
            web_url=str(raw.get("html_url", "")),
            description=str(raw.get("body") or ""),
            kind=kind,
        )
