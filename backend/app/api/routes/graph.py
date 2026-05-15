"""Graph API — view knowledge graph nodes, edges, and visualization data."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.knowledge_base import KnowledgeBase
from app.models.user import User

router = APIRouter(prefix="/knowledge-bases", tags=["graph"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class GraphNodeOut(BaseModel):
    id: str
    name: str
    entity_type: str
    description: str
    mention_count: int
    source_doc_count: int

class GraphEdgeOut(BaseModel):
    id: str
    source_id: str
    source_name: str
    target_id: str
    target_name: str
    relationship_type: str
    description: str
    weight: float

class GraphStatsOut(BaseModel):
    total_nodes: int
    total_edges: int
    entity_types: dict[str, int]
    relationship_types: dict[str, int]
    top_entities: list[dict]

class GraphVisualizationOut(BaseModel):
    """D3/vis.js compatible graph format."""
    nodes: list[dict]
    edges: list[dict]


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _get_kb_or_403(kb_id: uuid.UUID, workspace_id: uuid.UUID, db: AsyncSession) -> KnowledgeBase:
    result = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.id == kb_id,
            KnowledgeBase.workspace_id == workspace_id,
        )
    )
    kb = result.scalar_one_or_none()
    if kb is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="KnowledgeBase not found")
    return kb


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/{kb_id}/graph/stats", response_model=GraphStatsOut)
async def get_graph_stats(
    kb_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get graph statistics for a KB."""
    await _get_kb_or_403(kb_id, current_user.workspace_id, db)

    from app.services.graph.neo4j_client import get_graph_stats as neo4j_stats
    stats = await neo4j_stats(str(kb_id))

    return GraphStatsOut(
        total_nodes=stats.get("total_nodes", 0),
        total_edges=stats.get("total_edges", 0),
        entity_types={t: 0 for t in stats.get("entity_types", [])},
        relationship_types={},
        top_entities=[],
    )


@router.get("/{kb_id}/graph/nodes", response_model=list[GraphNodeOut])
async def list_graph_nodes(
    kb_id: uuid.UUID,
    entity_type: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all graph nodes for a KB, optionally filtered by entity type."""
    await _get_kb_or_403(kb_id, current_user.workspace_id, db)

    query = select(GraphNode).where(GraphNode.kb_id == kb_id)
    if entity_type:
        query = query.where(GraphNode.entity_type == entity_type)
    query = query.order_by(GraphNode.mention_count.desc())

    result = await db.execute(query)
    nodes = result.scalars().all()

    return [
        GraphNodeOut(
            id=str(n.id),
            name=n.name,
            entity_type=n.entity_type,
            description=n.description or "",
            mention_count=n.mention_count,
            source_doc_count=len(n.source_doc_ids) if n.source_doc_ids else 0,
        )
        for n in nodes
    ]


@router.get("/{kb_id}/graph/visualization", response_model=GraphVisualizationOut)
async def get_graph_visualization(
    kb_id: uuid.UUID,
    doc_id: uuid.UUID | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get the full graph in a format suitable for frontend visualization.
    Optionally filter by document ID to show only entities from a specific document.
    """
    await _get_kb_or_403(kb_id, current_user.workspace_id, db)

    from app.services.graph.neo4j_client import get_full_graph

    graph_data = await get_full_graph(str(kb_id))

    # Filter by document if doc_id provided
    if doc_id:
        doc_id_str = str(doc_id)
        # Filter nodes that have this doc in source_doc_ids
        filtered_nodes = [
            n for n in graph_data.get("nodes", [])
            if doc_id_str in (n.get("source_doc_ids") or [])
        ]
        filtered_node_names = {n["name"] for n in filtered_nodes}
        # Filter edges where both source and target are in filtered nodes
        filtered_edges = [
            e for e in graph_data.get("edges", [])
            if e.get("source") in filtered_node_names and e.get("target") in filtered_node_names
        ]
        graph_data = {"nodes": filtered_nodes, "edges": filtered_edges}

    # Type → color mapping
    type_colors = {
        "organization": "#4e79a7", "person": "#f28e2b", "role": "#e15759",
        "policy": "#76b7b2", "process": "#59a14f", "category": "#edc948",
        "location": "#9c755f", "amount": "#ff9da7", "department": "#b07aa1",
        "document": "#bab0ac", "concept": "#4e79a7", "rule": "#e15759",
    }

    vis_nodes = [
        {
            "id": n["name"],
            "label": n["name"],
            "type": n.get("entity_type", ""),
            "description": n.get("description", ""),
            "color": type_colors.get(n.get("entity_type", ""), "#aaaaaa"),
            "size": min(10 + (n.get("mention_count", 1) or 1) * 5, 40),
            "mentions": n.get("mention_count", 1),
        }
        for n in graph_data.get("nodes", [])
    ]

    vis_edges = [
        {
            "id": f"{e['source']}_{e['target']}_{e['type']}",
            "source": e["source"],
            "target": e["target"],
            "label": e.get("type", "").replace("_", " ").lower(),
            "type": e.get("type", ""),
            "description": e.get("description", ""),
            "weight": e.get("weight", 1.0),
            "source_name": e["source"],
            "target_name": e["target"],
        }
        for e in graph_data.get("edges", [])
    ]

    return GraphVisualizationOut(nodes=vis_nodes, edges=vis_edges)


@router.get("/{kb_id}/graph/neighborhood/{entity_name}")
async def get_node_neighborhood(
    kb_id: uuid.UUID,
    entity_name: str,
    hops: int = 2,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get the N-hop neighborhood of a specific entity by name.
    Uses Neo4j graph traversal.
    """
    await _get_kb_or_403(kb_id, current_user.workspace_id, db)

    from app.services.graph.neo4j_client import get_entity_neighborhood

    neighborhood = await get_entity_neighborhood(
        kb_id=str(kb_id),
        entity_names=[entity_name],
        max_hops=hops,
    )

    return {
        "center": entity_name,
        "nodes": neighborhood.get("nodes", []),
        "edges": neighborhood.get("edges", []),
    }
