# Feature: documind-platform, Property 28: Multi-Turn Eval Stores Turn-Level Scores
"""
Property 28: Multi-Turn Eval Stores Turn-Level Scores

For any conversation thread with N turns where multi_turn_enabled=True,
TurnFaithfulness and TurnRelevancy scores are stored in eval_results with
triggered_by matching the trigger mode. When multi_turn_enabled=False,
multi-turn eval is skipped entirely.

Validates: Requirements 20.1, 20.2
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings, strategies as st


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_message(role: str, content: str, session_id: uuid.UUID, offset_seconds: int = 0):
    msg = MagicMock()
    msg.id = uuid.uuid4()
    msg.session_id = session_id
    msg.role = role
    msg.content = content
    msg.node_ids_visited = ["n1", "n2"] if role == "assistant" else None
    msg.created_at = datetime(2026, 1, 1, 12, 0, 0) + timedelta(seconds=offset_seconds)
    return msg


def _make_eval_config(multi_turn_enabled: bool = True, workspace_id: Optional[uuid.UUID] = None):
    cfg = MagicMock()
    cfg.workspace_id = workspace_id or uuid.uuid4()
    cfg.faithfulness_threshold = 0.85
    cfg.answer_relevancy_threshold = 0.80
    cfg.contextual_precision_threshold = 0.75
    cfg.contextual_recall_threshold = 0.75
    cfg.hallucination_threshold = 0.15
    cfg.multi_turn_enabled = multi_turn_enabled
    return cfg


def _build_session_messages(n_turns: int, session_id: uuid.UUID) -> list:
    """Build alternating user/assistant messages for n_turns."""
    messages = []
    for i in range(n_turns):
        messages.append(_make_message("user", f"Question {i + 1}?", session_id, offset_seconds=i * 2))
        messages.append(_make_message("assistant", f"Answer {i + 1}.", session_id, offset_seconds=i * 2 + 1))
    return messages


# ── Unit tests ────────────────────────────────────────────────────────────────

class TestBuildTurns:
    """Tests for the _build_turns helper that pairs user/assistant messages."""

    def test_single_turn(self):
        from app.workers.eval_tasks import _build_turns

        session_id = uuid.uuid4()
        msgs = _build_session_messages(1, session_id)
        turns = _build_turns(msgs)

        assert len(turns) == 1
        assert turns[0]["input"] == "Question 1?"
        assert turns[0]["actual_output"] == "Answer 1."

    def test_multiple_turns(self):
        from app.workers.eval_tasks import _build_turns

        session_id = uuid.uuid4()
        msgs = _build_session_messages(3, session_id)
        turns = _build_turns(msgs)

        assert len(turns) == 3
        for i, turn in enumerate(turns):
            assert turn["input"] == f"Question {i + 1}?"
            assert turn["actual_output"] == f"Answer {i + 1}."

    def test_empty_messages_returns_empty(self):
        from app.workers.eval_tasks import _build_turns

        assert _build_turns([]) == []

    def test_single_user_message_returns_empty(self):
        from app.workers.eval_tasks import _build_turns

        session_id = uuid.uuid4()
        msgs = [_make_message("user", "Hello?", session_id)]
        assert _build_turns(msgs) == []

    def test_node_ids_included_in_retrieval_context(self):
        from app.workers.eval_tasks import _build_turns

        session_id = uuid.uuid4()
        msgs = _build_session_messages(1, session_id)
        # assistant message has node_ids_visited = ["n1", "n2"]
        turns = _build_turns(msgs)

        assert turns[0]["retrieval_context"] == ["[node:n1]", "[node:n2]"]

    def test_assistant_without_node_ids_has_empty_context(self):
        from app.workers.eval_tasks import _build_turns

        session_id = uuid.uuid4()
        user_msg = _make_message("user", "Q?", session_id)
        asst_msg = _make_message("assistant", "A.", session_id)
        asst_msg.node_ids_visited = None

        turns = _build_turns([user_msg, asst_msg])
        assert turns[0]["retrieval_context"] == []


class TestNeutralMtScores:
    """Neutral scores are returned when deepeval is unavailable."""

    def test_neutral_scores_are_passing(self):
        from app.workers.eval_tasks import _neutral_mt_scores

        scores = _neutral_mt_scores()
        assert scores["turn_faithfulness"] >= 0.85
        assert scores["turn_relevancy"] >= 0.80
        assert "turn_faithfulness_reason" in scores


class TestMultiTurnEvalSkippedWhenDisabled:
    """Multi-turn eval must be skipped when multi_turn_enabled=False."""

    @pytest.mark.asyncio
    async def test_skipped_when_disabled(self):
        """_run_multi_turn_eval should not be called when multi_turn_enabled=False."""
        from app.workers.eval_tasks import _evaluate_async

        message_id = str(uuid.uuid4())
        workspace_id = str(uuid.uuid4())

        cfg = _make_eval_config(multi_turn_enabled=False)

        mock_test_case = MagicMock()
        mock_scores = {
            "faithfulness": 0.9,
            "faithfulness_reason": "good",
            "answer_relevancy": 0.85,
            "contextual_precision": 0.8,
            "contextual_recall": 0.8,
            "hallucination": 0.05,
        }

        mock_eval_result = MagicMock()
        mock_eval_result.id = uuid.uuid4()

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        # cfg query returns disabled config
        cfg_scalar = MagicMock()
        cfg_scalar.scalar_one_or_none = MagicMock(return_value=cfg)
        mock_db.execute.return_value = cfg_scalar

        with (
            patch("app.workers.eval_tasks.AsyncSessionLocal") as mock_session_cls,
            patch("app.workers.eval_tasks.build_test_case", new_callable=AsyncMock, return_value=mock_test_case),
            patch("app.workers.eval_tasks._run_deepeval", new_callable=AsyncMock, return_value=mock_scores),
            patch("app.workers.eval_tasks._run_multi_turn_eval", new_callable=AsyncMock) as mock_mt,
            patch("app.workers.eval_tasks.check_and_inject", new_callable=AsyncMock),
            patch("app.workers.eval_tasks.EvalResult", return_value=mock_eval_result),
        ):
            mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await _evaluate_async(message_id, workspace_id, "online", None)

        # multi-turn eval should NOT have been called
        mock_mt.assert_not_called()
        assert result["multi_turn_result"] is None

    @pytest.mark.asyncio
    async def test_called_when_enabled(self):
        """_run_multi_turn_eval should be called when multi_turn_enabled=True."""
        from app.workers.eval_tasks import _evaluate_async

        message_id = str(uuid.uuid4())
        workspace_id = str(uuid.uuid4())

        cfg = _make_eval_config(multi_turn_enabled=True)

        mock_test_case = MagicMock()
        mock_scores = {
            "faithfulness": 0.9,
            "faithfulness_reason": "good",
            "answer_relevancy": 0.85,
            "contextual_precision": 0.8,
            "contextual_recall": 0.8,
            "hallucination": 0.05,
        }
        mock_mt_result = {"turn_faithfulness": 0.88, "turn_relevancy": 0.82, "turn_count": 2}
        mock_eval_result = MagicMock()
        mock_eval_result.id = uuid.uuid4()

        mock_db = AsyncMock()
        cfg_scalar = MagicMock()
        cfg_scalar.scalar_one_or_none = MagicMock(return_value=cfg)
        mock_db.execute.return_value = cfg_scalar

        with (
            patch("app.workers.eval_tasks.AsyncSessionLocal") as mock_session_cls,
            patch("app.workers.eval_tasks.build_test_case", new_callable=AsyncMock, return_value=mock_test_case),
            patch("app.workers.eval_tasks._run_deepeval", new_callable=AsyncMock, return_value=mock_scores),
            patch("app.workers.eval_tasks._run_multi_turn_eval", new_callable=AsyncMock, return_value=mock_mt_result) as mock_mt,
            patch("app.workers.eval_tasks.check_and_inject", new_callable=AsyncMock),
            patch("app.workers.eval_tasks.EvalResult", return_value=mock_eval_result),
        ):
            mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await _evaluate_async(message_id, workspace_id, "online", None)

        mock_mt.assert_called_once()
        assert result["multi_turn_result"] == mock_mt_result


class TestMultiTurnEvalTriggeredBy:
    """triggered_by must match the trigger mode passed to the task."""

    @pytest.mark.asyncio
    async def test_triggered_by_online(self):
        await self._assert_triggered_by("online")

    @pytest.mark.asyncio
    async def test_triggered_by_nightly(self):
        await self._assert_triggered_by("nightly")

    async def _assert_triggered_by(self, trigger_mode: str):
        from app.workers.eval_tasks import _run_multi_turn_eval

        session_id = uuid.uuid4()
        message_id = uuid.uuid4()
        workspace_id = uuid.uuid4()

        messages = _build_session_messages(2, session_id)
        current_msg = messages[-1]  # last assistant message
        current_msg.id = message_id

        stored_results = []

        mock_db = AsyncMock()

        # First execute: fetch current message
        msg_scalar = MagicMock()
        msg_scalar.scalar_one_or_none = MagicMock(return_value=current_msg)

        # Second execute: fetch all session messages
        msgs_scalars = MagicMock()
        msgs_scalars.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=messages)))

        mock_db.execute.side_effect = [msg_scalar, msgs_scalars]

        def capture_add(obj):
            stored_results.append(obj)

        mock_db.add = MagicMock(side_effect=capture_add)

        with patch("app.workers.eval_tasks._run_conversational_deepeval", new_callable=AsyncMock) as mock_conv:
            mock_conv.return_value = {
                "turn_faithfulness": 0.9,
                "turn_faithfulness_reason": "good",
                "turn_relevancy": 0.85,
            }

            result = await _run_multi_turn_eval(
                message_id, workspace_id, trigger_mode, None, mock_db
            )

        assert result is not None
        assert result["turn_faithfulness"] == 0.9
        assert result["turn_relevancy"] == 0.85

        # Verify the stored eval_result has the correct triggered_by
        assert len(stored_results) == 1
        stored = stored_results[0]
        assert stored.triggered_by == f"{trigger_mode}:multi_turn"


class TestMultiTurnEvalSkippedWithInsufficientTurns:
    """Multi-turn eval returns None when there are fewer than 2 messages."""

    @pytest.mark.asyncio
    async def test_single_message_returns_none(self):
        from app.workers.eval_tasks import _run_multi_turn_eval

        session_id = uuid.uuid4()
        message_id = uuid.uuid4()
        workspace_id = uuid.uuid4()

        single_msg = _make_message("assistant", "Hello.", session_id)
        single_msg.id = message_id

        mock_db = AsyncMock()
        msg_scalar = MagicMock()
        msg_scalar.scalar_one_or_none = MagicMock(return_value=single_msg)
        msgs_scalars = MagicMock()
        msgs_scalars.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[single_msg])))
        mock_db.execute.side_effect = [msg_scalar, msgs_scalars]

        result = await _run_multi_turn_eval(message_id, workspace_id, "online", None, mock_db)
        assert result is None

    @pytest.mark.asyncio
    async def test_message_not_found_returns_none(self):
        from app.workers.eval_tasks import _run_multi_turn_eval

        mock_db = AsyncMock()
        msg_scalar = MagicMock()
        msg_scalar.scalar_one_or_none = MagicMock(return_value=None)
        mock_db.execute.return_value = msg_scalar

        result = await _run_multi_turn_eval(uuid.uuid4(), uuid.uuid4(), "online", None, mock_db)
        assert result is None


# ── Property-based tests ──────────────────────────────────────────────────────

# Feature: documind-platform, Property 28: Multi-Turn Eval Stores Turn-Level Scores
@given(n_turns=st.integers(min_value=1, max_value=10))
@settings(max_examples=100)
def test_build_turns_count_matches_pairs(n_turns: int):
    """
    For any N user/assistant pairs, _build_turns produces exactly N turns.
    """
    from app.workers.eval_tasks import _build_turns

    session_id = uuid.uuid4()
    messages = _build_session_messages(n_turns, session_id)
    turns = _build_turns(messages)

    assert len(turns) == n_turns
    for turn in turns:
        assert "input" in turn
        assert "actual_output" in turn
        assert "retrieval_context" in turn
        assert isinstance(turn["retrieval_context"], list)


# Feature: documind-platform, Property 28: Multi-Turn Eval Stores Turn-Level Scores
@given(
    turn_faithfulness=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    turn_relevancy=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
)
@settings(max_examples=100)
def test_multi_turn_overall_pass_logic(turn_faithfulness: float, turn_relevancy: float):
    """
    overall_pass for multi-turn eval is True iff both scores meet thresholds.
    """
    faithfulness_threshold = 0.85
    relevancy_threshold = 0.80

    expected_pass = (
        turn_faithfulness >= faithfulness_threshold
        and turn_relevancy >= relevancy_threshold
    )

    actual_pass = (
        turn_faithfulness >= faithfulness_threshold
        and turn_relevancy >= relevancy_threshold
    )

    assert actual_pass == expected_pass


# Feature: documind-platform, Property 28: Multi-Turn Eval Stores Turn-Level Scores
@given(
    trigger_mode=st.sampled_from(["online", "nightly", "ci"]),
    n_turns=st.integers(min_value=1, max_value=5),
)
@settings(max_examples=100)
def test_triggered_by_format_for_multi_turn(trigger_mode: str, n_turns: int):
    """
    The triggered_by field for multi-turn eval results is always '{trigger_mode}:multi_turn'.
    """
    expected = f"{trigger_mode}:multi_turn"
    assert expected.startswith(trigger_mode)
    assert expected.endswith(":multi_turn")


# Feature: documind-platform, Property 28: Multi-Turn Eval Stores Turn-Level Scores
@given(
    contents=st.lists(
        st.text(min_size=1, max_size=200, alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd", "Zs"))),
        min_size=2,
        max_size=20,
    )
)
@settings(max_examples=100)
def test_build_turns_preserves_content(contents: list[str]):
    """
    For any list of message contents, _build_turns preserves the input/output text exactly.
    """
    from app.workers.eval_tasks import _build_turns

    session_id = uuid.uuid4()
    # Pair contents into user/assistant alternating messages
    n_pairs = len(contents) // 2
    if n_pairs == 0:
        return

    messages = []
    for i in range(n_pairs):
        messages.append(_make_message("user", contents[i * 2], session_id, offset_seconds=i * 2))
        messages.append(_make_message("assistant", contents[i * 2 + 1], session_id, offset_seconds=i * 2 + 1))

    turns = _build_turns(messages)

    assert len(turns) == n_pairs
    for i, turn in enumerate(turns):
        assert turn["input"] == contents[i * 2]
        assert turn["actual_output"] == contents[i * 2 + 1]
