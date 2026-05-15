# Feature: documind-platform, Property 21: Health Endpoints Reflect Actual Service State
import pytest
import anyio
from hypothesis import given, settings, strategies as st
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport
from app.main import app


async def _get(path: str) -> int:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(path)
        return response.status_code


# --- /health always returns 200 ---

def test_health_always_ok():
    status = anyio.run(_get, "/health")
    assert status == 200


# --- /health/db reflects DB state ---

@given(st.booleans())
@settings(max_examples=100)
def test_health_db_reflects_state(db_healthy: bool):
    async def run():
        if db_healthy:
            mock_execute = AsyncMock(return_value=MagicMock())
        else:
            mock_execute = AsyncMock(side_effect=Exception("DB down"))

        mock_session = AsyncMock()
        mock_session.execute = mock_execute

        async def override_get_db():
            yield mock_session

        from app.core.database import get_db
        app.dependency_overrides[get_db] = override_get_db
        try:
            status = await _get("/health/db")
        finally:
            app.dependency_overrides.pop(get_db, None)

        if db_healthy:
            assert status == 200
        else:
            assert status == 503

    anyio.run(run)


# --- /health/redis reflects Redis state ---

@given(st.booleans())
@settings(max_examples=100)
def test_health_redis_reflects_state(redis_healthy: bool):
    async def run():
        mock_redis = AsyncMock()
        if redis_healthy:
            mock_redis.ping = AsyncMock(return_value=True)
        else:
            mock_redis.ping = AsyncMock(side_effect=Exception("Redis down"))
        mock_redis.aclose = AsyncMock()

        with patch("app.api.routes.health.aioredis.from_url", return_value=mock_redis):
            status = await _get("/health/redis")

        if redis_healthy:
            assert status == 200
        else:
            assert status == 503

    anyio.run(run)
