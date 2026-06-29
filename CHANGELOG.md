# Changelog

All notable changes are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Jira backend (`--tracker jira`, Basic auth) in live and fixture modes:
  fixVersion as milestone, status name as the ready state, native epics for
  `--require-epic`. Commit refs are Jira keys (`PROJ-123`) — pass a matching
  `--ticket-regex`.
- Ticket-structure rules (opt-in): `--check-descriptions` flags milestone
  tickets with thin or missing descriptions; `--require-epic` requires each
  milestone ticket to roll up to a parent epic that is Ready for Release. Fully
  wired for the local `todo.txt` backend (`type:` / `parent:`); description
  checks work on all backends.

### Planned
- Native epic linking for the GitLab and GitHub backends.

## [0.2.0] — 2026-06-28

### Added
- Local `todo.txt` backend (`--tracker local`): tickets in a plain text file in
  your repo, fully offline — no token, no network. Each task is a ticket
  (`id:`, `milestone:`, `@ready`).
- GitHub Issues backend (`--tracker github`, `GITHUB_TOKEN`) in live and
  fixture modes, alongside GitLab.
- Diff any two refs — branch, tag, or commit — via `--from` / `--to`
  (`--base-branch` / `--release-branch` kept as aliases).
- Revert handling: an apply+revert pair (default `git revert` message) cancels
  out, so reverted work no longer counts as shipped.

## [0.1.0] — 2026-06-27

### Added
- Release-branch scope validation against a GitLab milestone.
- Six finding categories: `unauthorized`, `not-ready`, `missing`, `dropped`,
  `orphan`, `ambiguous-equivalence`.
- GitLab backend in two modes: live REST API (`GITLAB_API_TOKEN`) and an
  offline fixture mode (`--fixture-dir`); vendor-free validator core behind an
  `IssueTrackerBackend` protocol.
- Configurable base branch (`--base-branch`, default `main`).
- Markdown report; exit codes `0` (clean) / `1` (findings) / `2` (bad config).
