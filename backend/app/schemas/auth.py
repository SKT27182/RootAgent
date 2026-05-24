"""Auth API schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.db.models import UserRole


class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    role: UserRole
    created_at: datetime

    model_config = {"from_attributes": True}
