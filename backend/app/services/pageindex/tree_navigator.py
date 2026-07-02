"""PageIndex tree navigator — two-level LLM-driven reasoning over document trees.

Implements proper PageIndex navigation:
1. Coarse pass: LLM sees only top-level nodes with summaries → picks relevant chapters
2. Fine pass: LLM sees children of selected chapters → picks exact leaf nodes
3. Raw text of selected leaves is passed to the answer generator
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.services.llm.provider import LLMProvider
from app.services.pageindex.content_retriever import build_node_page_ranges

logger = logging.getLogger(__name__)

# ── Navigation Prompts ────────────────────────────────────────────────────────

_COARSE_NAVIGATION_PROMPT = """You are a document navigation expert implementing the PageIndex algorithm.
Given a user query and a list of top-level document sections with their summaries,
identify which sections are most likely to contain the answer.

Each section is shown as:
  node_id=<id> | <title> (pp.X-Y): <summary>

Return a JSON object with:
- selected_node_ids: array of node_id strings EXACTLY as shown, most relevant first, max 5
- rationale: brief explanation of why these sections were selected
- confidence: float 0.0-1.0

IMPORTANT: Use the FULL node_id value exactly as shown. Select sections whose summaries
indicate they contain information relevant to the query.
Return ONLY valid JSON with no explanation, no markdown fences."""

_FINE_NAVIGATION_PROMPT = """You are a document navigation expert implementing the PageIndex algorithm.
You have already identified relevant top-level sections. Now drill down into their sub-sections
to find the exact nodes that contain the answer.

Each sub-section is shown as:
  node_id=<id> | <title> (pp.X-Y): <summary>

Return a JSON object with:
- selected_node_ids: array of node_id strings EXACTLY as shown, most relevant first, max 10
- rationale: object mapping each node_id to a brief explanation
- confidence: float 0.0-1.0

IMPORTANT: Use the FULL node_id value exactly as shown. Select the most specific nodes
that directly answer the query.
Return ONLY valid JSON with no explanation, no markdown fences."""

# Legacy single-pass prompt (used as fallback for small trees)
_NAVIGATION_SYSTEM_PROMPT = """You are a document navigation expert implementing the PageIndex algorithm.
Given a list of document sections and a user query, identify the most relevant sections to answer the query.

Each section is shown as: node_id=<id> | <title> (pp.X-Y): <summary>

Return a JSON object with:
- selected_node_ids: array of node_id strings EXACTLY as shown, most relevant first, max 10
- rationale: object mapping each node_id to a brief explanation
- confidence: float 0.0-1.0

IMPORTANT: Use the FULL node_id value including the :: separator exactly as shown. Do NOT use just the doc UUID.
Return ONLY valid JSON with no explanation, no markdown fences."""

# Threshold: if total nodes across all docs is below this, use single-pass navigation
_TWO_LEVEL_THRESHOLD = 15


# ── Data Classes ──────────────────────────────────────────────────────────────

@dataclass
class NavigationResult:
    selected_node_ids: list[str]
    rationale: dict[str, str]
    confidence: float
    # Page ranges for each selected node — used by content_retriever at query time
    page_ranges: dict[str, str] = field(default_factory=dict)


# ── Tree Utilities ────────────────────────────────────────────────────────────

def prefix_node_ids(tree: dict, doc_id: str) -> dict:
    """
    Return a copy of the tree with all node_ids prefixed as '{doc_id}::{node_id}'.
    Used when merging trees from multiple documents to prevent ID collisions.
    """
    import copy
    tree_copy = copy.deepcopy(tree)
    tree_copy["doc_id"] = doc_id

    def _prefix(nodes: list) -> None:
        for node in nodes:
            node["node_id"] = f"{doc_id}::{node['node_id']}"
            _prefix(node.get("children", []))

    _prefix(tree_copy.get("nodes", []))
    return tree_copy


def merge_trees(trees: list[tuple[str, dict]]) -> dict:
    """
    Merge multiple document trees into a single tree.
    Each tree's node IDs are prefixed with its doc_id to prevent collisions.
    """
    merged_nodes: list[dict] = []

    for doc_id, tree in trees:
        prefixed = prefix_node_ids(tree, doc_id)
        merged_nodes.extend(prefixed.get("nodes", []))

    return {
        "doc_id": "merged",
        "title": "Merged Document Collection",
        "nodes": merged_nodes,
    }


def _get_tree_nodes(tree: dict) -> list:
    """Get top-level nodes from a tree dict."""
    if "nodes" in tree:
        return tree["nodes"]
    if "children" in tree:
        return tree["children"]
    return []


def _get_node_display_text(node: dict) -> str:
    """Get the best display text for a node — summary if available, else truncated text."""
    summary = node.get("summary", "")
    if summary:
        return summary
    # Fallback to truncated raw text
    return node.get("text", "")[:150]


def _count_total_nodes(trees: list[tuple[str, dict]]) -> int:
    """Count total nodes across all trees."""
    total = 0
    for _, tree in trees:
        def _count(nodes: list) -> int:
            c = 0
            for node in nodes:
                c += 1
                c += _count(node.get("children", []))
            return c
        total += _count(_get_tree_nodes(tree))
    return total


# ── TOC Builders ──────────────────────────────────────────────────────────────

def _build_coarse_toc(trees: list[tuple[str, dict]]) -> str:
    """
    Build a TOC showing ONLY top-level (depth-1) nodes with summaries.
    Used for the coarse navigation pass.
    """
    parts: list[str] = []
    for doc_id, tree in trees:
        doc_title = tree.get("title", doc_id)
        lines: list[str] = [f"\n=== {doc_title} ==="]

        for node in _get_tree_nodes(tree):
            prefixed_id = f"{doc_id}::{node['node_id']}"
            display = _get_node_display_text(node)
            lines.append(
                f"node_id={prefixed_id} | {node['title']} "
                f"(pp.{node.get('page_start', '?')}-{node.get('page_end', '?')}): "
                f"{display}"
            )

        parts.append("\n".join(lines))

    return "\n".join(parts)


def _build_fine_toc(selected_top_ids: list[str], trees: list[tuple[str, dict]]) -> str:
    """
    Build a TOC showing children of the selected top-level nodes.
    Used for the fine navigation pass.

    If a selected node has no children (is a leaf), include it directly.
    """
    # Build a lookup: prefixed_id -> (doc_id, node)
    node_map: dict[str, tuple[str, dict]] = {}
    for doc_id, tree in trees:
        for node in _get_tree_nodes(tree):
            prefixed_id = f"{doc_id}::{node['node_id']}"
            node_map[prefixed_id] = (doc_id, node)

    lines: list[str] = []
    for top_id in selected_top_ids:
        if top_id not in node_map:
            continue
        doc_id, parent_node = node_map[top_id]
        children = parent_node.get("children", [])

        lines.append(f"\n--- {parent_node['title']} ---")

        if not children:
            # Leaf node — include itself
            display = _get_node_display_text(parent_node)
            lines.append(
                f"node_id={top_id} | {parent_node['title']} "
                f"(pp.{parent_node.get('page_start', '?')}-{parent_node.get('page_end', '?')}): "
                f"{display}"
            )
        else:
            # Show children
            for child in children:
                child_prefixed_id = f"{doc_id}::{child['node_id']}"
                display = _get_node_display_text(child)
                lines.append(
                    f"node_id={child_prefixed_id} | {child['title']} "
                    f"(pp.{child.get('page_start', '?')}-{child.get('page_end', '?')}): "
                    f"{display}"
                )
                # Also show grandchildren if they exist (one more level)
                for grandchild in child.get("children", []):
                    gc_prefixed_id = f"{doc_id}::{grandchild['node_id']}"
                    gc_display = _get_node_display_text(grandchild)
                    lines.append(
                        f"  node_id={gc_prefixed_id} | {grandchild['title']} "
                        f"(pp.{grandchild.get('page_start', '?')}-{grandchild.get('page_end', '?')}): "
                        f"{gc_display}"
                    )

    return "\n".join(lines)


def _build_flat_toc(trees: list[tuple[str, dict]], max_nodes_per_doc: int = 20) -> str:
    """
    Build a flat TOC across all nodes (legacy single-pass format).
    Uses summaries when available, falls back to truncated text.
    """
    parts: list[str] = []
    for doc_id, tree in trees:
        doc_title = tree.get("title", doc_id)
        lines: list[str] = [f"\n=== {doc_title} ==="]
        count = 0

        def _format(nodes: list, indent: int = 0, _did: str = doc_id) -> None:
            nonlocal count
            for node in nodes:
                if count >= max_nodes_per_doc:
                    return
                prefix = "  " * indent
                prefixed_id = f"{_did}::{node['node_id']}"
                display = _get_node_display_text(node)
                lines.append(
                    f"{prefix}node_id={prefixed_id} | {node['title']} "
                    f"(pp.{node.get('page_start', '?')}-{node.get('page_end', '?')}): "
                    f"{display}"
                )
                count += 1
                _format(node.get("children", []), indent + 1, _did)

        _format(_get_tree_nodes(tree))
        parts.append("\n".join(lines))

    return "\n".join(parts)


# ── Response Parsing ──────────────────────────────────────────────────────────

def _parse_navigation_response(content: str) -> NavigationResult:
    """Parse LLM navigation response into a NavigationResult."""
    raw = content.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        data = json.loads(raw)
        # Handle rationale as either dict or string
        rationale = data.get("rationale", {})
        if isinstance(rationale, str):
            rationale = {"_overall": rationale}

        return NavigationResult(
            selected_node_ids=data.get("selected_node_ids", []),
            rationale=rationale,
            confidence=float(data.get("confidence", 0.5)),
        )
    except (json.JSONDecodeError, ValueError, TypeError):
        logger.warning("Failed to parse navigation response")
        return NavigationResult(selected_node_ids=[], rationale={}, confidence=0.0)


# ── Public API ────────────────────────────────────────────────────────────────

def collect_node_ids_from_merged(tree: dict) -> list[str]:
    """Collect all node IDs from a (potentially merged) tree."""
    ids: list[str] = []

    def _collect(nodes: list) -> None:
        for node in nodes:
            ids.append(node["node_id"])
            _collect(node.get("children", []))

    _collect(tree.get("nodes", []))
    return ids


async def navigate(
    query: str,
    trees: list[tuple[str, dict]],
    llm: LLMProvider,
    history: list[dict] | None = None,
) -> NavigationResult:
    """
    Use two-level LLM reasoning to select relevant tree nodes for a given query.

    For small trees (< 15 total nodes): single-pass navigation.
    For larger trees: two-level navigation (coarse → fine).

    Caches results in Redis for repeated identical queries.

    Args:
        query: The user's question.
        trees: List of (doc_id, tree_dict) tuples for all ready documents in the KB.
        llm: LLMProvider instance.
        history: Optional conversation history for multi-turn context.

    Returns:
        NavigationResult with selected node IDs (prefixed as doc_id::node_id),
        rationale, and confidence.
    """
    if not trees:
        return NavigationResult(selected_node_ids=[], rationale={}, confidence=0.0)

    # Build conversation context for navigation
    conv_context = _build_nav_context(history) if history else ""

    # Check cache (includes history context in key for multi-turn awareness)
    cached = await _get_cached_navigation(query + conv_context, trees)
    if cached:
        logger.info("Navigation cache hit", extra={"query": query[:50]})
        return cached

    total_nodes = _count_total_nodes(trees)

    if total_nodes <= _TWO_LEVEL_THRESHOLD:
        result = await _navigate_single_pass(query, trees, llm, conv_context)
    else:
        result = await _navigate_two_level(query, trees, llm, conv_context)

    # Populate page_ranges for every selected node so content_retriever
    # can fetch actual page content at answer-generation time
    for doc_id, tree in trees:
        if result.selected_node_ids:
            ranges = build_node_page_ranges(result.selected_node_ids, tree)
            result.page_ranges.update(ranges)

    # Cache the result
    await _cache_navigation(query + conv_context, trees, result)

    return result


def _build_nav_context(history: list[dict] | None) -> str:
    """Build a brief conversation context string for navigation.

    Uses the last 3 complete turns (6 messages = 3 user+assistant pairs)
    so the navigator can disambiguate follow-up queries like "what about
    the next section?" or "expand on that".
    Each message is truncated to 200 chars to stay within prompt budget.
    """
    if not history:
        return ""
    # Take last 6 messages (= 3 full turns), not 3 messages (= 1.5 turns)
    recent = history[-6:]
    lines = []
    for msg in recent:
        role = msg.get("role", "user").capitalize()
        content = msg.get("content", "")[:200]  # truncate each message
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


async def _get_cached_navigation(query: str, trees: list[tuple[str, dict]]) -> NavigationResult | None:
    """Check Redis for a cached navigation result."""
    try:
        import hashlib
        import redis.asyncio as aioredis
        from app.core.config import settings

        # Cache key = hash of query + doc IDs (changes when docs are added/removed)
        doc_ids = sorted(doc_id for doc_id, _ in trees)
        cache_input = f"{query.strip().lower()}|{'|'.join(doc_ids)}"
        cache_key = f"nav:{hashlib.sha256(cache_input.encode()).hexdigest()[:16]}"

        r = aioredis.from_url(settings.redis_url)
        try:
            data = await r.get(cache_key)
            if data:
                parsed = json.loads(data)
                return NavigationResult(
                    selected_node_ids=parsed["selected_node_ids"],
                    rationale=parsed.get("rationale", {}),
                    confidence=parsed.get("confidence", 0.5),
                )
        finally:
            await r.aclose()
    except Exception:
        pass  # Cache miss or error — proceed without cache
    return None


async def _cache_navigation(query: str, trees: list[tuple[str, dict]], result: NavigationResult) -> None:
    """Store navigation result in Redis with 1-hour TTL."""
    try:
        import hashlib
        import redis.asyncio as aioredis
        from app.core.config import settings

        doc_ids = sorted(doc_id for doc_id, _ in trees)
        cache_input = f"{query.strip().lower()}|{'|'.join(doc_ids)}"
        cache_key = f"nav:{hashlib.sha256(cache_input.encode()).hexdigest()[:16]}"

        data = json.dumps({
            "selected_node_ids": result.selected_node_ids,
            "rationale": result.rationale,
            "confidence": result.confidence,
        })

        r = aioredis.from_url(settings.redis_url)
        try:
            await r.setex(cache_key, 3600, data)  # 1 hour TTL
        finally:
            await r.aclose()
    except Exception:
        pass  # Caching is best-effort


async def _navigate_single_pass(
    query: str,
    trees: list[tuple[str, dict]],
    llm: LLMProvider,
    conv_context: str = "",
) -> NavigationResult:
    """Single-pass navigation for small trees — shows all nodes at once."""
    toc = _build_flat_toc(trees, max_nodes_per_doc=30)

    context_block = f"Conversation context:\n{conv_context}\n\n" if conv_context else ""
    messages = [
        {
            "role": "user",
            "content": f"{context_block}User query: {query}\n\nAvailable document sections:\n{toc}",
        }
    ]

    response = await llm.complete(messages, system_prompt=_NAVIGATION_SYSTEM_PROMPT)
    result = _parse_navigation_response(response.content)

    logger.info(
        "Single-pass navigation result",
        extra={
            "node_ids": result.selected_node_ids,
            "confidence": result.confidence,
        },
    )
    return result


async def _navigate_two_level(
    query: str,
    trees: list[tuple[str, dict]],
    llm: LLMProvider,
    conv_context: str = "",
) -> NavigationResult:
    """
    Two-level navigation for larger trees:
    1. Coarse pass: select relevant top-level chapters from summaries
    2. Fine pass: drill into selected chapters to find exact nodes
    """
    # ── Pass 1: Coarse navigation (top-level only) ────────────────────────────
    coarse_toc = _build_coarse_toc(trees)

    context_block = f"Conversation context:\n{conv_context}\n\n" if conv_context else ""
    coarse_messages = [
        {
            "role": "user",
            "content": f"{context_block}User query: {query}\n\nTop-level document sections:\n{coarse_toc}",
        }
    ]

    coarse_response = await llm.complete(coarse_messages, system_prompt=_COARSE_NAVIGATION_PROMPT)
    coarse_result = _parse_navigation_response(coarse_response.content)

    logger.info(
        "Coarse navigation result",
        extra={
            "selected_chapters": coarse_result.selected_node_ids,
            "confidence": coarse_result.confidence,
        },
    )

    if not coarse_result.selected_node_ids:
        return coarse_result

    # Check if any selected top-level nodes have children
    has_children = False
    node_map: dict[str, dict] = {}
    for doc_id, tree in trees:
        for node in _get_tree_nodes(tree):
            prefixed_id = f"{doc_id}::{node['node_id']}"
            node_map[prefixed_id] = node
            if prefixed_id in coarse_result.selected_node_ids and node.get("children"):
                has_children = True

    if not has_children:
        # All selected nodes are leaves — no need for fine pass
        return coarse_result

    # ── Pass 2: Fine navigation (drill into selected chapters) ────────────────
    fine_toc = _build_fine_toc(coarse_result.selected_node_ids, trees)

    fine_messages = [
        {
            "role": "user",
            "content": (
                f"User query: {query}\n\n"
                f"You previously identified these sections as relevant. "
                f"Now select the most specific sub-sections:\n{fine_toc}"
            ),
        }
    ]

    fine_response = await llm.complete(fine_messages, system_prompt=_FINE_NAVIGATION_PROMPT)
    fine_result = _parse_navigation_response(fine_response.content)

    logger.info(
        "Fine navigation result",
        extra={
            "selected_nodes": fine_result.selected_node_ids,
            "confidence": fine_result.confidence,
        },
    )

    # Merge: if fine pass found specific nodes, use those.
    # Also include any coarse-selected leaf nodes (no children) that weren't drilled into.
    final_ids = list(fine_result.selected_node_ids)
    for cid in coarse_result.selected_node_ids:
        if cid in node_map and not node_map[cid].get("children"):
            if cid not in final_ids:
                final_ids.append(cid)

    # Combine rationale from both passes
    combined_rationale = {**coarse_result.rationale, **fine_result.rationale}

    # Use the higher confidence between the two passes
    final_confidence = max(coarse_result.confidence, fine_result.confidence)

    return NavigationResult(
        selected_node_ids=final_ids,
        rationale=combined_rationale,
        confidence=final_confidence,
    )
