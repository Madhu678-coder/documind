"""PageIndex trace logger — records node traversal path, rationale, and confidence."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class NodeVisit:
    node_id: str
    title: str
    rationale: str
    depth: int = 1

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "title": self.title,
            "rationale": self.rationale,
            "depth": self.depth,
        }


@dataclass
class ReasoningTrace:
    nodes_visited: list[NodeVisit] = field(default_factory=list)
    confidence: float = 0.0
    query: str = ""
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict:
        return {
            "nodes_visited": [n.to_dict() for n in self.nodes_visited],
            "confidence": self.confidence,
            "query": self.query,
            "timestamp": self.timestamp,
        }

    @property
    def node_ids(self) -> list[str]:
        return [n.node_id for n in self.nodes_visited]


def build_trace(
    query: str,
    selected_node_ids: list[str],
    rationale: dict[str, str],
    confidence: float,
    trees: list[tuple[str, dict]],  # (doc_id, tree_dict)
) -> ReasoningTrace:
    """
    Build a ReasoningTrace from navigation results.

    Args:
        query: The user's original query.
        selected_node_ids: Ordered list of node IDs selected by tree_navigator.
        rationale: Mapping of node_id -> selection rationale from tree_navigator.
        confidence: Overall confidence signal from tree_navigator.
        trees: List of (doc_id, tree_dict) to look up node titles.

    Returns:
        ReasoningTrace with ordered NodeVisit entries.
    """
    # Build a node metadata map from all trees
    node_meta: dict[str, dict] = {}
    for doc_id, tree in trees:
        def _index(nodes: list) -> None:
            for node in nodes:
                node_meta[node["node_id"]] = node
                _index(node.get("children", []))
        _index(tree.get("nodes", []))

    visits: list[NodeVisit] = []
    for nid in selected_node_ids:
        meta = node_meta.get(nid, {})
        visits.append(NodeVisit(
            node_id=nid,
            title=meta.get("title", nid),
            rationale=rationale.get(nid, "Selected as relevant to query"),
            depth=meta.get("depth", 1),
        ))

    return ReasoningTrace(
        nodes_visited=visits,
        confidence=confidence,
        query=query,
    )
