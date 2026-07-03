from datetime import datetime

from pydantic import BaseModel, ConfigDict


class LoginRequest(BaseModel):
    password: str


class AuthSuccess(BaseModel):
    authenticated: bool


class SessionStatus(BaseModel):
    authenticated: bool


class ConversationCreate(BaseModel):
    title: str


class ConversationItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    created_at: datetime
    updated_at: datetime


class ConversationList(BaseModel):
    items: list[ConversationItem]
