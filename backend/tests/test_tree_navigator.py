# Feature: documind-platform, Property 13: Multi-Doc Node ID Prefixing
"""
Property 13: For any chat session linked to multiple documents, all node IDs in the
merged tree and in stored node_ids_visited should be prefixed with the source doc_id
in the format "{doc_id}::{node_id}", ensuring no collisions between documents.

Validates: Requirements 7.9
"""
import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from hypothesis import given, settings, strategies as st

from app.services.pageindex.tree_navigator import (
    NavigationResult,
    collect_node_ids_from_merged,
    merge_trees,
    navigate,
    prefix_node_ids,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_tree(doc_id: str, node_ids: list[str]) -> dict:
    """Build a simple flat tree with the given node IDs."""
    return {
        "doc_id": doc_id,
        "title": f"Document {doc_id[:8]}",
        "nodes": [
            {
                "node_id": nid,
                "title": f"Section {nid}",
                "page_start": i + 1,
                "page_end": i + 1,
                "depth": 1,
                "text": f"Content of {nid}",
                "children": [],
            }
            for i, nid in enumerate(node_ids)
        ],
    }


def _make_nested_tree(doc_id: str) -> dict:
    """Build a tree with nested children."""
    return {
        "doc_id": doc_id,
        "title": "Nested Doc",
        "nodes": [
            {
                "node_id": "n1",
                "title": "Chapter 1",
                "page_start": 1,
                "page_end": 10,
                "depth": 1,
                "text": "Chapter content",
                "children": [
                    {
                        "node_id": "n1.1",
                        "title": "Section 1.1",
                        "page_start": 2,
                        "page_end": 5,
                        "depth": 2,
                        "text": "Section content",
                        "children": [
                            {
                                "node_id": "n1.1.1",
                                "title": "Subsection 1.1.1",
                                "page_start": 3,
                                "page_end": 4,
                                "depth": 3,
                                "text": "Subsection content",
                                "children": [],
                            }
                        ],
                    }
                ],
            }
        ],
    }


def collect_all_node_ids(tree: dict) -> list[str]:
    """Collect all node IDs from a tree recursively."""
    ids: list[str] = []

    def _collect(nodes: list) -> None:
        for node in nodes:
            ids.append(node["node_id"])
            _collect(node.get("children", []))

    _collect(tree.get("nodes", []))
    return ids


# ── Property 13: Node ID prefixing ───────────────────────────────────────────

def test_prefix_node_ids_adds_doc_id_prefix():
    """Property 13: prefix_node_ids adds '{doc_id}::' prefix to all node IDs."""
    doc_id = str(uuid.uuid4())
    tree = _make_tree(doc_id, ["n1", "n2", "n3"])

    prefixed = prefix_node_ids(tree, doc_id)
    ids = collect_all_node_ids(prefixed)

    for nid in ids:
        assert nid.startswith(f"{doc_id}::"), f"Node ID '{nid}' missing prefix '{doc_id}::'"


def test_prefix_node_ids_preserves_original_node_id_suffix():
    """Property 13: original node IDs appear after the '::' separator."""
    doc_id = str(uuid.uuid4())
    original_ids = ["n1", "n2", "n3"]
    tree = _make_tree(doc_id, original_ids)

    prefixed = prefix_node_ids(tree, doc_id)
    ids = collect_all_node_ids(prefixed)

    suffixes = [nid.split("::", 1)[1] for nid in ids]
    assert suffixes == original_ids


def test_prefix_node_ids_handles_nested_children():
    """Property 13: prefix_node_ids applies to all nested children recursively."""
    doc_id = str(uuid.uuid4())
    tree = _make_nested_tree(doc_id)

    prefixed = prefix_node_ids(tree, doc_id)
    ids = collect_all_node_ids(prefixed)

    assert len(ids) == 3  # n1, n1.1, n1.1.1
    for nid in ids:
        assert nid.startswith(f"{doc_id}::")


def test_prefix_node_ids_does_not_mutate_original():
    """Property 13: prefix_node_ids returns a copy, not mutating the original."""
    doc_id = str(uuid.uuid4())
    tree = _make_tree(doc_id, ["n1", "n2"])
    original_ids = collect_all_node_ids(tree)[:]

    prefix_node_ids(tree, doc_id)

    assert collect_all_node_ids(tree) == original_ids


def test_merge_trees_no_collisions():
    """Property 13: merged tree has no duplicate node IDs across documents."""
    doc_id_1 = str(uuid.uuid4())
    doc_id_2 = str(uuid.uuid4())

    # Both trees have the same raw node IDs — would collide without prefixing
    tree1 = _make_tree(doc_id_1, ["n1", "n2", "n3"])
    tree2 = _make_tree(doc_id_2, ["n1", "n2", "n3"])

    merged = merge_trees([(doc_id_1, tree1), (doc_id_2, tree2)])
    ids = collect_all_node_ids(merged)

    assert len(ids) == len(set(ids)), "Duplicate node IDs found in merged tree"


def test_merge_trees_all_ids_prefixed():
    """Property 13: all node IDs in merged tree are prefixed with their doc_id."""
    doc_id_1 = str(uuid.uuid4())
    doc_id_2 = str(uuid.uuid4())

    tree1 = _make_tree(doc_id_1, ["n1", "n2"])
    tree2 = _make_tree(doc_id_2, ["n1", "n2"])

    merged = merge_trees([(doc_id_1, tree1), (doc_id_2, tree2)])
    ids = collect_all_node_ids(merged)

    for nid in ids:
        assert "::" in nid, f"Node ID '{nid}' is not prefixed"
        prefix = nid.split("::")[0]
        assert prefix in (doc_id_1, doc_id_2), f"Unknown prefix '{prefix}'"


def test_merge_trees_contains_all_nodes():
    """Property 13: merged tree contains all nodes from all source trees."""
    doc_id_1 = str(uuid.uuid4())
    doc_id_2 = str(uuid.uuid4())

    tree1 = _make_tree(doc_id_1, ["n1", "n2"])
    tree2 = _make_tree(doc_id_2, ["n1", "n2", "n3"])

    merged = merge_trees([(doc_id_1, tree1), (doc_id_2, tree2)])
    ids = collect_all_node_ids(merged)

    assert len(ids) == 5  # 2 from tree1 + 3 from tree2


def test_single_doc_navigate_prefixes_ids():
    """Property 13: even single-doc navigation prefixes node IDs."""
    doc_id = str(uuid.uuid4())
    tree = _make_tree(doc_id, ["n1", "n2"])

    async def _run():
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(return_value=MagicMock(
            content=f'{{"selected_node_ids": ["{doc_id}::n1"], "rationale": {{"{doc_id}::n1": "relevant"}}, "confidence": 0.9}}'
        ))
        result = await navigate("test query", [(doc_id, tree)], mock_llm)
        return result

    result = asyncio.run(_run())
    for nid in result.selected_node_ids:
        assert nid.startswith(f"{doc_id}::"), f"Node ID '{nid}' not prefixed"


# ── Hypothesis property tests ─────────────────────────────────────────────────

@given(
    doc_ids=st.lists(
        st.builds(lambda: str(uuid.uuid4())),
        min_size=2,
        max_size=5,
        unique=True,
    ),
    node_count=st.integers(min_value=1, max_value=5),
)
@settings(max_examples=50)
def test_merge_trees_no_collisions_hypothesis(doc_ids: list[str], node_count: int):
    """Property 13: no node ID collisions in merged tree for any number of documents."""
    trees = [
        (doc_id, _make_tree(doc_id, [f"n{i}" for i in range(1, node_count + 1)]))
        for doc_id in doc_ids
    ]

    merged = merge_trees(trees)
    ids = collect_all_node_ids(merged)

    assert len(ids) == len(set(ids)), "Duplicate node IDs in merged tree"
    assert len(ids) == len(doc_ids) * node_count


@given(
    doc_id=st.builds(lambda: str(uuid.uuid4())),
    raw_ids=st.lists(
        st.text(min_size=1, max_size=10, alphabet="abcdefghijklmnopqrstuvwxyz0123456789."),
        min_size=1,
        max_size=10,
        unique=True,
    ),
)
@settings(max_examples=50)
def test_prefix_format_is_always_doc_id_double_colon_node_id(doc_id: str, raw_ids: list[str]):
    """Property 13: prefix format is always '{doc_id}::{original_node_id}'."""
    tree = _make_tree(doc_id, raw_ids)
    prefixed = prefix_node_ids(tree, doc_id)
    ids = collect_all_node_ids(prefixed)

    for nid, original in zip(ids, raw_ids):
        assert nid == f"{doc_id}::{original}"
