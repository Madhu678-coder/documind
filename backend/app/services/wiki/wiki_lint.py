"""Wiki Lint — 7 structural health checks for the Karpathy LLM Wiki pattern.

Checks (mirrors Karpathy's lint spec):
  1. broken_links     — [[wikilinks]] pointing to non-existent pages
  2. orphan_pages     — pages with zero inbound links from other pages
  3. missing_backlinks — A links to B but B doesn't link back to A
  4. sparse_articles  — pages under 200 words (likely incomplete)
  5. stale_articles   — pages whose source document count differs from wiki_page.source_doc_ids
  6. source_coverage  — documents in the KB that have no corresponding wiki pages
  7. contradictions   — conflicting claims across pages (LLM-based, optional)

Usage:
    report = await run_lint(kb_id, db, llm=provider, run_llm_checks=True)
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.services.llm.provider import LLMProvider

import logging
logger = logging.getLogger(__name__)


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class LintIssue:
    check: str          # which check produced this
    severity: str       # "error" | "warning" | "suggestion"
    page_title: str
    message: str
    fix_hint: str = ""


@dataclass
class LintReport:
    kb_id: str
    run_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    issues: list[LintIssue] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    # Convenience counts
    @property
    def errors(self) -> list[LintIssue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[LintIssue]:
        return [i for i in self.issues if i.severity == "warning"]

    @property
    def suggestions(self) -> list[LintIssue]:
        return [i for i in self.issues if i.severity == "suggestion"]

    def to_markdown(self) -> str:
        lines = [
            f"# Wiki Lint Report",
            f"",
            f"**KB:** {self.kb_id}  ",
            f"**Run:** {self.run_at}  ",
            f"**Errors:** {len(self.errors)}  |  "
            f"**Warnings:** {len(self.warnings)}  |  "
            f"**Suggestions:** {len(self.suggestions)}",
            "",
        ]

        # Stats
        if self.stats:
            lines.append("## Stats")
            for k, v in self.stats.items():
                lines.append(f"- {k}: {v}")
            lines.append("")

        if not self.issues:
            lines.append("✅ No issues found — wiki is healthy.")
            return "\n".join(lines)

        # Group by check
        by_check: dict[str, list[LintIssue]] = {}
        for issue in self.issues:
            by_check.setdefault(issue.check, []).append(issue)

        severity_icon = {"error": "🔴", "warning": "🟡", "suggestion": "🔵"}

        for check, issues in by_check.items():
            lines.append(f"## {check.replace('_', ' ').title()}")
            for i in issues:
                icon = severity_icon.get(i.severity, "⚪")
                lines.append(f"{icon} **{i.page_title}** — {i.message}")
                if i.fix_hint:
                    lines.append(f"   *Fix: {i.fix_hint}*")
            lines.append("")

        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "kb_id": self.kb_id,
            "run_at": self.run_at,
            "stats": self.stats,
            "summary": {
                "errors": len(self.errors),
                "warnings": len(self.warnings),
                "suggestions": len(self.suggestions),
                "total": len(self.issues),
            },
            "issues": [
                {
                    "check": i.check,
                    "severity": i.severity,
                    "page_title": i.page_title,
                    "message": i.message,
                    "fix_hint": i.fix_hint,
                }
                for i in self.issues
            ],
        }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_wikilinks(content: str) -> set[str]:
    """Return set of all [[Title]] link targets in content."""
    return set(re.findall(r'\[\[([^\]]+)\]\]', content or ""))


def _word_count(content: str) -> int:
    """Count words in content, stripping frontmatter."""
    # Strip YAML frontmatter
    if content.startswith("---"):
        end = content.find("\n---\n", 4)
        if end != -1:
            content = content[end + 5:]
    return len(content.split())


# ── Individual checks ─────────────────────────────────────────────────────────

def check_broken_links(pages: list[Any]) -> list[LintIssue]:
    """Check 1: [[wikilinks]] pointing to non-existent pages."""
    valid_titles = {p.title.lower() for p in pages}
    issues = []
    for page in pages:
        links = _extract_wikilinks(page.content or "")
        for link in links:
            if link.lower() not in valid_titles:
                issues.append(LintIssue(
                    check="broken_links",
                    severity="error",
                    page_title=page.title,
                    message=f"Links to [[{link}]] which does not exist",
                    fix_hint=f"Create a page titled '{link}' or remove the wikilink",
                ))
    return issues


def check_orphan_pages(pages: list[Any]) -> list[LintIssue]:
    """Check 2: pages with zero inbound links from other pages."""
    # Count inbound links per page
    inbound: dict[str, int] = {p.title.lower(): 0 for p in pages}
    for page in pages:
        for link in _extract_wikilinks(page.content or ""):
            key = link.lower()
            if key in inbound:
                inbound[key] += 1

    issues = []
    for page in pages:
        if page.page_type in ("index", "log", "qa"):
            continue  # structural pages don't need inbound links
        if inbound.get(page.title.lower(), 0) == 0:
            issues.append(LintIssue(
                check="orphan_pages",
                severity="warning",
                page_title=page.title,
                message="No other pages link to this page",
                fix_hint="Add [[wikilinks]] from related pages, or this page may be redundant",
            ))
    return issues


def check_missing_backlinks(pages: list[Any]) -> list[LintIssue]:
    """Check 3: A links to B but B doesn't link back to A."""
    title_map = {p.title.lower(): p.title for p in pages}
    outbound: dict[str, set[str]] = {}
    for page in pages:
        outbound[page.title.lower()] = {
            link.lower() for link in _extract_wikilinks(page.content or "")
            if link.lower() in title_map
        }

    issues = []
    for page in pages:
        if page.page_type in ("index", "log"):
            continue
        a = page.title.lower()
        for b in outbound.get(a, set()):
            # Check if B links back to A
            if a not in outbound.get(b, set()):
                b_display = title_map.get(b, b)
                issues.append(LintIssue(
                    check="missing_backlinks",
                    severity="suggestion",
                    page_title=page.title,
                    message=f"Links to [[{b_display}]] but [[{b_display}]] does not link back",
                    fix_hint=f"Add [[{page.title}]] to the '{b_display}' page",
                ))
    return issues


def check_sparse_articles(pages: list[Any], min_words: int = 200) -> list[LintIssue]:
    """Check 4: pages under min_words (likely incomplete)."""
    issues = []
    for page in pages:
        if page.page_type in ("index", "log"):
            continue
        wc = _word_count(page.content or "")
        if wc < min_words:
            issues.append(LintIssue(
                check="sparse_articles",
                severity="warning",
                page_title=page.title,
                message=f"Only {wc} words (minimum recommended: {min_words})",
                fix_hint="Re-upload the source document or manually expand this page",
            ))
    return issues


def check_stale_articles(pages: list[Any], doc_ids_in_kb: set[str]) -> list[LintIssue]:
    """Check 5: pages whose source_doc_ids reference documents no longer in the KB."""
    issues = []
    for page in pages:
        if page.page_type in ("index", "log"):
            continue
        stale = [d for d in (page.source_doc_ids or []) if d not in doc_ids_in_kb]
        if stale:
            issues.append(LintIssue(
                check="stale_articles",
                severity="warning",
                page_title=page.title,
                message=f"References {len(stale)} deleted document(s): {stale[:2]}",
                fix_hint="Delete this page or re-upload the source documents",
            ))
    return issues


def check_source_coverage(pages: list[Any], doc_ids_in_kb: set[str]) -> list[LintIssue]:
    """Check 6: documents in KB that have not contributed to any wiki page."""
    docs_with_pages: set[str] = set()
    for page in pages:
        for d in (page.source_doc_ids or []):
            docs_with_pages.add(d)

    issues = []
    for doc_id in doc_ids_in_kb:
        if doc_id not in docs_with_pages:
            issues.append(LintIssue(
                check="source_coverage",
                severity="warning",
                page_title="(KB-level)",
                message=f"Document {doc_id[:8]}... has no wiki pages",
                fix_hint="Re-trigger indexing for this document",
            ))
    return issues


# ── LLM check: contradictions ─────────────────────────────────────────────────

_CONTRADICTION_SYSTEM = """\
You are reviewing wiki pages for contradictions.
Given pairs of page summaries, identify any that contain conflicting claims about the same topic.

Return ONLY valid JSON:
{"contradictions": [
  {"page_a": "Title A", "page_b": "Title B", "description": "brief description of conflict"}
]}
If no contradictions found, return {"contradictions": []}.
"""


async def check_contradictions(pages: list[Any], llm: "LLMProvider") -> list[LintIssue]:
    """Check 7: conflicting claims across pages (LLM-based)."""
    content_pages = [p for p in pages if p.page_type not in ("index", "log", "qa") and p.summary]
    if len(content_pages) < 2:
        return []

    # Build compact summaries for the LLM
    summaries = "\n".join(
        f"- **{p.title}**: {(p.summary or '')[:200]}"
        for p in content_pages[:30]  # cap to avoid token overflow
    )

    messages = [{"role": "user", "content": f"Wiki page summaries:\n{summaries}"}]

    try:
        response = await llm.complete(messages, system_prompt=_CONTRADICTION_SYSTEM, max_tokens=2048)
        raw = response.content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1].removeprefix("json").strip()
        import json
        data = json.loads(raw)
        contradictions = data.get("contradictions", [])

        issues = []
        for c in contradictions:
            page_a = c.get("page_a", "")
            page_b = c.get("page_b", "")
            desc = c.get("description", "")
            if page_a and page_b and desc:
                issues.append(LintIssue(
                    check="contradictions",
                    severity="error",
                    page_title=page_a,
                    message=f"Possible contradiction with [[{page_b}]]: {desc}",
                    fix_hint="Review both pages and add a conflict note: > ⚠️ **Conflict**: ...",
                ))
        return issues
    except Exception as exc:
        logger.warning("Contradiction check failed", extra={"error": str(exc)})
        return []


# ── Main entry point ──────────────────────────────────────────────────────────

async def run_lint(
    kb_id: uuid.UUID,
    db: "AsyncSession",
    llm: "LLMProvider | None" = None,
    run_llm_checks: bool = True,
) -> LintReport:
    """Run all 7 lint checks on a wiki KB.

    Args:
        kb_id: The knowledge base UUID.
        db: Async DB session.
        llm: LLM provider (required if run_llm_checks=True).
        run_llm_checks: Whether to run the contradiction check (costs tokens).

    Returns:
        LintReport with all issues and stats.
    """
    from sqlalchemy import select
    from app.models.wiki_page import WikiPage
    from app.models.document import Document, DocumentStatus

    report = LintReport(kb_id=str(kb_id))

    # Load all wiki pages for this KB
    pages_result = await db.execute(
        select(WikiPage).where(WikiPage.kb_id == kb_id)
    )
    all_pages = pages_result.scalars().all()
    content_pages = [p for p in all_pages if p.page_type not in ("index", "log")]

    # Load all ready document IDs for this KB
    docs_result = await db.execute(
        select(Document.id).where(
            Document.kb_id == kb_id,
            Document.status == DocumentStatus.ready,
        )
    )
    doc_ids_in_kb = {str(row[0]) for row in docs_result.all()}

    report.stats = {
        "total_pages": len(content_pages),
        "concept_pages": sum(1 for p in content_pages if p.page_type == "concept"),
        "connection_pages": sum(1 for p in content_pages if p.page_type == "connection"),
        "qa_pages": sum(1 for p in content_pages if p.page_type == "qa"),
        "documents_in_kb": len(doc_ids_in_kb),
        "has_index": any(p.page_type == "index" for p in all_pages),
        "has_log": any(p.page_type == "log" for p in all_pages),
    }

    # Run structural checks (free)
    report.issues.extend(check_broken_links(content_pages))
    report.issues.extend(check_orphan_pages(content_pages))
    report.issues.extend(check_missing_backlinks(content_pages))
    report.issues.extend(check_sparse_articles(content_pages))
    report.issues.extend(check_stale_articles(content_pages, doc_ids_in_kb))
    report.issues.extend(check_source_coverage(content_pages, doc_ids_in_kb))

    # LLM check (costs tokens)
    if run_llm_checks and llm and content_pages:
        contradiction_issues = await check_contradictions(content_pages, llm)
        report.issues.extend(contradiction_issues)

    logger.info(
        "Wiki lint complete",
        extra={
            "kb_id": str(kb_id),
            "errors": len(report.errors),
            "warnings": len(report.warnings),
            "suggestions": len(report.suggestions),
        },
    )
    return report
