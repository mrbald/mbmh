# Changelog

All notable changes are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Planned
- Ticket-structure rules: parent EPIC state (`Ready for Release` for done work,
  `In Progress` at commit time) and minimum-quality descriptions.
- More trackers (GitHub Issues, Jira) behind the `IssueTrackerBackend` protocol.

## [0.1.0] — unreleased

### Added
- Release-branch scope validation against a GitLab milestone.
- Six finding categories: `unauthorized`, `not-ready`, `missing`, `dropped`,
  `orphan`, `ambiguous-equivalence`.
- GitLab backend in two modes: live REST API (`GITLAB_API_TOKEN`) and an
  offline fixture mode (`--fixture-dir`); vendor-free validator core behind an
  `IssueTrackerBackend` protocol.
- Configurable base branch (`--base-branch`, default `main`).
- Markdown report; exit codes `0` (clean) / `1` (findings) / `2` (bad config).
