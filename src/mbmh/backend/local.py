"""Local `todo.txt` implementation of `IssueTrackerBackend`.

No network, no service — tickets live in a plain `todo.txt` file in your repo.
Each task line is a ticket, using standard todo.txt conventions:

    Fix login redirect loop id:42 milestone:1.4.0 @ready

  - `id:N`        the issue number (required — cite it from commits as `#N`)
  - `milestone:M` the milestone the ticket belongs to (matched by --milestone)
  - `@<ready>`    a context marking the ticket ready for release; the context
                  name is the space-stripped, lower-cased --ready-label
  - the remaining words are the title

Lines without an `id:` are ignored. Leading completion markers (`x`), dates,
priorities (`(A)`), `+project` tags and other `key:value` pairs are stripped
from the title. There is no web URL, so the report shows a bare ticket ref.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from mbmh.config import DEFAULT_READY_LABEL
from mbmh.models import Ticket, TicketRef

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_PRIORITY_RE = re.compile(r"^\([A-Z]\)$")
_KEY_RE = re.compile(r"^([A-Za-z][\w-]*):(.+)$")


@dataclass(frozen=True)
class _Task:
    number: int | None
    milestone: str | None
    title: str
    ready: bool


def _parse_line(line: str, *, ready_token: str) -> _Task | None:
    s = line.strip()
    if not s or s.startswith("#"):
        return None
    tokens = s.split()

    # Skip leading todo.txt markers: completion `x`, dates, priority `(A)`.
    i = 0
    if i < len(tokens) and tokens[i] == "x":
        i += 1
        while i < len(tokens) and _DATE_RE.match(tokens[i]):
            i += 1
    if i < len(tokens) and _PRIORITY_RE.match(tokens[i]):
        i += 1
    if i < len(tokens) and _DATE_RE.match(tokens[i]):
        i += 1

    number: int | None = None
    milestone: str | None = None
    contexts: set[str] = set()
    title_words: list[str] = []
    for tok in tokens[i:]:
        key_match = _KEY_RE.match(tok)
        if key_match:
            key, value = key_match.group(1).lower(), key_match.group(2)
            if key == "id":
                try:
                    number = int(value)
                except ValueError:
                    title_words.append(tok)
            elif key == "milestone":
                milestone = value
            # other key:value metadata is dropped from the title
            continue
        if len(tok) > 1 and tok[0] == "@":
            contexts.add(tok[1:].lower())
            continue
        if len(tok) > 1 and tok[0] == "+":  # project tag — dropped from title
            continue
        title_words.append(tok)

    return _Task(
        number=number,
        milestone=milestone,
        title=" ".join(title_words),
        ready=ready_token in contexts,
    )


@dataclass
class LocalBackend:
    """Issue tracker backed by a local `todo.txt` file. Fully offline."""

    issues_project: str
    ready_label: str = DEFAULT_READY_LABEL
    _tasks: list[_Task] = field(default_factory=list[_Task])

    @classmethod
    def from_file(
        cls,
        path: str | Path,
        *,
        issues_project: str,
        ready_label: str = DEFAULT_READY_LABEL,
    ) -> LocalBackend:
        ready_token = ready_label.replace(" ", "").lower()
        text = Path(path).read_text(encoding="utf-8")
        tasks: list[_Task] = []
        for line in text.splitlines():
            task = _parse_line(line, ready_token=ready_token)
            if task is not None:
                tasks.append(task)
        return cls(issues_project=issues_project, ready_label=ready_label, _tasks=tasks)

    @property
    def marker(self) -> str:
        return "todo.txt"

    def fetch_milestone_tickets(self, milestone: str) -> list[Ticket]:
        return [
            self._to_ticket(t)
            for t in self._tasks
            if t.number is not None and t.milestone == milestone
        ]

    def fetch_ticket(self, ref: TicketRef) -> Ticket | None:
        if ref.project != self.issues_project:
            return None
        for t in self._tasks:
            if t.number == ref.issue:
                return self._to_ticket(t)
        return None

    def close(self) -> None:
        """Nothing to release — the file is read once. Here for the Protocol."""

    def _to_ticket(self, task: _Task) -> Ticket:
        assert task.number is not None
        return Ticket(
            ref=TicketRef(project=self.issues_project, issue=task.number),
            title=task.title,
            state_ready=task.ready,
            web_url="",
        )
