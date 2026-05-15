"""PageIndex tree builder — integrates document extraction with LLM tree generation.

Implements the full PageIndex algorithm:
1. Extract text from document
2. Build hierarchical tree structure via LLM
3. Bottom-up summarization: leaf nodes summarized first, then rolled up to parents
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from app.services.document.extractor import extract_text
from app.services.llm.provider import LLMProvider

logger = logging.getLogger(__name__)

# ── Tree Structure Generation Prompt ──────────────────────────────────────────

_PAGEINDEX_SYSTEM_PROMPT = """You are a document structure analyzer implementing the PageIndex algorithm.
Given document text, produce a hierarchical JSON tree representing the document's structure.

Each node MUST have exactly these fields:
- node_id: unique string identifier (e.g. "n1", "n1.1", "n1.1.2")
- title: descriptive section title (string)
- page_start: starting page number (integer, 1-indexed)
- page_end: ending page number (integer, >= page_start)
- depth: nesting depth (integer, 1 = top-level chapter)
- text: raw section text excerpt (string, may be truncated)
- children: array of child nodes (same schema, empty array if leaf)

Return a JSON object with:
- doc_id: document identifier (string)
- title: document title (string)
- nodes: array of top-level nodes

Return ONLY valid JSON with no explanation, no markdown fences."""

# ── Summarization Prompts ─────────────────────────────────────────────────────

_LEAF_SUMMARY_SYSTEM_PROMPT = """You are a document summarizer. Given a section title and its raw text content,
write a concise 1-2 sentence summary that captures the key information in this section.

The summary should help someone quickly understand what this section covers without reading the full text.
Focus on: key facts, rules, numbers, entities, and actionable information.

Return ONLY the summary text — no JSON, no explanation, no quotes."""

_PARENT_SUMMARY_SYSTEM_PROMPT = """You are a document summarizer. Given a section title and the summaries of its
child sections, write a concise 1-2 sentence summary that captures what this entire section covers.

The summary should help someone quickly understand the scope of this section and its sub-sections.
Focus on: the overall theme, key topics covered, and the most important takeaways.

Return ONLY the summary text — no JSON, no explanation, no quotes."""

# ── Configuration ─────────────────────────────────────────────────────────────

# Increased from 7500 to 100K — Claude Sonnet has 200K context window.
# Most business documents (< 50 pages) fit in a single call.
_CHUNK_SIZE = 100_000  # chars per LLM call
_CHUNK_OVERLAP = 1000  # overlap between consecutive chunks for context continuity

# Maximum nodes to summarize in a single batch call
_SUMMARY_BATCH_SIZE = 10


def _parse_tree_response(content: str, filename: str, fallback_text: str) -> dict:
    """Parse LLM response into tree JSON, with fallback on parse failure."""
    raw = content.strip()
    # Strip markdown code fences if present
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        tree = json.loads(raw)
        # Validate minimal structure
        if "nodes" in tree and isinstance(tree["nodes"], list):
            return tree
    except (json.JSONDecodeError, ValueError):
        pass

    logger.warning("Failed to parse LLM tree response, using fallback", extra={"doc_filename": filename})
    return _fallback_tree(filename, fallback_text)


def _fallback_tree(filename: str, text: str) -> dict:
    """Minimal single-node tree used when LLM response cannot be parsed."""
    return {
        "doc_id": str(uuid.uuid4()),
        "title": filename,
        "nodes": [
            {
                "node_id": "n1",
                "title": "Full Document",
                "summary": f"Complete content of {filename}",
                "page_start": 1,
                "page_end": 1,
                "depth": 1,
                "text": text[:2000],
                "children": [],
            }
        ],
    }


def count_nodes(tree: dict) -> int:
    """Recursively count all nodes in a tree."""
    def _count(nodes: list) -> int:
        total = 0
        for node in nodes:
            total += 1
            total += _count(node.get("children", []))
        return total

    return _count(tree.get("nodes", []))


def max_depth(tree: dict) -> int:
    """Return the maximum depth of any node in the tree."""
    def _depth(nodes: list) -> int:
        if not nodes:
            return 0
        return max(
            node.get("depth", 1) + _depth(node.get("children", []))
            for node in nodes
        )

    return _depth(tree.get("nodes", []))


def collect_node_ids(tree: dict) -> list[str]:
    """Collect all node_ids from a tree (depth-first)."""
    ids: list[str] = []

    def _collect(nodes: list) -> None:
        for node in nodes:
            ids.append(node["node_id"])
            _collect(node.get("children", []))

    _collect(tree.get("nodes", []))
    return ids


def _split_text_into_chunks(text: str, chunk_size: int = _CHUNK_SIZE, overlap: int = _CHUNK_OVERLAP) -> list[str]:
    """Split document text into overlapping chunks for multi-pass tree building."""
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


def _merge_partial_trees(partial_trees: list[dict], filename: str) -> dict:
    """
    Merge trees built from consecutive text chunks into a single tree.

    Deduplicates nodes by title similarity and re-indexes node IDs to avoid
    collisions across chunks.
    """
    if len(partial_trees) == 1:
        return partial_trees[0]

    merged_nodes: list[dict] = []
    seen_titles: set[str] = set()
    node_counter = 1

    def _reindex(node: dict, prefix: str) -> dict:
        """Assign new unique node_id and recurse into children."""
        nonlocal node_counter
        new_id = f"n{node_counter}"
        node_counter += 1
        node["node_id"] = new_id
        node["children"] = [_reindex(c, prefix) for c in node.get("children", [])]
        return node

    for tree in partial_trees:
        for node in tree.get("nodes", []):
            title_key = node.get("title", "").strip().lower()
            # Skip near-duplicate top-level nodes from overlapping chunks
            if title_key and title_key in seen_titles:
                # Merge children of duplicate into existing node
                for existing in merged_nodes:
                    if existing.get("title", "").strip().lower() == title_key:
                        existing_child_titles = {
                            c.get("title", "").strip().lower()
                            for c in existing.get("children", [])
                        }
                        for child in node.get("children", []):
                            if child.get("title", "").strip().lower() not in existing_child_titles:
                                existing["children"].append(child)
                        # Extend page range
                        existing["page_end"] = max(
                            existing.get("page_end", 1),
                            node.get("page_end", 1),
                        )
                        # Merge text if the new chunk has more content
                        if len(node.get("text", "")) > len(existing.get("text", "")):
                            existing["text"] = node["text"]
                        break
                continue
            seen_titles.add(title_key)
            merged_nodes.append(node)

    # Re-index all node IDs to be globally unique
    merged_nodes = [_reindex(n, "") for n in merged_nodes]

    return {
        "doc_id": partial_trees[0].get("doc_id", str(uuid.uuid4())),
        "title": partial_trees[0].get("title", filename),
        "nodes": merged_nodes,
    }


# ── Bottom-Up Summarization ──────────────────────────────────────────────────


async def _summarize_leaf_node(node: dict, llm: LLMProvider) -> str:
    """Generate a 1-2 sentence summary for a leaf node from its raw text."""
    text = node.get("text", "")
    title = node.get("title", "")

    if not text.strip():
        return f"Section: {title}"

    # Truncate very long text to avoid wasting tokens on summarization
    text_for_summary = text[:3000]

    messages = [
        {
            "role": "user",
            "content": f"Section title: {title}\n\nSection content:\n{text_for_summary}",
        }
    ]

    try:
        response = await llm.complete(messages, system_prompt=_LEAF_SUMMARY_SYSTEM_PROMPT)
        summary = response.content.strip()
        # Clean up any accidental quotes or formatting
        summary = summary.strip('"').strip("'")
        return summary if summary else f"Section: {title}"
    except Exception as exc:
        logger.warning("Leaf summarization failed", extra={"node_id": node.get("node_id"), "error": str(exc)})
        return f"Section: {title}"


async def _summarize_parent_node(node: dict, children_summaries: list[str], llm: LLMProvider) -> str:
    """Generate a rolled-up summary for a parent node from its children's summaries."""
    title = node.get("title", "")

    children_text = "\n".join(f"- {s}" for s in children_summaries)

    messages = [
        {
            "role": "user",
            "content": f"Section title: {title}\n\nChild section summaries:\n{children_text}",
        }
    ]

    try:
        response = await llm.complete(messages, system_prompt=_PARENT_SUMMARY_SYSTEM_PROMPT)
        summary = response.content.strip()
        summary = summary.strip('"').strip("'")
        return summary if summary else f"Section: {title}"
    except Exception as exc:
        logger.warning("Parent summarization failed", extra={"node_id": node.get("node_id"), "error": str(exc)})
        return f"Section covering: {title}"


async def _summarize_nodes_batch(nodes: list[dict], llm: LLMProvider) -> list[str]:
    """
    Summarize multiple leaf nodes in a single LLM call for efficiency.
    Returns a list of summaries in the same order as input nodes.
    """
    if not nodes:
        return []

    # Build a batch prompt
    sections = []
    for i, node in enumerate(nodes):
        text = node.get("text", "")[:2000]
        title = node.get("title", "")
        sections.append(f"[{i+1}] Title: {title}\nContent: {text}")

    batch_prompt = "\n\n---\n\n".join(sections)

    system_prompt = """You are a document summarizer. For each numbered section below, write a concise 1-2 sentence summary.

Return a JSON array of strings where each element is the summary for the corresponding section number.
Example: ["Summary for section 1", "Summary for section 2", ...]

Return ONLY the JSON array — no explanation, no markdown fences."""

    messages = [{"role": "user", "content": batch_prompt}]

    try:
        response = await llm.complete(messages, system_prompt=system_prompt)
        raw = response.content.strip()
        if raw.startswith("```"):
            parts = raw.split("```")
            raw = parts[1] if len(parts) > 1 else raw
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        summaries = json.loads(raw)
        if isinstance(summaries, list) and len(summaries) == len(nodes):
            return [str(s) for s in summaries]
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        logger.warning("Batch summarization parse failed, falling back to individual", extra={"error": str(exc)})

    # Fallback: summarize individually
    results = []
    for node in nodes:
        summary = await _summarize_leaf_node(node, llm)
        results.append(summary)
    return results


async def _summarize_tree_bottom_up(tree: dict, llm: LLMProvider) -> dict:
    """
    Add summaries to all nodes in the tree using bottom-up roll-up strategy.

    Process:
    1. Collect all leaf nodes → batch summarize from raw text
    2. For parent nodes → summarize from children's summaries (rolled up)

    Modifies the tree in-place and returns it.
    """
    nodes = tree.get("nodes", [])
    if not nodes:
        return tree

    # Phase 1: Collect and summarize all leaf nodes in batches
    leaf_nodes: list[dict] = []

    def _collect_leaves(node_list: list) -> None:
        for node in node_list:
            children = node.get("children", [])
            if not children:
                leaf_nodes.append(node)
            else:
                _collect_leaves(children)

    _collect_leaves(nodes)

    # Batch summarize leaves
    for i in range(0, len(leaf_nodes), _SUMMARY_BATCH_SIZE):
        batch = leaf_nodes[i:i + _SUMMARY_BATCH_SIZE]
        summaries = await _summarize_nodes_batch(batch, llm)
        for node, summary in zip(batch, summaries):
            node["summary"] = summary

    # Phase 2: Bottom-up roll-up for parent nodes
    async def _rollup(node: dict) -> str:
        """Recursively ensure node has a summary, rolling up from children."""
        children = node.get("children", [])

        if not children:
            # Leaf — should already have summary from Phase 1
            if "summary" not in node:
                node["summary"] = await _summarize_leaf_node(node, llm)
            return node["summary"]

        # Parent — first ensure all children have summaries
        children_summaries = []
        for child in children:
            child_summary = await _rollup(child)
            children_summaries.append(child_summary)

        # Now summarize this parent from its children
        node["summary"] = await _summarize_parent_node(node, children_summaries, llm)
        return node["summary"]

    for node in nodes:
        await _rollup(node)

    logger.info(
        "Tree summarization complete",
        extra={"total_nodes": count_nodes(tree), "leaf_nodes": len(leaf_nodes)},
    )

    return tree


# ── Main Build Function ───────────────────────────────────────────────────────


async def build_tree(
    file_path: str,
    file_type: str,
    filename: str,
    llm: LLMProvider,
    doc_id: str | None = None,
) -> dict:
    """
    Extract text from a document and generate a PageIndex hierarchical tree via LLM.

    Full pipeline:
    1. Extract text from document
    2. Split into chunks if needed (most docs fit in one call with 100K limit)
    3. LLM generates hierarchical tree structure
    4. Merge partial trees if multiple chunks
    5. Bottom-up summarization: leaf summaries → parent roll-ups

    Args:
        file_path: Path to the document file on disk.
        file_type: One of "pdf", "docx", "txt", "md".
        filename: Original filename (used in prompts and fallback).
        llm: LLMProvider instance to use for tree generation.
        doc_id: Optional document UUID to embed in the tree root.

    Returns:
        Tree dict matching the PageIndex node schema (with summaries).
    """
    text = extract_text(file_path, file_type)
    chunks = _split_text_into_chunks(text)

    partial_trees: list[dict] = []
    for i, chunk in enumerate(chunks):
        chunk_label = f" (part {i + 1}/{len(chunks)})" if len(chunks) > 1 else ""
        messages = [
            {
                "role": "user",
                "content": (
                    f"Document filename: {filename}{chunk_label}\n\n"
                    f"{chunk}"
                ),
            }
        ]
        # Tree generation needs more output tokens for large documents
        response = await llm.complete(messages, system_prompt=_PAGEINDEX_SYSTEM_PROMPT, max_tokens=8192)
        partial = _parse_tree_response(response.content, filename, chunk)
        partial_trees.append(partial)

    tree = _merge_partial_trees(partial_trees, filename)

    if doc_id:
        tree["doc_id"] = doc_id

    # Bottom-up summarization — adds 'summary' field to every node
    tree = await _summarize_tree_bottom_up(tree, llm)

    logger.info(
        "Tree built with summaries",
        extra={
            "doc_filename": filename,
            "text_len": len(text),
            "chunks_processed": len(chunks),
            "total_nodes": count_nodes(tree),
        },
    )

    return tree
