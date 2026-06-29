"""Jira implementation of `IssueTrackerBackend`.

Maps Jira onto the `Ticket` model:
  - milestone   -> fixVersion (release version)
  - issue key   -> ref (`PROJ-123` -> project "PROJ", issue 123)
  - status name -> ready state (ready when it equals the ready label)
  - issuetype   -> kind (e.g. "epic", "story")
  - parent      -> parent epic/issue
  - description -> plain text (string, or extracted from an ADF document)

Auth is Basic (email + API token) for Jira Cloud: set `JIRA_EMAIL`,
`JIRA_API_TOKEN`, and `JIRA_BASE_URL` (`https://<site>.atlassian.net`).

Note: commit references are Jira keys like `PROJ-123`, so pass a matching
`--ticket-regex`, e.g. `(?P<project>[A-Z][A-Z0-9]+)-(?P<issue>\\d+)`.

Targets the Jira REST v2 `search` endpoint with offset pagination; the newest
Cloud token-pagination may need tuning.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import httpx

from mbmh.config import DEFAULT_READY_LABEL
from mbmh.models import Ticket, TicketRef

_FIELDS = "summary,status,issuetype,parent,description"


def _parse_key(key: str) -> TicketRef | None:
    """Parse a Jira key `PROJ-123` into a TicketRef, or None if malformed."""
    head, _, tail = key.rpartition("-")
    if not head or not tail.isdigit():
        return None
    return TicketRef(project=head, issue=int(tail))


def _str_field(value: Any, *keys: str) -> str:
    """Walk nested dict keys and return the string leaf, or ''."""
    cur: Any = value
    for k in keys:
        if not isinstance(cur, dict):
            return ""
        cur = cast("dict[str, Any]", cur).get(k)
    return cur if isinstance(cur, str) else ""


def _get(value: Any, key: str) -> Any:
    """Return `value[key]` if value is a dict, else None."""
    return cast("dict[str, Any]", value).get(key) if isinstance(value, dict) else None


def _adf_text(value: Any) -> str:
    """Return plain text from a Jira description (a string, or an ADF document)."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        node = cast("dict[str, Any]", value)
        parts: list[str] = []
        text = node.get("text")
        if isinstance(text, str):
            parts.append(text)
        content = node.get("content")
        if isinstance(content, list):
            parts.extend(_adf_text(child) for child in cast("list[Any]", content))
        return " ".join(p for p in parts if p)
    return ""


@dataclass
class JiraBackend:
    """Jira issue-tracker backend. `issues_project` is the Jira project key."""

    issues_project: str
    ready_label: str = DEFAULT_READY_LABEL
    _milestones: dict[str, list[dict[str, Any]]] | None = None
    _issues: dict[str, dict[str, Any]] | None = None
    _client: httpx.Client | None = None
    _browse_base: str = ""
    _marker: str = "live-api"

    @classmethod
    def from_fixture_dir(
        cls,
        path: str | Path,
        *,
        issues_project: str,
        ready_label: str = DEFAULT_READY_LABEL,
    ) -> JiraBackend:
        """Fixtures mirror the API: `milestones.json` maps a fixVersion name to a
        list of issues; `issues/<KEY>.json` holds individual issues."""
        root = Path(path)
        index_path = root / "milestones.json"
        milestones: dict[str, list[dict[str, Any]]] = (
            json.loads(index_path.read_text()) if index_path.exists() else {}
        )
        issues: dict[str, dict[str, Any]] = {}
        issues_dir = root / "issues"
        if issues_dir.exists():
            for issue_file in issues_dir.glob("*.json"):
                issues[issue_file.stem] = json.loads(issue_file.read_text())
        for issue_list in milestones.values():
            for raw in issue_list:
                key = str(raw.get("key", ""))
                if key:
                    issues.setdefault(key, raw)
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
        email: str,
        token: str,
        issues_project: str,
        ready_label: str = DEFAULT_READY_LABEL,
        client: httpx.Client | None = None,
    ) -> JiraBackend:
        """Connect to Jira Cloud with Basic auth (email + API token)."""
        base = base_url.rstrip("/")
        http = client or httpx.Client(
            base_url=base,
            auth=(email, token),
            headers={"Accept": "application/json"},
            timeout=httpx.Timeout(30.0),
        )
        return cls(
            issues_project=issues_project,
            ready_label=ready_label,
            _client=http,
            _browse_base=base,
            _marker="live-api",
        )

    # ----- IssueTrackerBackend protocol surface -----

    @property
    def marker(self) -> str:
        return self._marker

    def fetch_milestone_tickets(self, milestone: str) -> list[Ticket]:
        if self._client is not None:
            jql = f'project = "{self.issues_project}" AND fixVersion = "{milestone}"'
            return [self._to_ticket(raw) for raw in self._search(jql)]
        if self._milestones is None:
            raise RuntimeError("backend not loaded; use from_fixture_dir or from_token")
        if milestone not in self._milestones:
            raise KeyError(f"unknown milestone: {milestone}")
        return [self._to_ticket(raw) for raw in self._milestones[milestone]]

    def fetch_ticket(self, ref: TicketRef) -> Ticket | None:
        key = f"{ref.project}-{ref.issue}"
        if self._client is not None:
            resp = self._client.get(f"/rest/api/2/issue/{key}", params={"fields": _FIELDS})
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return self._to_ticket(resp.json())
        if self._issues is None:
            raise RuntimeError("backend not loaded; use from_fixture_dir or from_token")
        raw = self._issues.get(key)
        return self._to_ticket(raw) if raw is not None else None

    def close(self) -> None:
        """Close the live HTTP client, if any. A no-op in fixture mode."""
        if self._client is not None:
            self._client.close()

    # ----- live API internals -----

    def _search(self, jql: str) -> list[dict[str, Any]]:
        """Run a JQL search, following offset pagination to completion."""
        assert self._client is not None
        out: list[dict[str, Any]] = []
        start = 0
        while True:
            resp = self._client.get(
                "/rest/api/2/search",
                params={"jql": jql, "startAt": start, "maxResults": 100, "fields": _FIELDS},
            )
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
            page: list[dict[str, Any]] = data.get("issues", [])
            out.extend(page)
            start += len(page)
            if not page or start >= int(data.get("total", start)):
                return out

    # ----- shared helpers -----

    def _to_ticket(self, raw: dict[str, Any]) -> Ticket:
        key = str(raw.get("key", ""))
        ref = _parse_key(key) or TicketRef(project=self.issues_project, issue=0)
        fields = raw.get("fields", {})
        status = _str_field(fields, "status", "name")
        parent_key = _str_field(fields, "parent", "key")
        return Ticket(
            ref=ref,
            title=_str_field(fields, "summary"),
            state_ready=status == self.ready_label,
            web_url=f"{self._browse_base}/browse/{key}" if self._browse_base and key else "",
            description=_adf_text(_get(fields, "description")),
            kind=_str_field(fields, "issuetype", "name").lower(),
            parent=_parse_key(parent_key) if parent_key else None,
        )
