"""Eval config and results API endpoints (Requirement 13.7, Admin only)."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import Float, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user, require_role
from app.models.chat_message import ChatMessage
from app.models.chat_session import ChatSession
from app.models.document import Document
from app.models.eval_config import EvalConfig
from app.models.eval_result import EvalResult
from app.models.knowledge_base import KnowledgeBase
from app.models.user import User

router = APIRouter(prefix="/eval", tags=["eval"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class EvalConfigOut(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    faithfulness_threshold: float
    answer_relevancy_threshold: float
    contextual_precision_threshold: float
    contextual_recall_threshold: float
    hallucination_threshold: float
    multi_turn_enabled: bool = False

    model_config = {"from_attributes": True}


class EvalConfigUpdate(BaseModel):
    faithfulness_threshold: Optional[float] = None
    answer_relevancy_threshold: Optional[float] = None
    contextual_precision_threshold: Optional[float] = None
    contextual_recall_threshold: Optional[float] = None
    hallucination_threshold: Optional[float] = None
    multi_turn_enabled: Optional[bool] = None


class EvalResultOut(BaseModel):
    id: uuid.UUID
    message_id: uuid.UUID
    document_id: uuid.UUID
    faithfulness_score: float
    faithfulness_reason: str
    answer_relevancy_score: float
    contextual_precision_score: float
    contextual_recall_score: float
    hallucination_score: float
    overall_pass: bool
    eval_model: str
    triggered_by: str

    model_config = {"from_attributes": True}


# ── GET /eval/config ──────────────────────────────────────────────────────────

@router.get("/config", response_model=EvalConfigOut)
async def get_eval_config(
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Return workspace eval thresholds. Falls back to defaults when no config exists."""
    try:
        result = await db.execute(
            select(EvalConfig).where(EvalConfig.workspace_id == current_user.workspace_id)
        )
        cfg = result.scalar_one_or_none()
    except Exception:
        # Column may not exist yet (migration pending) — return defaults
        await db.rollback()
        cfg = None

    if cfg is None:
        return EvalConfigOut(
            id=uuid.UUID("00000000-0000-0000-0000-000000000000"),
            workspace_id=current_user.workspace_id,
            faithfulness_threshold=0.85,
            answer_relevancy_threshold=0.80,
            contextual_precision_threshold=0.75,
            contextual_recall_threshold=0.75,
            hallucination_threshold=0.15,
            multi_turn_enabled=False,
        )

    return cfg


# ── PATCH /eval/config ────────────────────────────────────────────────────────

@router.patch("/config", response_model=EvalConfigOut)
async def update_eval_config(
    body: EvalConfigUpdate,
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Update workspace eval thresholds. Creates a new config record if none exists."""
    try:
        result = await db.execute(
            select(EvalConfig).where(EvalConfig.workspace_id == current_user.workspace_id)
        )
        cfg = result.scalar_one_or_none()
    except Exception:
        await db.rollback()
        cfg = None

    if cfg is None:
        cfg = EvalConfig(
            workspace_id=current_user.workspace_id,
            faithfulness_threshold=0.85,
            answer_relevancy_threshold=0.80,
            contextual_precision_threshold=0.75,
            contextual_recall_threshold=0.75,
            hallucination_threshold=0.15,
            multi_turn_enabled=False,
        )
        db.add(cfg)

    update_data = body.model_dump(exclude_none=True)
    for field, value in update_data.items():
        setattr(cfg, field, value)

    try:
        await db.commit()
        await db.refresh(cfg)
    except Exception:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save config — run: alembic upgrade head",
        )
    return cfg


# ── GET /eval/results/{message_id} ────────────────────────────────────────────

@router.get("/results/{message_id}", response_model=EvalResultOut)
async def get_eval_result(
    message_id: uuid.UUID,
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Return eval scores for a specific message. Admin only."""
    result = await db.execute(
        select(EvalResult).where(EvalResult.message_id == message_id)
    )
    eval_result = result.scalar_one_or_none()

    if eval_result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Eval result not found for this message",
        )

    return eval_result


# ── Analytics schemas ─────────────────────────────────────────────────────────

class TopQueryItem(BaseModel):
    kb_id: str
    kb_name: str
    query_text: str
    count: int


class ConfidenceBucket(BaseModel):
    range: str
    count: int


class LowConfidenceItem(BaseModel):
    message_id: str
    session_id: str
    query_text: str
    confidence_score: float
    kb_name: str
    created_at: str


# ── GET /eval/analytics/top-queries ──────────────────────────────────────────

@router.get("/analytics/top-queries", response_model=dict)
async def get_top_queries(
    limit: int = Query(10, ge=1, le=100),
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Return the top N most-asked queries per KnowledgeBase in the workspace."""
    # Join chat_messages → chat_sessions → knowledge_bases, filter by workspace
    result = await db.execute(
        select(
            ChatMessage.content,
            ChatSession.kb_id,
            KnowledgeBase.name,
            func.count(ChatMessage.id).label("cnt"),
        )
        .join(ChatSession, ChatMessage.session_id == ChatSession.id)
        .join(KnowledgeBase, ChatSession.kb_id == KnowledgeBase.id)
        .where(
            ChatMessage.role == "user",
            ChatSession.workspace_id == current_user.workspace_id,
        )
        .group_by(ChatMessage.content, ChatSession.kb_id, KnowledgeBase.name)
        .order_by(func.count(ChatMessage.id).desc())
        .limit(limit)
    )
    rows = result.all()
    queries = [
        TopQueryItem(
            kb_id=str(row.kb_id),
            kb_name=row.name,
            query_text=row.content,
            count=row.cnt,
        )
        for row in rows
    ]
    return {"queries": queries}


# ── GET /eval/analytics/confidence-distribution ───────────────────────────────

@router.get("/analytics/confidence-distribution", response_model=dict)
async def get_confidence_distribution(
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Return answer_relevancy score distribution bucketed into 5 ranges."""
    ranges = [
        ("0.0-0.2", 0.0, 0.2),
        ("0.2-0.4", 0.2, 0.4),
        ("0.4-0.6", 0.4, 0.6),
        ("0.6-0.8", 0.6, 0.8),
        ("0.8-1.0", 0.8, 1.01),  # inclusive upper bound
    ]
    buckets = []
    for label, lo, hi in ranges:
        result = await db.execute(
            select(func.count(EvalResult.id))
            # EvalResult is on assistant messages — join via session for workspace filter
            .join(ChatMessage, EvalResult.message_id == ChatMessage.id)
            .join(ChatSession, ChatMessage.session_id == ChatSession.id)
            .where(
                ChatSession.workspace_id == current_user.workspace_id,
                ChatMessage.role == "assistant",
                EvalResult.answer_relevancy_score >= lo,
                EvalResult.answer_relevancy_score < hi,
            )
        )
        count = result.scalar_one() or 0
        buckets.append(ConfidenceBucket(range=label, count=count))
    return {"buckets": buckets}


# ── GET /eval/analytics/low-confidence ───────────────────────────────────────

@router.get("/analytics/low-confidence", response_model=dict)
async def get_low_confidence_queries(
    limit: int = Query(10, ge=1, le=100),
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Return the N most recent low-confidence assistant messages (answer_relevancy < 0.5)."""
    result = await db.execute(
        select(
            ChatMessage.id,
            ChatMessage.content,
            ChatMessage.session_id,
            ChatMessage.created_at,
            EvalResult.answer_relevancy_score,
            KnowledgeBase.name,
        )
        .join(EvalResult, EvalResult.message_id == ChatMessage.id)
        .join(ChatSession, ChatMessage.session_id == ChatSession.id)
        .join(KnowledgeBase, ChatSession.kb_id == KnowledgeBase.id)
        .where(
            ChatMessage.role == "assistant",
            ChatSession.workspace_id == current_user.workspace_id,
            EvalResult.answer_relevancy_score < 0.5,
        )
        .order_by(ChatMessage.created_at.desc())
        .limit(limit)
    )
    rows = result.all()
    queries = [
        LowConfidenceItem(
            message_id=str(row.id),
            session_id=str(row.session_id),
            query_text=row.content[:200],
            confidence_score=row.answer_relevancy_score,
            kb_name=row.name,
            created_at=row.created_at.isoformat(),
        )
        for row in rows
    ]
    return {"queries": queries}


# ── GET /eval/analytics/trend ─────────────────────────────────────────────────

@router.get("/analytics/trend", response_model=dict)
async def get_faithfulness_trend(
    days: int = Query(7, ge=1, le=30),
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Return daily average faithfulness scores for the past N days."""
    since = datetime.utcnow() - timedelta(days=days)
    
    # Create the date_trunc expression once to use in both SELECT and GROUP BY
    day_column = func.date_trunc("day", EvalResult.evaluated_at).label("day")
    
    result = await db.execute(
        select(
            day_column,
            func.avg(EvalResult.faithfulness_score).label("avg_faithfulness"),
        )
        .join(ChatMessage, EvalResult.message_id == ChatMessage.id)
        .join(ChatSession, ChatMessage.session_id == ChatSession.id)
        .where(
            ChatSession.workspace_id == current_user.workspace_id,
            EvalResult.evaluated_at >= since,
            ChatMessage.role == "assistant",
        )
        .group_by(day_column)
        .order_by(day_column)
    )
    rows = result.all()
    dates = [row.day.strftime("%Y-%m-%d") for row in rows]
    faithfulness = [float(row.avg_faithfulness) for row in rows]
    return {"dates": dates, "faithfulness": faithfulness}


# ── GET /eval/analytics/heatmap ───────────────────────────────────────────────

@router.get("/analytics/heatmap", response_model=dict)
async def get_quality_heatmap(
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Return per-document average quality scores."""
    result = await db.execute(
        select(
            Document.id,
            Document.filename,
            func.avg(EvalResult.faithfulness_score).label("avg_faithfulness"),
            func.avg(EvalResult.answer_relevancy_score).label("avg_relevancy"),
            func.avg(EvalResult.hallucination_score).label("avg_hallucination"),
        )
        .join(EvalResult, EvalResult.document_id == Document.id)
        .join(ChatMessage, EvalResult.message_id == ChatMessage.id)
        .join(ChatSession, ChatMessage.session_id == ChatSession.id)
        .where(ChatSession.workspace_id == current_user.workspace_id)
        .group_by(Document.id, Document.filename)
        .order_by(func.avg(EvalResult.faithfulness_score))
    )
    rows = result.all()
    documents = [
        {
            "doc_id": str(row.id),
            "filename": row.filename,
            "avg_faithfulness": float(row.avg_faithfulness or 0),
            "avg_relevancy": float(row.avg_relevancy or 0),
            "avg_hallucination": float(row.avg_hallucination or 0),
        }
        for row in rows
    ]
    return {"documents": documents}


# ── GET /eval/analytics/distribution ─────────────────────────────────────────

@router.get("/analytics/distribution", response_model=dict)
async def get_metric_distribution(
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Return all 5 metric score arrays for histogram rendering."""
    result = await db.execute(
        select(
            EvalResult.faithfulness_score,
            EvalResult.answer_relevancy_score,
            EvalResult.contextual_precision_score,
            EvalResult.contextual_recall_score,
            EvalResult.hallucination_score,
        )
        .join(ChatMessage, EvalResult.message_id == ChatMessage.id)
        .join(ChatSession, ChatMessage.session_id == ChatSession.id)
        .where(
            ChatSession.workspace_id == current_user.workspace_id,
            ChatMessage.role == "assistant",
        )
        .limit(500)  # cap for performance
    )
    rows = result.all()
    return {
        "faithfulness": [float(r.faithfulness_score) for r in rows],
        "answer_relevancy": [float(r.answer_relevancy_score) for r in rows],
        "contextual_precision": [float(r.contextual_precision_score) for r in rows],
        "contextual_recall": [float(r.contextual_recall_score) for r in rows],
        "hallucination": [float(r.hallucination_score) for r in rows],
    }


# ── GET /eval/analytics/low-scores ───────────────────────────────────────────

@router.get("/analytics/low-scores", response_model=dict)
async def get_low_score_messages(
    limit: int = Query(10, ge=1, le=100),
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Return messages with faithfulness below threshold (used by QualityMonitor)."""
    result = await db.execute(
        select(EvalConfig).where(EvalConfig.workspace_id == current_user.workspace_id)
    )
    cfg = result.scalar_one_or_none()
    threshold = cfg.faithfulness_threshold if cfg else 0.85

    # Use DISTINCT ON to get only one row per message_id (the lowest score)
    rows_result = await db.execute(
        select(
            ChatMessage.id,
            ChatMessage.session_id,
            ChatMessage.content,
            ChatMessage.created_at,
            EvalResult.faithfulness_score,
        )
        .join(EvalResult, EvalResult.message_id == ChatMessage.id)
        .join(ChatSession, ChatMessage.session_id == ChatSession.id)
        .where(
            ChatSession.workspace_id == current_user.workspace_id,
            ChatMessage.role == "assistant",
            EvalResult.faithfulness_score < threshold,
        )
        .distinct(ChatMessage.id)
        .order_by(ChatMessage.id, EvalResult.faithfulness_score)
        .limit(limit)
    )
    rows = rows_result.all()
    return {
        "messages": [
            {
                "message_id": str(r.id),
                "session_id": str(r.session_id),
                "content_preview": r.content[:150],
                "faithfulness_score": float(r.faithfulness_score),
                "evaluated_at": r.created_at.isoformat(),
            }
            for r in rows
        ]
    }
