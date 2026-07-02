"""OpenKB wiki lint — health checks on the compiled knowledge base.

Mirrors `openkb lint` from the OpenKB CLI.  Checks:

  - ghost_links      : [[wikilinks]] pointing to pages that do not exist.
  - orphans          : Pages that no other page links to (isolated nodes).
  - empty_content    : Pages whose content is very short or blank.
  - missing_summary  : Pages without a one-liner description.
  - duplicate_titles : Case-insensitive title collisions.

Returns a structured LintReport that the API route serialises as JSON.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

_MIN_CONTENT_CHARS = 80          # pages shorter than this are flagged as empty
_IGNORE_CATEGORIES = {"index"}   # the index page is meta — skip most checks


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class LintIssue:
    severity: str        # "error" | "warning" | "info"
    check: str           # check name, e.g. "ghost_links"
    page_title: str
    page_id: str
    detail: str


@dataclass
class LintReport:
    issues: list[LintIssue] = field(default_factory=list)
    pages_checked: int = 0

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "warning")

    @property
    def passed(self) -> bool:
        return self.error_count == 0

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "pages_checked": self.pages_checked,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "issues": [
                {
                    "severity": i.severity,
                    "check": i.check,
                    "page_title": i.page_title,
                    "page_id": i.page_id,
                    "detail": i.detail,
                }
                for i in self.issues
            ],
        }


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def lint_wiki(pages: list[Any]) -> LintReport:  # list[OpenKBPage]
    """Run all health checks on the compiled OpenKB wiki.

    Args:
        pages : All OpenKBPage rows for the KB.

    Returns:
        LintReport with categorised issues.
    """
    report = LintReport()

    content_pages = [p for p in pages if p.page_category not in _IGNORE_CATEGORIES]
    report.pages_checked = len(content_pages)

    if not content_pages:
        return report

    # Build lookup structures
    titles_lower: dict[str, list[Any]] = {}          # lowercase title → list of pages
    all_titles_lower: set[str] = {p.title.lower() for p in pages}

    for p in content_pages:
        key = p.title.lower()
        titles_lower.setdefault(key, []).append(p)

    # Build reverse-link map: title_lower → set of page ids that link to it
    linked_to: dict[str, set[str]] = {p.title.lower(): set() for p in content_pages}
    for p in content_pages:
        for linked_title in _extract_wikilinks(p.content or ""):
            if linked_title.lower() in linked_to:
                linked_to[linked_title.lower()].add(str(p.id))

    # ── Check: ghost wikilinks ────────────────────────────────────────────────
    for p in content_pages:
        ghosts = [
            t for t in _extract_wikilinks(p.content or "")
            if t.lower() not in all_titles_lower
        ]
        for ghost in ghosts:
            report.issues.append(
                LintIssue(
                    severity="warning",
                    check="ghost_links",
                    page_title=p.title,
                    page_id=str(p.id),
                    detail=f"[[{ghost}]] links to a page that does not exist.",
                )
            )

    # ── Check: orphaned pages ─────────────────────────────────────────────────
    for p in content_pages:
        if p.page_category == "summary":
            continue  # summary pages are root nodes — expected to be entry points
        if not linked_to.get(p.title.lower()):
            report.issues.append(
                LintIssue(
                    severity="info",
                    check="orphans",
                    page_title=p.title,
                    page_id=str(p.id),
                    detail="No other page links to this page.",
                )
            )

    # ── Check: empty / very short content ────────────────────────────────────
    for p in content_pages:
        content_len = len((p.content or "").strip())
        if content_len < _MIN_CONTENT_CHARS:
            report.issues.append(
                LintIssue(
                    severity="error" if content_len == 0 else "warning",
                    check="empty_content",
                    page_title=p.title,
                    page_id=str(p.id),
                    detail=(
                        "Page content is empty."
                        if content_len == 0
                        else f"Page content is very short ({content_len} chars)."
                    ),
                )
            )

    # ── Check: missing one-liner summary ─────────────────────────────────────
    for p in content_pages:
        if not (p.summary or "").strip():
            report.issues.append(
                LintIssue(
                    severity="warning",
                    check="missing_summary",
                    page_title=p.title,
                    page_id=str(p.id),
                    detail="Page is missing a one-liner description (summary field).",
                )
            )

    # ── Check: duplicate titles (case-insensitive) ────────────────────────────
    for key, group in titles_lower.items():
        if len(group) > 1:
            ids = ", ".join(str(p.id) for p in group)
            for p in group:
                report.issues.append(
                    LintIssue(
                        severity="error",
                        check="duplicate_titles",
                        page_title=p.title,
                        page_id=str(p.id),
                        detail=f"Title collision with {len(group) - 1} other page(s). IDs: {ids}",
                    )
                )

    return report


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_wikilinks(content: str) -> list[str]:
    """Return all [[Target]] titles found in content."""
    return re.findall(r"\[\[([^\]]+)\]\]", content)
