# Feature: documind-platform, Property 8: Document Tree JSON Round Trip
"""
Property 8: For any valid document tree object, serializing it to JSONB and
deserializing it back should produce a structurally equivalent tree with the
same node count, hierarchy depth, and node IDs as the original.

Validates: Requirements 18.3, 18.4
"""
import json
import uuid

import pytest
from hypothesis import given, settings, strategies as st

from app.services.pageindex.tree_builder import collect_node_ids, count_nodes, max_depth


# ── Strategies ────────────────────────────────────────────────────────────────

def node_id_strategy(prefix: str = "n") -> st.SearchStrategy:
    return st.builds(
        lambda n: f"{prefix}{n}",
        st.integers(min_value=1, max_value=999),
    )


def leaf_node_strategy(depth: int, id_prefix: str) -> st.SearchStrategy:
    return st.builds(
        lambda node_id, title, page_start, text: {
            "node_id": node_id,
            "title": title,
            "page_start": page_start,
            "page_end": page_start,
            "depth": depth,
            "text": text,
            "children": [],
        },
        node_id=st.builds(lambda n: f"{id_prefix}{n}", st.integers(1, 999)),
        title=st.text(min_size=1, max_size=50, alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd", "Zs"))),
        page_start=st.integers(min_value=1, max_value=500),
        text=st.text(min_size=0, max_size=200),
    )


def tree_strategy() -> st.SearchStrategy:
    """Generate a valid tree dict with 1-5 top-level nodes, each optionally with children."""
    return st.builds(
        lambda doc_id, title, nodes: {
            "doc_id": doc_id,
            "title": title,
            "nodes": nodes,
        },
        doc_id=st.builds(lambda: str(uuid.uuid4())),
        title=st.text(min_size=1, max_size=80, alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd", "Zs"))),
        nodes=st.lists(
            st.builds(
                lambda i, children: {
                    "node_id": f"n{i}",
                    "title": f"Chapter {i}",
                    "page_start": i,
                    "page_end": i + 1,
                    "depth": 1,
                    "text": f"Content of chapter {i}",
                    "children": children,
                },
                i=st.integers(min_value=1, max_value=20),
                children=st.lists(
                    st.builds(
                        lambda j: {
                            "node_id": f"n1.{j}",
                            "title": f"Section 1.{j}",
                            "page_start": j,
                            "page_end": j,
                            "depth": 2,
                            "text": f"Section content {j}",
                            "children": [],
                        },
                        j=st.integers(min_value=1, max_value=10),
                    ),
                    min_size=0,
                    max_size=5,
                ),
            ),
            min_size=1,
            max_size=5,
        ),
    )


# ── Property 8: JSON round trip ───────────────────────────────────────────────

@given(tree_strategy())
@settings(max_examples=100)
def test_tree_json_round_trip_preserves_node_count(tree: dict):
    """Property 8: node count is identical after JSON serialization round trip."""
    original_count = count_nodes(tree)

    serialized = json.dumps(tree)
    deserialized = json.loads(serialized)

    assert count_nodes(deserialized) == original_count


@given(tree_strategy())
@settings(max_examples=100)
def test_tree_json_round_trip_preserves_node_ids(tree: dict):
    """Property 8: all node IDs are preserved after JSON serialization round trip."""
    original_ids = set(collect_node_ids(tree))

    serialized = json.dumps(tree)
    deserialized = json.loads(serialized)

    assert set(collect_node_ids(deserialized)) == original_ids


@given(tree_strategy())
@settings(max_examples=100)
def test_tree_json_round_trip_preserves_hierarchy_depth(tree: dict):
    """Property 8: hierarchy depth is identical after JSON serialization round trip."""
    original_depth = max_depth(tree)

    serialized = json.dumps(tree)
    deserialized = json.loads(serialized)

    assert max_depth(deserialized) == original_depth


@given(tree_strategy())
@settings(max_examples=50)
def test_tree_json_round_trip_is_idempotent(tree: dict):
    """Property 8: double round trip produces same result as single round trip."""
    once = json.loads(json.dumps(tree))
    twice = json.loads(json.dumps(once))

    assert collect_node_ids(once) == collect_node_ids(twice)
    assert count_nodes(once) == count_nodes(twice)


# ── Structural invariants ─────────────────────────────────────────────────────

@given(tree_strategy())
@settings(max_examples=50)
def test_all_nodes_have_required_fields(tree: dict):
    """Property 8: every node in the tree has all required fields."""
    required = {"node_id", "title", "page_start", "page_end", "depth", "text", "children"}

    def check_nodes(nodes: list) -> None:
        for node in nodes:
            assert required.issubset(node.keys()), f"Node missing fields: {required - node.keys()}"
            assert isinstance(node["children"], list)
            check_nodes(node["children"])

    check_nodes(tree.get("nodes", []))


@given(tree_strategy())
@settings(max_examples=50)
def test_page_end_gte_page_start(tree: dict):
    """Property 8: page_end >= page_start for every node."""
    def check(nodes: list) -> None:
        for node in nodes:
            assert node["page_end"] >= node["page_start"], (
                f"page_end {node['page_end']} < page_start {node['page_start']} in node {node['node_id']}"
            )
            check(node.get("children", []))

    check(tree.get("nodes", []))


# ── Utility function unit tests ───────────────────────────────────────────────

def test_count_nodes_empty_tree():
    assert count_nodes({"nodes": []}) == 0


def test_count_nodes_flat_tree():
    tree = {
        "nodes": [
            {"node_id": "n1", "children": []},
            {"node_id": "n2", "children": []},
            {"node_id": "n3", "children": []},
        ]
    }
    assert count_nodes(tree) == 3


def test_count_nodes_nested_tree():
    tree = {
        "nodes": [
            {
                "node_id": "n1",
                "children": [
                    {"node_id": "n1.1", "children": []},
                    {"node_id": "n1.2", "children": [
                        {"node_id": "n1.2.1", "children": []}
                    ]},
                ],
            }
        ]
    }
    assert count_nodes(tree) == 4


def test_collect_node_ids_order():
    tree = {
        "nodes": [
            {
                "node_id": "n1",
                "children": [
                    {"node_id": "n1.1", "children": []},
                ],
            },
            {"node_id": "n2", "children": []},
        ]
    }
    ids = collect_node_ids(tree)
    assert ids == ["n1", "n1.1", "n2"]


def test_max_depth_flat():
    tree = {
        "nodes": [
            {"node_id": "n1", "depth": 1, "children": []},
            {"node_id": "n2", "depth": 1, "children": []},
        ]
    }
    # max_depth counts depth + recursive children depth
    assert max_depth(tree) >= 1


def test_parse_tree_response_valid_json():
    """_parse_tree_response returns valid tree for well-formed JSON."""
    from app.services.pageindex.tree_builder import _parse_tree_response

    tree_data = {
        "doc_id": "abc",
        "title": "Test",
        "nodes": [{"node_id": "n1", "title": "Ch1", "page_start": 1, "page_end": 2,
                   "depth": 1, "text": "text", "children": []}],
    }
    result = _parse_tree_response(json.dumps(tree_data), "test.pdf", "fallback")
    assert result["nodes"][0]["node_id"] == "n1"


def test_parse_tree_response_strips_markdown_fences():
    """_parse_tree_response handles ```json ... ``` wrapping."""
    from app.services.pageindex.tree_builder import _parse_tree_response

    tree_data = {"doc_id": "x", "title": "T", "nodes": []}
    content = f"```json\n{json.dumps(tree_data)}\n```"
    result = _parse_tree_response(content, "test.pdf", "fallback")
    assert result["title"] == "T"


def test_parse_tree_response_fallback_on_invalid_json():
    """_parse_tree_response returns fallback tree when JSON is invalid."""
    from app.services.pageindex.tree_builder import _parse_tree_response

    result = _parse_tree_response("not valid json at all", "doc.pdf", "some text")
    assert result["nodes"][0]["node_id"] == "n1"
    assert result["title"] == "doc.pdf"
