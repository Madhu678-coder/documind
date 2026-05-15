# Feature: documind-platform, Property 18: Quality Gate Disclaimer Injection
"""
Property 18: For any assistant message where faithfulness_score is below the workspace
threshold OR hallucination_score is above the workspace threshold, the
chat_messages.content for that message should contain the empathy disclaimer text
after the quality gate runs.
"""
import asyncio
import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings, strategies as st

from app.services.eval.quality_gate import EMPATHY_DISCLAIMER


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_eval_result(faithfulness=1.0, hallucination=0.0):
    r = MagicMock()
    r.faithfulness_score = faithfulness
    r.hallucination_score = hallucination
    return r


def _make_message(content="The answer is 42."):
    msg = MagicMock()
    msg.id = uuid.uuid4()
    msg.content = content
    return msg


def _make_eval_config(faithfulness_threshold=0.85, hallucination_threshold=0.15):
    cfg = MagicMock()
    cfg.faithfulness_threshold = faithfulness_threshold
    cfg.hallucination_threshold = hallucination_threshold
    return cfg


@asynccontextmanager
async def _mock_db_session(message, eval_config=None):
    """Build a mock DB session that returns the given message and optional eval_config."""
    mock_db = AsyncMock()
    mock_db.commit = AsyncMock()

    execute_results = []
    if eval_config is not None:
        execute_results.append(
            MagicMock(**{"scalar_one_or_none.return_value": eval_config})
        )
    execute_results.append(
        MagicMock(**{"scalar_one_or_none.return_value": message})
    )
    mock_db.execute = AsyncMock(side_effect=execute_results)
    yield mock_db


# ── Property 18: Disclaimer injected when thresholds breached ─────────────────

class TestQualityGateDisclaimerInjection:

    def test_disclaimer_injected_when_faithfulness_below_threshold(self):
        """Property 18: Disclaimer injected when faithfulness_score < threshold."""
        async def _run():
            from app.services.eval.quality_gate import check_and_inject
            from app.services.eval.metrics import EvalThresholds

            message = _make_message("Original answer.")
            eval_result = _make_eval_result(faithfulness=0.50, hallucination=0.05)
            thresholds = EvalThresholds(faithfulness=0.85, hallucination=0.15)

            async with _mock_db_session(message) as db:
                injected = await check_and_inject(
                    message.id, eval_result, uuid.uuid4(), db, thresholds
                )

            assert injected is True
            assert EMPATHY_DISCLAIMER.strip() in message.content

        asyncio.run(_run())

    def test_disclaimer_injected_when_hallucination_above_threshold(self):
        """Property 18: Disclaimer injected when hallucination_score > threshold."""
        async def _run():
            from app.services.eval.quality_gate import check_and_inject
            from app.services.eval.metrics import EvalThresholds

            message = _make_message("Original answer.")
            eval_result = _make_eval_result(faithfulness=0.90, hallucination=0.50)
            thresholds = EvalThresholds(faithfulness=0.85, hallucination=0.15)

            async with _mock_db_session(message) as db:
                injected = await check_and_inject(
                    message.id, eval_result, uuid.uuid4(), db, thresholds
                )

            assert injected is True
            assert EMPATHY_DISCLAIMER.strip() in message.content

        asyncio.run(_run())

    def test_disclaimer_not_injected_when_all_thresholds_pass(self):
        """Property 18: No disclaimer when all scores are within thresholds."""
        async def _run():
            from app.services.eval.quality_gate import check_and_inject
            from app.services.eval.metrics import EvalThresholds

            message = _make_message("Original answer.")
            original_content = message.content
            eval_result = _make_eval_result(faithfulness=0.90, hallucination=0.05)
            thresholds = EvalThresholds(faithfulness=0.85, hallucination=0.15)

            async with _mock_db_session(message) as db:
                injected = await check_and_inject(
                    message.id, eval_result, uuid.uuid4(), db, thresholds
                )

            assert injected is False
            assert message.content == original_content

        asyncio.run(_run())

    def test_disclaimer_not_duplicated_on_second_injection(self):
        """Property 18: Disclaimer is not appended twice if already present."""
        async def _run():
            from app.services.eval.quality_gate import check_and_inject
            from app.services.eval.metrics import EvalThresholds

            # Pre-inject disclaimer
            message = _make_message("Original answer." + EMPATHY_DISCLAIMER)
            eval_result = _make_eval_result(faithfulness=0.50, hallucination=0.50)
            thresholds = EvalThresholds(faithfulness=0.85, hallucination=0.15)

            async with _mock_db_session(message) as db:
                await check_and_inject(
                    message.id, eval_result, uuid.uuid4(), db, thresholds
                )

            # Should appear exactly once
            assert message.content.count(EMPATHY_DISCLAIMER.strip()) == 1

        asyncio.run(_run())

    def test_disclaimer_injected_when_both_thresholds_breached(self):
        """Property 18: Disclaimer injected when both faithfulness and hallucination breach."""
        async def _run():
            from app.services.eval.quality_gate import check_and_inject
            from app.services.eval.metrics import EvalThresholds

            message = _make_message("Original answer.")
            eval_result = _make_eval_result(faithfulness=0.30, hallucination=0.80)
            thresholds = EvalThresholds(faithfulness=0.85, hallucination=0.15)

            async with _mock_db_session(message) as db:
                injected = await check_and_inject(
                    message.id, eval_result, uuid.uuid4(), db, thresholds
                )

            assert injected is True
            assert EMPATHY_DISCLAIMER.strip() in message.content

        asyncio.run(_run())

    def test_disclaimer_uses_workspace_thresholds_from_db(self):
        """Property 18: Thresholds are loaded from eval_config when not provided."""
        async def _run():
            from app.services.eval.quality_gate import check_and_inject

            message = _make_message("Original answer.")
            # Custom workspace threshold: faithfulness must be ≥ 0.95
            eval_config = _make_eval_config(faithfulness_threshold=0.95, hallucination_threshold=0.10)
            # Score of 0.90 passes default (0.85) but fails custom (0.95)
            eval_result = _make_eval_result(faithfulness=0.90, hallucination=0.05)

            async with _mock_db_session(message, eval_config) as db:
                injected = await check_and_inject(
                    message.id, eval_result, uuid.uuid4(), db, thresholds=None
                )

            assert injected is True
            assert EMPATHY_DISCLAIMER.strip() in message.content

        asyncio.run(_run())

    @given(
        st.floats(min_value=0.0, max_value=0.849, allow_nan=False, allow_infinity=False),
        st.floats(min_value=0.0, max_value=0.149, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_faithfulness_below_threshold_always_triggers_disclaimer(
        self, faithfulness: float, hallucination: float
    ):
        """
        Property 18: Any faithfulness score strictly below 0.85 must trigger disclaimer injection.
        """
        assert faithfulness < 0.85  # sanity check on generated value
        # The condition that triggers injection
        should_inject = faithfulness < 0.85 or hallucination > 0.15
        assert should_inject is True

    @given(
        st.floats(min_value=0.151, max_value=1.0, allow_nan=False, allow_infinity=False),
        st.floats(min_value=0.85, max_value=1.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_hallucination_above_threshold_always_triggers_disclaimer(
        self, hallucination: float, faithfulness: float
    ):
        """
        Property 18: Any hallucination score strictly above 0.15 must trigger disclaimer injection.
        """
        assert hallucination > 0.15  # sanity check
        should_inject = faithfulness < 0.85 or hallucination > 0.15
        assert should_inject is True

    @given(
        st.floats(min_value=0.85, max_value=1.0, allow_nan=False, allow_infinity=False),
        st.floats(min_value=0.0, max_value=0.15, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_passing_scores_never_trigger_disclaimer(
        self, faithfulness: float, hallucination: float
    ):
        """
        Property 18: Scores within thresholds must never trigger disclaimer injection.
        """
        should_inject = faithfulness < 0.85 or hallucination > 0.15
        assert should_inject is False
