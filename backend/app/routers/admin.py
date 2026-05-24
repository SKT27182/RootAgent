"""RootAgent-scoped admin endpoints.

Hierarchy: INFRA_ADMIN (main_db) > ADMIN (RootAgent-only) > USER
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.core.dependencies import (
    DbSession,
    is_infra_admin,
    require_admin,
    require_infra_admin,
)
from app.db.models import User, UserRole
from app.schemas.auth import UserResponse

router = APIRouter(prefix="/admin", tags=["Admin"])


@router.get("/users", response_model=list[UserResponse])
async def list_users(
    db: DbSession,
    current_user: Annotated[User, Depends(require_admin)],
) -> list[User]:
    _ = current_user
    result = await db.execute(select(User).order_by(User.created_at))
    return list(result.scalars().all())


@router.patch("/users/{user_id}/role", response_model=UserResponse)
async def set_user_role(
    user_id: uuid.UUID,
    role: UserRole,
    db: DbSession,
    current_user: Annotated[User, Depends(require_infra_admin)],
) -> User:
    """Infra-hub admins may promote/demote between USER and ADMIN only."""
    if role not in (UserRole.USER, UserRole.ADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Can only assign USER or ADMIN roles",
        )

    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    if is_infra_admin(target):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot modify infra-hub admin accounts",
        )

    target.role = role
    await db.commit()
    await db.refresh(target)
    return target


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: uuid.UUID,
    db: DbSession,
    current_user: Annotated[User, Depends(require_infra_admin)],
) -> None:
    """Infra-hub admins may delete RootAgent-local ADMIN and USER accounts."""
    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    if is_infra_admin(target):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot delete infra-hub admin accounts from RootAgent",
        )

    if target.id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")

    await db.delete(target)
    await db.commit()
