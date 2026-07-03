"""API for creating and inspecting RAG benchmark runs."""
from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import BenchmarkRun, ModeResult
from app.orchestrator import run_benchmark
from app.schemas import RunCreate, RunOut, RunSummary

router = APIRouter(prefix="/runs", tags=["runs"])


@router.post("", response_model=RunOut, status_code=status.HTTP_201_CREATED)
async def create_run(body: RunCreate, db: AsyncSession = Depends(get_db)) -> BenchmarkRun:
    if not body.modes:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "At least one RAG mode must be selected")
    if not body.questions:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "At least one test question is required")

    run = BenchmarkRun(
        name=body.name,
        dataset_source_type=body.dataset_source_type,
        dataset_source_ref=body.dataset_source_ref,
        modes=[m.model_dump() for m in body.modes],
        questions=[q.model_dump() for q in body.questions],
        status="pending",
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    # Fire-and-forget: the run executes against the live DocuMind API in the
    # background; the frontend polls GET /runs/{id} for progress.
    asyncio.create_task(run_benchmark(run.id))

    loaded = await _load_run(db, run.id)
    assert loaded is not None
    return loaded


@router.get("", response_model=list[RunSummary])
async def list_runs(db: AsyncSession = Depends(get_db)) -> list[RunSummary]:
    result = await db.execute(
        select(BenchmarkRun)
        .options(selectinload(BenchmarkRun.mode_results))
        .order_by(BenchmarkRun.created_at.desc())
    )
    runs = result.scalars().all()
    return [
        RunSummary(
            id=run.id,
            name=run.name,
            status=run.status,
            created_at=run.created_at,
            completed_at=run.completed_at,
            mode_count=len(run.mode_results),
        )
        for run in runs
    ]


@router.get("/{run_id}", response_model=RunOut)
async def get_run(run_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> BenchmarkRun:
    run = await _load_run(db, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")
    return run


@router.get("/{run_id}/export")
async def export_run(run_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> dict:
    """Raw JSON export — same shape as docs/rag-benchmark-results.template.json
    in the main DocuMind repo, so results can be diffed/archived alongside it."""
    run = await _load_run(db, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")
    return _to_template_json(run)


@router.delete("/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_run(run_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> None:
    run = (
        await db.execute(select(BenchmarkRun).where(BenchmarkRun.id == run_id))
    ).scalar_one_or_none()
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")
    await db.delete(run)
    await db.commit()


async def _load_run(db: AsyncSession, run_id: uuid.UUID) -> BenchmarkRun | None:
    result = await db.execute(
        select(BenchmarkRun)
        .options(selectinload(BenchmarkRun.mode_results).selectinload(ModeResult.query_results))
        .where(BenchmarkRun.id == run_id)
    )
    return result.scalar_one_or_none()


def _to_template_json(run: BenchmarkRun) -> dict:
    return {
        "run_id": str(run.id),
        "run_date": run.created_at.date().isoformat(),
        "status": run.status,
        "error": run.error,
        "dataset": {
            "source_type": run.dataset_source_type,
            "source_ref": run.dataset_source_ref,
            "document_count": len(run.document_names or []),
            "document_names": run.document_names or [],
        },
        "modes": [
            {
                "rag_mode": mr.rag_mode,
                "retrieval_mode": mr.retrieval_mode,
                "kb_id": mr.kb_id,
                "status": mr.status,
                "error": mr.error,
                "ingestion": {
                    "documents_ingested": mr.documents_ingested,
                    "documents_failed": mr.documents_failed,
                    "avg_ingestion_time_seconds": mr.avg_ingestion_time_seconds,
                    "total_size_bytes": mr.total_size_bytes,
                },
                "robustness": {
                    "unanswerable_total": mr.unanswerable_total,
                    "unanswerable_handled": mr.unanswerable_handled,
                    "unanswerable_handled_rate": mr.unanswerable_handled_rate,
                },
                "citation_metrics": {
                    "supported": mr.citation_metrics_supported,
                    "precision_mean": mr.citation_precision_mean,
                    "recall_mean": mr.citation_recall_mean,
                    "note": "only meaningful for pageindex/vector — see methodology doc",
                },
                "queries": [
                    {
                        "question_id": qr.question_id,
                        "question": qr.question,
                        "expected_answer": qr.expected_answer,
                        "is_unanswerable": qr.is_unanswerable,
                        "expected_source_documents": qr.expected_source_documents,
                        "actual_answer": qr.actual_answer,
                        "node_ids_visited": qr.node_ids_visited,
                        "cited_doc_names": qr.cited_doc_names,
                        "citation_count": qr.citation_count,
                        "citation_precision": qr.citation_precision,
                        "citation_recall": qr.citation_recall,
                        "latency_ms": qr.latency_ms,
                        "eval_status": qr.eval_status,
                        "refused_correctly": qr.refused_correctly,
                        "scores": {
                            "faithfulness_score": qr.faithfulness_score,
                            "faithfulness_reason": qr.faithfulness_reason,
                            "answer_relevancy_score": qr.answer_relevancy_score,
                            "contextual_precision_score": qr.contextual_precision_score,
                            "contextual_recall_score": qr.contextual_recall_score,
                            "hallucination_score": qr.hallucination_score,
                            "overall_pass": qr.overall_pass,
                            "eval_model": qr.eval_model,
                        },
                    }
                    for qr in mr.query_results
                ],
                "aggregate": {
                    "faithfulness_mean": mr.faithfulness_mean,
                    "answer_relevancy_mean": mr.answer_relevancy_mean,
                    "contextual_precision_mean": mr.contextual_precision_mean,
                    "contextual_recall_mean": mr.contextual_recall_mean,
                    "hallucination_mean": mr.hallucination_mean,
                    "pass_rate": mr.pass_rate,
                    "p50_latency_ms": mr.p50_latency_ms,
                    "p95_latency_ms": mr.p95_latency_ms,
                },
            }
            for mr in run.mode_results
        ],
    }
