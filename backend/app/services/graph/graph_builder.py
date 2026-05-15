"""GraphRAG builder — extracts entities and relationships from documents via LLM.

Build pipeline:
1. Split document into chunks (handles large docs without timeout)
2. Extract entities + relationships per chunk (parallel LLM calls)
3. Deduplicate entities across chunks (merge descriptions)
4. Clean relationships (remove orphans, deduplicate)
5. Store nodes and edges in the database
6. Generate embeddings for new nodes (for vector-based entity resolution)
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.services.llm.provider import LLMProvider
    from app.services.embedding.provider import EmbeddingProvider

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────

_CHUNK_SIZE = 25000      # chars per chunk (~6000 tokens input) — fewer chunks = faster
_CHUNK_OVERLAP = 1000    # char overlap between chunks
_MAX_PARALLEL = 5        # max concurrent LLM calls for extraction

# ── Extraction Prompt ─────────────────────────────────────────────────────────

_EXTRACTION_SYSTEM_PROMPT = """\
You are a knowledge graph extraction expert. Given a text chunk from a document, \
extract all entities and relationships to build a knowledge graph.

**Entities** — For each provide:
- name: canonical name (consistent casing, no abbreviations unless standard)
- type: one of "organization", "person", "role", "policy", "process", "category", \
"location", "amount", "department", "document", "concept", "rule"
- description: 1-2 sentence description of what this entity is/does

**Relationships** — For each provide:
- source: exact entity name (must match an entity you extracted)
- target: exact entity name (must match an entity you extracted)
- type: verb phrase in snake_case (e.g. "eligible_for", "requires_approval_from", \
"varies_by", "includes", "belongs_to", "processed_by", "managed_by", "defines")
- description: 1 sentence explaining this relationship
- weight: strength 1-10 (10 = core/definitive relationship, 1 = weak/implied)

**Rules:**
- Extract 5-20 entities per chunk depending on content density
- Extract 5-30 relationships per chunk
- Every relationship's source and target MUST match an entity name exactly
- Use consistent naming across the chunk
- Include amounts, dates, and specific values as entities when they define rules
- Resolve pronouns to their actual entity

Return ONLY valid JSON:
{"entities": [{"name": "", "type": "", "description": ""}], \
"relationships": [{"source": "", "target": "", "type": "", "description": "", "weight": 5}]}
"""


# ── Text Chunking ─────────────────────────────────────────────────────────────


def _split_into_chunks(text: str, chunk_size: int = _CHUNK_SIZE, overlap: int = _CHUNK_OVERLAP) -> list[str]:
    """Split text into overlapping chunks for parallel extraction."""
    if len(text) <= chunk_size:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        chunks.append(chunk)
        start += chunk_size - overlap
    return chunks


# ── Per-Chunk Extraction ──────────────────────────────────────────────────────


async def _extract_from_chunk(
    chunk: str,
    chunk_index: int,
    total_chunks: int,
    filename: str,
    provider: "LLMProvider",
) -> dict[str, list[dict]]:
    """Extract entities and relationships from a single chunk."""
    chunk_label = f" (chunk {chunk_index + 1}/{total_chunks})" if total_chunks > 1 else ""
    messages = [
        {
            "role": "user",
            "content": f"Document: {filename}{chunk_label}\n\n{chunk}",
        }
    ]

    try:
        response = await provider.complete(
            messages, system_prompt=_EXTRACTION_SYSTEM_PROMPT, max_tokens=4096
        )
        return _parse_extraction_response(response.content)
    except Exception as exc:
        logger.warning(
            "Graph chunk extraction failed",
            extra={"chunk_index": chunk_index, "error": str(exc)},
        )
        return {"entities": [], "relationships": []}


def _parse_extraction_response(raw: str) -> dict[str, list[dict]]:
    """Parse LLM response into entities and relationships."""
    content = raw.strip()
    if content.startswith("```"):
        lines = content.split("\n")
        content = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
        if content.startswith("json"):
            content = content[4:]

    try:
        data = json.loads(content)
        entities = data.get("entities", [])
        relationships = data.get("relationships", [])

        # Validate entities
        valid_entities = []
        for e in entities:
            if isinstance(e, dict) and e.get("name") and e.get("type"):
                valid_entities.append({
                    "name": str(e["name"]).strip(),
                    "type": str(e["type"]).strip().lower(),
                    "description": str(e.get("description", "")).strip(),
                })

        # Validate relationships
        entity_names = {e["name"].lower() for e in valid_entities}
        valid_relationships = []
        for r in relationships:
            if isinstance(r, dict) and r.get("source") and r.get("target") and r.get("type"):
                source = str(r["source"]).strip()
                target = str(r["target"]).strip()
                if source.lower() in entity_names and target.lower() in entity_names and source.lower() != target.lower():
                    valid_relationships.append({
                        "source": source,
                        "target": target,
                        "type": str(r["type"]).strip().lower().replace(" ", "_"),
                        "description": str(r.get("description", "")).strip(),
                        "weight": min(max(float(r.get("weight", 5)), 1.0), 10.0),
                    })

        return {"entities": valid_entities, "relationships": valid_relationships}

    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        logger.warning("Graph extraction JSON parse failed", extra={"error": str(exc)})
        return {"entities": [], "relationships": []}


# ── Deduplication ─────────────────────────────────────────────────────────────


def _deduplicate_entities(all_entities: list[dict]) -> dict[str, dict]:
    """
    Merge duplicate entities by normalized name + type.
    Merges descriptions from multiple chunks.
    Returns: {normalized_key -> entity_dict}
    """
    merged: dict[str, dict] = {}

    for entity in all_entities:
        key = f"{entity['name'].lower().strip()}::{entity['type']}"

        if key not in merged:
            merged[key] = entity.copy()
        else:
            # Merge descriptions
            existing_desc = merged[key].get("description", "")
            new_desc = entity.get("description", "")
            if new_desc and new_desc.lower() not in existing_desc.lower():
                if existing_desc:
                    merged[key]["description"] = f"{existing_desc} | {new_desc}"
                else:
                    merged[key]["description"] = new_desc

    return merged


def _clean_relationships(
    all_relationships: list[dict],
    valid_entity_names: set[str],
) -> list[dict]:
    """
    Remove orphan relationships and deduplicate.
    Uses hash of (source, target, type) to detect duplicates.
    For duplicates, keep the one with higher weight.
    """
    seen: dict[str, dict] = {}

    for rel in all_relationships:
        source_lower = rel["source"].lower().strip()
        target_lower = rel["target"].lower().strip()

        # Only keep if both entities exist
        if source_lower not in valid_entity_names or target_lower not in valid_entity_names:
            continue

        # Skip self-loops
        if source_lower == target_lower:
            continue

        # Dedup key
        key = f"{source_lower}|{target_lower}|{rel['type']}"
        if key not in seen or rel.get("weight", 5) > seen[key].get("weight", 5):
            seen[key] = rel

    return list(seen.values())


# ── Full Extraction Pipeline ──────────────────────────────────────────────────


async def extract_graph(
    provider: "LLMProvider",
    text: str,
    filename: str,
) -> dict[str, Any]:
    """
    Extract entities and relationships from document text.
    Splits into chunks and processes in parallel for reliability.

    Returns dict with 'entities' (deduplicated dict) and 'relationships' (cleaned list).
    """
    chunks = _split_into_chunks(text)
    logger.info(
        "Graph extraction starting",
        extra={"doc_filename": filename, "chunks": len(chunks), "text_len": len(text)},
    )

    # Process chunks in parallel (limited concurrency)
    semaphore = asyncio.Semaphore(_MAX_PARALLEL)

    async def _extract_with_limit(chunk: str, idx: int) -> dict:
        async with semaphore:
            return await _extract_from_chunk(chunk, idx, len(chunks), filename, provider)

    tasks = [_extract_with_limit(chunk, i) for i, chunk in enumerate(chunks)]
    results = await asyncio.gather(*tasks)

    # Collect all entities and relationships
    all_entities: list[dict] = []
    all_relationships: list[dict] = []
    for result in results:
        all_entities.extend(result.get("entities", []))
        all_relationships.extend(result.get("relationships", []))

    logger.info(
        "Raw extraction complete",
        extra={"raw_entities": len(all_entities), "raw_relationships": len(all_relationships)},
    )

    # Deduplicate
    entities_map = _deduplicate_entities(all_entities)
    valid_names = {e["name"].lower().strip() for e in entities_map.values()}
    relationships = _clean_relationships(all_relationships, valid_names)

    logger.info(
        "Graph extraction complete",
        extra={"entities": len(entities_map), "relationships": len(relationships)},
    )

    return {"entities": entities_map, "relationships": relationships}


# ── Database Storage ──────────────────────────────────────────────────────────


async def build_graph(
    provider: "LLMProvider",
    embedding_provider: "EmbeddingProvider",
    text: str,
    filename: str,
    doc_id: str,
    kb_id: str,
    workspace_id: str,
    db: "AsyncSession",
) -> dict[str, int]:
    """
    Full graph build pipeline for a document using Neo4j.

    1. Extract entities + relationships (chunk-by-chunk, parallel)
    2. Deduplicate via Neo4j MERGE (handles dedup natively)
    3. Store nodes and edges in Neo4j
    4. No separate embedding step — Neo4j full-text search handles entity resolution

    Returns: {"nodes_created": N, "nodes_updated": M, "edges_created": E}
    """
    from app.services.graph.neo4j_client import upsert_entity, upsert_relationship, ensure_schema

    # Ensure Neo4j schema exists
    await ensure_schema()

    # Step 1: Extract (chunk-by-chunk, parallel)
    extracted = await extract_graph(provider, text, filename)
    entities_map = extracted["entities"]
    relationships = extracted["relationships"]

    if not entities_map:
        logger.warning("No entities extracted", extra={"doc_filename": filename})
        return {"nodes_created": 0, "nodes_updated": 0, "edges_created": 0}

    # Step 2: Upsert entities into Neo4j (MERGE handles dedup)
    nodes_created = 0
    for key, entity in entities_map.items():
        await upsert_entity(
            kb_id=kb_id,
            name=entity["name"],
            entity_type=entity["type"],
            description=entity["description"],
            doc_id=doc_id,
        )
        nodes_created += 1

    # Step 3: Upsert relationships into Neo4j
    edges_created = 0
    for rel in relationships:
        await upsert_relationship(
            kb_id=kb_id,
            source_name=rel["source"],
            target_name=rel["target"],
            rel_type=rel["type"],
            description=rel["description"],
            weight=rel.get("weight", 5),
            doc_id=doc_id,
        )
        edges_created += 1

    logger.info(
        "Graph built in Neo4j",
        extra={
            "doc_filename": filename,
            "nodes_upserted": nodes_created,
            "edges_upserted": edges_created,
        },
    )

    return {
        "nodes_created": nodes_created,
        "nodes_updated": 0,  # Neo4j MERGE handles this internally
        "edges_created": edges_created,
    }
