"""Neo4j client — connection management and query helpers for GraphRAG."""
from __future__ import annotations

import logging
from typing import Any

from neo4j import AsyncGraphDatabase, AsyncDriver

from app.core.config import settings

logger = logging.getLogger(__name__)

_driver: AsyncDriver | None = None


async def get_neo4j_driver() -> AsyncDriver:
    """Create a new Neo4j async driver (no singleton — avoids event loop conflicts in Celery)."""
    return AsyncGraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )


async def close_neo4j_driver() -> None:
    """Close the Neo4j driver (no-op since we don't use singleton anymore)."""
    pass


async def run_query(query: str, parameters: dict | None = None) -> list[dict]:
    """Run a Cypher query and return results as list of dicts."""
    driver = await get_neo4j_driver()
    try:
        async with driver.session() as session:
            result = await session.run(query, parameters or {})
            records = await result.data()
            return records
    finally:
        await driver.close()


async def run_write(query: str, parameters: dict | None = None) -> None:
    """Run a write Cypher query."""
    driver = await get_neo4j_driver()
    try:
        async with driver.session() as session:
            await session.run(query, parameters or {})
    finally:
        await driver.close()


# ── Schema Setup ──────────────────────────────────────────────────────────────


async def ensure_schema() -> None:
    """Create indexes and constraints for the graph schema."""
    driver = await get_neo4j_driver()
    async with driver.session() as session:
        # Unique constraint on Entity node by kb_id + name
        await session.run("""
            CREATE CONSTRAINT entity_unique IF NOT EXISTS
            FOR (e:Entity) REQUIRE (e.kb_id, e.name) IS UNIQUE
        """)
        # Index on kb_id for fast filtering
        await session.run("""
            CREATE INDEX entity_kb_idx IF NOT EXISTS
            FOR (e:Entity) ON (e.kb_id)
        """)
        # Index on entity type
        await session.run("""
            CREATE INDEX entity_type_idx IF NOT EXISTS
            FOR (e:Entity) ON (e.entity_type)
        """)
        # Full-text index for entity search
        try:
            await session.run("""
                CREATE FULLTEXT INDEX entity_search IF NOT EXISTS
                FOR (e:Entity) ON EACH [e.name, e.description]
            """)
        except Exception:
            pass  # May already exist

    logger.info("Neo4j schema ensured")


# ── Graph Operations ──────────────────────────────────────────────────────────


async def upsert_entity(
    kb_id: str,
    name: str,
    entity_type: str,
    description: str,
    doc_id: str,
    properties: dict | None = None,
) -> str:
    """Create or update an entity node. Returns the node element ID."""
    query = """
        MERGE (e:Entity {kb_id: $kb_id, name: $name})
        ON CREATE SET
            e.entity_type = $entity_type,
            e.description = $description,
            e.source_doc_ids = [$doc_id],
            e.mention_count = 1,
            e.created_at = datetime()
        ON MATCH SET
            e.mention_count = e.mention_count + 1,
            e.source_doc_ids = CASE
                WHEN NOT $doc_id IN e.source_doc_ids
                THEN e.source_doc_ids + $doc_id
                ELSE e.source_doc_ids
            END,
            e.description = CASE
                WHEN size($description) > size(coalesce(e.description, ''))
                THEN $description
                ELSE e.description
            END,
            e.updated_at = datetime()
        RETURN elementId(e) as node_id
    """
    results = await run_query(query, {
        "kb_id": kb_id,
        "name": name,
        "entity_type": entity_type,
        "description": description or "",
        "doc_id": doc_id,
    })
    return results[0]["node_id"] if results else ""


async def upsert_relationship(
    kb_id: str,
    source_name: str,
    target_name: str,
    rel_type: str,
    description: str,
    weight: float,
    doc_id: str,
) -> None:
    """Create or strengthen a relationship between two entities."""
    # Sanitize relationship type for Cypher (must be valid identifier)
    import re
    safe_rel_type = re.sub(r'[^A-Z0-9_]', '_', rel_type.upper().replace(" ", "_"))
    if not safe_rel_type:
        safe_rel_type = "RELATED_TO"

    # Use APOC if available, otherwise use a two-step approach
    # Since dynamic relationship types can't use parameters, we build the query string
    query = f"""
        MATCH (s:Entity {{kb_id: $kb_id, name: $source_name}})
        MATCH (t:Entity {{kb_id: $kb_id, name: $target_name}})
        MERGE (s)-[r:{safe_rel_type}]->(t)
        ON CREATE SET
            r.description = $description,
            r.weight = $weight,
            r.source_doc_ids = [$doc_id],
            r.kb_id = $kb_id,
            r.created_at = datetime()
        ON MATCH SET
            r.weight = CASE
                WHEN r.weight + $weight_increment > 10.0 THEN 10.0
                ELSE r.weight + $weight_increment
            END,
            r.source_doc_ids = CASE
                WHEN NOT $doc_id IN r.source_doc_ids
                THEN r.source_doc_ids + $doc_id
                ELSE r.source_doc_ids
            END,
            r.updated_at = datetime()
    """
    await run_write(query, {
        "kb_id": kb_id,
        "source_name": source_name,
        "target_name": target_name,
        "description": description or "",
        "weight": float(weight),
        "weight_increment": float(weight) / 10.0,
        "doc_id": doc_id,
    })


async def get_entity_neighborhood(
    kb_id: str,
    entity_names: list[str],
    max_hops: int = 2,
    limit: int = 50,
) -> dict[str, list[dict]]:
    """
    Get N-hop neighborhood of entities via Cypher traversal.
    Returns {"nodes": [...], "edges": [...]}.
    """
    query = """
        MATCH (start:Entity {kb_id: $kb_id})
        WHERE start.name IN $entity_names
        CALL apoc.path.subgraphAll(start, {
            maxLevel: $max_hops,
            relationshipFilter: '>',
            labelFilter: '+Entity'
        })
        YIELD nodes, relationships
        UNWIND nodes AS n
        WITH COLLECT(DISTINCT n) AS allNodes, relationships
        UNWIND relationships AS r
        WITH allNodes, COLLECT(DISTINCT r) AS allRels
        UNWIND allNodes AS node
        WITH COLLECT(DISTINCT {
            name: node.name,
            entity_type: node.entity_type,
            description: node.description,
            mention_count: node.mention_count
        }) AS nodeList, allRels
        UNWIND allRels AS rel
        RETURN nodeList,
               COLLECT(DISTINCT {
                   source: startNode(rel).name,
                   target: endNode(rel).name,
                   type: type(rel),
                   description: rel.description,
                   weight: rel.weight
               }) AS edgeList
    """

    # Fallback to simpler query if APOC not available
    fallback_query = """
        MATCH (start:Entity {kb_id: $kb_id})
        WHERE start.name IN $entity_names
        OPTIONAL MATCH path = (start)-[*1..2]-(connected:Entity {kb_id: $kb_id})
        WITH start, connected, relationships(path) AS rels
        UNWIND rels AS r
        WITH COLLECT(DISTINCT {
            name: connected.name,
            entity_type: connected.entity_type,
            description: connected.description,
            mention_count: connected.mention_count,
            source_doc_ids: connected.source_doc_ids
        }) + COLLECT(DISTINCT {
            name: start.name,
            entity_type: start.entity_type,
            description: start.description,
            mention_count: start.mention_count,
            source_doc_ids: start.source_doc_ids
        }) AS nodeList,
        COLLECT(DISTINCT {
            source: startNode(r).name,
            target: endNode(r).name,
            type: type(r),
            description: r.description,
            weight: r.weight
        }) AS edgeList
        RETURN nodeList, edgeList
    """

    try:
        results = await run_query(query, {
            "kb_id": kb_id,
            "entity_names": entity_names,
            "max_hops": max_hops,
        })
    except Exception:
        # APOC might not be available, use fallback
        results = await run_query(fallback_query, {
            "kb_id": kb_id,
            "entity_names": entity_names,
        })

    if not results:
        return {"nodes": [], "edges": []}

    return {
        "nodes": results[0].get("nodeList", []) if results else [],
        "edges": results[0].get("edgeList", []) if results else [],
    }


async def search_entities(
    kb_id: str,
    search_terms: list[str],
    limit: int = 10,
) -> list[dict]:
    """Search entities by name/description using full-text index."""
    # Build search string for full-text index
    search_string = " OR ".join(search_terms)

    try:
        query = """
            CALL db.index.fulltext.queryNodes('entity_search', $search_string)
            YIELD node, score
            WHERE node.kb_id = $kb_id
            RETURN node.name AS name, node.entity_type AS entity_type,
                   node.description AS description, node.mention_count AS mention_count,
                   score
            ORDER BY score DESC
            LIMIT $limit
        """
        return await run_query(query, {
            "kb_id": kb_id,
            "search_string": search_string,
            "limit": limit,
        })
    except Exception:
        # Fallback to CONTAINS search if full-text index not ready
        query = """
            MATCH (e:Entity {kb_id: $kb_id})
            WHERE ANY(term IN $search_terms WHERE toLower(e.name) CONTAINS toLower(term)
                  OR toLower(e.description) CONTAINS toLower(term))
            RETURN e.name AS name, e.entity_type AS entity_type,
                   e.description AS description, e.mention_count AS mention_count,
                   1.0 AS score
            ORDER BY e.mention_count DESC
            LIMIT $limit
        """
        return await run_query(query, {
            "kb_id": kb_id,
            "search_terms": search_terms,
            "limit": limit,
        })


async def get_full_graph(kb_id: str, doc_id: str | None = None) -> dict[str, list[dict]]:
    """Get the graph for a KB, optionally filtered by document ID."""
    if doc_id:
        nodes_query = """
            MATCH (e:Entity {kb_id: $kb_id})
            WHERE $doc_id IN e.source_doc_ids
            RETURN e.name AS name, e.entity_type AS entity_type,
                   e.description AS description, e.mention_count AS mention_count,
                   e.source_doc_ids AS source_doc_ids
            ORDER BY e.mention_count DESC
        """
        nodes = await run_query(nodes_query, {"kb_id": kb_id, "doc_id": doc_id})

        # Get edges between filtered nodes only
        node_names = [n["name"] for n in nodes]
        if node_names:
            edges_query = """
                MATCH (s:Entity {kb_id: $kb_id})-[r]->(t:Entity {kb_id: $kb_id})
                WHERE s.name IN $node_names AND t.name IN $node_names
                RETURN s.name AS source, t.name AS target, type(r) AS type,
                       r.description AS description, r.weight AS weight
                ORDER BY r.weight DESC
            """
            edges = await run_query(edges_query, {"kb_id": kb_id, "node_names": node_names})
        else:
            edges = []
    else:
        nodes_query = """
            MATCH (e:Entity {kb_id: $kb_id})
            RETURN e.name AS name, e.entity_type AS entity_type,
                   e.description AS description, e.mention_count AS mention_count,
                   e.source_doc_ids AS source_doc_ids
            ORDER BY e.mention_count DESC
        """
        edges_query = """
            MATCH (s:Entity {kb_id: $kb_id})-[r]->(t:Entity {kb_id: $kb_id})
            RETURN s.name AS source, t.name AS target, type(r) AS type,
                   r.description AS description, r.weight AS weight
            ORDER BY r.weight DESC
        """
        nodes = await run_query(nodes_query, {"kb_id": kb_id})
        edges = await run_query(edges_query, {"kb_id": kb_id})

    return {"nodes": nodes, "edges": edges}


async def get_graph_stats(kb_id: str) -> dict:
    """Get graph statistics for a KB."""
    query = """
        MATCH (e:Entity {kb_id: $kb_id})
        WITH count(e) AS nodeCount,
             COLLECT(DISTINCT e.entity_type) AS types
        OPTIONAL MATCH (s:Entity {kb_id: $kb_id})-[r]->(t:Entity {kb_id: $kb_id})
        RETURN nodeCount, count(r) AS edgeCount, types
    """
    results = await run_query(query, {"kb_id": kb_id})
    if results:
        return {
            "total_nodes": results[0]["nodeCount"],
            "total_edges": results[0]["edgeCount"],
            "entity_types": results[0]["types"],
        }
    return {"total_nodes": 0, "total_edges": 0, "entity_types": []}
