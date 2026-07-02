"""Render PageIndex tree structures to Markdown — mirrors OpenKB tree_renderer.py."""
from __future__ import annotations


def _render_nodes(nodes: list[dict], depth: int) -> str:
    lines: list[str] = []
    prefix = "#" * min(depth, 6)
    for node in nodes:
        title = node.get("title", "")
        start = node.get("start_index", "")
        end = node.get("end_index", "")
        summary = node.get("summary", "")
        children = node.get("nodes", [])
        lines.append(f"{prefix} {title} (pages {start}–{end})\n")
        if summary:
            lines.append(f"Summary: {summary}\n")
        if children:
            lines.append(_render_nodes(children, depth + 1))
    return "\n".join(lines)


def render_summary_md(tree: dict, source_name: str, doc_id: str, description: str = "") -> str:
    """Render a PageIndex tree dict to a Markdown summary page.

    Mirrors OpenKB's tree_renderer.render_summary_md().
    Frontmatter is managed by code — not included in the returned string
    (openkb_tasks.py stores doc_type and description separately in the DB).
    """
    structure = tree.get("structure", [])
    body = _render_nodes(structure, depth=1)
    header = f"# {source_name}\n\n"
    if description:
        header += f"{description}\n\n"
    return header + body
