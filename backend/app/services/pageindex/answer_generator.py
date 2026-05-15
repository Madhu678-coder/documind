"""PageIndex answer generator — produces cited answers from selected tree nodes."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import AsyncIterator, Any

from app.services.llm.provider import LLMProvider

logger = logging.getLogger(__name__)

_CITATION_SYSTEM_PROMPT = """You are a precise document analyst. Given selected document sections and a user query,
produce a comprehensive answer with inline citations. Format your answer using Markdown:
- Use **bold** for key terms and important information
- Use bullet lists or numbered lists where appropriate
- Use headings (##) for multi-section answers
- Keep paragraphs concise and scannable

For each claim in your answer, cite the source section using [citation:N] markers.
At the end, provide a JSON citations array where each entry has exactly these fields:
- doc_name: document filename (string)
- section_title: section title from the tree node (string)
- page_number: page number (integer)
- node_id: the node_id from the tree (string)
- verbatim_excerpt: exact quote from the section text (string, non-empty)

Format your response as:
<answer>
Your markdown-formatted answer with [citation:1], [citation:2] markers...
</answer>
<citations>
[{"doc_name": "...", "section_title": "...", "page_number": 1, "node_id": "...", "verbatim_excerpt": "..."}]
</citations>"""

# Maximum number of prior conversation turns to include as context
MAX_CONTEXT_TURNS = 5


@dataclass
class Citation:
    doc_name: str
    section_title: str
    page_number: int
    node_id: str
    verbatim_excerpt: str
    doc_id: str = ""  # document UUID for frontend linking

    def to_dict(self) -> dict:
        return {
            "document_id": self.doc_id,
            "filename": self.doc_name,
            "page_number": self.page_number,
            "node_id": self.node_id,
            "excerpt": self.verbatim_excerpt,
            # keep originals for backward compat
            "doc_name": self.doc_name,
            "section_title": self.section_title,
            "verbatim_excerpt": self.verbatim_excerpt,
        }


@dataclass
class GeneratedAnswer:
    content: str
    citations: list[Citation] = field(default_factory=list)


def extract_nodes_text(node_ids: list[str], tree: dict) -> list[dict]:
    """
    Fetch raw section text for the given node IDs from a tree.

    Returns list of dicts with node metadata needed for citations.
    """
    node_map: dict[str, dict] = {}

    def _index(nodes: list) -> None:
        for node in nodes:
            node_map[node["node_id"]] = node
            _index(node.get("children", []))

    _index(tree.get("nodes", []))

    result = []
    for nid in node_ids:
        if nid in node_map:
            result.append(node_map[nid])
    return result


def _build_context_from_history(history: list[dict]) -> str:
    """Format the last MAX_CONTEXT_TURNS message turns as context string."""
    # Take only the last MAX_CONTEXT_TURNS turns
    recent = history[-MAX_CONTEXT_TURNS:]
    lines = []
    for msg in recent:
        role = msg.get("role", "user").capitalize()
        content = msg.get("content", "")
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _build_sections_context(nodes: list[dict], doc_name: str) -> str:
    """Format selected nodes as context for the LLM."""
    parts = []
    for node in nodes:
        parts.append(
            f"[Node: {node['node_id']}] {node['title']} "
            f"(pp.{node.get('page_start', '?')}-{node.get('page_end', '?')})\n"
            f"{node.get('text', '')}"
        )
    return f"Document: {doc_name}\n\n" + "\n\n---\n\n".join(parts)


def _parse_answer_and_citations(content: str) -> tuple[str, list[Citation]]:
    """Parse the structured LLM response into answer text and citations."""
    answer_text = content
    citations: list[Citation] = []

    # Extract answer block
    if "<answer>" in content and "</answer>" in content:
        start = content.index("<answer>") + len("<answer>")
        end = content.index("</answer>")
        answer_text = content[start:end].strip()
    
    # Extract citations block
    if "<citations>" in content and "</citations>" in content:
        start = content.index("<citations>") + len("<citations>")
        end = content.index("</citations>")
        citations_raw = content[start:end].strip()
        try:
            citations_data = json.loads(citations_raw)
            for c in citations_data:
                if all(k in c for k in ("doc_name", "section_title", "page_number", "node_id", "verbatim_excerpt")):
                    # Extract doc_id from prefixed node_id if present (format: "doc_id::node_id")
                    raw_node_id = c["node_id"]
                    doc_id = raw_node_id.split("::")[0] if "::" in raw_node_id else ""
                    citations.append(Citation(
                        doc_name=c["doc_name"],
                        section_title=c["section_title"],
                        page_number=int(c["page_number"]),
                        node_id=raw_node_id,
                        verbatim_excerpt=c["verbatim_excerpt"],
                        doc_id=doc_id,
                    ))
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            logger.warning(f"Failed to parse citations from LLM response: {e}")
    
    # Clean up any remaining XML-like tags from the answer text
    # Remove <answer> and </answer> tags if they're still in the text
    answer_text = answer_text.replace("<answer>", "").replace("</answer>", "")
    
    # Remove the entire <citations>...</citations> block if it's still in the answer
    if "<citations>" in answer_text and "</citations>" in answer_text:
        cit_start = answer_text.index("<citations>")
        cit_end = answer_text.index("</citations>") + len("</citations>")
        answer_text = answer_text[:cit_start] + answer_text[cit_end:]
    
    # Clean up [citation:N] markers - replace with superscript numbers
    import re
    answer_text = re.sub(r'\[citation:(\d+)\]', r'[\1]', answer_text)
    
    return answer_text.strip(), citations


async def generate_answer(
    query: str,
    node_ids: list[str],
    trees: list[tuple[str, str, dict]],  # (doc_id, doc_name, tree_dict)
    history: list[dict],
    llm: LLMProvider,
) -> GeneratedAnswer:
    """
    Generate a cited answer from selected tree nodes.

    Args:
        query: The user's question.
        node_ids: Selected node IDs from tree_navigator (may be prefixed with doc_id::).
        trees: List of (doc_id, doc_name, tree_dict) for all documents in the session.
        history: Full message history for multi-turn context (last 5 turns used).
        llm: LLMProvider instance.

    Returns:
        GeneratedAnswer with answer text and structured citations.
    """
    # Build a unified node map across all trees
    # Keys include both raw node_id AND prefixed doc_id::node_id to handle both cases
    all_nodes: dict[str, tuple[str, dict]] = {}  # node_id -> (doc_name, node_dict)
    for doc_id, doc_name, tree in trees:
        def _index(nodes: list, dname: str, did: str) -> None:
            for node in nodes:
                raw_id = node["node_id"]
                all_nodes[raw_id] = (dname, node)
                # Also register prefixed form in case navigator returned prefixed IDs
                all_nodes[f"{did}::{raw_id}"] = (dname, node)
                _index(node.get("children", []), dname, did)
        # Handle both {'nodes': [...]} and root-node-with-children formats
        top_nodes = tree.get("nodes") or tree.get("children", [])
        _index(top_nodes, doc_name, doc_id)

    # Gather selected node contexts
    sections_parts: list[str] = []
    for nid in node_ids:
        if nid in all_nodes:
            doc_name, node = all_nodes[nid]
            sections_parts.append(
                f"[Node: {nid}] {node['title']} "
                f"(pp.{node.get('page_start', '?')}-{node.get('page_end', '?')}) "
                f"from '{doc_name}':\n{node.get('text', '')}"
            )

    sections_context = "\n\n---\n\n".join(sections_parts) if sections_parts else "No relevant sections found."

    # Build conversation context from last MAX_CONTEXT_TURNS turns
    conv_context = _build_context_from_history(history)

    user_content = (
        f"Prior conversation:\n{conv_context}\n\n"
        f"Current query: {query}\n\n"
        f"Relevant document sections:\n{sections_context}"
    )

    messages = [{"role": "user", "content": user_content}]
    response = await llm.complete(messages, system_prompt=_CITATION_SYSTEM_PROMPT)

    answer_text, citations = _parse_answer_and_citations(response.content)
    return GeneratedAnswer(content=answer_text, citations=citations)


async def stream_answer(
    query: str,
    node_ids: list[str],
    trees: list[tuple[str, str, dict]],
    history: list[dict],
    llm: LLMProvider,
) -> AsyncIterator[str]:
    """
    Stream answer tokens via SSE. Yields raw text chunks.
    Citations are embedded in the final chunk as a JSON block.
    """
    # Build node map
    all_nodes: dict[str, tuple[str, dict]] = {}
    for doc_id, doc_name, tree in trees:
        def _index(nodes: list, dname: str, did: str) -> None:
            for node in nodes:
                raw_id = node["node_id"]
                all_nodes[raw_id] = (dname, node)
                all_nodes[f"{did}::{raw_id}"] = (dname, node)
                _index(node.get("children", []), dname, did)
        top_nodes = tree.get("nodes") or tree.get("children", [])
        _index(top_nodes, doc_name, doc_id)

    sections_parts: list[str] = []
    for nid in node_ids:
        if nid in all_nodes:
            doc_name, node = all_nodes[nid]
            sections_parts.append(
                f"[Node: {nid}] {node['title']} "
                f"(pp.{node.get('page_start', '?')}-{node.get('page_end', '?')}) "
                f"from '{doc_name}':\n{node.get('text', '')}"
            )

    sections_context = "\n\n---\n\n".join(sections_parts) if sections_parts else "No relevant sections found."
    conv_context = _build_context_from_history(history)

    user_content = (
        f"Prior conversation:\n{conv_context}\n\n"
        f"Current query: {query}\n\n"
        f"Relevant document sections:\n{sections_context}"
    )

    messages = [{"role": "user", "content": user_content}]
    async for chunk in llm.stream(messages, system_prompt=_CITATION_SYSTEM_PROMPT):
        yield chunk
