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
and a user query, produce a clear, concise answer.

Rules:
- Answer directly — don't repeat the question or add unnecessary preamble
- Be concise — if the answer is a simple fact, give it in 1-2 sentences
- Only elaborate when the question requires explanation
- Use **bold** for key facts (numbers, names, dates)
- Use bullet points only when listing multiple items
- Do NOT add "Note" sections suggesting the user look elsewhere
- Do NOT add disclaimers about needing more information

For each claim, cite using [citation:N] markers.
At the end, provide a JSON citations array:
- doc_name: entity name (string)
- section_title: entity type (string)  
- page_number: 1
- node_id: entity name (string)
- verbatim_excerpt: the fact from the graph (string)

Format:
<answer>
Your concise answer with [citation:1] markers...
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
    # Fetch source_doc_ids, page_number, source_text directly from Neo4j
    node_doc_map: dict[str, str] = {}
    node_page_map: dict[str, int] = {}
    node_text_map: dict[str, str] = {}
    try:
        from app.services.graph.neo4j_client import run_query
        node_names = [n["name"] for n in graph_context.nodes if n.get("name")]
        if node_names:
            doc_id_results = await run_query(
                "MATCH (e:Entity) WHERE e.name IN $names AND e.source_doc_ids IS NOT NULL "
                "RETURN e.name AS name, e.source_doc_ids AS source_doc_ids, "
                "e.page_number AS page_number, e.source_text AS source_text",
                {"names": node_names}
            )
            for r in doc_id_results:
                src_ids = r.get("source_doc_ids") or []
                if src_ids:
                    node_doc_map[r["name"].lower()] = src_ids[0]
                node_page_map[r["name"].lower()] = r.get("page_number") or 1
                node_text_map[r["name"].lower()] = r.get("source_text") or ""
    except Exception:
        pass

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
            # Try to find doc_id: check node_id, then doc_name, then partial match
            doc_id = ""
            # Exact match on node_id
            doc_id = node_doc_map.get(citation.node_id.lower(), "")
            # Try doc_name if node_id didn't match
            if not doc_id:
                doc_id = node_doc_map.get(citation.doc_name.lower(), "")
            # Try partial match on any node name
            if not doc_id:
                for name, did in node_doc_map.items():
                    if name in citation.node_id.lower() or citation.node_id.lower() in name:
                        doc_id = did
                        break
                    if name in citation.doc_name.lower() or citation.doc_name.lower() in name:
                        doc_id = did
                        break
            # Fallback
            if not doc_id:
                doc_id = default_doc_id

            enriched.append(Citation(
                doc_name=citation.doc_name,
                section_title=citation.section_title,
                page_number=node_page_map.get(citation.node_id.lower(), 1),
                node_id=citation.node_id,
                verbatim_excerpt=node_text_map.get(citation.node_id.lower(), "") or citation.verbatim_excerpt,
                doc_id=doc_id,
            ))
    else:
        # Auto-generate citations from start nodes
        for node in graph_context.nodes[:5]:
            src_ids = node.get("source_doc_ids") or []
            name_lower = node["name"].lower()
            enriched.append(Citation(
                doc_name=node["name"],
                section_title=node["entity_type"],
                page_number=node_page_map.get(name_lower, 1),
                node_id=node["name"],
                verbatim_excerpt=node_text_map.get(name_lower, "") or node["description"],
                doc_id=node_doc_map.get(name_lower, "") or (src_ids[0] if src_ids else default_doc_id),
            ))

    return GeneratedAnswer(content=answer_text, citations=enriched)
