"""PageIndex content retriever — fetches specific page ranges from stored content.

At query time the navigator selects tree nodes and identifies which page ranges
contain the answer. This module retrieves the actual page content for those
ranges from the stored source_pages JSON.

This is the key difference from the old implementation:
  OLD: text was embedded in tree nodes at index time — no way to get more
  NEW: full per-page content is stored separately; retriever fetches on demand
"""
from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


def parse_page_spec(spec: str) -> list[int]:
    """Parse a page range spec like '3-5,7,10-12' into sorted page numbers."""
    result: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            segs = part.split("-", 1)
            try:
                start, end = int(segs[0]), int(segs[1])
                result.update(range(start, end + 1))
            except (ValueError, IndexError):
                pass
        else:
            try:
                result.add(int(part))
            except ValueError:
                pass
    return sorted(n for n in result if n > 0)


def node_page_spec(node: dict) -> str:
    """Return the page range spec string for a tree node."""
    ps = node.get("page_start", 1)
    pe = node.get("page_end", ps)
    if ps == pe:
        return str(ps)
    return f"{ps}-{pe}"


def retrieve_pages(
    source_pages: list[dict],
    page_spec: str,
    max_chars: int = 20_000,
) -> str:
    """Retrieve and format content for a page spec from stored source pages.

    Args:
        source_pages: Per-page dicts from page_extractor (stored in DocumentTree).
        page_spec:    Comma-separated page numbers/ranges, e.g. "3-5,7,10-12".
        max_chars:    Cap total returned content to avoid context overflow.

    Returns:
        Formatted string:
          [Page 3]
          <content>

          [Page 4]
          <content>
          ...
    """
    if not source_pages:
        return ""

    page_map = {p["page"]: p for p in source_pages}
    requested = parse_page_spec(page_spec)

    parts: list[str] = []
    total_chars = 0

    for page_num in requested:
        if page_num not in page_map:
            continue
        page = page_map[page_num]
        content = page.get("content", "").strip()
        if not content:
            continue

        block = f"[Page {page_num}]\n{content}"

        # Include image references
        images = page.get("images", [])
        if images:
            img_refs = ", ".join(img.get("path", "") for img in images if img.get("path"))
            if img_refs:
                block += f"\n[Images: {img_refs}]"

        if total_chars + len(block) > max_chars:
            # Include partial content if there's room
            remaining = max_chars - total_chars
            if remaining > 200:
                parts.append(block[:remaining] + "\n…[truncated]")
            break

        parts.append(block)
        total_chars += len(block)

    return "\n\n".join(parts)


def retrieve_nodes(
    tree: dict,
    node_ids: list[str],
    source_pages: list[dict],
    max_chars_per_node: int = 8000,
) -> list[dict]:
    """Retrieve full page content for a list of selected node IDs.

    Returns a list of dicts:
      {
        "node_id":    str,
        "title":      str,
        "page_start": int,
        "page_end":   int,
        "content":    str,   # full page content from source_pages
        "summary":    str,   # pre-computed node summary
      }

    Used by the answer generator instead of the truncated node.text.
    """
    # Build node lookup
    node_map: dict[str, dict] = {}

    def _index(nodes: list) -> None:
        for n in nodes:
            node_map[n["node_id"]] = n
            _index(n.get("children", []))

    _index(tree.get("nodes", []))

    results: list[dict] = []
    for nid in node_ids:
        # Handle both raw node_id and prefixed doc_id::node_id
        raw_id = nid.split("::")[-1] if "::" in nid else nid
        node = node_map.get(raw_id) or node_map.get(nid)
        if not node:
            continue

        ps = node.get("page_start", 1)
        pe = node.get("page_end", ps)
        page_spec = f"{ps}-{pe}" if ps != pe else str(ps)
        content = retrieve_pages(source_pages, page_spec, max_chars=max_chars_per_node)

        results.append({
            "node_id":    nid,
            "title":      node.get("title", ""),
            "page_start": ps,
            "page_end":   pe,
            "content":    content or node.get("text", ""),  # fallback to embedded text
            "summary":    node.get("summary", ""),
        })

    return results


def build_node_page_ranges(
    selected_node_ids: list[str],
    tree: dict,
) -> dict[str, str]:
    """Build a mapping of node_id → page_spec for all selected nodes.

    Useful for the navigator to report which page ranges it will retrieve.
    """
    node_map: dict[str, dict] = {}

    def _index(nodes: list) -> None:
        for n in nodes:
            node_map[n["node_id"]] = n
            _index(n.get("children", []))

    _index(tree.get("nodes", []))

    result: dict[str, str] = {}
    for nid in selected_node_ids:
        raw_id = nid.split("::")[-1] if "::" in nid else nid
        node = node_map.get(raw_id) or node_map.get(nid)
        if node:
            result[nid] = node_page_spec(node)

    return result
