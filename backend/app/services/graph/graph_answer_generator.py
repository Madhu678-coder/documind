"""GraphRAG answer generator — produces cited answers from graph traversal context."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.services.pageindex.answer_generator import (
    Citation,
    GeneratedAnswer,
    _build_context_from_history,
    _parse_answer_and_citations,
)
from app.services.graph.graph_navigator import GraphContext

if TYPE_CHECKING:
    from app.services.llm.provider import LLMProvider

logger = logging.getLogger(__name__)

_GRAPH_ANSWER_SYSTEM_PROMPT = """\
You are a precise knowledge graph analyst. Given entities and relationships from a knowledge graph \
and a user query, produce a comprehensive answer with inline citations.

Format your answer using Markdown:
- Use **bold** for key terms and entity names
- Use bullet lists for enumerating relationships
- Use headings (##) for multi-section answers
- Keep paragraphs concise and scannable

For each claim, cite the source entity or relationship using [citation:N] markers.
At the end, provide a JSON citations array where each entry has:
- doc_name: the entity name that is the source of this fact (string)
- section_title: the relationship type or entity type (string)
- page_number: 1 (graphs don't have pages)
- node_id: the entity name (string)
- verbatim_excerpt: the relationship description or entity description (string)

Format your response as:
<answer>
Your markdown-formatted answer with [citation:1], [citation:2] markers...
</answer>
<citations>
[{"doc_name": "...", "section_title": "...", "page_number": 1, "node_id": "...", "verbatim_excerpt": "..."}]
</citations>"""


async def generate_answer_from_graph(
    query: str,
    graph_context: GraphContext,
    history: list[dict],
    llm: "LLMProvider",
) -> GeneratedAnswer:
    """
    Generate a cited answer from graph traversal context.

    Uses the same citation format as PageIndex/Wiki for frontend compatibility.
    """
    if graph_context.is_empty:
        return GeneratedAnswer(
            content="I could not find relevant entities or relationships in the knowledge graph to answer your question.",
            citations=[],
        )

    # Build context string from graph
    graph_text = graph_context.to_prompt_context()
    conv_context = _build_context_from_history(history)

    user_content = (
        f"Prior conversation:\n{conv_context}\n\n"
        f"Current query: {query}\n\n"
        f"Knowledge graph context:\n{graph_text}"
    )

    messages = [{"role": "user", "content": user_content}]
    response = await llm.complete(messages, system_prompt=_GRAPH_ANSWER_SYSTEM_PROMPT)

    answer_text, raw_citations = _parse_answer_and_citations(response.content)

    # Enrich citations with graph node info
    # Build a map of entity names to their source doc IDs
    node_doc_map: dict[str, str] = {}
    for node in graph_context.nodes:
        src_ids = node.get("source_doc_ids") or []
        if src_ids:
            node_doc_map[node["name"].lower()] = src_ids[0]

    # Get the first available doc_id from any node in context
    default_doc_id = ""
    for node in graph_context.nodes:
        src_ids = node.get("source_doc_ids") or []
        if src_ids:
            default_doc_id = src_ids[0]
            break

    enriched: list[Citation] = []
    if raw_citations:
        for citation in raw_citations:
            # Try to find doc_id from the citation's node_id (entity name)
            doc_id = node_doc_map.get(citation.node_id.lower(), default_doc_id)
            enriched.append(Citation(
                doc_name=citation.doc_name,
                section_title=citation.section_title,
                page_number=1,
                node_id=citation.node_id,
                verbatim_excerpt=citation.verbatim_excerpt,
                doc_id=doc_id,
            ))
    else:
        # Auto-generate citations from start nodes
        for node in graph_context.nodes[:5]:
            src_ids = node.get("source_doc_ids") or []
            enriched.append(Citation(
                doc_name=node["name"],
                section_title=node["entity_type"],
                page_number=1,
                node_id=node["name"],
                verbatim_excerpt=node["description"],
                doc_id=src_ids[0] if src_ids else default_doc_id,
            ))

    return GeneratedAnswer(content=answer_text, citations=enriched)
