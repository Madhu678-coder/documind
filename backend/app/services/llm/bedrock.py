"""AWS Bedrock LLM provider using Claude Sonnet 4.5."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator

import boto3
from botocore.exceptions import ClientError

from app.core.config import settings
from app.services.llm.provider import LLMProvider, LLMResponse

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
_MAX_RETRIES = 3
_RETRYABLE_ERRORS = {"ThrottlingException", "ModelNotReadyException", "ServiceUnavailableException"}


def _build_client():
    """Build a boto3 bedrock-runtime client using the correct credential chain."""
    session_kwargs: dict = {}
    if settings.aws_profile:
        # Local dev: use named SSO profile from ~/.aws/config
        session_kwargs["profile_name"] = settings.aws_profile
    # Production: no profile → boto3 falls back to EC2 instance role via IMDS
    session = boto3.Session(**session_kwargs)
    return session.client("bedrock-runtime", region_name=settings.aws_bedrock_region)


class BedrockProvider:
    """
    Default LLMProvider backed by AWS Bedrock (Claude Sonnet 4.5).

    Credential chain:
    - Local dev: AWS_PROFILE env var → SSO short-lived tokens via ~/.aws
    - Production: EC2 instance role via IMDS (no static credentials)
    """

    def __init__(self, model: str = _DEFAULT_MODEL):
        self.model = model
        self._client = _build_client()

    def _build_body(self, messages: list[dict], system_prompt: str | None, max_tokens: int = 4096) -> dict:
        body: dict = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if system_prompt:
            body["system"] = system_prompt
        return body

    async def complete(
        self,
        messages: list[dict],
        system_prompt: str | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        body = self._build_body(messages, system_prompt, max_tokens=max_tokens or 4096)
        response_body = await self._invoke_with_retry(body)
        content = response_body["content"][0]["text"]
        usage = response_body.get("usage", {})
        return LLMResponse(
            content=content,
            model=self.model,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
        )

    async def stream(
        self,
        messages: list[dict],
        system_prompt: str | None = None,
    ) -> AsyncIterator[str]:
        body = self._build_body(messages, system_prompt)
        body_bytes = json.dumps(body).encode()

        for attempt in range(_MAX_RETRIES):
            try:
                response = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self._client.invoke_model_with_response_stream(
                        modelId=self.model,
                        body=body_bytes,
                        contentType="application/json",
                        accept="application/json",
                    ),
                )
                async for chunk in self._iter_stream(response):
                    yield chunk
                return
            except ClientError as exc:
                error_code = exc.response["Error"]["Code"]
                if error_code in _RETRYABLE_ERRORS and attempt < _MAX_RETRIES - 1:
                    wait = (2 ** attempt) * 1.0
                    logger.warning("Bedrock stream throttled, retrying", extra={"attempt": attempt, "wait": wait})
                    await asyncio.sleep(wait)
                else:
                    raise

    async def _iter_stream(self, response) -> AsyncIterator[str]:
        stream = response.get("body")
        for event in stream:
            chunk = event.get("chunk")
            if chunk:
                data = json.loads(chunk["bytes"].decode())
                if data.get("type") == "content_block_delta":
                    delta = data.get("delta", {})
                    if delta.get("type") == "text_delta":
                        yield delta.get("text", "")

    async def _invoke_with_retry(self, body: dict) -> dict:
        body_bytes = json.dumps(body).encode()
        last_exc: Exception | None = None

        for attempt in range(_MAX_RETRIES):
            try:
                response = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self._client.invoke_model(
                        modelId=self.model,
                        body=body_bytes,
                        contentType="application/json",
                        accept="application/json",
                    ),
                )
                return json.loads(response["body"].read())
            except ClientError as exc:
                error_code = exc.response["Error"]["Code"]
                last_exc = exc
                if error_code in _RETRYABLE_ERRORS and attempt < _MAX_RETRIES - 1:
                    wait = (2 ** attempt) * 1.0
                    logger.warning(
                        "Bedrock invocation retryable error",
                        extra={"attempt": attempt, "error_code": error_code, "wait": wait},
                    )
                    await asyncio.sleep(wait)
                else:
                    raise

        raise last_exc  # type: ignore[misc]
