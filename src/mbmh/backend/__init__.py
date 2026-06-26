"""Issue-tracker backend boundary.

The validator core depends only on `IssueTrackerBackend`. Vendor-specific
implementations (GitLab, GitHub, Jira, ...) live in their own modules.
"""

from __future__ import annotations

from mbmh.backend.protocol import IssueTrackerBackend

__all__ = ["IssueTrackerBackend"]
