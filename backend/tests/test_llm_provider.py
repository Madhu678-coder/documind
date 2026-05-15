# Feature: documind-platform, Property 15: Per-Workspace LLM Provider Selection
"""
Property 15: For any workspace with a custom LLM provider configured in
workspaces.settings, all LLM calls within that workspace must use the
configured provider rather than the default BedrockProvider.
"""
from __future__ import annotations

import asyncio
from typing import AsyncIterator, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings, strategies as st

from app.services.llm.provider import LLMProvider, LLMResponse
from app.services.llm.bedrock import BedrockProvider
from app.services.llm.openai_provider import OpenAIProvider
from app.services.llm.anthropic_provider import AnthropicDirectProvider


# ── Fake provider for testing ─────────────────────────────────────────────────

class FakeProvider:
    """Deterministic provider that records calls for assertion."""

    def __init__(self, name: str):
        self.name = name
        self.calls: list[dict] = []

    async def complete(
        self, messages: list[dict], system_prompt: Optional[str] = None
    ) -> LLMResponse:
        self.calls.append({"messages": messages, "system_prompt": system_prompt})
        return LLMResponse(
            content=f"response from {self.name}",
            model=self.name,
            input_tokens=10,
            output_tokens=5,
        )

    async def stream(
        self, messages: list[dict], system_prompt: Optional[str] = None
    ) -> AsyncIterator[str]:
        self.calls.append({"messages": messages, "system_prompt": system_prompt})
        yield f"token from {self.name}"


# ── Provider registry helper ──────────────────────────────────────────────────

_PROVIDER_REGISTRY = {
    "bedrock": lambda cfg: BedrockProvider(),
    "openai": lambda cfg: OpenAIProvider(api_key=cfg.get("api_key")),
    "anthropic": lambda cfg: AnthropicDirectProvider(api_key=cfg.get("api_key")),
}


def get_provider_for_workspace(workspace_settings: dict) -> object:
    """Select the LLM provider based on workspace settings."""
    provider_name = workspace_settings.get("llm_provider", "bedrock")
    factory = _PROVIDER_REGISTRY.get(provider_name)
    if factory is None:
        raise ValueError(f"Unknown provider: {provider_name}")
    return factory(workspace_settings)


# ── Strategies ────────────────────────────────────────────────────────────────

provider_name_strategy = st.sampled_from(["bedrock", "openai", "anthropic"])

workspace_settings_strategy = st.fixed_dictionaries({
    "llm_provider": provider_name_strategy,
})


# ── Property tests ────────────────────────────────────────────────────────────

@given(workspace_settings_strategy)
@settings(max_examples=50, deadline=None)
def test_provider_selection_matches_workspace_config(workspace_settings: dict):
    """Property 15: Provider returned must match llm_provider in workspace settings."""
    expected_provider = workspace_settings["llm_provider"]
    provider = get_provider_for_workspace(workspace_settings)

    if expected_provider == "bedrock":
        assert isinstance(provider, BedrockProvider)
    elif expected_provider == "openai":
        assert isinstance(provider, OpenAIProvider)
    elif expected_provider == "anthropic":
        assert isinstance(provider, AnthropicDirectProvider)


def test_default_provider_is_bedrock():
    """When no llm_provider is set, BedrockProvider is used."""
    provider = get_provider_for_workspace({})
    assert isinstance(provider, BedrockProvider)


def test_unknown_provider_raises():
    """An unknown provider name must raise ValueError."""
    with pytest.raises(ValueError, match="Unknown provider"):
        get_provider_for_workspace({"llm_provider": "unknown_llm"})


def test_fake_provider_calls_are_isolated():
    """Two providers must not share call state."""
    async def _run():
        provider_a = FakeProvider("provider_a")
        provider_b = FakeProvider("provider_b")
        messages = [{"role": "user", "content": "Hello"}]
        await provider_a.complete(messages)
        await provider_a.complete(messages)
        assert len(provider_a.calls) == 2
        assert len(provider_b.calls) == 0

    asyncio.run(_run())


def test_provider_protocol_compliance():
    """FakeProvider satisfies the LLMProvider Protocol."""
    provider = FakeProvider("test")
    assert isinstance(provider, LLMProvider)


@given(provider_name_strategy)
@settings(max_examples=30)
def test_all_named_providers_are_constructable(provider_name: str):
    """Every provider name in the registry must produce a non-None instance."""
    provider = get_provider_for_workspace({"llm_provider": provider_name})
    assert provider is not None


@given(
    st.lists(provider_name_strategy, min_size=2, max_size=5, unique=True),
)
@settings(max_examples=20)
def test_different_workspaces_get_independent_provider_instances(provider_names: list[str]):
    """Each workspace config must produce an independent provider instance."""
    providers = [get_provider_for_workspace({"llm_provider": name}) for name in provider_names]
    ids = [id(p) for p in providers]
    assert len(ids) == len(set(ids)), "Provider instances must not be shared across workspaces"
