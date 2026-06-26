"""Render a ValidationResult to a markdown report.

Five sections per spec: Header, Errors, Scope tree, Reconciliation, Footer.
"""

from __future__ import annotations

from datetime import UTC, datetime

from mbmh import __version__
from mbmh.models import (
    CATEGORY_SEVERITY,
    Commit,
    ErrorCategory,
    Finding,
    Severity,
    Ticket,
    ValidationResult,
)


def render_report(
    result: ValidationResult,
    *,
    now: datetime | None = None,
) -> str:
    parts: list[str] = []
    parts.append(_header(result))
    parts.append(_errors(result))
    parts.append(_scope_tree(result))
    parts.append(_reconciliation(result))
    parts.append(_footer(result, now=now))
    return "\n".join(parts).rstrip() + "\n"


def _header(result: ValidationResult) -> str:
    counts = result.error_counts
    lines: list[str] = []
    lines.append(f"# Release scope report — `{result.release_name}`")
    lines.append("")
    lines.append(f"- Milestone: **{result.milestone_name}**")
    lines.append(f"- Release branch: `{result.release_branch}`")
    if result.previous_branch is not None:
        lines.append(f"- Previous branch: `{result.previous_branch}`")
    lines.append(f"- Commits inspected: **{len(result.commits)}**")
    lines.append(f"- Milestone tickets: **{len(result.milestone_tickets)}**")
    if counts:
        lines.append("- Findings by category:")
        # Stable ordering by category enum order, then count desc.
        for cat in ErrorCategory:
            n = counts.get(cat, 0)
            if n == 0:
                continue
            sev = CATEGORY_SEVERITY[cat].value
            lines.append(f"  - `{cat.value}` ({sev}): **{n}**")
    else:
        lines.append("- Findings: **none**")
    return "\n".join(lines) + "\n"


def _errors(result: ValidationResult) -> str:
    lines: list[str] = ["## Errors", ""]
    if not result.findings:
        lines.append("_No errors or warnings._")
        return "\n".join(lines) + "\n"

    grouped: dict[ErrorCategory, list[Finding]] = {}
    for f in result.findings:
        grouped.setdefault(f.category, []).append(f)

    for cat in ErrorCategory:
        if cat not in grouped:
            continue
        sev = CATEGORY_SEVERITY[cat]
        lines.append(f"### `{cat.value}` ({sev.value})")
        lines.append("")
        # Stable order: by commit_sha then ticket str then message.
        items = sorted(
            grouped[cat],
            key=lambda f: (
                f.commit_sha or "",
                str(f.ticket) if f.ticket else "",
                f.message,
            ),
        )
        for f in items:
            link = _finding_link(f, result)
            extra = f" — {f.detail}" if f.detail else ""
            lines.append(f"- {f.message}{extra}{link}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _finding_link(f: Finding, result: ValidationResult) -> str:
    """Best-effort link rendering. Backend-aware via ticket web_url when known."""
    chunks: list[str] = []
    if f.ticket is not None:
        ticket_url = _ticket_url(f.ticket, result)
        if ticket_url:
            chunks.append(f" [{f.ticket}]({ticket_url})")
        else:
            chunks.append(f" `{f.ticket}`")
    if f.commit_sha:
        chunks.append(f" `{f.commit_sha[:12]}`")
    return "".join(chunks)


def _ticket_url(ref: object, result: ValidationResult) -> str:
    for t in result.milestone_tickets:
        if t.ref == ref:
            return t.web_url
    return ""


def _scope_tree(result: ValidationResult) -> str:
    """milestone → ticket → commits, plus a section for orphans."""
    lines: list[str] = ["## Scope tree", ""]
    lines.append(f"- Milestone: **{result.milestone_name}**")

    # Tickets in milestone, sorted by ref string for determinism.
    tickets_sorted = sorted(result.milestone_tickets, key=lambda t: str(t.ref))
    for t in tickets_sorted:
        lines.append(_ticket_branch(t, result))
        commits = result.commits_by_ticket.get(str(t.ref), [])
        commits_sorted = sorted(commits, key=lambda c: c.sha)
        for c in commits_sorted:
            lines.append(f"    - `{c.sha[:12]}` {c.subject}")
        if not commits:
            lines.append("    - _(no commits)_")

    # Orphan commits — referenced no tickets at all.
    orphan_commits = [c for c in result.commits if not c.ticket_refs]
    if orphan_commits:
        lines.append("- Orphan commits (no ticket reference):")
        for c in sorted(orphan_commits, key=lambda c: c.sha):
            lines.append(f"    - `{c.sha[:12]}` {c.subject}")

    # Unauthorized refs — commits cited tickets that aren't in the milestone.
    unauth_refs: dict[str, list[Commit]] = {}
    milestone_ref_strs = {str(t.ref) for t in result.milestone_tickets}
    for c in result.commits:
        for ref in c.ticket_refs:
            if str(ref) not in milestone_ref_strs:
                unauth_refs.setdefault(str(ref), []).append(c)
    if unauth_refs:
        lines.append("- Unauthorized ticket refs (not in milestone):")
        for ref_str in sorted(unauth_refs):
            lines.append(f"  - `{ref_str}`")
            for c in sorted(unauth_refs[ref_str], key=lambda c: c.sha):
                lines.append(f"    - `{c.sha[:12]}` {c.subject}")
    return "\n".join(lines) + "\n"


def _ticket_branch(t: Ticket, result: ValidationResult) -> str:
    state = "ready" if t.state_ready else "not-ready"
    label = f"[{t.ref}]({t.web_url})" if t.web_url else f"`{t.ref}`"
    return f"  - {label} — {t.title} _({state})_"


def _reconciliation(result: ValidationResult) -> str:
    """Collapsible audit trail. Not part of the strict comparison per spec."""
    lines: list[str] = [
        "## Reconciliation",
        "",
        "<details>",
        "<summary>full audit trail</summary>",
        "",
    ]
    lines.append(f"_Commits walked_: {len(result.commits)}")
    lines.append("")
    for c in result.commits:
        refs = ", ".join(str(r) for r in c.ticket_refs) or "_(no refs)_"
        lines.append(f"- `{c.sha[:12]}` {c.subject} — refs: {refs}")
    lines.append("")
    lines.append(f"_Milestone tickets_: {len(result.milestone_tickets)}")
    lines.append("")
    for t in result.milestone_tickets:
        s = "ready" if t.state_ready else "not-ready"
        lines.append(f"- `{t.ref}` ({s}) — {t.title}")
    if result.dropped_previous_commits:
        lines.append("")
        lines.append(
            f"_Previous-branch commits without equivalent_: {len(result.dropped_previous_commits)}"
        )
        for c in result.dropped_previous_commits:
            lines.append(f"- `{c.sha[:12]}` {c.subject}")
    lines.append("")
    lines.append("</details>")
    return "\n".join(lines) + "\n"


def _footer(result: ValidationResult, *, now: datetime | None) -> str:
    ts = (now or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [
        "## Footer",
        "",
        f"- Generated: `{ts}`",
        f"- Tool version: `{__version__}`",
        f"- Data source: `{result.fixture_marker}`",
    ]
    # Severity summary for caller convenience.
    sev_count = sum(1 for f in result.findings if f.severity is Severity.ERROR)
    warn_count = sum(1 for f in result.findings if f.severity is Severity.WARNING)
    lines.append(f"- Errors: **{sev_count}** — Warnings: **{warn_count}**")
    return "\n".join(lines) + "\n"
