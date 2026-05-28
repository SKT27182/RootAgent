"""RootAgent-scoped admin endpoints.

Hierarchy: INFRA_ADMIN (main_db) > ADMIN (RootAgent-only) > USER
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select

from app.core.dependencies import (
    DbSession,
    is_infra_admin,
    require_admin,
    require_infra_admin,
)
from app.core.security import get_password_hash
from app.db.models import User, UserRole
from app.core.config import settings
from app.schemas.auth import UserResponse
from app.utils.logger import create_logger

logger = create_logger(__name__, level=settings.log_level)

router = APIRouter(prefix="/admin", tags=["Admin"])


class AdminCreateUser(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    role: str = Field(default="USER", pattern="^(ADMIN|USER)$")


@router.get("/users", response_model=list[UserResponse])
async def list_users(
    db: DbSession,
    current_user: Annotated[User, Depends(require_admin)],
) -> list[User]:
    _ = current_user
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    return list(result.scalars().all())


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    user_data: AdminCreateUser,
    db: DbSession,
    current_user: Annotated[User, Depends(require_admin)],
) -> User:
    """Create a new user. Only infra-hub admins may create ADMIN accounts."""
    if user_data.role == "ADMIN" and not is_infra_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only infra-hub admins can create administrator accounts",
        )

    result = await db.execute(select(User).where(User.email == user_data.email))
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    user = User(
        email=user_data.email,
        hashed_password=get_password_hash(user_data.password),
        role=UserRole(user_data.role),
        infra_hub_user_id=None,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    logger.info("Admin created user: %s role=%s", user.email, user.role.value)
    return user


@router.patch("/users/{user_id}/role", response_model=UserResponse)
async def set_user_role(
    user_id: uuid.UUID,
    role: UserRole,
    db: DbSession,
    _: Annotated[User, Depends(require_infra_admin)],
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
    logger.info("User role updated: %s -> %s", target.email, role.value)
    return target


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: uuid.UUID,
    db: DbSession,
    current_user: Annotated[User, Depends(require_admin)],
) -> None:
    """Delete a user. Infra admins may delete ADMIN/USER; RootAgent admins only USER."""
    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    if is_infra_admin(target):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot delete infra-hub admin accounts from RootAgent",
        )

    if target.role == UserRole.ADMIN and not is_infra_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only infra-hub admins can delete administrator accounts",
        )

    if target.id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")

    await db.delete(target)
    await db.commit()
    logger.info("User deleted: %s", target.email)
