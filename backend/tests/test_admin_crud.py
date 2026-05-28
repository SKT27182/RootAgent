"""Admin CRUD role rules."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.db.models import User, UserRole
from app.routers import admin as admin_router


def test_user_role_values():
    assert UserRole.INFRA_ADMIN.value == "INFRA_ADMIN"
    assert UserRole.ADMIN.value == "ADMIN"
    assert UserRole.USER.value == "USER"


@pytest.mark.asyncio
async def test_create_user_rejects_admin_from_app_admin():
    """APP ADMIN cannot create ADMIN accounts."""
    current = User(
        id=uuid.uuid4(),
        email="admin@local.com",
        hashed_password="x",
        role=UserRole.ADMIN,
    )
    body = admin_router.AdminCreateUser(
        email="new@local.com",
        password="password123",
        role="ADMIN",
    )
    db = AsyncMock()

    with pytest.raises(HTTPException) as exc:
        await admin_router.create_user(body, db, current)

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_delete_user_rejects_admin_target_from_app_admin():
    """APP ADMIN cannot delete ADMIN accounts."""
    current = User(
        id=uuid.uuid4(),
        email="admin@local.com",
        hashed_password="x",
        role=UserRole.ADMIN,
    )
    target_id = uuid.uuid4()
    target = User(
        id=target_id,
        email="other@local.com",
        hashed_password="x",
        role=UserRole.ADMIN,
    )
    db = AsyncMock()
    db.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=lambda: target)
    )

    with pytest.raises(HTTPException) as exc:
        await admin_router.delete_user(target_id, db, current)

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_delete_user_rejects_infra_admin_target():
    current = User(
        id=uuid.uuid4(),
        email="infra@infra.local",
        hashed_password="x",
        role=UserRole.INFRA_ADMIN,
        infra_hub_user_id=1,
    )
    target_id = uuid.uuid4()
    target = User(
        id=target_id,
        email="linked@infra.local",
        hashed_password="x",
        role=UserRole.INFRA_ADMIN,
        infra_hub_user_id=2,
    )
    db = AsyncMock()
    db.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=lambda: target)
    )

    with pytest.raises(HTTPException) as exc:
        await admin_router.delete_user(target_id, db, current)

    assert exc.value.status_code == 403
