"""OpenKB navigator — multi-step wiki navigation that mirrors OpenKB's query agent.

OpenKB's query agent follows this strategy:
  1. Read index.md to see all documents and concepts.
  2. Read relevant summary pages.
  3. Read concept/entity pages for cross-document synthesis.
  4. For long (pageindex) docs: retrieve specific page ranges via get_page_content.
  5. Synthesise a cited answer.

This navigator implements the same 3-step process without the OpenAI Agents SDK:
  Step A: LLM reads the index and picks which summary/concept/entity pages to load.
  Step B: LLM reads selected pages and (for long docs) requests page ranges.
  Step C: Returns all gathered context to the answer generator.

See answer_generator.py for the final generation step.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.services.llm.provider import LLMProvider

logger = logging.getLogger(__name__)

_MAX_SELECTED_PAGES = 10
_MAX_PAGE_RANGE_CHARS = 12_000   # cap per page-range retrieval to avoid overflow

# ---------------------------------------------------------------------------
# Prompts — mirrors OpenKB's _QUERY_INSTRUCTIONS_TEMPLATE strategy
# ---------------------------------------------------------------------------

_NAVIGATE_SYSTEM = """\
You are OpenKB, a knowledge-base Q&A agent. You answer questions by searching the wiki.

## Wiki structure
- index.md — catalog of every document, concept, and entity with one-liner descriptions.
  Each document is marked (short) or (pageindex) to indicate its type:
  - short    → full source text is embedded in the summary page.
  - pageindex → source is a long PDF; retrieve specific page ranges via page-range requests.
- summaries/ — one summary page per source document; includes tree structure for pageindex docs.
- concepts/  — cross-document concept synthesis pages.
- entities/  — pages for specific people, organisations, places, products, works, events.

## Search strategy (mirrors OpenKB query agent)
1. Read index.md to see all documents and concepts with brief summaries.
2. Select relevant summary pages (prefer concept/entity pages for general questions).
3. Read selected pages to understand content.
4. For pageindex summaries: identify page ranges from the tree structure to retrieve.
5. Synthesise a cited answer grounded in wiki content.
"""

_SELECT_PAGES_USER = """\
Query: {query}

{conv_context}

Index page:
{index_content}

Based on the index, select which pages to read to answer this query.

Return ONLY valid JSON:
{{
  "summary_pages": ["doc_name1", "doc_name2"],
  "concept_pages": ["slug1", "slug2"],
  "entity_pages":  ["slug1"],
  "rationale": "brief explanation"
}}

Select 1-{max_pages} pages total. If nothing is relevant, return empty lists.
"""

_REQUEST_PAGE_RANGES_USER = """\
You are reading the following wiki pages to answer this query:

Query: {query}

{pages_content}

Some documents are marked (pageindex) — they are long PDFs whose page content
can be retrieved. Based on the summaries above, do you need specific page ranges
from any pageindex document?

Return ONLY valid JSON:
{{
  "needs_page_ranges": true/false,
  "requests": [
    {{"doc_name": "...", "pages": "3-5,7,10-12", "reason": "..."}},
    ...
  ]
}}

If the summaries/concepts are sufficient, set needs_page_ranges to false.
"""


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class OpenKBNavResult:
    """Gathered context ready to pass to the answer generator."""
    selected_pages: list[Any] = field(default_factory=list)   # list[OpenKBPage]
    page_range_content: list[dict] = field(default_factory=list)  # [{doc_name, pages, content}]
    index_content: str = ""
    rationale: str = ""
    confidence: float = 0.8

    # IDs of selected pages (for reasoning_trace in chat)
    @property
    def selected_page_ids(self) -> list[str]:
        return [str(p.id) for p in self.selected_pages]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def navigate_openkb(
    query: str,
    pages: list[Any],             # list[OpenKBPage]
    llm: "LLMProvider",
    history: list[dict] | None = None,
) -> OpenKBNavResult:
    """Multi-step wiki navigation — mirrors OpenKB query agent strategy.

    Args:
        query:   User's question.
        pages:   All OpenKBPage rows for this KB.
        llm:     LLM provider.
        history: Recent conversation turns.

    Returns:
        OpenKBNavResult with selected pages and any page-range content.
    """
    # Separate index from content pages
    index_page = next((p for p in pages if p.title == "__index__"), None)
    content_pages = [p for p in pages if p.page_category != "index"]

    if not content_pages:
        return OpenKBNavResult()

    index_content = (index_page.content if index_page else _build_fallback_index(content_pages))

    # --- Step A: Select pages from index ---
    conv_context = _build_conv_context(history)
    select_prompt = _SELECT_PAGES_USER.format(
        query=query,
        conv_context=conv_context,
        index_content=index_content[:6000],
        max_pages=_MAX_SELECTED_PAGES,
    )

    rationale = ""
    selected: list[Any] = []
    try:
        resp = await llm.complete(
            [{"role": "user", "content": select_prompt}],
            system_prompt=_NAVIGATE_SYSTEM,
        )
        sel_data = _parse_json_safe(resp.content)
        if isinstance(sel_data, dict):
            rationale = sel_data.get("rationale", "")
            selected = _resolve_pages(sel_data, content_pages)
    except Exception as exc:
        logger.warning("OpenKB navigator step A failed: %s", exc)

    if not selected:
        # Fallback: pick top 5 by category priority (concepts first)
        priority = {"concept": 0, "entity": 1, "summary": 2}
        selected = sorted(content_pages, key=lambda p: priority.get(p.page_category, 9))[:5]

    # --- Step B: Check if page-range retrieval is needed (pageindex docs) ---
    page_range_content: list[dict] = []
    pageindex_summaries = [p for p in selected if p.page_category == "summary"
                           and getattr(p, "doc_type", "short") == "pageindex"]

    if pageindex_summaries:
        pages_content = _format_selected_pages(selected)
        range_prompt = _REQUEST_PAGE_RANGES_USER.format(
            query=query,
            pages_content=pages_content[:8000],
        )
        try:
            range_resp = await llm.complete(
                [{"role": "user", "content": range_prompt}],
                system_prompt=_NAVIGATE_SYSTEM,
            )
            range_data = _parse_json_safe(range_resp.content)
            if isinstance(range_data, dict) and range_data.get("needs_page_ranges"):
                for req in (range_data.get("requests") or []):
                    doc_name = req.get("doc_name", "")
                    page_spec = req.get("pages", "")
                    if doc_name and page_spec:
                        summary_page = next(
                            (p for p in pageindex_summaries if p.title == doc_name), None
                        )
                        if summary_page and summary_page.source_data:
                            content = _get_page_content(
                                summary_page.source_data, page_spec
                            )
                            if content:
                                page_range_content.append({
                                    "doc_name": doc_name,
                                    "pages": page_spec,
                                    "content": content,
                                })
        except Exception as exc:
            logger.warning("OpenKB navigator step B failed: %s", exc)

    logger.info(
        "OpenKB navigator: selected %d pages, %d page-range retrievals",
        len(selected), len(page_range_content),
    )
    return OpenKBNavResult(
        selected_pages=selected,
        page_range_content=page_range_content,
        index_content=index_content,
        rationale=rationale,
    )


# ---------------------------------------------------------------------------
# Page-range content retrieval — mirrors OpenKB's get_wiki_page_content
# ---------------------------------------------------------------------------


def _parse_page_spec(pages: str) -> set[int]:
    """Parse "3-5,7,10-12" into {3,4,5,7,10,11,12}."""
    result: set[int] = set()
    for part in pages.split(","):
        part = part.strip()
        if "-" in part:
            segs = part.split("-")
            try:
                if len(segs) == 2:
                    result.update(range(int(segs[0]), int(segs[1]) + 1))
            except ValueError:
                pass
        else:
            try:
                result.add(int(part))
            except ValueError:
                pass
    return {n for n in result if n > 0}


def _get_page_content(source_data: list, page_spec: str) -> str:
    """Retrieve formatted content for specified pages from stored per-page JSON.

    Mirrors OpenKB's get_wiki_page_content().
    """
    if not source_data:
        return ""
    requested = _parse_page_spec(page_spec)
    matches = [e for e in source_data if e.get("page") in requested]
    if not matches:
        return ""
    parts: list[str] = []
    total = 0
    for entry in matches:
        block = f"[Page {entry['page']}]\n{entry.get('content', '')}"
        images = entry.get("images", [])
        if images:
            paths = ", ".join(img["path"] for img in images if "path" in img)
            if paths:
                block += f"\n[Images: {paths}]"
        if total + len(block) > _MAX_PAGE_RANGE_CHARS:
            break
        parts.append(block)
        total += len(block)
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_pages(sel_data: dict, content_pages: list) -> list:
    pages_map_summary = {p.title: p for p in content_pages if p.page_category == "summary"}
    pages_map_concept = {p.title: p for p in content_pages if p.page_category == "concept"}
    pages_map_entity  = {p.title: p for p in content_pages if p.page_category == "entity"}

    selected: list = []
    seen_ids: set[str] = set()

    def _add(page) -> None:
        pid = str(page.id)
        if pid not in seen_ids:
            seen_ids.add(pid)
            selected.append(page)

    for name in (sel_data.get("summary_pages") or []):
        if p := pages_map_summary.get(name):
            _add(p)
    for slug in (sel_data.get("concept_pages") or []):
        if p := pages_map_concept.get(slug):
            _add(p)
    for slug in (sel_data.get("entity_pages") or []):
        if p := pages_map_entity.get(slug):
            _add(p)

    return selected[:_MAX_SELECTED_PAGES]


def _format_selected_pages(pages: list) -> str:
    parts: list[str] = []
    for p in pages:
        doc_type_label = f" [{getattr(p, 'doc_type', 'short')}]" if p.page_category == "summary" else ""
        header = f"## [{p.page_category.upper()}{doc_type_label}] {p.title}\n"
        parts.append(header + (p.content or "")[:3000])
    return "\n\n---\n\n".join(parts)


def _build_fallback_index(pages: list) -> str:
    lines = ["# Index", ""]
    for p in sorted(pages, key=lambda x: x.page_category):
        brief = (p.summary or "").replace("\n", " ")[:80]
        lines.append(f"- [{p.page_category}] {p.title}: {brief}")
    return "\n".join(lines)


def _build_conv_context(history: list[dict] | None) -> str:
    if not history:
        return ""
    recent = history[-4:]
    lines = [f"{m.get('role', 'user').capitalize()}: {m.get('content', '')[:200]}" for m in recent]
    return "Conversation context:\n" + "\n".join(lines) + "\n\n"


def _parse_json_safe(text: str) -> dict | list | None:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        first_nl = cleaned.find("\n")
        cleaned = cleaned[first_nl + 1:] if first_nl != -1 else cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.removeprefix("json").strip()
    try:
        return json.loads(cleaned)
    except Exception:
        return None
