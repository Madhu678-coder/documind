"""
LLM provider factory — resolves the workspace's configured default LLM provider.

Usage:
    llm = await get_llm_provider(workspace_id, db)
    response = await llm.complete(messages)

Fallback chain when no workspace config is found:
    BedrockProvider() with the default cross-region inference profile.

Supported provider_name values in ModelProviderConfig:
    bedrock    — AWS Bedrock (no API key needed; uses IAM / SSO credentials)
    openai     — OpenAI chat completions
    anthropic  — Anthropic direct (messages API, OpenAI-SDK compatible)
    deepseek   — DeepSeek (OpenAI-compatible, api.deepseek.com)
    grok       — xAI Grok   (OpenAI-compatible, api.x.ai)
    gemini     — Google Gemini (google-genai SDK)
"""
from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.llm.provider import LLMProvider

logger = logging.getLogger(__name__)

# Provider names that use the OpenAI-compatible SDK
_OPENAI_COMPAT = {"openai", "deepseek", "grok", "anthropic"}


async def get_llm_provider(
    workspace_id: uuid.UUID,
    db: AsyncSession,
) -> LLMProvider:
    """
    Return the default LLM provider for the given workspace.

    Queries ModelProviderConfig for the row where
    provider_type='llm' and is_default=True, then instantiates
    the matching provider class.  Falls back to BedrockProvider()
    if no config exists.
    """
    from app.models.model_provider import ModelProviderConfig

    result = await db.execute(
        select(ModelProviderConfig).where(
            ModelProviderConfig.workspace_id == workspace_id,
            ModelProviderConfig.provider_type == "llm",
            ModelProviderConfig.is_default == True,
        )
    )
    config = result.scalar_one_or_none()

    if config is None:
        logger.debug("No default LLM provider configured, using Bedrock fallback")
        from app.services.llm.bedrock import BedrockProvider
        return BedrockProvider()

    return _instantiate(config.provider_name, config.model_id, config.api_key, config.region)


def _instantiate(
    provider_name: str,
    model_id: str,
    api_key: str | None,
    region: str | None,
) -> LLMProvider:
    """Instantiate the correct provider class from stored config."""

    if provider_name == "bedrock":
        from app.services.llm.bedrock import BedrockProvider
        return BedrockProvider(model=model_id)

    if provider_name == "gemini":
        from app.services.llm.gemini_provider import GeminiProvider
        return GeminiProvider(model=model_id, api_key=api_key)

    if provider_name in _OPENAI_COMPAT:
        from app.services.llm.openai_compat import OpenAICompatProvider
        if not api_key:
            raise ValueError(f"API key is required for provider '{provider_name}'")
        return OpenAICompatProvider.from_provider_name(
            provider_name=provider_name,
            model=model_id,
            api_key=api_key,
        )

    # Unknown provider — log and fall back to Bedrock
    logger.warning(
        "Unknown LLM provider name '%s', falling back to Bedrock", provider_name
    )
    from app.services.llm.bedrock import BedrockProvider
    return BedrockProvider()
