# Changelog

All notable changes are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Planned
- Live GitLab API backend (`from_token`) via personal or CI job token.
- Configurable base branch (`--base-branch`), instead of assuming `main`.
- Ticket-structure rules: parent EPIC state and minimum-quality descriptions.

## [0.1.0] — unreleased

### Added
- Release-branch scope validation against a GitLab milestone.
- Six finding categories: `unauthorized`, `not-ready`, `missing`, `dropped`,
  `orphan`, `ambiguous-equivalence`.
- Offline fixture backend (`--fixture-dir`); a vendor-free validator core
  behind an `IssueTrackerBackend` protocol.
- Markdown report; exit codes `0` (clean) / `1` (findings) / `2` (bad config).
