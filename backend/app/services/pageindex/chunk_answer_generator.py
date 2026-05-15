"""Answer generator for Vector RAG mode — produces cited answers from retrieved chunks."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.services.pageindex.answer_generator import (
    Citation,
    GeneratedAnswer,
    _build_context_from_history,
    _parse_answer_and_citations,
    _CITATION_SYSTEM_PROMPT,
)

if TYPE_CHECKING:
    from app.services.llm.provider import LLMProvider
    from app.services.retrieval.retriever import RetrievalResult

logger = logging.getLogger(__name__)


async def generate_answer_from_chunks(
    query: str,
    chunks: list["RetrievalResult"],
    history: list[dict],
    llm: "LLMProvider",
) -> GeneratedAnswer:
    """
    Generate a cited answer from retrieved document chunks (Vector RAG mode).

    Uses the same citation format and LLM prompt as the PageIndex answer generator,
    but takes RetrievalResult objects instead of tree nodes.

    Args:
        query: The user's question
        chunks: List of RetrievalResult from the retriever
        history: Full message history for multi-turn context
        llm: LLMProvider instance

    Returns:
        GeneratedAnswer with answer text and structured citations
    """
    if not chunks:
        return GeneratedAnswer(
            content="I could not find relevant information in the knowledge base to answer your question.",
            citations=[],
        )

    # Build context from retrieved chunks
    sections_parts: list[str] = []
    for chunk in chunks:
        sections_parts.append(
            f"[Chunk {chunk.chunk_index + 1}] From '{chunk.doc_filename}' "
            f"(page {chunk.page_number}, score={chunk.score:.3f}):\n{chunk.text}"
        )

    sections_context = "\n\n---\n\n".join(sections_parts)

    # Build conversation context
    conv_context = _build_context_from_history(history)

    # Build citations context for the LLM so it knows the node_ids to reference
    chunk_list_for_prompt = "\n".join(
        f"- chunk_id={chunk.chunk_id}, doc={chunk.doc_filename}, page={chunk.page_number}, index={chunk.chunk_index}"
        for chunk in chunks
    )

    user_content = (
        f"Prior conversation:\n{conv_context}\n\n"
        f"Current query: {query}\n\n"
        f"Available chunk references:\n{chunk_list_for_prompt}\n\n"
        f"Relevant document sections:\n{sections_context}"
    )

    messages = [{"role": "user", "content": user_content}]
    response = await llm.complete(messages, system_prompt=_CITATION_SYSTEM_PROMPT)

    answer_text, raw_citations = _parse_answer_and_citations(response.content)

    # Re-map citations to use chunk data for better accuracy
    # If the LLM produced citations, enrich them with chunk metadata
    enriched_citations: list[Citation] = []
    chunk_map = {c.chunk_id: c for c in chunks}

    if raw_citations:
        for citation in raw_citations:
            # Try to find the matching chunk by node_id
            matched_chunk = chunk_map.get(citation.node_id)
            if matched_chunk:
                enriched_citations.append(Citation(
                    doc_name=matched_chunk.doc_filename,
                    section_title=f"Chunk {matched_chunk.chunk_index + 1}",
                    page_number=matched_chunk.page_number,
                    node_id=matched_chunk.chunk_id,
                    verbatim_excerpt=matched_chunk.text[:200],
                    doc_id=matched_chunk.document_id,
                ))
            else:
                enriched_citations.append(citation)
    else:
        # Fallback: auto-generate citations from all retrieved chunks
        for chunk in chunks:
            enriched_citations.append(Citation(
                doc_name=chunk.doc_filename,
                section_title=f"Chunk {chunk.chunk_index + 1}",
                page_number=chunk.page_number,
                node_id=chunk.chunk_id,
                verbatim_excerpt=chunk.text[:200],
                doc_id=chunk.document_id,
            ))

    return GeneratedAnswer(content=answer_text, citations=enriched_citations)
