import uuid
from typing import Optional
from pydantic import BaseModel, Field, EmailStr
from datetime import datetime


class User(BaseModel):
    """User model stored in Redis"""

    user_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    username: str
    email: str
    hashed_password: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class UserCreate(BaseModel):
    """Schema for user registration"""

    username: str = Field(min_length=3, max_length=50)
    email: str
    password: str = Field(min_length=6)


class UserLogin(BaseModel):
    """Schema for user login"""

    username: str
    password: str


class Token(BaseModel):
    """JWT token response"""

    access_token: str
    token_type: str = "bearer"
    user_id: str
    username: str


class TokenData(BaseModel):
    """Data encoded in JWT token"""

    user_id: str
    username: str
