import uuid
from typing import List, Optional
from pydantic import BaseModel, Field
from datetime import datetime

class Message(BaseModel):
    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    role: str
    content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class Session(BaseModel):
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    messages: List[Message] = []

class ChatRequest(BaseModel):
    query: str
    user_id: str
    session_id: Optional[str] = None
    images: Optional[List[str]] = []

class ChatResponse(BaseModel):
    response: str
    session_id: str
    message_id: str
