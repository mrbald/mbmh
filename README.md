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

The validator core is **vendor-free** — it talks to an `IssueTrackerBackend`
protocol. **GitLab** and **GitHub** are supported today; more can be added.

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

### Compare two points

`--from` and `--to` take any ref — branch, tag, or commit — so you can diff two
release tags on the same branch (e.g. `--from v1.3.0 --to v1.4.0`). Cherry-picked
commits are matched by `patch-id` / `Change-Id`, and an apply-then-revert pair
(default `git revert` message) cancels out. `--from` defaults to `main`; the old
`--base-branch` / `--release-branch` names still work.

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

- Ticket-structure rules: parent **EPIC** state (`Ready for Release` for done
  work, `In Progress` at commit time) and minimum-quality descriptions.
- More trackers (e.g. Jira) behind the same `IssueTrackerBackend`.

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
