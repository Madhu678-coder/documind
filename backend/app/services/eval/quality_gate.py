"""Quality gate: append empathy disclaimer when eval scores breach thresholds (Requirements 13.6, 13.7)."""
from __future__ import annotations

import logging
import uuid
from typing import Any

logger = logging.getLogger(__name__)

EMPATHY_DISCLAIMER = (
    "\n\n---\n"
    "⚠️ **Transparency Notice:** This response may not fully reflect the source documents. "
    "Please verify key information directly in the cited sections before relying on this answer."
)


async def check_and_inject(
    message_id: uuid.UUID,
    eval_result: Any,
    workspace_id: uuid.UUID,
    db_session: Any,
    thresholds: Any | None = None,
) -> bool:
    """
    Check eval scores against workspace thresholds and inject the empathy disclaimer
    into chat_messages.content if faithfulness is below threshold OR hallucination
    is above threshold.

    Args:
        message_id: UUID of the ChatMessage to potentially update.
        eval_result: EvalResult ORM instance with score fields.
        workspace_id: UUID of the workspace (for threshold lookup if thresholds not provided).
        db_session: Active AsyncSession.
        thresholds: Pre-loaded EvalThresholds; if None, loads from DB.

    Returns:
        True if disclaimer was injected, False otherwise.
    """
    from sqlalchemy import select
    from app.models.chat_message import ChatMessage
    from app.models.eval_config import EvalConfig
    from app.services.eval.metrics import EvalThresholds

    # Resolve thresholds
    if thresholds is None:
        cfg_result = await db_session.execute(
            select(EvalConfig).where(EvalConfig.workspace_id == workspace_id)
        )
        cfg: EvalConfig | None = cfg_result.scalar_one_or_none()
        thresholds = EvalThresholds(
            faithfulness=cfg.faithfulness_threshold if cfg else 0.85,
            hallucination=cfg.hallucination_threshold if cfg else 0.15,
        )

    # Check breach conditions
    faithfulness_breached = eval_result.faithfulness_score < thresholds.faithfulness
    hallucination_breached = eval_result.hallucination_score > thresholds.hallucination

    if not (faithfulness_breached or hallucination_breached):
        return False

    # Load and update the message
    result = await db_session.execute(
        select(ChatMessage).where(ChatMessage.id == message_id)
    )
    message: ChatMessage | None = result.scalar_one_or_none()
    if message is None:
        logger.warning("ChatMessage not found for disclaimer injection", extra={"message_id": str(message_id)})
        return False

    # Only inject if not already present
    if EMPATHY_DISCLAIMER.strip() not in message.content:
        message.content = message.content + EMPATHY_DISCLAIMER
        await db_session.commit()
        logger.info(
            "Empathy disclaimer injected",
            extra={
                "message_id": str(message_id),
                "faithfulness_breached": faithfulness_breached,
                "hallucination_breached": hallucination_breached,
            },
        )

    return True
