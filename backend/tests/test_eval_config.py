# Feature: documind-platform, Property 19: Workspace Eval Threshold Precedence
"""
Property 19: For any workspace with an eval_config record, the thresholds used
during evaluation should match the values in that record. For any workspace without
an eval_config record, the default thresholds should be used.
"""
import asyncio
import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings, strategies as st

from app.services.eval.metrics import (
    DEFAULT_FAITHFULNESS_THRESHOLD,
    DEFAULT_ANSWER_RELEVANCY_THRESHOLD,
    DEFAULT_CONTEXTUAL_PRECISION_THRESHOLD,
    DEFAULT_CONTEXTUAL_RECALL_THRESHOLD,
    DEFAULT_HALLUCINATION_THRESHOLD,
    EvalThresholds,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_eval_config(
    workspace_id=None,
    faithfulness=0.85,
    answer_relevancy=0.80,
    contextual_precision=0.75,
    contextual_recall=0.75,
    hallucination=0.15,
):
    cfg = MagicMock()
    cfg.workspace_id = workspace_id or uuid.uuid4()
    cfg.faithfulness_threshold = float(faithfulness)
    cfg.answer_relevancy_threshold = float(answer_relevancy)
    cfg.contextual_precision_threshold = float(contextual_precision)
    cfg.contextual_recall_threshold = float(contextual_recall)
    cfg.hallucination_threshold = float(hallucination)
    return cfg


# ── Property 19: Default thresholds ───────────────────────────────────────────

class TestDefaultThresholds:

    def test_default_faithfulness_threshold(self):
        assert DEFAULT_FAITHFULNESS_THRESHOLD == 0.85

    def test_default_answer_relevancy_threshold(self):
        assert DEFAULT_ANSWER_RELEVANCY_THRESHOLD == 0.80

    def test_default_contextual_precision_threshold(self):
        assert DEFAULT_CONTEXTUAL_PRECISION_THRESHOLD == 0.75

    def test_default_contextual_recall_threshold(self):
        assert DEFAULT_CONTEXTUAL_RECALL_THRESHOLD == 0.75

    def test_default_hallucination_threshold(self):
        assert DEFAULT_HALLUCINATION_THRESHOLD == 0.15

    def test_eval_thresholds_dataclass_defaults(self):
        """EvalThresholds() with no args must use the documented defaults."""
        t = EvalThresholds()
        assert t.faithfulness == DEFAULT_FAITHFULNESS_THRESHOLD
        assert t.answer_relevancy == DEFAULT_ANSWER_RELEVANCY_THRESHOLD
        assert t.contextual_precision == DEFAULT_CONTEXTUAL_PRECISION_THRESHOLD
        assert t.contextual_recall == DEFAULT_CONTEXTUAL_RECALL_THRESHOLD
        assert t.hallucination == DEFAULT_HALLUCINATION_THRESHOLD


# ── Property 19: Workspace config takes precedence ────────────────────────────

class TestWorkspaceThresholdPrecedence:

    def test_workspace_config_overrides_defaults(self):
        """
        Property 19: When eval_config exists for a workspace, its thresholds
        must be used instead of the defaults.
        """
        custom_faithfulness = 0.92
        custom_hallucination = 0.08

        cfg = _make_eval_config(
            faithfulness=custom_faithfulness,
            hallucination=custom_hallucination,
        )

        # Simulate the threshold resolution logic from eval_tasks._evaluate_async
        thresholds = EvalThresholds(
            faithfulness=cfg.faithfulness_threshold,
            answer_relevancy=cfg.answer_relevancy_threshold,
            contextual_precision=cfg.contextual_precision_threshold,
            contextual_recall=cfg.contextual_recall_threshold,
            hallucination=cfg.hallucination_threshold,
        )

        assert thresholds.faithfulness == custom_faithfulness
        assert thresholds.hallucination == custom_hallucination

    def test_no_workspace_config_uses_defaults(self):
        """
        Property 19: When no eval_config exists for a workspace (cfg=None),
        default thresholds must be used.
        """
        cfg = None  # No config in DB

        thresholds = EvalThresholds(
            faithfulness=cfg.faithfulness_threshold if cfg else DEFAULT_FAITHFULNESS_THRESHOLD,
            answer_relevancy=cfg.answer_relevancy_threshold if cfg else DEFAULT_ANSWER_RELEVANCY_THRESHOLD,
            contextual_precision=cfg.contextual_precision_threshold if cfg else DEFAULT_CONTEXTUAL_PRECISION_THRESHOLD,
            contextual_recall=cfg.contextual_recall_threshold if cfg else DEFAULT_CONTEXTUAL_RECALL_THRESHOLD,
            hallucination=cfg.hallucination_threshold if cfg else DEFAULT_HALLUCINATION_THRESHOLD,
        )

        assert thresholds.faithfulness == DEFAULT_FAITHFULNESS_THRESHOLD
        assert thresholds.answer_relevancy == DEFAULT_ANSWER_RELEVANCY_THRESHOLD
        assert thresholds.contextual_precision == DEFAULT_CONTEXTUAL_PRECISION_THRESHOLD
        assert thresholds.contextual_recall == DEFAULT_CONTEXTUAL_RECALL_THRESHOLD
        assert thresholds.hallucination == DEFAULT_HALLUCINATION_THRESHOLD

    def test_evaluate_async_uses_workspace_thresholds(self):
        """
        Property 19: _evaluate_async must load eval_config from DB and use its thresholds.
        """
        async def _run():
            message_id = str(uuid.uuid4())
            workspace_id = str(uuid.uuid4())
            ws_uuid = uuid.UUID(workspace_id)

            # Custom thresholds that differ from defaults
            custom_cfg = _make_eval_config(
                workspace_id=ws_uuid,
                faithfulness=0.95,
                answer_relevancy=0.90,
                contextual_precision=0.80,
                contextual_recall=0.80,
                hallucination=0.10,
            )

            captured_thresholds = []

            async def mock_run_deepeval(test_case, thresholds):
                captured_thresholds.append(thresholds)
                return {
                    "faithfulness": 1.0,
                    "faithfulness_reason": "ok",
                    "answer_relevancy": 1.0,
                    "contextual_precision": 1.0,
                    "contextual_recall": 1.0,
                    "hallucination": 0.0,
                }

            assistant_msg = MagicMock()
            assistant_msg.id = uuid.uuid4()
            assistant_msg.session_id = uuid.uuid4()
            assistant_msg.role = "assistant"
            assistant_msg.content = "Answer"
            assistant_msg.node_ids_visited = []
            assistant_msg.created_at = __import__("datetime").datetime.utcnow()

            user_msg = MagicMock()
            user_msg.content = "Question"

            @asynccontextmanager
            async def mock_session():
                mock_db = AsyncMock()
                mock_db.add = MagicMock()
                mock_db.commit = AsyncMock()
                mock_db.refresh = AsyncMock()
                mock_db.execute = AsyncMock(side_effect=[
                    MagicMock(**{"scalar_one_or_none.return_value": assistant_msg}),
                    MagicMock(**{"scalar_one_or_none.return_value": user_msg}),
                    # eval_config (no tree query since node_ids_visited is empty)
                    MagicMock(**{"scalar_one_or_none.return_value": custom_cfg}),
                ])
                yield mock_db

            with patch("app.core.database.AsyncSessionLocal", mock_session), \
                 patch("app.workers.eval_tasks._run_deepeval", side_effect=mock_run_deepeval), \
                 patch("app.services.eval.quality_gate.check_and_inject", new_callable=AsyncMock):

                from app.workers.eval_tasks import _evaluate_async
                await _evaluate_async(message_id, workspace_id, "online", None)

            assert len(captured_thresholds) == 1
            t = captured_thresholds[0]
            assert t.faithfulness == 0.95
            assert t.answer_relevancy == 0.90
            assert t.contextual_precision == 0.80
            assert t.contextual_recall == 0.80
            assert t.hallucination == 0.10

        asyncio.run(_run())

    def test_evaluate_async_uses_defaults_when_no_config(self):
        """
        Property 19: _evaluate_async must use default thresholds when no eval_config exists.
        """
        async def _run():
            message_id = str(uuid.uuid4())
            workspace_id = str(uuid.uuid4())

            captured_thresholds = []

            async def mock_run_deepeval(test_case, thresholds):
                captured_thresholds.append(thresholds)
                return {
                    "faithfulness": 1.0,
                    "faithfulness_reason": "ok",
                    "answer_relevancy": 1.0,
                    "contextual_precision": 1.0,
                    "contextual_recall": 1.0,
                    "hallucination": 0.0,
                }

            assistant_msg = MagicMock()
            assistant_msg.id = uuid.uuid4()
            assistant_msg.session_id = uuid.uuid4()
            assistant_msg.role = "assistant"
            assistant_msg.content = "Answer"
            assistant_msg.node_ids_visited = []
            assistant_msg.created_at = __import__("datetime").datetime.utcnow()

            user_msg = MagicMock()
            user_msg.content = "Question"

            @asynccontextmanager
            async def mock_session():
                mock_db = AsyncMock()
                mock_db.add = MagicMock()
                mock_db.commit = AsyncMock()
                mock_db.refresh = AsyncMock()
                mock_db.execute = AsyncMock(side_effect=[
                    MagicMock(**{"scalar_one_or_none.return_value": assistant_msg}),
                    MagicMock(**{"scalar_one_or_none.return_value": user_msg}),
                    # eval_config (no tree query since node_ids_visited is empty)
                    MagicMock(**{"scalar_one_or_none.return_value": None}),  # No config
                ])
                yield mock_db

            with patch("app.core.database.AsyncSessionLocal", mock_session), \
                 patch("app.workers.eval_tasks._run_deepeval", side_effect=mock_run_deepeval), \
                 patch("app.services.eval.quality_gate.check_and_inject", new_callable=AsyncMock):

                from app.workers.eval_tasks import _evaluate_async
                await _evaluate_async(message_id, workspace_id, "online", None)

            assert len(captured_thresholds) == 1
            t = captured_thresholds[0]
            assert t.faithfulness == DEFAULT_FAITHFULNESS_THRESHOLD
            assert t.answer_relevancy == DEFAULT_ANSWER_RELEVANCY_THRESHOLD
            assert t.contextual_precision == DEFAULT_CONTEXTUAL_PRECISION_THRESHOLD
            assert t.contextual_recall == DEFAULT_CONTEXTUAL_RECALL_THRESHOLD
            assert t.hallucination == DEFAULT_HALLUCINATION_THRESHOLD

        asyncio.run(_run())

    @given(
        st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_workspace_thresholds_always_override_defaults(
        self,
        faithfulness: float,
        answer_relevancy: float,
        contextual_precision: float,
        contextual_recall: float,
        hallucination: float,
    ):
        """
        Property 19: Any custom threshold value from eval_config must be used
        verbatim — never replaced by the default.
        """
        cfg = _make_eval_config(
            faithfulness=faithfulness,
            answer_relevancy=answer_relevancy,
            contextual_precision=contextual_precision,
            contextual_recall=contextual_recall,
            hallucination=hallucination,
        )

        resolved = EvalThresholds(
            faithfulness=cfg.faithfulness_threshold,
            answer_relevancy=cfg.answer_relevancy_threshold,
            contextual_precision=cfg.contextual_precision_threshold,
            contextual_recall=cfg.contextual_recall_threshold,
            hallucination=cfg.hallucination_threshold,
        )

        assert resolved.faithfulness == faithfulness
        assert resolved.answer_relevancy == answer_relevancy
        assert resolved.contextual_precision == contextual_precision
        assert resolved.contextual_recall == contextual_recall
        assert resolved.hallucination == hallucination
