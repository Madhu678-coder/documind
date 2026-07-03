"""LLM-assisted draft question generation for a benchmark run.

This suite deliberately never talks to Bedrock/OpenAI/Anthropic directly (see
config.py's module docstring) — every LLM call lives inside the main DocuMind
backend. To draft a question set here without duplicating that logic, we reuse
DocuMind's own chat pipeline: create a throwaway pageindex KB, upload the
dataset, wait for ingestion, ask one chat message that instructs the model to
propose a JSON question set, parse the response, then delete the scratch KB.

This is a starting point, not a black box — the New Run page shows every draft
for the user to edit or remove before a real benchmark run is submitted.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from pathlib import Path

from app.config import get_settings
from app.documind_client import DocuMindAPIError, DocuMindClient

logger = logging.getLogger(__name__)

_JSON_ARRAY_RE = re.compile(r"\[.*\]", re.DOTALL)
_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


class QuestionGenError(RuntimeError):
    """Raised for any failure in the draft-generation flow — dataset issues,
    DocuMind API errors, or an unparseable model response — with a message
    safe to surface directly in the New Run page."""


def _build_prompt(doc_names: list[str], count: int) -> str:
    doc_list = "\n".join(f"- {name}" for name in doc_names)
    return f"""You are helping build a test set for a RAG benchmark. The knowledge base
you can see contains exactly these source documents:
{doc_list}

Propose {count} test questions covering a realistic mix:
- Most should be answerable directly from one document (fact lookup).
- If there is more than one document, include at least one question that
  requires synthesizing information across two or more documents.
- Include exactly 1-2 questions that sound plausible but are NOT answerable
  from these documents at all (e.g. a topic adjacent to but not covered by the
  content) — mark these with "is_unanswerable": true and leave
  "expected_answer" as an empty string.

Respond with ONLY a raw JSON array (no prose, no markdown code fences) where
each element has exactly these keys:
  "question": string
  "expected_answer": string (a short factual answer; empty string if is_unanswerable)
  "is_unanswerable": boolean
  "expected_source_documents": array of filenames drawn ONLY from the list above
    (empty array if is_unanswerable)

Every filename in "expected_source_documents" must be copied exactly,
character for character, from the list above."""


def _extract_json_array(raw_text: str) -> list[dict]:
    text = _FENCE_RE.sub("", raw_text.strip()).strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed
    except json.JSONDecodeError:
        pass

    match = _JSON_ARRAY_RE.search(raw_text)
    if match:
        try:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass

    raise QuestionGenError(
        "DocuMind's response wasn't valid JSON, so no draft questions could be "
        f"parsed. Raw response started with: {raw_text[:300]!r}"
    )


async def generate_question_drafts(files: list[Path], count: int, run_token: str | None = None) -> list[dict]:
    """Create a scratch pageindex KB from `files`, ask DocuMind's own chat
    pipeline to draft `count` benchmark questions, then delete the scratch KB.

    Returns a list of dicts shaped like QuestionSpec minus `id` (the caller
    assigns ids). Raises QuestionGenError on any failure; always attempts to
    clean up the scratch KB regardless of outcome."""
    settings = get_settings()
    if not (settings.documind_admin_email and settings.documind_admin_password):
        raise QuestionGenError(
            "BENCHMARK_DOCUMIND_ADMIN_EMAIL / BENCHMARK_DOCUMIND_ADMIN_PASSWORD are not "
            "configured — question generation logs into DocuMind the same way a real run does."
        )
    if not files:
        raise QuestionGenError("No dataset files were resolved — nothing to generate questions from.")

    doc_names = [f.name for f in files]
    token = run_token or uuid.uuid4().hex[:8]
    kb_id: str | None = None

    client = DocuMindClient(
        settings.documind_api_base_url,
        settings.documind_admin_email,
        settings.documind_admin_password,
    )
    try:
        await client.login()

        kb = await client.create_kb(name=f"bench-qgen-{token}", settings={"rag_mode": "pageindex"})
        kb_id = kb["id"]

        doc_ids = []
        for path in files:
            doc = await client.upload_document(kb_id, path)
            doc_ids.append(doc["id"])

        ready, failed, _avg, _bytes = await client.wait_for_documents_ready(
            doc_ids,
            timeout_seconds=settings.question_gen_ingestion_timeout_seconds,
            poll_interval_seconds=settings.poll_interval_seconds,
        )
        if ready == 0:
            raise QuestionGenError(
                f"None of the {len(doc_ids)} document(s) finished ingesting in time "
                f"({failed} failed/timed out) — can't draft questions from them yet. "
                "Try again once ingestion is faster, or generate against a smaller dataset."
            )

        session = await client.create_session(kb_id, title="benchmark-question-generation")
        prompt = _build_prompt(doc_names, count)
        message, _latency = await client.send_message(session["id"], prompt)
        raw_content = message.get("content") or ""
        drafts = _extract_json_array(raw_content)

        results: list[dict] = []
        for item in drafts:
            if not isinstance(item, dict) or not str(item.get("question") or "").strip():
                continue
            expected_sources = [
                d for d in (item.get("expected_source_documents") or []) if d in doc_names
            ]
            results.append(
                {
                    "question": str(item["question"]).strip(),
                    "expected_answer": str(item.get("expected_answer") or "").strip(),
                    "is_unanswerable": bool(item.get("is_unanswerable", False)),
                    "expected_source_documents": expected_sources,
                }
            )

        if not results:
            raise QuestionGenError(
                "DocuMind's response parsed as JSON but contained no usable question "
                "objects — try again, or lower the requested count."
            )
        return results
    except DocuMindAPIError as exc:
        raise QuestionGenError(f"DocuMind API error while generating questions: {exc}") from exc
    finally:
        if kb_id:
            try:
                await client.delete_kb(kb_id)
            except Exception:
                logger.warning("Failed to clean up scratch KB %s after question generation", kb_id)
        await client.close()
