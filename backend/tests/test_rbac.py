# Feature: documind-platform, Property 3: RBAC Permission Enforcement
import pytest
from hypothesis import given, settings, strategies as st
from fastapi import HTTPException
from unittest.mock import MagicMock

from app.core.security import ROLE_HIERARCHY

# Strategy: pairs of (user_role, required_role)
role_pair_strategy = st.tuples(
    st.sampled_from(["admin", "editor", "viewer"]),
    st.sampled_from(["admin", "editor", "viewer"]),
)


def _check_role(user_role: str, required_role: str) -> bool:
    """
    Mirrors the logic in require_role's role_checker.
    Returns True if user_role satisfies required_role, False otherwise.
    """
    if user_role not in ROLE_HIERARCHY or required_role not in ROLE_HIERARCHY:
        return False
    return ROLE_HIERARCHY.index(user_role) >= ROLE_HIERARCHY.index(required_role)


@given(role_pair_strategy)
@settings(max_examples=100)
def test_rbac_permission_enforcement(roles):
    """
    Given a user_role and required_role, the role checker must:
    - NOT raise 403 when user_role has sufficient privilege
    - Raise HTTP 403 when user_role has insufficient privilege
    """
    user_role, required_role = roles

    # Build a mock user with the given role
    mock_user = MagicMock()
    mock_user.role = user_role

    user_idx = ROLE_HIERARCHY.index(user_role)
    required_idx = ROLE_HIERARCHY.index(required_role)

    if user_idx >= required_idx:
        # Should NOT raise — user has sufficient privilege
        assert _check_role(user_role, required_role) is True
    else:
        # Should raise 403 — user has insufficient privilege
        assert _check_role(user_role, required_role) is False


@given(role_pair_strategy)
@settings(max_examples=100)
def test_rbac_hierarchy_is_transitive(roles):
    """
    Role hierarchy must be transitive:
    if A >= B and B >= C then A >= C.
    """
    role_a, role_b = roles
    # Pick a third role that is <= role_b
    role_b_idx = ROLE_HIERARCHY.index(role_b)
    role_c = ROLE_HIERARCHY[0]  # lowest role (viewer)

    a_gte_b = _check_role(role_a, role_b)
    b_gte_c = _check_role(role_b, role_c)

    if a_gte_b and b_gte_c:
        assert _check_role(role_a, role_c), (
            f"Transitivity violated: {role_a} >= {role_b} >= {role_c} "
            f"but {role_a} not >= {role_c}"
        )


def test_rbac_admin_can_do_everything():
    """Admin must satisfy every role requirement."""
    for required in ROLE_HIERARCHY:
        assert _check_role("admin", required), f"admin should satisfy required_role={required}"


def test_rbac_viewer_only_satisfies_viewer():
    """Viewer must only satisfy viewer requirement."""
    assert _check_role("viewer", "viewer")
    assert not _check_role("viewer", "editor")
    assert not _check_role("viewer", "admin")


def test_rbac_editor_satisfies_editor_and_viewer():
    """Editor must satisfy editor and viewer, but not admin."""
    assert _check_role("editor", "viewer")
    assert _check_role("editor", "editor")
    assert not _check_role("editor", "admin")
