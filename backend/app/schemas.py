import json
from datetime import datetime

from pydantic import BaseModel, ConfigDict, TypeAdapter


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


class ChatMessageInput(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessageInput]


def parse_chat_request_json(raw: str) -> ChatRequest:
    parsed = json.loads(raw)
    if isinstance(parsed, list):
        messages = TypeAdapter(list[ChatMessageInput]).validate_python(parsed)
        return ChatRequest(messages=messages)
    return ChatRequest.model_validate(parsed)


class MessageItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    conversation_id: int
    role: str
    content: str
    created_at: datetime


class MessageList(BaseModel):
    items: list[MessageItem]
