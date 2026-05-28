"""FastAPI dependencies for auth and database."""

import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import decode_access_token
from app.db.models import User, UserRole
from app.db.postgres import get_session
from app.utils.logger import create_logger

logger = create_logger(__name__, level=settings.log_level)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

DbSession = Annotated[AsyncSession, Depends(get_session)]


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: DbSession,
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    payload = decode_access_token(token)
    if payload is None:
        logger.debug("Auth rejected: invalid token")
        raise credentials_exception

    user_id_str: str | None = payload.get("sub")
    if user_id_str is None:
        logger.debug("Auth rejected: missing subject in token")
        raise credentials_exception

    try:
        user_uuid = uuid.UUID(user_id_str)
    except ValueError:
        logger.debug("Auth rejected: invalid user id in token")
        raise credentials_exception from None

    result = await db.execute(select(User).where(User.id == user_uuid))
    user = result.scalar_one_or_none()
    if user is None:
        logger.debug("Auth rejected: user not found")
        raise credentials_exception
    return user


async def get_current_active_user(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    return current_user


def is_infra_admin(user: User) -> bool:
    return user.role == UserRole.INFRA_ADMIN


def is_rootagent_admin(user: User) -> bool:
    """RootAgent-scoped admin (not infra-hub)."""
    return user.role == UserRole.ADMIN


def has_admin_access(user: User) -> bool:
    return user.role in (UserRole.INFRA_ADMIN, UserRole.ADMIN)


async def require_admin(
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> User:
    if not has_admin_access(current_user):
        logger.warning("Admin access denied for user %s", current_user.email)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )
    return current_user


async def require_infra_admin(
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> User:
    if not is_infra_admin(current_user):
        logger.warning("Infra admin required, denied for %s", current_user.email)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Infra-hub admin privileges required",
        )
    return current_user
