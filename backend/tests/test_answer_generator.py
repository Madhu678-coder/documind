# Feature: documind-platform, Property 12: Citation Format Completeness
# Feature: documind-platform, Property 14: Multi-Turn Context Window
"""
Property 12: For any assistant message containing citations, every citation object
should contain all five required fields: doc_name, section_title, page_number,
node_id, and verbatim_excerpt. No field should be null or empty.

Property 14: For any conversation with more than 5 prior turns, the answer generator
should include exactly the last 5 turns in the LLM context — no more, no fewer.

Validates: Requirements 7.7, 7.8
"""
import asyncio
import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from hypothesis import given, settings, strategies as st

from app.services.pageindex.answer_generator import (
    MAX_CONTEXT_TURNS,
    Citation,
    GeneratedAnswer,
    _build_context_from_history,
    _parse_answer_and_citations,
    generate_answer,
)

# ── Helpers ───────────────────────────────────────────────────────────────────

CITATION_FIELDS = {"doc_name", "section_title", "page_number", "node_id", "verbatim_excerpt"}


def _make_citation_dict(**overrides) -> dict:
    base = {
        "doc_name": "contract.pdf",
        "section_title": "Section 4.2 — Termination",
        "page_number": 12,
        "node_id": "n4.2",
        "verbatim_excerpt": "Either party may terminate this agreement with 30 days notice.",
    }
    base.update(overrides)
    return base


def _make_llm_response(answer: str, citations: list[dict]) -> str:
    return (
        f"<answer>\n{answer}\n</answer>\n"
        f"<citations>\n{json.dumps(citations)}\n</citations>"
    )


def _make_tree(doc_id: str, doc_name: str) -> tuple[str, str, dict]:
    return (
        doc_id,
        doc_name,
        {
            "doc_id": doc_id,
            "title": doc_name,
            "nodes": [
                {
                    "node_id": f"{doc_id}::n1",
                    "title": "Chapter 1",
                    "page_start": 1,
                    "page_end": 5,
                    "depth": 1,
                    "text": "Chapter content here.",
                    "children": [],
                }
            ],
        },
    )


# ── Property 12: Citation format completeness ─────────────────────────────────

def test_citation_has_all_required_fields():
    """Property 12: Citation dataclass has all 5 required fields."""
    c = Citation(
        doc_name="doc.pdf",
        section_title="Section 1",
        page_number=1,
        node_id="n1",
        verbatim_excerpt="Some text.",
    )
    d = c.to_dict()
    assert CITATION_FIELDS.issubset(d.keys())


def test_parse_answer_extracts_all_citation_fields():
    """Property 12: _parse_answer_and_citations extracts all 5 fields correctly."""
    citations = [_make_citation_dict()]
    content = _make_llm_response("The answer is [citation:1].", citations)

    answer, parsed = _parse_answer_and_citations(content)

    assert len(parsed) == 1
    c = parsed[0]
    assert c.doc_name == "contract.pdf"
    assert c.section_title == "Section 4.2 — Termination"
    assert c.page_number == 12
    assert c.node_id == "n4.2"
    assert c.verbatim_excerpt != ""


def test_parse_answer_rejects_incomplete_citations():
    """Property 12: citations missing required fields are excluded."""
    incomplete = [{"doc_name": "doc.pdf", "section_title": "S1"}]  # missing 3 fields
    content = _make_llm_response("Answer.", incomplete)

    _, parsed = _parse_answer_and_citations(content)
    assert len(parsed) == 0


def test_parse_answer_multiple_citations_all_complete():
    """Property 12: multiple citations all have complete fields."""
    citations = [
        _make_citation_dict(node_id="n1", page_number=1),
        _make_citation_dict(node_id="n2", page_number=5),
        _make_citation_dict(node_id="n3", page_number=10),
    ]
    content = _make_llm_response("Answer with [citation:1], [citation:2], [citation:3].", citations)

    _, parsed = _parse_answer_and_citations(content)
    assert len(parsed) == 3
    for c in parsed:
        assert all(getattr(c, f.replace("_", "_")) for f in ["doc_name", "section_title", "node_id", "verbatim_excerpt"])
        assert c.page_number > 0


@given(
    st.lists(
        st.fixed_dictionaries({
            "doc_name": st.text(min_size=1, max_size=50),
            "section_title": st.text(min_size=1, max_size=100),
            "page_number": st.integers(min_value=1, max_value=1000),
            "node_id": st.text(min_size=1, max_size=30),
            "verbatim_excerpt": st.text(min_size=1, max_size=200),
        }),
        min_size=1,
        max_size=10,
    )
)
@settings(max_examples=50)
def test_all_complete_citations_are_parsed(citations: list[dict]):
    """Property 12: any list of complete citation dicts is fully parsed."""
    content = _make_llm_response("Answer.", citations)
    _, parsed = _parse_answer_and_citations(content)

    assert len(parsed) == len(citations)
    for c in parsed:
        d = c.to_dict()
        assert CITATION_FIELDS.issubset(d.keys())
        for field in CITATION_FIELDS:
            assert d[field] is not None
            if isinstance(d[field], str):
                assert d[field] != ""


def test_generate_answer_returns_citations():
    """Property 12: generate_answer returns citations with all required fields."""
    async def _run():
        doc_id = str(uuid.uuid4())
        doc_name = "report.pdf"
        tree = _make_tree(doc_id, doc_name)
        node_id = f"{doc_id}::n1"

        citations = [_make_citation_dict(node_id=node_id, doc_name=doc_name)]
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(return_value=MagicMock(
            content=_make_llm_response("The answer.", citations)
        ))

        result = await generate_answer(
            query="What is the termination clause?",
            node_ids=[node_id],
            trees=[tree],
            history=[],
            llm=mock_llm,
        )
        return result

    result = asyncio.run(_run())
    assert isinstance(result, GeneratedAnswer)
    assert len(result.citations) == 1
    c = result.citations[0]
    assert all([c.doc_name, c.section_title, c.node_id, c.verbatim_excerpt])
    assert c.page_number > 0


# ── Property 14: Multi-turn context window ────────────────────────────────────

def test_max_context_turns_is_five():
    """Property 14: MAX_CONTEXT_TURNS must be exactly 5."""
    assert MAX_CONTEXT_TURNS == 5


def test_build_context_uses_last_five_turns():
    """Property 14: _build_context_from_history uses exactly the last 5 turns."""
    history = [
        {"role": "user", "content": f"Message {i}"}
        for i in range(10)
    ]
    context = _build_context_from_history(history)

    # Should contain messages 5-9, not 0-4
    for i in range(5, 10):
        assert f"Message {i}" in context
    for i in range(0, 5):
        assert f"Message {i}" not in context


def test_build_context_with_fewer_than_five_turns():
    """Property 14: when fewer than 5 turns exist, all are included."""
    history = [
        {"role": "user", "content": "Q1"},
        {"role": "assistant", "content": "A1"},
        {"role": "user", "content": "Q2"},
    ]
    context = _build_context_from_history(history)

    assert "Q1" in context
    assert "A1" in context
    assert "Q2" in context


def test_build_context_with_empty_history():
    """Property 14: empty history produces empty context string."""
    context = _build_context_from_history([])
    assert context == ""


@given(
    history_length=st.integers(min_value=6, max_value=50),
)
@settings(max_examples=50)
def test_context_always_uses_at_most_five_turns(history_length: int):
    """Property 14: context never includes more than MAX_CONTEXT_TURNS turns."""
    history = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"TURN_MARKER_{i:04d}"}
        for i in range(history_length)
    ]
    context = _build_context_from_history(history)

    # Count how many "TURN_MARKER_NNNN" entries appear in context
    included = sum(1 for i in range(history_length) if f"TURN_MARKER_{i:04d}" in context)
    assert included <= MAX_CONTEXT_TURNS


@given(
    history_length=st.integers(min_value=6, max_value=50),
)
@settings(max_examples=50)
def test_context_includes_exactly_last_five_turns(history_length: int):
    """Property 14: context includes exactly the last 5 turns for long histories."""
    history = [
        {"role": "user", "content": f"UNIQUE_{i:04d}_MSG"}
        for i in range(history_length)
    ]
    context = _build_context_from_history(history)

    # Last 5 must be present
    for i in range(history_length - MAX_CONTEXT_TURNS, history_length):
        assert f"UNIQUE_{i:04d}_MSG" in context

    # Earlier ones must not be present
    for i in range(0, history_length - MAX_CONTEXT_TURNS):
        assert f"UNIQUE_{i:04d}_MSG" not in context


def test_generate_answer_passes_last_five_turns_to_llm():
    """Property 14: generate_answer passes only last 5 turns to LLM."""
    async def _run():
        doc_id = str(uuid.uuid4())
        tree = _make_tree(doc_id, "doc.pdf")

        # 10 turns of history with zero-padded IDs to avoid substring collisions
        history = [
            {"role": "user" if i % 2 == 0 else "assistant", "content": f"TURN_{i:04d}_END"}
            for i in range(10)
        ]

        captured_messages = []

        async def mock_complete(messages, system_prompt=None):
            captured_messages.extend(messages)
            return MagicMock(content="<answer>Answer.</answer><citations>[]</citations>")

        mock_llm = AsyncMock()
        mock_llm.complete = mock_complete

        await generate_answer(
            query="test query",
            node_ids=[],
            trees=[tree],
            history=history,
            llm=mock_llm,
        )
        return captured_messages

    messages = asyncio.run(_run())
    assert len(messages) > 0
    user_content = messages[0]["content"]

    # Last 5 turns (5-9) should be in context
    for i in range(5, 10):
        assert f"TURN_{i:04d}_END" in user_content

    # First 5 turns (0-4) should NOT be in context
    for i in range(0, 5):
        assert f"TURN_{i:04d}_END" not in user_content
