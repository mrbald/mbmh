# How mbmh checks a release

mbmh compares **what shipped** (the commits between two points in git) against
**what was promised** (a milestone's tickets in your tracker) and reports where
they disagree. This page lists every check and exactly when it fires.

## The short version

- It lists the commits introduced between a **base** ref and the **release**
  ref, reads each commit's **ticket reference(s)**, and pulls the **milestone's
  tickets** from your tracker.
- It cancels out **apply+revert pairs** and treats **cherry-picks** as
  equivalent, so that noise doesn't trigger false findings.
- It then runs the **checks** below, each producing **findings** of severity
  **error** or **warning**.
- Exit code: **0** = clean, **1** = at least one *error*, **2** = bad
  configuration. Warnings alone do **not** fail the run.

## What goes in

**Commits.** mbmh lists commits reachable from `--to` but not from `--from`
(`--from` defaults to `main`; both accept a branch, tag, or commit). It walks
first-parent and skips merge commits unless `--include-merges`.

**Ticket references.** Each commit message is scanned with `--ticket-regex`
(default matches `group/project#123`, `project#42`, and bare `#7`). A bare `#7`
resolves to `--issues-project`. A commit may cite several tickets; each is
checked. (Jira keys like `PROJ-123` need a custom regex.)

**Fingerprints.** For each commit mbmh records a Gerrit `Change-Id` (if present)
and a stable `git patch-id` — used to recognise the same change across branches
(cherry-picks, back-ports).

**Reverts.** A commit using the default `git revert` message
(`This reverts commit <sha>.`) is paired with its target; if both are in range,
**both are removed** before any checks run — a change applied and then reverted
counts as *not shipped*. The report says how many pairs were collapsed. (This
applies to the previous-release commit list too.)

**Milestone tickets.** Pulled from the tracker backend
(`--tracker gitlab|github|jira|local`). Each ticket carries a title, a **ready**
flag (a label/status equal to `--ready-label`), an optional description, a kind
(issue type), and a parent epic.

## The checks

### Always on

**`orphan`** — *error*
A commit you can't trace to any ticket.
*Fires when:* a commit in range has **no** ticket reference your
`--ticket-regex` can parse.

**`unauthorized`** — *error*
A commit for work the milestone didn't sign off on.
*Fires when:* a commit references a ticket that is **not in the milestone**.
mbmh looks the ticket up in the tracker to say which — *"exists but not in this
milestone"* or *"does not exist in tracker."*

**`not-ready`** — *error*
A commit for a milestone ticket that isn't approved to ship.
*Fires when:* a commit references a milestone ticket whose state is **not**
ready (its label/status ≠ `--ready-label`, default "Ready for Release").

**`missing`** — *error*
The milestone promised it, but nothing shipped.
*Fires when:* a milestone ticket has **no commits** in range referencing it.

### When you pass a previous release (`--previous`)

These compare the current release to a prior one to catch regressions. mbmh
matches commits across the two by `Change-Id` first, then `patch-id`, so
cherry-picks and back-ports line up.

**`dropped`** — *error*
Work that was in the last release but isn't in this one.
*Fires when:* a previous-release commit **has a fingerprint** (Change-Id or
patch-id) but **no equivalent** on the current release.

**`ambiguous-equivalence`** — *warning*
Can't tell whether something was dropped.
*Fires when:* a previous-release commit has **neither** a Change-Id **nor** a
patch-id (e.g. an empty-diff commit), so equivalence can't be decided. Flagged
for a human rather than silently dropped.

### Opt-in: ticket structure

**`poor-description`** — *warning* — enable with `--check-descriptions`
A milestone ticket with a thin or empty description.
*Fires when:* a milestone ticket's description has **fewer than
`--min-description-words`** words (default 5). A length/non-emptiness heuristic,
**not** a grammar check.

**`missing-epic`** — *error* — enable with `--require-epic`
A milestone ticket that doesn't roll up to an epic.
*Fires when:* a milestone ticket has **no parent epic**, or its parent **isn't
of kind `--epic-kind`** (default "epic"). Tickets that are themselves epics are
exempt. How the parent epic is found depends on the tracker (native for
Jira/local/GitHub; via `GitLabEpicResolver` for live GitLab; or your own
`EpicResolver` — see the README "Extending" section).

**`epic-not-ready`** — *error* — enable with `--require-epic`
A milestone ticket whose epic isn't approved to ship.
*Fires when:* the ticket's parent epic exists but is **not** in the ready state.

> The epic rule checks the *"done"* half of "parent epic **Ready for Release**
> for done work / **In Progress** at commit time." The *"In Progress at commit
> time"* half needs per-commit state history mbmh doesn't have, so it isn't
> checked.

## Severities and exit codes

| Severity | Categories | Effect |
|---|---|---|
| **error** | `unauthorized`, `not-ready`, `missing`, `dropped`, `orphan`, `missing-epic`, `epic-not-ready` | exit code **1** if any are present |
| **warning** | `ambiguous-equivalence`, `poor-description` | reported, but do **not** fail the run |

Exit codes: **0** clean · **1** one or more errors · **2** bad configuration
(e.g. a missing token, or a `todo.txt` that isn't found).

## What the report shows

A markdown report with five parts:

- **Header** — counts (commits inspected, milestone tickets, reverts collapsed)
  and a per-category findings summary.
- **Errors** — every finding, grouped by category, linked to its ticket/commit.
- **Scope tree** — milestone → ticket → commits, plus orphan commits and any
  unauthorized ticket references.
- **Reconciliation** — a collapsible audit trail: every commit walked, the
  milestone tickets, dropped previous-branch commits, and the reverts collapsed.
- **Footer** — timestamp, tool version, and data source (`fixture` / `live-api`
  / `todo.txt`).
