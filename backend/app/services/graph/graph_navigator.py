"""GraphRAG navigator — entity resolution + graph traversal for query answering.

Query pipeline:
1. LLM extracts key entities from user query
2. Vector similarity finds matching graph nodes
3. BFS traversal collects connected nodes + edges (2 hops)
4. Assembled context passed to answer generator
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from sqlalchemy import select, text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.services.llm.provider import LLMProvider
    from app.services.embedding.provider import EmbeddingProvider

from app.models.graph_node import GraphNode
from app.models.graph_edge import GraphEdge

logger = logging.getLogger(__name__)

_ENTITY_EXTRACTION_PROMPT = """\
You are an entity extractor. Given a user query, identify the key entities, concepts, \
or topics the user is asking about.

Return ONLY valid JSON:
{"entities": ["entity1", "entity2", ...], "intent": "find_relationship|find_entity|summarize"}

Extract 1-5 entities. Use canonical names where possible.\
"""

_MAX_HOPS = 2
_MAX_EDGES_PER_NODE = 15
_TOP_K_NODES = 8


@dataclass
class GraphContext:
    """Context assembled from graph traversal for answer generation."""
    nodes: list[dict] = field(default_factory=list)
    edges: list[dict] = field(default_factory=list)
    query_entities: list[str] = field(default_factory=list)
    start_node_ids: list[str] = field(default_factory=list)

    def to_prompt_context(self) -> str:
        """Format graph context as a string for the answer generator."""
        lines: list[str] = []

        if self.nodes:
            lines.append("=== Entities ===")
            for node in self.nodes:
                lines.append(
                    f"• {node['name']} ({node['entity_type']}): {node['description']}"
                )

        if self.edges:
            lines.append("\n=== Relationships ===")
            for edge in self.edges:
                lines.append(
                    f"• {edge['source_name']} → [{edge['relationship_type']}] → {edge['target_name']}: "
                    f"{edge['description']}"
                )

        return "\n".join(lines) if lines else "No relevant entities or relationships found in the knowledge graph."

    @property
    def is_empty(self) -> bool:
        return not self.nodes and not self.edges


async def extract_query_entities(query: str, llm: "LLMProvider") -> list[str]:
    """Extract key entities from the user's query via LLM."""
    messages = [{"role": "user", "content": query}]

    try:
        response = await llm.complete(messages, system_prompt=_ENTITY_EXTRACTION_PROMPT)
        raw = response.content.strip()
        if raw.startswith("```"):
            parts = raw.split("```")
            raw = parts[1] if len(parts) > 1 else raw
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        data = json.loads(raw)
        entities = data.get("entities", [])
        logger.info("Query entities extracted", extra={"entities": entities})
        return [str(e).strip() for e in entities if e]
    except Exception as exc:
        logger.warning("Query entity extraction failed", extra={"error": str(exc)})
        # Fallback: use the query words as entities
        words = [w for w in query.split() if len(w) > 3]
        return words[:5]


@dataclass
class ResolvedNode:
    """Lightweight node object for graph navigation (avoids SQLAlchemy model issues)."""
    name: str
    entity_type: str = ""
    description: str = ""
    mention_count: int = 1


async def resolve_entities(
    query_entities: list[str],
    kb_id: uuid.UUID,
    embedding_provider: "EmbeddingProvider",
    db: "AsyncSession",
) -> list[ResolvedNode]:
    """
    Resolve extracted entity names to actual graph nodes using Neo4j full-text search.
    """
    if not query_entities:
        return []

    from app.services.graph.neo4j_client import search_entities

    results = await search_entities(str(kb_id), query_entities, limit=_TOP_K_NODES)

    resolved: list[ResolvedNode] = []
    for r in results:
        resolved.append(ResolvedNode(
            name=r["name"],
            entity_type=r.get("entity_type", ""),
            description=r.get("description", ""),
            mention_count=r.get("mention_count", 1) or 1,
        ))

    logger.info(
        "Entities resolved via Neo4j",
        extra={"query_entities": query_entities, "resolved_count": len(resolved)},
    )
    return resolved


async def _fallback_text_search(
    query_entities: list[str],
    kb_id: uuid.UUID,
    db: "AsyncSession",
) -> list[ResolvedNode]:
    """Fallback: find nodes by text search in Neo4j when full-text index fails."""
    from app.services.graph.neo4j_client import search_entities

    results = await search_entities(str(kb_id), query_entities, limit=_TOP_K_NODES)
    resolved: list[ResolvedNode] = []
    for r in results:
        resolved.append(ResolvedNode(
            name=r["name"],
            entity_type=r.get("entity_type", ""),
            description=r.get("description", ""),
            mention_count=r.get("mention_count", 1) or 1,
        ))
    return resolved


async def traverse_graph(
    start_nodes: list[GraphNode],
    kb_id: uuid.UUID,
    db: "AsyncSession",
    max_hops: int = _MAX_HOPS,
) -> GraphContext:
    """
    Traverse the graph from start nodes using Neo4j Cypher.
    Returns GraphContext with all discovered nodes and edges.
    """
    from app.services.graph.neo4j_client import get_entity_neighborhood

    entity_names = [n.name for n in start_nodes]

    neighborhood = await get_entity_neighborhood(
        kb_id=str(kb_id),
        entity_names=entity_names,
        max_hops=max_hops,
    )

    context_nodes = []
    seen_names: set[str] = set()
    for node_data in neighborhood.get("nodes", []):
        name = node_data.get("name", "")
        if name and name not in seen_names:
            seen_names.add(name)
            context_nodes.append({
                "id": name,
                "name": name,
                "entity_type": node_data.get("entity_type", ""),
                "description": node_data.get("description", ""),
                "mention_count": node_data.get("mention_count", 1),
            })

    context_edges = []
    for edge_data in neighborhood.get("edges", []):
        context_edges.append({
            "source_name": edge_data.get("source", ""),
            "target_name": edge_data.get("target", ""),
            "relationship_type": edge_data.get("type", ""),
            "description": edge_data.get("description", ""),
            "weight": edge_data.get("weight", 1.0),
        })

    logger.info(
        "Graph traversal complete (Neo4j)",
        extra={"nodes": len(context_nodes), "edges": len(context_edges)},
    )

    return GraphContext(
        nodes=context_nodes,
        edges=context_edges,
        query_entities=[n.name for n in start_nodes],
        start_node_ids=[n.name for n in start_nodes],
    )


async def navigate_graph(
    query: str,
    kb_id: uuid.UUID,
    llm: "LLMProvider",
    embedding_provider: "EmbeddingProvider",
    db: "AsyncSession",
) -> GraphContext:
    """
    Full graph navigation pipeline:
    1. Extract entities from query
    2. Resolve to graph nodes via vector similarity
    3. Traverse graph (2 hops BFS)
    4. Return assembled context

    Args:
        query: User's question
        kb_id: Knowledge base UUID
        llm: LLM provider for entity extraction
        embedding_provider: For vector-based node resolution
        db: Database session

    Returns:
        GraphContext ready for answer generation
    """
    # Step 1: Extract entities from query
    query_entities = await extract_query_entities(query, llm)

    if not query_entities:
        return GraphContext()

    # Step 2: Resolve to graph nodes
    resolved_nodes = await resolve_entities(query_entities, kb_id, embedding_provider, db)

    if not resolved_nodes:
        # Fallback: try text search
        resolved_nodes = await _fallback_text_search(query_entities, kb_id, db)

    if not resolved_nodes:
        return GraphContext(query_entities=query_entities)

    # Step 3: Traverse graph
    context = await traverse_graph(resolved_nodes, kb_id, db)
    context.query_entities = query_entities

    return context
