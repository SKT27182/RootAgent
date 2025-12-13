from fastapi import APIRouter, HTTPException, Depends, Header
from typing import Optional
from functools import lru_cache
from backend.app.models.user import UserCreate, UserLogin, Token, User
from backend.app.services.auth_service import AuthService
from backend.app.core.config import Config
from backend.app.utils.logger import create_logger

router = APIRouter(prefix="/auth", tags=["Authentication"])
logger = create_logger(__name__, level=Config.LOG_LEVEL)


@lru_cache()
def get_auth_service():
    return AuthService()


async def get_current_user(
    authorization: Optional[str] = Header(None),
    auth_service: AuthService = Depends(get_auth_service),
) -> User:
    """Dependency to get the current authenticated user from JWT token"""
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header missing")

    # Extract token from "Bearer <token>" format
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=401, detail="Invalid authorization header format"
        )

    token = parts[1]
    token_data = auth_service.decode_token(token)

    if not token_data:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user = await auth_service.get_user_by_id(token_data.user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    return user


@router.post("/register", response_model=Token)
async def register(
    user_data: UserCreate,
    auth_service: AuthService = Depends(get_auth_service),
):
    """Register a new user"""
    logger.info(f"Registration attempt for username: {user_data.username}")

    user = await auth_service.create_user(user_data)
    if not user:
        raise HTTPException(status_code=400, detail="Username already exists")

    # Create token for the new user
    access_token = auth_service.create_access_token(user.user_id, user.username)

    logger.info(f"User registered successfully: {user.username}")
    return Token(
        access_token=access_token,
        user_id=user.user_id,
        username=user.username,
    )


@router.post("/login", response_model=Token)
async def login(
    credentials: UserLogin,
    auth_service: AuthService = Depends(get_auth_service),
):
    """Login and receive a JWT token"""
    logger.info(f"Login attempt for username: {credentials.username}")

    user = await auth_service.authenticate_user(
        credentials.username, credentials.password
    )
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password")

    access_token = auth_service.create_access_token(user.user_id, user.username)

    logger.info(f"User logged in successfully: {user.username}")
    return Token(
        access_token=access_token,
        user_id=user.user_id,
        username=user.username,
    )


@router.get("/me")
async def get_me(current_user: User = Depends(get_current_user)):
    """Get current user info from JWT token"""
    return {
        "user_id": current_user.user_id,
        "username": current_user.username,
        "email": current_user.email,
        "created_at": current_user.created_at.isoformat(),
    }
