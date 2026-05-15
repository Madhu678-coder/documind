from __future__ import annotations

import os
import uuid
from datetime import datetime
from typing import AsyncIterator, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from hypothesis import HealthCheck, settings

# Set required env vars before importing the app so Settings() can initialize
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("CELERY_BROKER_URL", "redis://localhost:6379/0")
os.environ.setdefault("CELERY_RESULT_BACKEND", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests-only")

# ── Hypothesis profiles ───────────────────────────────────────────────────────

settings.register_profile(
    "default",
    max_examples=100,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
settings.register_profile("ci", max_examples=100, deadline=None)
settings.register_profile("fast", max_examples=10)
settings.load_profile("default")


# ── Mock LLM provider ─────────────────────────────────────────────────────────

class MockLLMProvider:
    """Deterministic mock LLM that returns fixed responses for testing."""

    def __init__(self, response_content: str = "Mock LLM response."):
        self.response_content = response_content
        self.calls: list[dict] = []

    async def complete(self, messages: list[dict], system_prompt: Optional[str] = None):
        from app.services.llm.provider import LLMResponse

        self.calls.append({"messages": messages, "system_prompt": system_prompt})
        return LLMResponse(
            content=self.response_content,
            model="mock-model",
            input_tokens=10,
            output_tokens=5,
        )

    async def stream(self, messages: list[dict], system_prompt: Optional[str] = None):
        self.calls.append({"messages": messages, "system_prompt": system_prompt})
        for token in self.response_content.split():
            yield token


@pytest.fixture
def mock_llm():
    """Returns a deterministic mock LLM provider."""
    return MockLLMProvider()


# ── Test workspace and user factories ─────────────────────────────────────────

def make_test_workspace(workspace_id: Optional[uuid.UUID] = None, name: str = "Test Workspace"):
    """Create a mock workspace object."""
    ws = MagicMock()
    ws.id = workspace_id or uuid.uuid4()
    ws.name = name
    ws.owner_id = uuid.uuid4()
    ws.settings = {}
    return ws


def make_test_user(
    workspace_id: Optional[uuid.UUID] = None,
    role: str = "editor",
    user_id: Optional[uuid.UUID] = None,
):
    """Create a mock user object."""
    user = MagicMock()
    user.id = user_id or uuid.uuid4()
    user.workspace_id = workspace_id or uuid.uuid4()
    user.role = role
    user.email = f"user-{user.id}@example.com"
    user.name = "Test User"
    user.created_at = datetime.utcnow()
    return user


@pytest.fixture
def test_workspace():
    """Fixture providing a test workspace."""
    return make_test_workspace()


@pytest.fixture
def test_user(test_workspace):
    """Fixture providing a test user in the test workspace."""
    return make_test_user(workspace_id=test_workspace.id)


@pytest.fixture
def admin_user(test_workspace):
    """Fixture providing an admin user in the test workspace."""
    return make_test_user(workspace_id=test_workspace.id, role="admin")


# ── Mock database session ─────────────────────────────────────────────────────

@pytest.fixture
def mock_db():
    """Returns a mock async SQLAlchemy session."""
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.delete = AsyncMock()
    db.flush = AsyncMock()
    db.rollback = AsyncMock()
    return db


# ── AsyncClient test client ───────────────────────────────────────────────────

@pytest_asyncio.fixture
async def async_client():
    """Returns an httpx AsyncClient wired to the FastAPI app."""
    from httpx import AsyncClient, ASGITransport
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
