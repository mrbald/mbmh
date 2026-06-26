# Contributing

Thanks for your interest. Please open an issue before a large PR so we can
agree on scope first.

## Development setup

```sh
git clone https://github.com/mrbald/mbmh
cd mbmh
uv sync
```

## Checks (all must pass)

```sh
uv run pytest
uv run ruff check
uv run ruff format --check
uv run pyright
```

`pyright` runs in strict mode — keep it clean.

## Pull requests

- One coherent change per PR.
- Add tests for new behaviour.
- Update `CHANGELOG.md` under `[Unreleased]`.

## Adding an issue-tracker backend

Implement `IssueTrackerBackend` (`mbmh.backend.protocol`) in a new module under
`mbmh/backend/`. The validator core, git operations, and report renderer do not
change.

## Licensing of contributions (please read)

mbmh is released under AGPL-3.0-or-later, and the maintainer also intends to
offer it under separate, more permissive terms to specific parties. For that
dual model to remain possible, the project must hold the rights to relicense
every line.

By submitting a contribution you agree that the maintainer may license your
contribution under both the AGPL **and** other terms (including permissive or
commercial licenses) — in practice, a Contributor License Agreement (CLA). The
exact CLA is still being finalised; until it is in place, outside contributions
may be held or declined. This note is not legal advice.
