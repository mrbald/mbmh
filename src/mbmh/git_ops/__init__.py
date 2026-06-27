"""Git operations: walks, patch-ids, ticket extraction."""

from __future__ import annotations

from mbmh.git_ops.commits import (
    RevertCollapse,
    collapse_reverts,
    collapse_reverts_detailed,
    extract_ticket_refs,
    list_commits,
    patch_equivalence_set,
)

__all__ = [
    "RevertCollapse",
    "collapse_reverts",
    "collapse_reverts_detailed",
    "extract_ticket_refs",
    "list_commits",
    "patch_equivalence_set",
]
