"""Wiki navigator — selects relevant wiki pages for a query at chat time."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.services.llm.provider import LLMProvider

logger = logging.getLogger(__name__)

_MAX_SELECTED_PAGES = 8

_NAVIGATE_SYSTEM_PROMPT = """\
You are navigating a knowledge base wiki to find the most relevant pages for a user query.

Review the available wiki pages (id, type, title, summary) and select those that contain \
information useful for answering the query.

Return ONLY valid JSON:
{"selected_page_ids": ["uuid1", "uuid2"], "rationale": "brief explanation", "confidence": 0.85}

Select between 1 and 8 pages. If no pages are relevant, return an empty selected_page_ids list.\
"""


@dataclass
class WikiNavResult:
    selected_page_ids: list[str] = field(default_factory=list)
    rationale: str = ""
    confidence: float = 0.0


async def navigate_wiki(
    query: str,
    wiki_pages: list[Any],  # list[WikiPage] — avoid import cycle
    llm: "LLMProvider",
    history: list[dict] | None = None,
) -> WikiNavResult:
    """
    Select the most relevant wiki pages for a query.

    Args:
        query: User's question
        wiki_pages: All WikiPage objects in the KB
        llm: LLMProvider instance
        history: Optional conversation history for multi-turn context

    Returns:
        WikiNavResult with selected_page_ids, rationale, confidence
    """
    if not wiki_pages:
        return WikiNavResult()

    toc = _build_toc(wiki_pages)

    # Build conversation context for multi-turn awareness
    conv_context = ""
    if history:
        recent = history[-3:]
        conv_lines = [f"{m.get('role', 'user').capitalize()}: {m.get('content', '')[:200]}" for m in recent]
        conv_context = f"Conversation context:\n" + "\n".join(conv_lines) + "\n\n"

    messages = [
        {
            "role": "user",
            "content": f"{conv_context}Query: {query}\n\nAvailable wiki pages:\n{toc}",
        }
    ]

    try:
        response = await llm.complete(messages, system_prompt=_NAVIGATE_SYSTEM_PROMPT)
        return _parse_nav_result(response.content, wiki_pages)
    except Exception as exc:
        logger.warning("Wiki navigation failed", extra={"error": str(exc)})
        return WikiNavResult()


def _build_toc(wiki_pages: list[Any]) -> str:
    """Build a compact table-of-contents string for the LLM."""
    lines = []
    for page in wiki_pages:
        summary = (page.summary or "").replace("\n", " ")
        lines.append(f"id={page.id} | {page.page_type} | {page.title}: {summary}")
    return "\n".join(lines)


def _parse_nav_result(raw: str, wiki_pages: list[Any]) -> WikiNavResult:
    """Parse LLM navigation response. Falls back to empty result on any error."""
    try:
        content = raw.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
            if content.startswith("json"):
                content = content[4:]

        data = json.loads(content)
        page_ids_raw = data.get("selected_page_ids", [])
        if not isinstance(page_ids_raw, list):
            page_ids_raw = []

        # Validate against actual page IDs to prevent hallucinated UUIDs
        valid_ids = {str(p.id) for p in wiki_pages}
        selected = [pid for pid in page_ids_raw if str(pid) in valid_ids]
        selected = selected[:_MAX_SELECTED_PAGES]

        return WikiNavResult(
            selected_page_ids=selected,
            rationale=str(data.get("rationale", "")),
            confidence=float(data.get("confidence", 0.0)),
        )
    except Exception as exc:
        logger.warning("Wiki nav result parse failed", extra={"error": str(exc)})
        return WikiNavResult()
