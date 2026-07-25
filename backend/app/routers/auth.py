"""Authentication endpoints."""

from datetime import datetime, timezone
import ipaddress
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
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
    WebSocketTicketResponse,
)
from app.core.config import settings
from app.services.auth_login import authenticate_user
from app.services.redis_store import RedisStore, get_redis_store
from app.utils.logger import create_logger
from app.core.metrics import RATE_LIMIT_REJECTIONS

logger = create_logger(__name__, level=settings.log_level)

router = APIRouter(prefix="/auth", tags=["Authentication"])


def _client_ip(request: Request) -> str:
    peer = request.client.host if request.client else "unknown"
    try:
        peer_address = ipaddress.ip_address(peer)
    except ValueError:
        return peer
    if not any(peer_address in network for network in settings.trusted_proxy_networks):
        return str(peer_address)
    forwarded = request.headers.get("X-Forwarded-For", "").split(",", 1)[0].strip()
    try:
        return str(ipaddress.ip_address(forwarded))
    except ValueError:
        return str(peer_address)


async def _enforce_rate_limit(
    redis_store: RedisStore,
    *,
    namespace: str,
    identity: str,
    limit: int,
    window_seconds: int,
) -> None:
    result = await redis_store.check_rate_limit(
        namespace,
        identity,
        limit=limit,
        window_seconds=window_seconds,
    )
    if not result.allowed:
        RATE_LIMIT_REJECTIONS.labels(namespace).inc()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests",
            headers={"Retry-After": str(result.retry_after_seconds)},
        )


@router.post(
    "/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED
)
async def register(
    user_data: UserRegister,
    request: Request,
    db: DbSession,
    redis_store: Annotated[RedisStore, Depends(get_redis_store)],
) -> User:
    """Register a RootAgent-local user (always USER role)."""
    await _enforce_rate_limit(
        redis_store,
        namespace="registration",
        identity=_client_ip(request),
        limit=settings.registration_rate_limit,
        window_seconds=settings.registration_rate_window_seconds,
    )
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
    request: Request,
    db: DbSession,
    redis_store: Annotated[RedisStore, Depends(get_redis_store)],
) -> Token:
    """
    Login with email/password.

    Infra-hub admins authenticate against main_db.users (read-only).
    RootAgent users authenticate against the rootagent database only.
    """
    await _enforce_rate_limit(
        redis_store,
        namespace="login",
        identity=_client_ip(request),
        limit=settings.login_rate_limit,
        window_seconds=settings.login_rate_window_seconds,
    )
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


@router.post("/ws-ticket", response_model=WebSocketTicketResponse)
async def create_ws_ticket(
    current_user: Annotated[User, Depends(get_current_active_user)],
    redis_store: Annotated[RedisStore, Depends(get_redis_store)],
) -> WebSocketTicketResponse:
    ticket, ttl = await redis_store.issue_ws_ticket(str(current_user.id))
    return WebSocketTicketResponse(ticket=ticket, expires_in=ttl)


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
