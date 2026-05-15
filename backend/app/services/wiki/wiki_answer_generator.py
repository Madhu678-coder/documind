"""Wiki answer generator — produces cited answers from selected wiki pages."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from app.services.pageindex.answer_generator import (
    Citation,
    GeneratedAnswer,
    _CITATION_SYSTEM_PROMPT,
    _build_context_from_history,
    _parse_answer_and_citations,
)

if TYPE_CHECKING:
    from app.services.llm.provider import LLMProvider

logger = logging.getLogger(__name__)


async def generate_answer_from_wiki(
    query: str,
    selected_pages: list[Any],  # list[WikiPage]
    history: list[dict],
    llm: "LLMProvider",
) -> GeneratedAnswer:
    """
    Generate a cited answer from selected wiki pages.

    Reuses the same citation system prompt and parsing logic as PageIndex,
    so the frontend receives identical citation structures across all RAG modes.

    Citations use the wiki page id as node_id and the first source_doc_id as doc_id,
    so frontend deep-links go to the originating document.
    """
    if not selected_pages:
        return GeneratedAnswer(
            content="I could not find relevant information in the knowledge base wiki to answer your question.",
            citations=[],
        )

    # Build context from selected wiki pages
    sections_parts: list[str] = []
    for page in selected_pages:
        source_count = len(page.source_doc_ids) if page.source_doc_ids else 0
        sections_parts.append(
            f"[Wiki: {page.title}] (type: {page.page_type}, sources: {source_count} doc(s))\n"
            f"node_id={page.id}\n\n"
            f"{page.content}"
        )

    sections_context = "\n\n---\n\n".join(sections_parts)
    conv_context = _build_context_from_history(history)

    user_content = (
        f"Prior conversation:\n{conv_context}\n\n"
        f"Current query: {query}\n\n"
        f"Wiki knowledge base content:\n{sections_context}"
    )

    messages = [{"role": "user", "content": user_content}]
    response = await llm.complete(messages, system_prompt=_CITATION_SYSTEM_PROMPT)
    answer_text, raw_citations = _parse_answer_and_citations(response.content)

    # Enrich citations with wiki page metadata
    page_map = {str(p.id): p for p in selected_pages}
    enriched: list[Citation] = []

    if raw_citations:
        for citation in raw_citations:
            page = page_map.get(citation.node_id)
            if page:
                # doc_id = first source document (for frontend deep-link)
                doc_id = page.source_doc_ids[0] if page.source_doc_ids else ""
                enriched.append(Citation(
                    doc_name=page.title,
                    section_title=page.page_type.capitalize(),
                    page_number=citation.page_number or 1,
                    node_id=str(page.id),
                    verbatim_excerpt=citation.verbatim_excerpt or page.summary or "",
                    doc_id=doc_id,
                ))
            else:
                enriched.append(citation)
    else:
        # Auto-generate citations from all selected pages
        for page in selected_pages:
            doc_id = page.source_doc_ids[0] if page.source_doc_ids else ""
            enriched.append(Citation(
                doc_name=page.title,
                section_title=page.page_type.capitalize(),
                page_number=1,
                node_id=str(page.id),
                verbatim_excerpt=page.summary or "",
                doc_id=doc_id,
            ))

    return GeneratedAnswer(content=answer_text, citations=enriched)
