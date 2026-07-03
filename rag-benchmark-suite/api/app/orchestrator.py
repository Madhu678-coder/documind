"""Core benchmark runner — implements the methodology end to end.

For a given BenchmarkRun: for every rag_mode requested, create a fresh
KnowledgeBase in the real DocuMind app, upload the identical document set,
wait for async ingestion, ask the identical question set over chat, and poll
DocuMind's own DeepEval pipeline for scores. Nothing here scores anything
itself — it only orchestrates the existing app and aggregates what comes back,
so results stay consistent with what DocuMind reports in its own Eval Config
page.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.dataset import resolve_dataset
from app.documind_client import DocuMindAPIError, DocuMindClient
from app.models import BenchmarkRun, ModeResult, QueryResult
from app.schemas import CITATION_METRIC_MODES

logger = logging.getLogger(__name__)

_METRIC_FIELDS = (
    "faithfulness_score",
    "answer_relevancy_score",
    "contextual_precision_score",
    "contextual_recall_score",
    "hallucination_score",
)

# Matches DocuMind's own default hallucination_threshold (EvalConfig / metrics.py).
# Used as the "did it fabricate an answer instead of refusing" proxy for
# questions flagged as unanswerable.
_HALLUCINATION_THRESHOLD = 0.15


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    k = (len(ordered) - 1) * (pct / 100)
    f = int(k)
    c = min(f + 1, len(ordered) - 1)
    if f == c:
        return ordered[f]
    return ordered[f] + (ordered[c] - ordered[f]) * (k - f)


def _mode_label(rag_mode: str, retrieval_mode: str | None) -> str:
    return f"{rag_mode}:{retrieval_mode}" if retrieval_mode else rag_mode


def _normalize_doc_name(name: str) -> str:
    return name.strip().lower()


def _citation_precision_recall(
    expected: list[str], cited: list[str]
) -> tuple[float | None, float | None]:
    """Document-level precision/recall of cited filenames against an expected
    filename list. Only meaningful when doc_name is a real filename — callers
    must gate this on CITATION_METRIC_MODES themselves."""
    if not expected:
        return None, None
    expected_set = {_normalize_doc_name(n) for n in expected if n}
    cited_set = {_normalize_doc_name(n) for n in cited if n}
    true_positives = len(expected_set & cited_set)
    precision = true_positives / len(cited_set) if cited_set else 0.0
    recall = true_positives / len(expected_set) if expected_set else None
    return precision, recall


async def run_benchmark(run_id: uuid.UUID) -> None:
    settings = get_settings()

    async with AsyncSessionLocal() as db:
        run = (await db.execute(select(BenchmarkRun).where(BenchmarkRun.id == run_id))).scalar_one_or_none()
        if run is None:
            logger.error("run_benchmark: run %s not found", run_id)
            return

        run.status = "running"
        await db.commit()

        try:
            files: list[Path] = resolve_dataset(run.dataset_source_type, run.dataset_source_ref)
        except Exception as exc:
            run.status = "failed"
            run.error = f"Dataset resolution failed: {exc}"
            run.completed_at = datetime.utcnow()
            await db.commit()
            return

        run.document_names = [f.name for f in files]
        await db.commit()

        if not settings.documind_admin_email or not settings.documind_admin_password:
            run.status = "failed"
            run.error = (
                "BENCHMARK_DOCUMIND_ADMIN_EMAIL / BENCHMARK_DOCUMIND_ADMIN_PASSWORD are not "
                "configured — see .env.example. Credentials must never be pasted into the UI."
            )
            run.completed_at = datetime.utcnow()
            await db.commit()
            return

        try:
            client = DocuMindClient(
                settings.documind_api_base_url,
                settings.documind_admin_email,
                settings.documind_admin_password,
            )
            await client.login()
        except Exception as exc:
            run.status = "failed"
            run.error = f"Could not reach/authenticate to DocuMind API: {exc}"
            run.completed_at = datetime.utcnow()
            await db.commit()
            return

        run_token = uuid.uuid4().hex[:8]

        try:
            for mode_spec in run.modes:
                rag_mode = mode_spec["rag_mode"]
                retrieval_mode = mode_spec.get("retrieval_mode")
                label = _mode_label(rag_mode, retrieval_mode)

                mode_result = ModeResult(
                    run_id=run.id,
                    rag_mode=rag_mode,
                    retrieval_mode=retrieval_mode,
                    status="pending",
                    citation_metrics_supported=rag_mode in CITATION_METRIC_MODES,
                )
                db.add(mode_result)
                await db.commit()
                await db.refresh(mode_result)

                await _run_one_mode(db, client, run, mode_result, files, label, run_token, settings)

            run.status = "completed"
        except Exception as exc:
            logger.exception("run_benchmark: unexpected failure")
            run.status = "failed"
            run.error = str(exc)
        finally:
            run.completed_at = datetime.utcnow()
            await db.commit()
            await client.close()


async def _run_one_mode(
    db,
    client: DocuMindClient,
    run: BenchmarkRun,
    mode_result: ModeResult,
    files: list[Path],
    label: str,
    run_token: str,
    settings,
) -> None:
    try:
        kb_settings: dict = {"rag_mode": mode_result.rag_mode}
        if mode_result.retrieval_mode:
            kb_settings["retrieval_mode"] = mode_result.retrieval_mode

        kb = await client.create_kb(name=f"bench-{run_token}-{label}"[:60], settings=kb_settings)
        kb_id = kb["id"]
        mode_result.kb_id = kb_id
        mode_result.status = "ingesting"
        await db.commit()

        doc_ids: list[str] = []
        for file_path in files:
            try:
                doc = await client.upload_document(kb_id, file_path)
                doc_ids.append(doc["document_id"])
            except DocuMindAPIError as exc:
                logger.warning("upload failed for %s in mode %s: %s", file_path.name, label, exc)

        ready, failed, avg_seconds, total_bytes = await client.wait_for_documents_ready(
            doc_ids, settings.ingestion_timeout_seconds, settings.poll_interval_seconds
        )
        mode_result.documents_ingested = ready
        mode_result.documents_failed = failed
        mode_result.avg_ingestion_time_seconds = avg_seconds
        mode_result.total_size_bytes = total_bytes
        await db.commit()

        if ready == 0:
            raise RuntimeError("No documents reached 'ready' status for this mode — see documents_failed.")

        mode_result.status = "querying"
        await db.commit()

        session = await client.create_session(kb_id, title=f"benchmark-{label}")
        session_id = session["id"]

        latencies: list[float] = []
        metric_values: dict[str, list[float]] = {f: [] for f in _METRIC_FIELDS}
        pass_count = 0
        scored_count = 0
        unanswerable_total = 0
        unanswerable_handled = 0
        citation_precisions: list[float] = []
        citation_recalls: list[float] = []

        for question in run.questions:
            is_unanswerable = bool(question.get("is_unanswerable", False))
            expected_source_documents = question.get("expected_source_documents") or []
            qr = QueryResult(
                mode_result_id=mode_result.id,
                question_id=question["id"],
                question=question["question"],
                expected_answer=question.get("expected_answer"),
                is_unanswerable=is_unanswerable,
                expected_source_documents=expected_source_documents,
                eval_status="pending",
            )
            try:
                msg, latency_ms = await client.send_message(session_id, question["question"])
            except DocuMindAPIError as exc:
                qr.eval_status = "error"
                qr.error = str(exc)
                db.add(qr)
                await db.commit()
                continue

            citations = msg.get("citations") or []
            cited_doc_names = [c.get("doc_name") for c in citations if c.get("doc_name")]

            qr.actual_answer = msg.get("content")
            qr.node_ids_visited = msg.get("node_ids_visited") or []
            qr.cited_doc_names = cited_doc_names
            qr.citation_count = len(citations)
            qr.latency_ms = latency_ms
            latencies.append(latency_ms)

            if mode_result.citation_metrics_supported and expected_source_documents:
                precision, recall = _citation_precision_recall(expected_source_documents, cited_doc_names)
                qr.citation_precision = precision
                qr.citation_recall = recall
                if precision is not None:
                    citation_precisions.append(precision)
                if recall is not None:
                    citation_recalls.append(recall)

            eval_result = await client.poll_eval_result(
                str(msg["id"]), settings.eval_timeout_seconds, settings.poll_interval_seconds
            )
            if eval_result is not None:
                qr.faithfulness_score = eval_result.get("faithfulness_score")
                qr.faithfulness_reason = eval_result.get("faithfulness_reason")
                qr.answer_relevancy_score = eval_result.get("answer_relevancy_score")
                qr.contextual_precision_score = eval_result.get("contextual_precision_score")
                qr.contextual_recall_score = eval_result.get("contextual_recall_score")
                qr.hallucination_score = eval_result.get("hallucination_score")
                qr.overall_pass = eval_result.get("overall_pass")
                qr.eval_model = eval_result.get("eval_model")
                qr.eval_status = "scored"
                scored_count += 1
                if qr.overall_pass:
                    pass_count += 1
                for field in _METRIC_FIELDS:
                    value = eval_result.get(field)
                    if value is not None:
                        metric_values[field].append(value)

                if is_unanswerable:
                    unanswerable_total += 1
                    hallucination = eval_result.get("hallucination_score")
                    if hallucination is not None and hallucination <= _HALLUCINATION_THRESHOLD:
                        qr.refused_correctly = True
                        unanswerable_handled += 1
                    else:
                        qr.refused_correctly = False
            else:
                qr.eval_status = "timeout"

            db.add(qr)
            await db.commit()

        mode_result.p50_latency_ms = _percentile(latencies, 50)
        mode_result.p95_latency_ms = _percentile(latencies, 95)
        if scored_count:
            mode_result.faithfulness_mean = _avg(metric_values["faithfulness_score"])
            mode_result.answer_relevancy_mean = _avg(metric_values["answer_relevancy_score"])
            mode_result.contextual_precision_mean = _avg(metric_values["contextual_precision_score"])
            mode_result.contextual_recall_mean = _avg(metric_values["contextual_recall_score"])
            mode_result.hallucination_mean = _avg(metric_values["hallucination_score"])
            mode_result.pass_rate = pass_count / scored_count
        mode_result.unanswerable_total = unanswerable_total
        mode_result.unanswerable_handled = unanswerable_handled
        mode_result.unanswerable_handled_rate = (
            unanswerable_handled / unanswerable_total if unanswerable_total else None
        )
        mode_result.citation_precision_mean = _avg(citation_precisions)
        mode_result.citation_recall_mean = _avg(citation_recalls)
        mode_result.status = "completed"
        await db.commit()

    except Exception as exc:
        logger.exception("mode %s failed", label)
        mode_result.status = "failed"
        mode_result.error = str(exc)
        await db.commit()


def _avg(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None
