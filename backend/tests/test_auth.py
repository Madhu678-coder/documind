# Feature: documind-platform, Property 2: JWT Authentication Round Trip
import pytest
from hypothesis import given, settings, strategies as st
from fastapi import HTTPException

from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    ROLE_HIERARCHY,
)

# Strategies
user_id_strategy = st.text(min_size=1, max_size=50)
workspace_id_strategy = st.text(min_size=1, max_size=50)
role_strategy = st.sampled_from(["admin", "editor", "viewer"])


@given(user_id_strategy, workspace_id_strategy, role_strategy)
@settings(max_examples=100)
def test_access_token_round_trip(user_id: str, workspace_id: str, role: str):
    """create_access_token → decode_token preserves sub, workspace_id, role, and type."""
    token = create_access_token(user_id=user_id, workspace_id=workspace_id, role=role)
    payload = decode_token(token)

    assert payload["sub"] == user_id
    assert payload["workspace_id"] == workspace_id
    assert payload["role"] == role
    assert payload["type"] == "access"


@given(user_id_strategy)
@settings(max_examples=100)
def test_refresh_token_round_trip(user_id: str):
    """create_refresh_token → decode_token preserves sub and type=refresh."""
    token = create_refresh_token(user_id=user_id)
    payload = decode_token(token)

    assert payload["sub"] == user_id
    assert payload["type"] == "refresh"


@given(user_id_strategy)
@settings(max_examples=100)
def test_refresh_token_cannot_be_used_as_access_token(user_id: str):
    """A refresh token must not pass the type='access' check."""
    token = create_refresh_token(user_id=user_id)
    payload = decode_token(token)

    # The decoded payload must NOT have type='access'
    assert payload.get("type") != "access", (
        "Refresh token should not be accepted as an access token"
    )


@given(user_id_strategy, workspace_id_strategy, role_strategy)
@settings(max_examples=100)
def test_access_token_cannot_be_used_as_refresh_token(user_id: str, workspace_id: str, role: str):
    """An access token must not pass the type='refresh' check."""
    token = create_access_token(user_id=user_id, workspace_id=workspace_id, role=role)
    payload = decode_token(token)

    assert payload.get("type") != "refresh", (
        "Access token should not be accepted as a refresh token"
    )
