"""ORM models for the RAG Benchmark Suite's own database.

Three tables, one benchmark run fans out to N mode results, each mode result
fans out to N query results (one per test question). Mirrors the shape of
docs/rag-benchmark-results.template.json in the main DocuMind repo so the
`/runs/{id}/export` endpoint can produce that exact structure.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, JSON, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class BenchmarkRun(Base):
    __tablename__ = "benchmark_runs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="pending")  # pending|running|completed|failed
    dataset_source_type: Mapped[str] = mapped_column(Text)  # folder_path | s3 | confluence | gdrive | sharepoint
    dataset_source_ref: Mapped[str] = mapped_column(Text)
    document_names: Mapped[list] = mapped_column(JSON, default=list)
    modes: Mapped[list] = mapped_column(JSON, default=list)
    questions: Mapped[list] = mapped_column(JSON, default=list)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    mode_results: Mapped[list["ModeResult"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="ModeResult.id"
    )


class ModeResult(Base):
    __tablename__ = "benchmark_mode_results"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("benchmark_runs.id", ondelete="CASCADE"))
    rag_mode: Mapped[str] = mapped_column(Text)
    retrieval_mode: Mapped[str | None] = mapped_column(Text, nullable=True)
    kb_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, default="pending")  # pending|ingesting|querying|completed|failed
    documents_ingested: Mapped[int] = mapped_column(Integer, default=0)
    documents_failed: Mapped[int] = mapped_column(Integer, default=0)
    avg_ingestion_time_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    faithfulness_mean: Mapped[float | None] = mapped_column(Float, nullable=True)
    answer_relevancy_mean: Mapped[float | None] = mapped_column(Float, nullable=True)
    contextual_precision_mean: Mapped[float | None] = mapped_column(Float, nullable=True)
    contextual_recall_mean: Mapped[float | None] = mapped_column(Float, nullable=True)
    hallucination_mean: Mapped[float | None] = mapped_column(Float, nullable=True)
    pass_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    p50_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    p95_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Robustness: how well this mode refuses to answer questions flagged as
    # unanswerable, using hallucination_score as the "did it fabricate an
    # answer instead of refusing" proxy.
    unanswerable_total: Mapped[int] = mapped_column(Integer, default=0)
    unanswerable_handled: Mapped[int] = mapped_column(Integer, default=0)
    unanswerable_handled_rate: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Document-level citation precision/recall against QuestionSpec.expected_source_documents.
    # Only meaningful for rag_mode in (pageindex, vector) — see
    # docs/rag-benchmark-methodology.md §5.1 "Open gap": for wiki/graph/openkb,
    # CitationOut.doc_name is a page title / entity name, not a source filename,
    # so the comparison would be comparing the wrong thing. citation_metrics_supported
    # records which case applied to this mode result.
    citation_metrics_supported: Mapped[bool] = mapped_column(Boolean, default=False)
    citation_precision_mean: Mapped[float | None] = mapped_column(Float, nullable=True)
    citation_recall_mean: Mapped[float | None] = mapped_column(Float, nullable=True)

    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    run: Mapped["BenchmarkRun"] = relationship(back_populates="mode_results")
    query_results: Mapped[list["QueryResult"]] = relationship(
        back_populates="mode_result", cascade="all, delete-orphan", order_by="QueryResult.id"
    )


class QueryResult(Base):
    __tablename__ = "benchmark_query_results"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    mode_result_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("benchmark_mode_results.id", ondelete="CASCADE")
    )
    question_id: Mapped[str] = mapped_column(Text)
    question: Mapped[str] = mapped_column(Text)
    expected_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_unanswerable: Mapped[bool] = mapped_column(Boolean, default=False)
    expected_source_documents: Mapped[list] = mapped_column(JSON, default=list)
    actual_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    node_ids_visited: Mapped[list] = mapped_column(JSON, default=list)
    cited_doc_names: Mapped[list] = mapped_column(JSON, default=list)
    citation_count: Mapped[int] = mapped_column(Integer, default=0)
    citation_precision: Mapped[float | None] = mapped_column(Float, nullable=True)
    citation_recall: Mapped[float | None] = mapped_column(Float, nullable=True)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)

    faithfulness_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    faithfulness_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    answer_relevancy_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    contextual_precision_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    contextual_recall_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    hallucination_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    overall_pass: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    eval_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    eval_status: Mapped[str] = mapped_column(Text, default="pending")  # pending|scored|timeout|error

    # Set only when is_unanswerable is True and the question got scored: True if
    # the mode refused/avoided fabrication (hallucination_score under threshold).
    refused_correctly: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    mode_result: Mapped["ModeResult"] = relationship(back_populates="query_results")
