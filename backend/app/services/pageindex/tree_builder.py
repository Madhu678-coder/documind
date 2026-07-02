"""PageIndex tree builder — builds hierarchical index from per-page content.

Full pipeline (replaces the old LLM-from-raw-text approach):

  1. page_extractor  → per-page content with accurate page numbers
  2. structure_analyzer → hierarchical section plan (LLM detects boundaries)
  3. Bottom-up summarization → every node gets a 1-2 sentence summary
  4. Returns tree dict ready for storage in DocumentTree.tree_json

The key difference from the old implementation:
  - Page numbers are REAL (from actual document pages, not guessed from text)
  - Per-page content is stored separately for retrieval at query time
  - Structure is detected from page-level signals (headings, content changes)
    not from a single raw-text-to-tree LLM call that had to guess everything
"""
from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.llm.provider import LLMProvider

logger = logging.getLogger(__name__)

_SUMMARY_BATCH_SIZE = 10
_LEAF_SUMMARY_SYSTEM = """\
You are a document summarizer. Given a section title and its raw text, write a
concise 1-2 sentence summary capturing the key information.
Focus on: key facts, rules, numbers, entities, actionable information.
Return ONLY the summary text — no JSON, no quotes, no explanation."""

_PARENT_SUMMARY_SYSTEM = """\
You are a document summarizer. Given a section title and summaries of its child
sections, write a concise 1-2 sentence summary of what this entire section covers.
Return ONLY the summary text — no JSON, no quotes, no explanation."""

_BATCH_SUMMARY_SYSTEM = """\
You are a document summarizer. For each numbered section, write a concise
1-2 sentence summary.
Return a JSON array of strings, one per section, in the same order.
Example: ["Summary 1", "Summary 2"]
Return ONLY the JSON array — no explanation, no markdown fences."""


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def count_nodes(tree: dict) -> int:
    def _count(nodes: list) -> int:
        return sum(1 + _count(n.get("children", [])) for n in nodes)
    return _count(tree.get("nodes", []))


def max_depth(tree: dict) -> int:
    def _depth(nodes: list) -> int:
        if not nodes:
            return 0
        return max(n.get("depth", 1) + _depth(n.get("children", [])) for n in nodes)
    return _depth(tree.get("nodes", []))


def collect_node_ids(tree: dict) -> list[str]:
    ids: list[str] = []
    def _collect(nodes: list) -> None:
        for n in nodes:
            ids.append(n["node_id"])
            _collect(n.get("children", []))
    _collect(tree.get("nodes", []))
    return ids


# ---------------------------------------------------------------------------
# Bottom-up summarization (kept from original, works on the new node schema)
# ---------------------------------------------------------------------------

async def _summarize_leaves_batch(
    leaf_nodes: list[dict],
    llm: "LLMProvider",
) -> None:
    """Batch-summarize leaf nodes in groups of _SUMMARY_BATCH_SIZE."""
    for i in range(0, len(leaf_nodes), _SUMMARY_BATCH_SIZE):
        batch = leaf_nodes[i : i + _SUMMARY_BATCH_SIZE]
        sections: list[str] = []
        for j, node in enumerate(batch):
            text = node.get("text", "")[:2000]
            title = node.get("title", "")
            sections.append(f"[{j+1}] Title: {title}\nContent: {text}")

        messages = [{"role": "user", "content": "\n\n---\n\n".join(sections)}]
        try:
            resp = await llm.complete(messages, system_prompt=_BATCH_SUMMARY_SYSTEM)
            raw = resp.content.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                raw = raw.removeprefix("json").strip()
                if raw.endswith("```"):
                    raw = raw[:-3]
            summaries = json.loads(raw)
            if isinstance(summaries, list) and len(summaries) == len(batch):
                for node, summary in zip(batch, summaries):
                    node["summary"] = str(summary).strip().strip('"')
                continue
        except Exception as exc:
            logger.warning("Batch summary failed: %s — falling back to individual", exc)

        # Individual fallback
        for node in batch:
            text = node.get("text", "")[:2000]
            title = node.get("title", "")
            try:
                r = await llm.complete(
                    [{"role": "user", "content": f"Title: {title}\n\nContent:\n{text}"}],
                    system_prompt=_LEAF_SUMMARY_SYSTEM,
                )
                node["summary"] = r.content.strip().strip('"') or f"Section: {title}"
            except Exception:
                node["summary"] = f"Section: {title}"


async def _rollup_summaries(node: dict, llm: "LLMProvider") -> str:
    """Recursively ensure node has a summary, rolling up from children."""
    children = node.get("children", [])
    if not children:
        if not node.get("summary"):
            text = node.get("text", "")[:2000]
            title = node.get("title", "")
            try:
                r = await llm.complete(
                    [{"role": "user", "content": f"Title: {title}\n\nContent:\n{text}"}],
                    system_prompt=_LEAF_SUMMARY_SYSTEM,
                )
                node["summary"] = r.content.strip().strip('"') or f"Section: {title}"
            except Exception:
                node["summary"] = f"Section: {title}"
        return node["summary"]

    child_summaries = [await _rollup_summaries(c, llm) for c in children]

    children_text = "\n".join(f"- {s}" for s in child_summaries)
    title = node.get("title", "")
    try:
        r = await llm.complete(
            [{"role": "user", "content": f"Title: {title}\n\nChild summaries:\n{children_text}"}],
            system_prompt=_PARENT_SUMMARY_SYSTEM,
        )
        node["summary"] = r.content.strip().strip('"') or f"Section: {title}"
    except Exception:
        node["summary"] = f"Section covering: {title}"

    return node["summary"]


async def _summarize_tree(tree: dict, llm: "LLMProvider") -> dict:
    """Add summaries to all nodes via bottom-up roll-up."""
    nodes = tree.get("nodes", [])

    # Phase 1: batch-summarize all leaves
    leaf_nodes: list[dict] = []
    def _collect_leaves(nlist: list) -> None:
        for n in nlist:
            if not n.get("children"):
                leaf_nodes.append(n)
            else:
                _collect_leaves(n["children"])
    _collect_leaves(nodes)

    await _summarize_leaves_batch(leaf_nodes, llm)

    # Phase 2: roll up parents
    for node in nodes:
        await _rollup_summaries(node, llm)

    logger.info("Tree summarization complete", extra={"nodes": count_nodes(tree)})
    return tree


# ---------------------------------------------------------------------------
# Main build function
# ---------------------------------------------------------------------------

async def build_tree(
    file_path: str,
    file_type: str,
    filename: str,
    llm: "LLMProvider",
    doc_id: str | None = None,
    images_dir: Path | None = None,
) -> tuple[dict, list[dict]]:
    """Build a PageIndex hierarchical tree from a document.

    Returns:
        (tree_dict, source_pages)

        tree_dict — hierarchical node tree for navigation and display
        source_pages — per-page raw content for page-range retrieval at query time

    Tree node schema:
      {
        "node_id":    str,    # e.g. "n1", "n1.1"
        "title":      str,
        "page_start": int,    # 1-indexed, REAL page number from document
        "page_end":   int,
        "depth":      int,    # 1 = top-level chapter
        "text":       str,    # leaf: full content; parent: first-page excerpt
        "summary":    str,    # 1-2 sentence LLM summary
        "images":     list,   # [{path: str}]  image refs
        "children":   list,   # nested nodes
      }
    """
    from app.services.pageindex.page_extractor import extract_pages
    from app.services.pageindex.structure_analyzer import analyze_structure

    doc_name = Path(filename).stem

    # ── Step 1: Extract per-page content ─────────────────────────────────────
    logger.info("PageIndex: extracting pages for %s", filename)
    source_pages = extract_pages(
        file_path=file_path,
        file_type=file_type,
        doc_name=doc_name,
        images_dir=images_dir,
    )

    if not source_pages:
        # Empty document fallback
        fallback_tree = {
            "doc_id": doc_id or str(uuid.uuid4()),
            "title": filename,
            "nodes": [{
                "node_id": "n1",
                "title": "Full Document",
                "page_start": 1,
                "page_end": 1,
                "depth": 1,
                "text": "",
                "summary": f"Content of {filename}",
                "images": [],
                "children": [],
            }],
        }
        return fallback_tree, source_pages

    # ── Step 2: Analyze structure → build node hierarchy ─────────────────────
    logger.info(
        "PageIndex: analyzing structure for %s (%d pages)",
        filename, len(source_pages),
    )
    nodes, doc_title = await analyze_structure(
        pages=source_pages,
        filename=filename,
        llm=llm,
        file_path=file_path,
        file_type=file_type,
    )

    if not nodes:
        # Structure analysis produced nothing — single-node fallback
        all_content = "\n\n".join(p.get("content", "") for p in source_pages)
        nodes = [{
            "node_id":    "n1",
            "title":      doc_title or filename,
            "page_start": source_pages[0]["page"],
            "page_end":   source_pages[-1]["page"],
            "depth":      1,
            "text":       all_content[:5000],
            "summary":    "",
            "images":     [],
            "children":   [],
        }]

    # ── Step 3: Bottom-up summarization ──────────────────────────────────────
    tree = {
        "doc_id": doc_id or str(uuid.uuid4()),
        "title":  doc_title or filename,
        "nodes":  nodes,
    }

    logger.info(
        "PageIndex: summarizing %d nodes for %s",
        count_nodes(tree), filename,
    )
    tree = await _summarize_tree(tree, llm)

    logger.info(
        "PageIndex tree built",
        extra={
            "doc": filename,
            "pages": len(source_pages),
            "nodes": count_nodes(tree),
            "depth": max_depth(tree),
        },
    )

    return tree, source_pages
