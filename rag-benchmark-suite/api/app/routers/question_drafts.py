"""On-demand LLM-assisted draft question generation — used by the New Run page
before a real benchmark run is submitted. See app/question_gen.py for how the
draft LLM call is made without this suite needing its own AWS/LLM credentials."""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException, status

from app import dataset
from app.question_gen import QuestionGenError, generate_question_drafts
from app.schemas import QuestionDraftOut, QuestionDraftRequest, QuestionDraftResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/question-drafts", tags=["question-drafts"])


@router.post("", response_model=QuestionDraftResponse)
async def create_question_drafts(body: QuestionDraftRequest) -> QuestionDraftResponse:
    try:
        files = await asyncio.to_thread(
            dataset.resolve_dataset, body.dataset_source_type, body.dataset_source_ref
        )
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    try:
        drafts = await generate_question_drafts(files, body.count)
    except QuestionGenError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    return QuestionDraftResponse(
        document_names=[f.name for f in files],
        questions=[QuestionDraftOut(**d) for d in drafts],
    )
