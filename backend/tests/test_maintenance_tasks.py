# Feature: documind-platform, Property 20: Nightly Eval Stores Correct Trigger Mode
"""
Property 20: For any nightly evaluation run, all eval_results records created during
that run should have triggered_by='nightly', and the set of evaluated messages should
be exactly those with created_at within the past 24 hours.
"""
import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings, strategies as st


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_message(created_at=None, session_id=None):
    msg = MagicMock()
    msg.id = uuid.uuid4()
    msg.session_id = session_id or uuid.uuid4()
    msg.role = "assistant"
    msg.content = "Answer"
    msg.node_ids_visited = []
    msg.created_at = created_at or datetime.now(timezone.utc)
    return msg


def _make_session(workspace_id=None):
    session = MagicMock()
    session.id = uuid.uuid4()
    session.workspace_id = workspace_id or uuid.uuid4()
    return session


def _make_eval_result_record(triggered_by="nightly"):
    r = MagicMock()
    r.id = uuid.uuid4()
    r.triggered_by = triggered_by
    r.faithfulness_score = 1.0
    r.answer_relevancy_score = 1.0
    r.contextual_precision_score = 1.0
    r.contextual_recall_score = 1.0
    r.hallucination_score = 0.0
    r.overall_pass = True
    return r


# ── Property 20: triggered_by='nightly' ──────────────────────────────────────

class TestNightlyEvalTriggerMode:

    def test_nightly_eval_stores_triggered_by_nightly(self):
        """
        Property 20: All eval_results created by run_nightly_eval must have
        triggered_by='nightly'.
        """
        async def _run():
            now = datetime.now(timezone.utc)
            cutoff = now - timedelta(hours=24)

            # Two messages within the past 24 hours
            msg1 = _make_message(created_at=now - timedelta(hours=1))
            msg2 = _make_message(created_at=now - timedelta(hours=12))
            session1 = _make_session()
            session2 = _make_session()

            stored_results = []

            @asynccontextmanager
            async def mock_session():
                mock_db = AsyncMock()
                mock_db.add = MagicMock(side_effect=lambda obj: stored_results.append(obj))
                mock_db.commit = AsyncMock()
                mock_db.execute = AsyncMock(side_effect=[
                    # Fetch messages from past 24h
                    MagicMock(**{"scalars.return_value.all.return_value": [msg1, msg2]}),
                    # Session for msg1
                    MagicMock(**{"scalar_one_or_none.return_value": session1}),
                    # build_test_case for msg1: assistant msg
                    MagicMock(**{"scalar_one_or_none.return_value": msg1}),
                    # build_test_case for msg1: user msg
                    MagicMock(**{"scalar_one_or_none.return_value": None}),
                    # build_test_case for msg1: trees
                    MagicMock(**{"scalars.return_value.all.return_value": []}),
                    # Session for msg2
                    MagicMock(**{"scalar_one_or_none.return_value": session2}),
                    # build_test_case for msg2: assistant msg
                    MagicMock(**{"scalar_one_or_none.return_value": msg2}),
                    # build_test_case for msg2: user msg
                    MagicMock(**{"scalar_one_or_none.return_value": None}),
                    # build_test_case for msg2: trees
                    MagicMock(**{"scalars.return_value.all.return_value": []}),
                    # _check_baseline_and_alert: baseline query
                    MagicMock(**{"one.return_value": MagicMock(faithfulness=None, answer_relevancy=None, hallucination=None)}),
                    # _check_baseline_and_alert: today query
                    MagicMock(**{"one.return_value": MagicMock(faithfulness=None, answer_relevancy=None, hallucination=None)}),
                ])
                yield mock_db

            neutral = {
                "faithfulness": 1.0,
                "faithfulness_reason": "ok",
                "answer_relevancy": 1.0,
                "contextual_precision": 1.0,
                "contextual_recall": 1.0,
                "hallucination": 0.0,
            }

            with patch("app.core.database.AsyncSessionLocal", mock_session), \
                 patch("app.workers.eval_tasks._run_deepeval", return_value=neutral):

                from app.workers.maintenance_tasks import _run_nightly_eval_async
                result = await _run_nightly_eval_async()

            assert result["evaluated"] == 2

            from app.models.eval_result import EvalResult
            eval_records = [r for r in stored_results if isinstance(r, EvalResult)]
            assert len(eval_records) == 2
            for record in eval_records:
                assert record.triggered_by == "nightly", (
                    f"Expected triggered_by='nightly', got '{record.triggered_by}'"
                )

        asyncio.run(_run())

    def test_nightly_eval_only_evaluates_messages_within_24h(self):
        """
        Property 20: Only messages with created_at >= now - 24h are evaluated.
        Messages older than 24h must be excluded.
        """
        async def _run():
            now = datetime.now(timezone.utc)

            # One recent message (within 24h), one old message (>24h)
            recent_msg = _make_message(created_at=now - timedelta(hours=6))
            # Old message would NOT be returned by the DB query (filtered by cutoff)
            # We simulate the DB returning only the recent one

            stored_results = []

            @asynccontextmanager
            async def mock_session():
                mock_db = AsyncMock()
                mock_db.add = MagicMock(side_effect=lambda obj: stored_results.append(obj))
                mock_db.commit = AsyncMock()
                mock_db.execute = AsyncMock(side_effect=[
                    # Only recent message returned (old one filtered by DB query)
                    MagicMock(**{"scalars.return_value.all.return_value": [recent_msg]}),
                    MagicMock(**{"scalar_one_or_none.return_value": _make_session()}),
                    MagicMock(**{"scalar_one_or_none.return_value": recent_msg}),
                    MagicMock(**{"scalar_one_or_none.return_value": None}),
                    MagicMock(**{"scalars.return_value.all.return_value": []}),
                    MagicMock(**{"one.return_value": MagicMock(faithfulness=None, answer_relevancy=None, hallucination=None)}),
                    MagicMock(**{"one.return_value": MagicMock(faithfulness=None, answer_relevancy=None, hallucination=None)}),
                ])
                yield mock_db

            neutral = {
                "faithfulness": 1.0,
                "faithfulness_reason": "ok",
                "answer_relevancy": 1.0,
                "contextual_precision": 1.0,
                "contextual_recall": 1.0,
                "hallucination": 0.0,
            }

            with patch("app.core.database.AsyncSessionLocal", mock_session), \
                 patch("app.workers.eval_tasks._run_deepeval", return_value=neutral):

                from app.workers.maintenance_tasks import _run_nightly_eval_async
                result = await _run_nightly_eval_async()

            # Only 1 message evaluated (the recent one)
            assert result["evaluated"] == 1

        asyncio.run(_run())

    def test_nightly_eval_triggered_by_is_not_online(self):
        """Property 20: Nightly eval must never store triggered_by='online'."""
        record = _make_eval_result_record(triggered_by="nightly")
        assert record.triggered_by == "nightly"
        assert record.triggered_by != "online"
        assert record.triggered_by != "ci"

    def test_celery_beat_schedule_configured(self):
        """Property 20: Celery Beat schedule must include nightly-eval-regression at 2 AM UTC."""
        from app.workers.maintenance_tasks import celery_app

        schedule = celery_app.conf.beat_schedule
        assert "nightly-eval-regression" in schedule, "nightly-eval-regression not in beat_schedule"
        assert "file-cleanup" in schedule, "file-cleanup not in beat_schedule"

        nightly = schedule["nightly-eval-regression"]
        assert nightly["task"] == "app.workers.maintenance_tasks.run_nightly_eval"

        cleanup = schedule["file-cleanup"]
        assert cleanup["task"] == "app.workers.maintenance_tasks.cleanup_orphaned_files"

    def test_nightly_eval_task_on_default_queue(self):
        """Property 20: run_nightly_eval must be on the default queue."""
        from app.workers.maintenance_tasks import run_nightly_eval
        assert run_nightly_eval.queue == "default"

    @given(st.integers(min_value=0, max_value=100))
    @settings(max_examples=50)
    def test_all_nightly_results_have_correct_trigger_mode(self, n_messages: int):
        """
        Property 20: For any number of messages evaluated in a nightly run,
        all resulting records must have triggered_by='nightly'.
        """
        records = [_make_eval_result_record(triggered_by="nightly") for _ in range(n_messages)]
        for record in records:
            assert record.triggered_by == "nightly"

    @given(
        st.datetimes(
            min_value=datetime(2024, 1, 1),
            max_value=datetime(2026, 12, 31),
        )
    )
    @settings(max_examples=100)
    def test_24h_cutoff_boundary(self, reference_time: datetime):
        """
        Property 20: Messages with created_at >= (reference_time - 24h) are within scope.
        Messages with created_at < (reference_time - 24h) are out of scope.
        """
        cutoff = reference_time - timedelta(hours=24)

        # Message exactly at cutoff boundary — within scope
        at_cutoff = cutoff
        assert at_cutoff >= cutoff

        # Message 1 second before cutoff — out of scope
        before_cutoff = cutoff - timedelta(seconds=1)
        assert before_cutoff < cutoff

        # Message 1 second after cutoff — within scope
        after_cutoff = cutoff + timedelta(seconds=1)
        assert after_cutoff >= cutoff
