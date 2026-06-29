# mbmh

[![CI](https://github.com/mrbald/mbmh/actions/workflows/ci.yml/badge.svg)](https://github.com/mrbald/mbmh/actions/workflows/ci.yml)
[![License: AGPL-3.0-or-later](https://img.shields.io/badge/license-AGPL--3.0--or--later-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/)

> **[M]essy [b]ed — [m]essy [h]ead!**

Hygiene checks for your engineering process: if you don't tidy up after
yourself, a tool should catch it — not a teammate.

**v0.1** validates a **release branch against its milestone.** Every commit on
the branch must trace to a ticket the milestone actually authorises and marks
ready; every ticket the milestone promises must actually ship. It is the first
of a planned family of process-hygiene checks.

## What it checks

| Finding | Severity | Meaning |
|---|---|---|
| `unauthorized` | error | a commit references a ticket not in the milestone |
| `not-ready` | error | a commit references a milestone ticket not marked *Ready for Release* |
| `missing` | error | a milestone ticket has no commits on the release branch |
| `dropped` | error | a previous-release commit has no patch-equivalent on this branch |
| `orphan` | error | a commit has no parseable ticket reference |
| `ambiguous-equivalence` | warning | a previous-branch commit has no fingerprint to match on |
| `poor-description` | warning | a milestone ticket's description is thin or missing (opt-in) |
| `missing-epic` | error | a milestone ticket has no parent epic (opt-in) |
| `epic-not-ready` | error | a ticket's parent epic is not Ready for Release (opt-in) |

The validator core is **vendor-free** — it talks to an `IssueTrackerBackend`
protocol. **GitLab**, **GitHub**, **Jira**, and a local **`todo.txt`** are
supported today; more can be added.

## Install

```sh
uv add "git+https://github.com/mrbald/mbmh"
# or: pipx install "git+https://github.com/mrbald/mbmh"
```

Requires Python ≥ 3.12 and `git` on the `PATH`. (A PyPI release will follow.)

## Use

Against recorded fixtures (offline, no token needed):

```sh
mbmh \
  --repo /path/to/repo \
  --release-branch release/1.4.0 \
  --milestone 1.4.0 \
  --issues-project mygroup/myproject \
  --previous-branch release/1.3.0 \
  --fixture-dir ./fixtures \
  --output report.md
```

Exit codes: `0` clean · `1` error-severity findings present · `2` bad config.

Other options: `--ready-label` (default `Ready for Release`), `--ticket-regex`,
`--include-merges`, `--output`/`-o`.

Against a live GitLab instance, set a token instead of passing `--fixture-dir`:

```sh
export GITLAB_API_TOKEN=glpat-xxxxxxxxxxxxxxxxxxxx
# self-hosted? also set: export GITLAB_BASE_URL=https://gitlab.example.com
mbmh \
  --repo /path/to/repo \
  --release-branch release/1.4.0 \
  --milestone 1.4.0 \
  --issues-project mygroup/myproject
```

The token needs `read_api` scope on the issues project.

### GitHub

Use `--tracker github` with a `GITHUB_TOKEN`; `--issues-project` is `owner/repo`:

```sh
export GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx
# GitHub Enterprise? also set: export GITHUB_API_URL=https://ghe.example.com/api/v3
mbmh \
  --tracker github \
  --repo /path/to/repo \
  --to v1.4.0 --from v1.3.0 \
  --milestone 1.4.0 \
  --issues-project myorg/myrepo
```

### Jira

`--tracker jira` with Basic auth (email + API token). The milestone maps to a
**fixVersion** and the ready state to a **status** name:

```sh
export JIRA_BASE_URL=https://your-site.atlassian.net
export JIRA_EMAIL=you@example.com
export JIRA_API_TOKEN=xxxxxxxx
mbmh --tracker jira \
  --repo . --to v1.4.0 --from v1.3.0 \
  --milestone 1.4.0 --issues-project PROJ \
  --ready-label "Ready for Release" \
  --ticket-regex '(?P<project>[A-Z][A-Z0-9]+)-(?P<issue>\d+)'
```

Commits reference Jira keys like `PROJ-123`, so the `--ticket-regex` above is
required. Epics are native, so `--require-epic` works directly.

### Local (todo.txt)

No tracker at all — keep tickets in a `todo.txt` in your repo, fully offline.
`--tracker local` reads `<repo>/todo.txt` (or `--todo-file PATH`); each task
line is a ticket:

```text
Fix login redirect loop id:42 milestone:1.4.0 @ready
Add signup form id:43 milestone:1.4.0
```

`id:N` is the issue number (cite it from commits as `#42`), `milestone:M` groups
by release, and the `@ready` context marks it ready for release. Lines without
an `id:` are ignored.

```sh
mbmh --tracker local \
  --repo . --to v1.4.0 --from v1.3.0 \
  --milestone 1.4.0 --issues-project myrepo --ready-label ready
```

### Compare two points

`--from` and `--to` take any ref — branch, tag, or commit — so you can diff two
release tags on the same branch (e.g. `--from v1.3.0 --to v1.4.0`). Cherry-picked
commits are matched by `patch-id` / `Change-Id`, and an apply-then-revert pair
(default `git revert` message) cancels out. `--from` defaults to `main`; the old
`--base-branch` / `--release-branch` names still work.

### Ticket-structure rules (opt-in)

Two extra checks, off by default:

- `--check-descriptions` (with `--min-description-words N`, default 5) flags
  milestone tickets whose description is missing or too short. A length
  heuristic, not a grammar engine.
- `--require-epic` (with `--epic-kind`, default `epic`) requires each milestone
  ticket to roll up to a parent epic that is *Ready for Release*.

The epic rule is fully wired for the local `todo.txt` backend — mark the epic
`type:epic` and point children at it with `parent:<id>`:

```text
Build the auth subsystem end to end id:100 type:epic @ready
Implement the login form fully id:42 milestone:1.4.0 parent:100 @ready
```

GitLab and GitHub populate descriptions (and best-effort issue type); native
epic linking for them is a later step. Only the *Ready-for-Release* half of the
rule is checked — "In Progress at commit time" would need per-commit state
history.

## Fixture layout

Fixtures mirror the GitLab REST JSON shape:

```
fixtures/
  milestones.json                 # [{"id": 99, "title": "1.4.0"}, ...]
  milestone-99-issues.json        # [{issue JSON}, ...]
  issues/
    mygroup__myproject/           # "/" in a project path is encoded as "__"
      7.json                      # single-issue JSON
```

## Roadmap

`mbmh` is meant to grow into a set of engineering-hygiene checks. Next up:

- Native epic linking for the GitLab and GitHub backends.

## Add a backend

Implement `IssueTrackerBackend` (`mbmh.backend.protocol`) for GitHub, Jira,
Linear, or any other tracker. The validator core, git operations, and report
renderer don't change.

## License

[AGPL-3.0-or-later](LICENSE) — strong, network-aware copyleft: use it, fork it,
even run it as a service, but share your changes back.

A separate **commercial / non-copyleft license** is available from the
copyright holder for those who can't accept the AGPL. Open an issue to ask.

## Development

```sh
uv sync
uv run pytest
uv run ruff check && uv run ruff format --check
uv run pyright
```

---

_Most of the code is written with the assistance of industrial coding agents —
primarily Anthropic's Claude — while the original ideas and design are my own._
