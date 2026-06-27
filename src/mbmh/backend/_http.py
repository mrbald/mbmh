"""Shared HTTP helpers for live issue-tracker backends.

Both GitLab and GitHub paginate via RFC 5988 `Link` headers, so the walk lives
here rather than in each backend.
"""

from __future__ import annotations

from typing import Any

import httpx


def next_link(link_header: str) -> str | None:
    """Return the `rel="next"` URL from a `Link` header, or None."""
    for part in link_header.split(","):
        segments = part.split(";")
        url = segments[0].strip().strip("<>")
        if any(seg.strip() == 'rel="next"' for seg in segments[1:]):
            return url
    return None


def paginate(
    client: httpx.Client, path: str, params: dict[str, str | int] | None = None
) -> list[dict[str, Any]]:
    """GET `path` and follow `Link: rel="next"` pages, concatenating results."""
    out: list[dict[str, Any]] = []
    resp = client.get(path, params=params)
    while True:
        resp.raise_for_status()
        page: list[dict[str, Any]] = resp.json()
        out.extend(page)
        nxt = next_link(resp.headers.get("link", ""))
        if not nxt:
            return out
        resp = client.get(nxt)
