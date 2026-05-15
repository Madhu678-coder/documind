# Feature: documind-platform, Property 23: Rate Limiting Returns HTTP 429
"""
Property 23: For any user who sends more requests to the chat API than the configured
per-user rate limit within the rate window, all excess requests should receive HTTP 429.

Validates: Requirements 16.5
"""
import time
import uuid
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given, settings, strategies as st

from app.api.routes.chat import _check_rate_limit, _rate_limit_store
from app.core.config import settings as app_settings


# ── Helpers ───────────────────────────────────────────────────────────────────

def _clear_rate_limit(user_id: str) -> None:
    """Clear rate limit state for a user."""
    _rate_limit_store.pop(user_id, None)


# ── Property 23: Rate limiting ────────────────────────────────────────────────

def test_requests_within_limit_are_allowed():
    """Property 23: requests within the rate limit are not rejected."""
    from fastapi import HTTPException

    user_id = str(uuid.uuid4())
    _clear_rate_limit(user_id)

    # Should not raise for requests within limit
    for _ in range(min(5, app_settings.rate_limit_per_minute)):
        _check_rate_limit(user_id)  # no exception expected

    _clear_rate_limit(user_id)


def test_excess_requests_return_429():
    """Property 23: requests exceeding the rate limit raise HTTP 429."""
    from fastapi import HTTPException

    user_id = str(uuid.uuid4())
    _clear_rate_limit(user_id)

    # Fill up the rate limit
    limit = app_settings.rate_limit_per_minute
    for _ in range(limit):
        _check_rate_limit(user_id)

    # Next request should be rejected
    with pytest.raises(HTTPException) as exc_info:
        _check_rate_limit(user_id)

    assert exc_info.value.status_code == 429
    _clear_rate_limit(user_id)


def test_rate_limit_is_per_user():
    """Property 23: rate limit is tracked independently per user."""
    from fastapi import HTTPException

    user_a = str(uuid.uuid4())
    user_b = str(uuid.uuid4())
    _clear_rate_limit(user_a)
    _clear_rate_limit(user_b)

    limit = app_settings.rate_limit_per_minute

    # Exhaust user_a's limit
    for _ in range(limit):
        _check_rate_limit(user_a)

    # user_a is now rate limited
    with pytest.raises(HTTPException) as exc_info:
        _check_rate_limit(user_a)
    assert exc_info.value.status_code == 429

    # user_b should still be allowed
    _check_rate_limit(user_b)  # no exception

    _clear_rate_limit(user_a)
    _clear_rate_limit(user_b)


def test_rate_limit_window_resets_after_expiry():
    """Property 23: rate limit resets after the time window expires."""
    from fastapi import HTTPException

    user_id = str(uuid.uuid4())
    _clear_rate_limit(user_id)

    limit = app_settings.rate_limit_per_minute

    # Inject old timestamps (outside the 60s window)
    old_time = time.time() - 120  # 2 minutes ago
    _rate_limit_store[user_id] = [old_time] * limit

    # Should be allowed since all timestamps are expired
    _check_rate_limit(user_id)  # no exception

    _clear_rate_limit(user_id)


def test_rate_limit_error_message_is_descriptive():
    """Property 23: HTTP 429 response includes a descriptive detail message."""
    from fastapi import HTTPException

    user_id = str(uuid.uuid4())
    _clear_rate_limit(user_id)

    limit = app_settings.rate_limit_per_minute
    for _ in range(limit):
        _check_rate_limit(user_id)

    with pytest.raises(HTTPException) as exc_info:
        _check_rate_limit(user_id)

    assert "429" in str(exc_info.value.status_code)
    assert exc_info.value.detail  # non-empty detail

    _clear_rate_limit(user_id)


# ── Hypothesis property tests ─────────────────────────────────────────────────

@given(
    burst_size=st.integers(min_value=1, max_value=10),
)
@settings(max_examples=20)
def test_all_excess_requests_get_429(burst_size: int):
    """Property 23: every request beyond the limit receives HTTP 429."""
    from fastapi import HTTPException

    user_id = str(uuid.uuid4())
    _clear_rate_limit(user_id)

    limit = app_settings.rate_limit_per_minute

    # Fill up the limit
    for _ in range(limit):
        _check_rate_limit(user_id)

    # All excess requests must get 429
    for _ in range(burst_size):
        with pytest.raises(HTTPException) as exc_info:
            _check_rate_limit(user_id)
        assert exc_info.value.status_code == 429

    _clear_rate_limit(user_id)


@given(
    n_users=st.integers(min_value=2, max_value=5),
)
@settings(max_examples=10)
def test_rate_limit_isolation_across_users(n_users: int):
    """Property 23: exhausting one user's limit does not affect other users."""
    from fastapi import HTTPException

    user_ids = [str(uuid.uuid4()) for _ in range(n_users)]
    for uid in user_ids:
        _clear_rate_limit(uid)

    limit = app_settings.rate_limit_per_minute

    # Exhaust first user's limit
    for _ in range(limit):
        _check_rate_limit(user_ids[0])

    # First user is rate limited
    with pytest.raises(HTTPException):
        _check_rate_limit(user_ids[0])

    # All other users should still be allowed
    for uid in user_ids[1:]:
        _check_rate_limit(uid)  # no exception

    for uid in user_ids:
        _clear_rate_limit(uid)
