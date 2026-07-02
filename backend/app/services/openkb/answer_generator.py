"""OpenKB answer generator — produces cited answers from navigator context.

Mirrors OpenKB's query agent answer synthesis:
- Receives selected wiki pages + any page-range content for long docs.
- Builds a rich context string (index + selected pages + retrieved page ranges).
- Asks the LLM to synthesise a concise, cited answer.
- Uses the same Citation/GeneratedAnswer types as the rest of documind.
"""
from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from app.services.pageindex.answer_generator import (
    Citation,
    GeneratedAnswer,
    _build_context_from_history,
    _parse_answer_and_citations,
)

if TYPE_CHECKING:
    from app.services.llm.provider import LLMProvider
    from app.services.openkb.navigator import OpenKBNavResult

logger = logging.getLogger(__name__)

_ANSWER_SYSTEM = """\
You are OpenKB, a precise knowledge-base assistant.
Answer questions using ONLY the wiki content provided below.

Rules:
- Answer directly and concisely.
- Be factual: only state what appears in the context.
- Use **bold** for key facts (numbers, names, dates, policy values).
- Use bullet points only for lists of multiple items.
- For each factual claim add a [citation:N] marker referencing the page.
- If the context does not contain enough information, say so clearly.
- Do NOT add disclaimers suggesting the user look elsewhere.

At the end, provide a JSON citations block:
[{"doc_name": "...", "section_title": "...", "page_number": 1,
  "node_id": "<page-uuid>", "verbatim_excerpt": "..."}]

Format:
<answer>
Your concise answer with [citation:1] markers...
</answer>
<citations>
[{"doc_name": "...", "section_title": "...", "page_number": 1,
  "node_id": "...", "verbatim_excerpt": "..."}]
</citations>
"""


async def generate_answer_from_openkb(
    query: str,
    nav_result: "OpenKBNavResult",
    history: list[dict],
    llm: "LLMProvider",
) -> GeneratedAnswer:
    """Generate a cited answer from OpenKB navigator context.

    Uses the same Citation/GeneratedAnswer format as other documind RAG modes.
    """
    if not nav_result.selected_pages:
        return GeneratedAnswer(
            content="I could not find relevant information in the knowledge base to answer your question.",
            citations=[],
        )

    # --- Build context string (mirrors OpenKB agent's tool-read output) ---
    context_parts: list[str] = []

    # 1. Index overview (first 2000 chars — gives LLM the KB structure)
    if nav_result.index_content:
        context_parts.append(f"## Knowledge Base Index\n{nav_result.index_content[:2000]}")

    # 2. Selected wiki pages
    for page in nav_result.selected_pages:
        doc_type_tag = ""
        if page.page_category == "summary":
            doc_t = getattr(page, "doc_type", "short") or "short"
            doc_type_tag = f" [{doc_t}]"
        header = (
            f"## [{page.page_category.upper()}{doc_type_tag}] {page.title}\n"
            f"node_id={page.id}\n"
        )
        context_parts.append(header + (page.content or ""))

    # 3. Retrieved page ranges for long docs
    for pr in nav_result.page_range_content:
        context_parts.append(
            f"## [PAGE RANGE] {pr['doc_name']} — pages {pr['pages']}\n{pr['content']}"
        )

    context_str = "\n\n---\n\n".join(context_parts)
    conv_context = _build_context_from_history(history)

    user_content = (
        f"Prior conversation:\n{conv_context}\n\n"
        f"Current query: {query}\n\n"
        f"Wiki content:\n{context_str}"
    )

    resp = await llm.complete(
        [{"role": "user", "content": user_content}],
        system_prompt=_ANSWER_SYSTEM,
    )
    answer_text, raw_citations = _parse_answer_and_citations(resp.content)

    # --- Enrich citations with page metadata ---
    page_map = {str(p.id): p for p in nav_result.selected_pages}
    enriched: list[Citation] = []

    if raw_citations:
        for c in raw_citations:
            page = page_map.get(c.node_id)
            if page:
                doc_id = (page.source_doc_ids or [""])[0]
                enriched.append(Citation(
                    doc_name=page.title,
                    section_title=page.page_type.capitalize(),
                    page_number=1,
                    node_id=str(page.id),
                    verbatim_excerpt=c.verbatim_excerpt or page.summary or "",
                    doc_id=doc_id,
                ))
            else:
                enriched.append(c)
    else:
        # Auto-generate citations from selected pages
        for page in nav_result.selected_pages[:5]:
            doc_id = (page.source_doc_ids or [""])[0]
            enriched.append(Citation(
                doc_name=page.title,
                section_title=page.page_type.capitalize(),
                page_number=1,
                node_id=str(page.id),
                verbatim_excerpt=page.summary or "",
                doc_id=doc_id,
            ))

    return GeneratedAnswer(content=answer_text, citations=enriched)
