"""Authentication endpoints."""

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select

from app.core.dependencies import DbSession, get_current_active_user
from app.core.security import create_access_token, get_password_hash, verify_password
from app.db.models import User, UserRole
from app.schemas.auth import (
    PasswordChange,
    ProfileUpdate,
    Token,
    UserRegister,
    UserResponse,
)
from app.core.config import settings
from app.services.auth_login import authenticate_user
from app.utils.logger import create_logger

logger = create_logger(__name__, level=settings.log_level)

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED
)
async def register(
    user_data: UserRegister,
    db: DbSession,
) -> User:
    """Register a RootAgent-local user (always USER role)."""
    result = await db.execute(select(User).where(User.email == user_data.email))
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    user = User(
        email=user_data.email,
        name=user_data.name.strip(),
        hashed_password=get_password_hash(user_data.password),
        role=UserRole.USER,
        infra_hub_user_id=None,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    logger.info("User registered: %s", user_data.email)
    return user


@router.post("/login", response_model=Token)
async def login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: DbSession,
) -> Token:
    """
    Login with email/password.

    Infra-hub admins authenticate against main_db.users (read-only).
    RootAgent users authenticate against the rootagent database only.
    """
    user = await authenticate_user(db, form_data.username, form_data.password)
    if not user:
        logger.debug("Login failed for %s", form_data.username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(
        data={"sub": str(user.id), "role": user.role.value}
    )
    logger.info("User logged in: %s (%s)", user.email, user.role.value)
    return Token(access_token=access_token)


@router.get("/me", response_model=UserResponse)
async def get_me(
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> User:
    return current_user


@router.patch("/me/profile", response_model=UserResponse)
async def update_profile(
    body: ProfileUpdate,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: DbSession,
) -> User:
    if current_user.infra_hub_user_id is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Infra-hub linked accounts must update name in Infra Hub",
        )
    current_user.name = body.name.strip()
    current_user.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(current_user)
    logger.info("Profile updated for user %s", current_user.email)
    return current_user


@router.post("/me/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    body: PasswordChange,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: DbSession,
) -> None:
    if current_user.infra_hub_user_id is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Infra-hub linked accounts must change password in Infra Hub",
        )
    if not verify_password(body.current_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )
    current_user.hashed_password = get_password_hash(body.new_password)
    current_user.updated_at = datetime.now(timezone.utc)
    await db.commit()
    logger.info("Password changed for user %s", current_user.email)
