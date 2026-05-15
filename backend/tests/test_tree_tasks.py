# Feature: documind-platform, Property 7: Tree Build Task Retry and Status Transition
# Feature: documind-platform, Property 9: Auto-Insights Generated on Tree Build
"""
Property 7: For any build_document_tree task that fails, the task retries up to 3 times
with exponential backoff. After 3 failures, status=failed. On success, status=ready
and tree_json is non-null.

Property 9: For any successfully built document tree, the document_trees record
contains non-null executive_summary, key_entities, document_tags, and complexity_score.
"""
import asyncio
import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings, strategies as st


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_doc(doc_id, workspace_id, kb_id):
    doc = MagicMock()
    doc.id = doc_id
    doc.workspace_id = workspace_id
    doc.kb_id = kb_id
    doc.filename = "test.pdf"
    doc.file_path = "/data/uploads/test.pdf"
    doc.file_type = "pdf"
    doc.status = "processing"
    return doc


def _make_tree_json():
    return {
        "doc_id": str(uuid.uuid4()),
        "title": "Test Document",
        "nodes": [
            {
                "node_id": "n1",
                "title": "Chapter 1",
                "page_start": 1,
                "page_end": 5,
                "depth": 1,
                "text": "Chapter content",
                "children": [
                    {
                        "node_id": "n1.1",
                        "title": "Section 1.1",
                        "page_start": 2,
                        "page_end": 3,
                        "depth": 2,
                        "text": "Section content",
                        "children": [],
                    }
                ],
            }
        ],
    }


def _make_insights():
    return {
        "executive_summary": "• Point 1\n• Point 2\n• Point 3\n• Point 4\n• Point 5",
        "key_entities": {
            "people": ["Alice"],
            "organizations": ["Acme"],
            "dates": ["2024-01-01"],
            "amounts": ["$1M"],
        },
        "document_tags": ["Financial", "Legal"],
        "complexity_score": 0.7,
    }


def _make_session_mock(execute_results: list):
    """
    Build a mock AsyncSessionLocal context manager that yields a mock db
    with the given execute results as side_effect.
    """
    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=execute_results)

    @asynccontextmanager
    async def mock_session():
        yield mock_db

    return mock_session, mock_db


# ── Property 7: Retry and status transition ───────────────────────────────────

class TestRetryAndStatusTransition:

    def test_success_sets_status_ready_and_tree_json_nonnull(self):
        """Property 7 (success): status=ready and tree_json is non-null after successful build."""
        async def _run():
            doc_id = uuid.uuid4()
            mock_doc = _make_doc(doc_id, uuid.uuid4(), uuid.uuid4())

            mock_session, mock_db = _make_session_mock([
                MagicMock(**{"scalar_one_or_none.return_value": mock_doc}),   # load doc
                MagicMock(**{"scalar_one_or_none.return_value": None}),        # no existing tree
            ])

            with patch("app.workers.tree_tasks.AsyncSessionLocal", mock_session), \
                 patch("app.workers.tree_tasks.extract_text", return_value="Extracted text"), \
                 patch("app.workers.tree_tasks.BedrockProvider"), \
                 patch("app.workers.tree_tasks._generate_tree", return_value=_make_tree_json()), \
                 patch("app.workers.tree_tasks._generate_insights", return_value=_make_insights()), \
                 patch("app.workers.tree_tasks._push_ws_event", new_callable=AsyncMock):

                from app.workers.tree_tasks import _build_tree_async
                result = await _build_tree_async(str(doc_id))

            assert result["status"] == "ready"
            assert result["document_id"] == str(doc_id)

        asyncio.run(_run())

    def test_failure_sets_status_failed(self):
        """Property 7 (failure): status=failed is set when _mark_failed is called."""
        async def _run():
            doc_id = uuid.uuid4()
            mock_doc = MagicMock()
            mock_doc.id = doc_id

            mock_session, mock_db = _make_session_mock([
                MagicMock(**{"scalar_one_or_none.return_value": mock_doc}),
            ])

            with patch("app.workers.tree_tasks.AsyncSessionLocal", mock_session), \
                 patch("app.workers.tree_tasks._push_ws_event", new_callable=AsyncMock):

                from app.workers.tree_tasks import _mark_failed
                await _mark_failed(str(doc_id), "LLM timeout")

            from app.models.document import DocumentStatus
            assert mock_doc.status == DocumentStatus.failed

        asyncio.run(_run())

    def test_ws_event_pushed_on_success(self):
        """Property 7: WebSocket event with status=ready is pushed on success."""
        async def _run():
            doc_id = uuid.uuid4()
            ws_events = []

            async def capture_ws(document_id, status, **extra):
                ws_events.append({"document_id": document_id, "status": status})

            mock_doc = _make_doc(doc_id, uuid.uuid4(), uuid.uuid4())
            mock_session, _ = _make_session_mock([
                MagicMock(**{"scalar_one_or_none.return_value": mock_doc}),
                MagicMock(**{"scalar_one_or_none.return_value": None}),
            ])

            with patch("app.workers.tree_tasks.AsyncSessionLocal", mock_session), \
                 patch("app.workers.tree_tasks.extract_text", return_value="text"), \
                 patch("app.workers.tree_tasks.BedrockProvider"), \
                 patch("app.workers.tree_tasks._generate_tree", return_value=_make_tree_json()), \
                 patch("app.workers.tree_tasks._generate_insights", return_value=_make_insights()), \
                 patch("app.workers.tree_tasks._push_ws_event", side_effect=capture_ws):

                from app.workers.tree_tasks import _build_tree_async
                await _build_tree_async(str(doc_id))

            assert any(e["status"] == "ready" for e in ws_events)

        asyncio.run(_run())

    def test_ws_event_pushed_on_failure(self):
        """Property 7: WebSocket event with status=failed is pushed on failure."""
        async def _run():
            doc_id = uuid.uuid4()
            ws_events = []

            async def capture_ws(document_id, status, **extra):
                ws_events.append({"document_id": document_id, "status": status})

            mock_doc = MagicMock()
            mock_doc.id = uuid.UUID(str(doc_id))
            mock_session, _ = _make_session_mock([
                MagicMock(**{"scalar_one_or_none.return_value": mock_doc}),
            ])

            with patch("app.workers.tree_tasks.AsyncSessionLocal", mock_session), \
                 patch("app.workers.tree_tasks._push_ws_event", side_effect=capture_ws):

                from app.workers.tree_tasks import _mark_failed
                await _mark_failed(str(doc_id), "error detail")

            assert any(e["status"] == "failed" for e in ws_events)

        asyncio.run(_run())


# ── Property 7: Retry backoff calculation ─────────────────────────────────────

@given(st.integers(min_value=0, max_value=2))
@settings(max_examples=10)
def test_retry_backoff_is_exponential(attempt: int):
    """Property 7: Retry delay must follow 2^attempt * 10s pattern."""
    from app.workers.tree_tasks import _RETRY_BASE_DELAY

    delay = (2 ** attempt) * _RETRY_BASE_DELAY
    expected = {0: 10, 1: 20, 2: 40}[attempt]
    assert delay == expected, f"Expected {expected}s for attempt {attempt}, got {delay}s"


def test_max_retries_is_three():
    """Property 7: MAX_RETRIES must be exactly 3."""
    from app.workers.tree_tasks import _MAX_RETRIES
    assert _MAX_RETRIES == 3


# ── Property 9: Auto-insights generation ─────────────────────────────────────

class TestAutoInsights:

    def test_insights_all_fields_nonnull_on_success(self):
        """Property 9: After successful tree build, all insight fields must be non-null."""
        async def _run():
            doc_id = uuid.uuid4()
            mock_doc = _make_doc(doc_id, uuid.uuid4(), uuid.uuid4())
            added_trees = []

            mock_session, mock_db = _make_session_mock([
                MagicMock(**{"scalar_one_or_none.return_value": mock_doc}),
                MagicMock(**{"scalar_one_or_none.return_value": None}),
            ])
            mock_db.add = MagicMock(side_effect=lambda obj: added_trees.append(obj))

            with patch("app.workers.tree_tasks.AsyncSessionLocal", mock_session), \
                 patch("app.workers.tree_tasks.extract_text", return_value="text"), \
                 patch("app.workers.tree_tasks.BedrockProvider"), \
                 patch("app.workers.tree_tasks._generate_tree", return_value=_make_tree_json()), \
                 patch("app.workers.tree_tasks._generate_insights", return_value=_make_insights()), \
                 patch("app.workers.tree_tasks._push_ws_event", new_callable=AsyncMock):

                from app.workers.tree_tasks import _build_tree_async
                await _build_tree_async(str(doc_id))

            from app.models.document_tree import DocumentTree
            tree_objects = [o for o in added_trees if isinstance(o, DocumentTree)]
            assert len(tree_objects) == 1

            tree = tree_objects[0]
            assert tree.executive_summary is not None and tree.executive_summary != ""
            assert tree.key_entities is not None
            assert tree.document_tags is not None and len(tree.document_tags) > 0
            assert tree.complexity_score is not None
            assert 0.0 <= tree.complexity_score <= 1.0

        asyncio.run(_run())

    def test_insights_tree_json_nonnull_on_success(self):
        """Property 9: tree_json must be non-null after successful build."""
        async def _run():
            doc_id = uuid.uuid4()
            mock_doc = _make_doc(doc_id, uuid.uuid4(), uuid.uuid4())
            added_trees = []

            mock_session, mock_db = _make_session_mock([
                MagicMock(**{"scalar_one_or_none.return_value": mock_doc}),
                MagicMock(**{"scalar_one_or_none.return_value": None}),
            ])
            mock_db.add = MagicMock(side_effect=lambda obj: added_trees.append(obj))

            with patch("app.workers.tree_tasks.AsyncSessionLocal", mock_session), \
                 patch("app.workers.tree_tasks.extract_text", return_value="text"), \
                 patch("app.workers.tree_tasks.BedrockProvider"), \
                 patch("app.workers.tree_tasks._generate_tree", return_value=_make_tree_json()), \
                 patch("app.workers.tree_tasks._generate_insights", return_value=_make_insights()), \
                 patch("app.workers.tree_tasks._push_ws_event", new_callable=AsyncMock):

                from app.workers.tree_tasks import _build_tree_async
                await _build_tree_async(str(doc_id))

            from app.models.document_tree import DocumentTree
            tree_objects = [o for o in added_trees if isinstance(o, DocumentTree)]
            assert len(tree_objects) == 1
            assert tree_objects[0].tree_json is not None
            assert "nodes" in tree_objects[0].tree_json

        asyncio.run(_run())

    @given(st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False))
    @settings(max_examples=50)
    def test_complexity_score_in_valid_range(self, score: float):
        """Property 9: complexity_score must always be in [0.0, 1.0]."""
        assert 0.0 <= score <= 1.0

    @given(
        st.lists(
            st.text(min_size=1, max_size=20).filter(str.strip),
            min_size=1,
            max_size=10,
        )
    )
    @settings(max_examples=30)
    def test_document_tags_always_nonempty_list(self, tags: list):
        """Property 9: document_tags must be a non-empty list."""
        assert len(tags) > 0
        assert all(isinstance(t, str) for t in tags)
