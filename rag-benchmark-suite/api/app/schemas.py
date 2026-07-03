from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

RAG_MODES = ("pageindex", "vector", "wiki", "graph", "openkb")
RETRIEVAL_MODES = ("vector", "fulltext", "hybrid")

# doc_name on citations is a real source filename only for these two modes —
# see docs/rag-benchmark-methodology.md §5.1 "Open gap".
CITATION_METRIC_MODES = ("pageindex", "vector")


class ModeSpec(BaseModel):
    rag_mode: Literal["pageindex", "vector", "wiki", "graph", "openkb"]
    retrieval_mode: Optional[Literal["vector", "fulltext", "hybrid"]] = None

    @property
    def label(self) -> str:
        return f"{self.rag_mode}:{self.retrieval_mode}" if self.retrieval_mode else self.rag_mode


class QuestionSpec(BaseModel):
    id: str
    question: str
    expected_answer: Optional[str] = None
    is_unanswerable: bool = False
    expected_source_documents: list[str] = Field(
        default_factory=list,
        description=(
            "Filenames the answer should cite. Only scored into citation "
            "precision/recall for pageindex/vector modes — see methodology doc."
        ),
    )


class QuestionDraftRequest(BaseModel):
    """Same dataset addressing as RunCreate — draft generation reads the
    identical dataset a real run would use, before any modes are picked."""

    dataset_source_type: Literal["folder_path", "s3", "confluence", "gdrive", "sharepoint"]
    dataset_source_ref: str
    count: int = Field(8, ge=1, le=20)


class QuestionDraftOut(BaseModel):
    question: str
    expected_answer: Optional[str] = None
    is_unanswerable: bool = False
    expected_source_documents: list[str] = []


class QuestionDraftResponse(BaseModel):
    document_names: list[str]
    questions: list[QuestionDraftOut]


class RunCreate(BaseModel):
    name: str
    dataset_source_type: Literal["folder_path", "s3", "confluence", "gdrive", "sharepoint"]
    dataset_source_ref: str = Field(
        ...,
        description=(
            "folder_path: a mounted local path. s3: s3://bucket/prefix. "
            "confluence: SPACEKEY or SPACEKEY:PAGEID. gdrive: a Drive folder ID. "
            "sharepoint: 'hostname|/sites/site-name|folder/path'."
        ),
    )
    modes: list[ModeSpec]
    questions: list[QuestionSpec]


class QueryResultOut(BaseModel):
    id: uuid.UUID
    question_id: str
    question: str
    expected_answer: Optional[str] = None
    is_unanswerable: bool = False
    expected_source_documents: list[str] = []
    actual_answer: Optional[str] = None
    node_ids_visited: list[str] = []
    cited_doc_names: list[str] = []
    citation_count: int = 0
    citation_precision: Optional[float] = None
    citation_recall: Optional[float] = None
    latency_ms: Optional[float] = None
    faithfulness_score: Optional[float] = None
    faithfulness_reason: Optional[str] = None
    answer_relevancy_score: Optional[float] = None
    contextual_precision_score: Optional[float] = None
    contextual_recall_score: Optional[float] = None
    hallucination_score: Optional[float] = None
    overall_pass: Optional[bool] = None
    eval_model: Optional[str] = None
    eval_status: str
    refused_correctly: Optional[bool] = None
    error: Optional[str] = None

    model_config = {"from_attributes": True}


class ModeResultOut(BaseModel):
    id: uuid.UUID
    rag_mode: str
    retrieval_mode: Optional[str] = None
    kb_id: Optional[str] = None
    status: str
    documents_ingested: int
    documents_failed: int
    avg_ingestion_time_seconds: Optional[float] = None
    total_size_bytes: Optional[int] = None
    faithfulness_mean: Optional[float] = None
    answer_relevancy_mean: Optional[float] = None
    contextual_precision_mean: Optional[float] = None
    contextual_recall_mean: Optional[float] = None
    hallucination_mean: Optional[float] = None
    pass_rate: Optional[float] = None
    p50_latency_ms: Optional[float] = None
    p95_latency_ms: Optional[float] = None
    unanswerable_total: int = 0
    unanswerable_handled: int = 0
    unanswerable_handled_rate: Optional[float] = None
    citation_metrics_supported: bool = False
    citation_precision_mean: Optional[float] = None
    citation_recall_mean: Optional[float] = None
    error: Optional[str] = None
    query_results: list[QueryResultOut] = []

    model_config = {"from_attributes": True}


class RunOut(BaseModel):
    id: uuid.UUID
    name: str
    status: str
    dataset_source_type: str
    dataset_source_ref: str
    document_names: list[str] = []
    modes: list[dict]
    questions: list[dict]
    error: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None
    mode_results: list[ModeResultOut] = []

    model_config = {"from_attributes": True}


class RunSummary(BaseModel):
    id: uuid.UUID
    name: str
    status: str
    created_at: datetime
    completed_at: Optional[datetime] = None
    mode_count: int

    model_config = {"from_attributes": True}
