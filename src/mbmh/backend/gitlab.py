"""GitLab implementation of `IssueTrackerBackend`.

Two constructors:
  - `from_token(...)` — live GitLab API (not yet wired; use `from_fixture_dir`).
  - `from_fixture_dir(...)` — reads recorded JSON responses from a directory.

GitLab JSON shape (relevant subset):

  Milestone issues:    GET /projects/:id/milestones/:id/issues
    [{"iid": 7, "title": "...", "labels": ["Ready for Release"], "web_url": "..."}, ...]

  Single issue:        GET /projects/:id/issues/:iid
    {"iid": 7, "title": "...", "labels": [...], "web_url": "..."}

  Milestone resolution by name: GET /projects/:id/milestones?title=...
    [{"id": 123, "iid": 4, "title": "1.4.0"}, ...]

The fixture layout mirrors this:
  <dir>/milestones.json              # list of milestones
  <dir>/milestone-<id>-issues.json   # issues for milestone
  <dir>/issues/<project>/<iid>.json  # individual issues (for unauthorized lookup)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mbmh.config import DEFAULT_READY_LABEL
from mbmh.models import Ticket, TicketRef


@dataclass
class GitLabBackend:
    """GitLab issue-tracker backend.

    Concrete class (not the Protocol). Structural typing makes any instance
    of this class satisfy `IssueTrackerBackend`.
    """

    issues_project: str
    ready_label: str = DEFAULT_READY_LABEL
    # When loaded from fixture: maps milestone-name-or-id -> issues JSON list
    _milestones: dict[str, list[dict[str, Any]]] | None = None
    # Maps (project, iid) -> single-issue JSON (for `fetch_ticket`)
    _issues: dict[tuple[str, int], dict[str, Any]] | None = None
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
    ) -> GitLabBackend:
        # Live API path: kept as a stub on purpose. The validator core,
        # the report renderer, and the fixture path all work; wire this
        # up when a live run is needed.
        _ = (base_url, token)
        raise NotImplementedError(
            "Live GitLab API not wired in this release. Use from_fixture_dir() "
            "or implement here. See docstring for endpoints."
        )

    # ----- IssueTrackerBackend protocol surface -----

    @property
    def marker(self) -> str:
        return self._marker

    def fetch_milestone_tickets(self, milestone: str) -> list[Ticket]:
        if self._milestones is None:
            raise RuntimeError("backend not loaded; use from_fixture_dir or from_token")
        if milestone not in self._milestones:
            raise KeyError(f"unknown milestone: {milestone}")
        return [self._to_ticket(raw) for raw in self._milestones[milestone]]

    def fetch_ticket(self, ref: TicketRef) -> Ticket | None:
        if self._issues is None:
            raise RuntimeError("backend not loaded; use from_fixture_dir or from_token")
        raw = self._issues.get((ref.project, ref.issue))
        if raw is None:
            return None
        return self._to_ticket(raw, ref=ref)

    # ----- helpers -----

    def _to_ticket(self, raw: dict[str, Any], *, ref: TicketRef | None = None) -> Ticket:
        project = raw.get("project_path") or self.issues_project
        iid = int(raw["iid"])
        labels = raw.get("labels", [])
        ready = self.ready_label in labels
        web_url = str(raw.get("web_url", ""))
        return Ticket(
            ref=ref or TicketRef(project=str(project), issue=iid),
            title=str(raw.get("title", "")),
            state_ready=ready,
            web_url=web_url,
        )
