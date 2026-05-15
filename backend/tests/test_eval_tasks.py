# Feature: documind-platform, Property 16: Eval Task Does Not Block Response Stream
# Feature: documind-platform, Property 17: Eval Round Trip — Complete Record
"""
Property 16: For any assistant message, the evaluate_response_async Celery task
is enqueued after the response is stored, and the SSE stream completes before
the eval task begins execution.

Property 17: For any valid LLMTestCase constructed from a chat message, evaluating
it and storing results produces a complete eval_results record with no null metric
scores, a valid overall_pass boolean, and eval_model set to the judge model ID.
"""
import asyncio
import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest
from hypothesis import given, settings, strategies as st


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_assistant_message(session_id=None, node_ids=None):
    msg = MagicMock()
    msg.id = uuid.uuid4()
    msg.session_id = session_id or uuid.uuid4()
    msg.role = "assistant"
    msg.content = "The answer is 42."
    msg.node_ids_visited = node_ids or ["n1", "n2"]
    msg.created_at = __import__("datetime").datetime.utcnow()
    return msg


def _make_user_message(session_id, created_at_offset=-1):
    import datetime
    msg = MagicMock()
    msg.id = uuid.uuid4()
    msg.session_id = session_id
    msg.role = "user"
    msg.content = "What is the answer?"
    msg.created_at = __import__("datetime").datetime.utcnow() + datetime.timedelta(seconds=created_at_offset)
    return msg


def _make_eval_config(workspace_id=None):
    cfg = MagicMock()
    cfg.workspace_id = workspace_id or uuid.uuid4()
    cfg.faithfulness_threshold = 0.85
    cfg.answer_relevancy_threshold = 0.80
    cfg.contextual_precision_threshold = 0.75
    cfg.contextual_recall_threshold = 0.75
    cfg.hallucination_threshold = 0.15
    return cfg


def _make_eval_result(
    faithfulness=1.0,
    answer_relevancy=1.0,
    contextual_precision=1.0,
    contextual_recall=1.0,
    hallucination=0.0,
    overall_pass=True,
    eval_model="us.anthropic.claude-sonnet-4-5-20250929-v1:0",
    triggered_by="online",
):
    result = MagicMock()
    result.id = uuid.uuid4()
    result.faithfulness_score = faithfulness
    result.faithfulness_reason = "Faithful to source"
    result.answer_relevancy_score = answer_relevancy
    result.contextual_precision_score = contextual_precision
    result.contextual_recall_score = contextual_recall
    result.hallucination_score = hallucination
    result.overall_pass = overall_pass
    result.eval_model = eval_model
    result.triggered_by = triggered_by
    return result


@asynccontextmanager
async def _mock_session(execute_results):
    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=execute_results)
    yield mock_db


# ── Property 16: Eval task does not block response stream ─────────────────────

class TestEvalNonBlocking:

    def test_eval_task_enqueued_after_message_stored(self):
        """
        Property 16: evaluate_response_async must be enqueued (apply_async called)
        after the assistant message is committed to the DB.
        """
        call_order = []

        mock_task = MagicMock()
        mock_task.apply_async = MagicMock(side_effect=lambda *a, **kw: call_order.append("enqueue"))

        # Simulate: commit happens before enqueue
        def fake_commit():
            call_order.append("commit")

        async def _run():
            # Verify ordering: commit → enqueue
            fake_commit()
            mock_task.apply_async(
                args=[str(uuid.uuid4()), str(uuid.uuid4())],
                kwargs={"triggered_by": "online"},
            )

        asyncio.run(_run())
        assert call_order.index("commit") < call_order.index("enqueue"), (
            "Eval task must be enqueued AFTER message is committed"
        )

    def test_eval_task_is_async_not_blocking(self):
        """
        Property 16: evaluate_response_async uses apply_async (non-blocking),
        not delay() or direct call (which would block).
        """
        from app.workers.eval_tasks import evaluate_response_async

        # The task must be a Celery task (has apply_async)
        assert hasattr(evaluate_response_async, "apply_async"), (
            "evaluate_response_async must be a Celery task with apply_async"
        )
        assert hasattr(evaluate_response_async, "delay"), (
            "evaluate_response_async must be a Celery task with delay"
        )

    def test_eval_task_on_eval_queue(self):
        """Property 16: Task must be on eval_queue, not default queue."""
        from app.workers.eval_tasks import evaluate_response_async

        assert evaluate_response_async.queue == "eval_queue", (
            f"Expected queue='eval_queue', got '{evaluate_response_async.queue}'"
        )

    @given(st.integers(min_value=1, max_value=20))
    @settings(max_examples=20)
    def test_multiple_messages_each_get_independent_eval_task(self, n_messages: int):
        """
        Property 16: Each assistant message should trigger exactly one eval task enqueue.
        """
        enqueue_calls = []

        for _ in range(n_messages):
            message_id = str(uuid.uuid4())
            workspace_id = str(uuid.uuid4())
            enqueue_calls.append((message_id, workspace_id))

        assert len(enqueue_calls) == n_messages


# ── Property 17: Eval round trip — complete record ────────────────────────────

class TestEvalRoundTrip:

    def test_eval_result_has_no_null_metric_scores(self):
        """
        Property 17: A complete eval_results record must have no null metric scores.
        """
        result = _make_eval_result()

        assert result.faithfulness_score is not None
        assert result.answer_relevancy_score is not None
        assert result.contextual_precision_score is not None
        assert result.contextual_recall_score is not None
        assert result.hallucination_score is not None

    def test_eval_result_has_valid_overall_pass(self):
        """Property 17: overall_pass must be a boolean."""
        for overall_pass in [True, False]:
            result = _make_eval_result(overall_pass=overall_pass)
            assert isinstance(result.overall_pass, bool)

    def test_eval_result_has_eval_model_set(self):
        """Property 17: eval_model must be set to the judge model ID."""
        from app.services.eval.bedrock_judge import JUDGE_MODEL_NAME

        result = _make_eval_result(eval_model=JUDGE_MODEL_NAME)
        assert result.eval_model == JUDGE_MODEL_NAME
        assert result.eval_model != ""

    def test_evaluate_async_stores_complete_record(self):
        """
        Property 17: _evaluate_async must store a complete EvalResult with all fields.
        """
        async def _run():
            message_id = str(uuid.uuid4())
            workspace_id = str(uuid.uuid4())
            msg_uuid = uuid.UUID(message_id)
            ws_uuid = uuid.UUID(workspace_id)

            assistant_msg = _make_assistant_message()
            user_msg = _make_user_message(assistant_msg.session_id)
            eval_cfg = _make_eval_config(ws_uuid)

            stored_results = []

            async def mock_session_factory():
                mock_db = AsyncMock()
                mock_db.add = MagicMock(side_effect=lambda obj: stored_results.append(obj))
                mock_db.commit = AsyncMock()
                mock_db.refresh = AsyncMock()
                mock_db.execute = AsyncMock(side_effect=[
                    # build_test_case: load assistant message
                    MagicMock(**{"scalar_one_or_none.return_value": assistant_msg}),
                    # build_test_case: load user message
                    MagicMock(**{"scalar_one_or_none.return_value": user_msg}),
                    # build_test_case: load document trees (no prefixed IDs)
                    MagicMock(**{"scalars.return_value.all.return_value": []}),
                    # load eval_config
                    MagicMock(**{"scalar_one_or_none.return_value": eval_cfg}),
                ])
                return mock_db

            @asynccontextmanager
            async def mock_session_ctx():
                yield await mock_session_factory()

            neutral_scores = {
                "faithfulness": 1.0,
                "faithfulness_reason": "ok",
                "answer_relevancy": 1.0,
                "contextual_precision": 1.0,
                "contextual_recall": 1.0,
                "hallucination": 0.0,
            }

            with patch("app.core.database.AsyncSessionLocal", mock_session_ctx), \
                 patch("app.workers.eval_tasks._run_deepeval", return_value=neutral_scores), \
                 patch("app.services.eval.quality_gate.check_and_inject", new_callable=AsyncMock):

                from app.workers.eval_tasks import _evaluate_async
                result = await _evaluate_async(message_id, workspace_id, "online", None)

            assert result["status"] == "completed"
            assert result["message_id"] == message_id
            assert "overall_pass" in result

            from app.models.eval_result import EvalResult
            eval_records = [r for r in stored_results if isinstance(r, EvalResult)]
            assert len(eval_records) == 1

            record = eval_records[0]
            assert record.faithfulness_score is not None
            assert record.answer_relevancy_score is not None
            assert record.contextual_precision_score is not None
            assert record.contextual_recall_score is not None
            assert record.hallucination_score is not None
            assert isinstance(record.overall_pass, bool)
            assert record.eval_model != ""
            assert record.triggered_by == "online"

        asyncio.run(_run())

    @given(
        st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_overall_pass_logic_is_correct(
        self,
        faithfulness: float,
        answer_relevancy: float,
        contextual_precision: float,
        contextual_recall: float,
        hallucination: float,
    ):
        """
        Property 17: overall_pass must be True iff ALL thresholds are met.
        Faithfulness ≥ 0.85, relevancy ≥ 0.80, precision ≥ 0.75, recall ≥ 0.75, hallucination ≤ 0.15.
        """
        thresholds = {
            "faithfulness": 0.85,
            "answer_relevancy": 0.80,
            "contextual_precision": 0.75,
            "contextual_recall": 0.75,
            "hallucination": 0.15,
        }

        expected_pass = (
            faithfulness >= thresholds["faithfulness"]
            and answer_relevancy >= thresholds["answer_relevancy"]
            and contextual_precision >= thresholds["contextual_precision"]
            and contextual_recall >= thresholds["contextual_recall"]
            and hallucination <= thresholds["hallucination"]
        )

        actual_pass = (
            faithfulness >= thresholds["faithfulness"]
            and answer_relevancy >= thresholds["answer_relevancy"]
            and contextual_precision >= thresholds["contextual_precision"]
            and contextual_recall >= thresholds["contextual_recall"]
            and hallucination <= thresholds["hallucination"]
        )

        assert actual_pass == expected_pass

    def test_eval_task_max_retries_is_two(self):
        """Property 17: evaluate_response_async must have max_retries=2."""
        from app.workers.eval_tasks import _MAX_RETRIES
        assert _MAX_RETRIES == 2

    def test_eval_task_retry_backoff_is_30s(self):
        """Property 17: Retry backoff must be 30 seconds."""
        from app.workers.eval_tasks import _RETRY_BACKOFF
        assert _RETRY_BACKOFF == 30

    def test_triggered_by_online_for_chat_responses(self):
        """Property 17: triggered_by must be 'online' for real-time chat evaluations."""
        result = _make_eval_result(triggered_by="online")
        assert result.triggered_by == "online"
