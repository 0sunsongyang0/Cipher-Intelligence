import json
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, TypeAdapter, field_validator


ChatModelId = Literal[
    "deepseek-v4-flash",
    "deepseek-v4-pro",
    "chatgpt-5.5-official",
    "chatgpt-5.4-az",
    "chatgpt-5.5-backup",
    "chatgpt-5.4-backup",
    "claude-opus-4-7-official",
    "claude-opus-4-6-aws",
    "claude-sonnet-4-6-az",
    "claude-opus-4-7-backup",
    "claude-opus-4-6-backup",
    "claude-sonnet-4-6-backup",
]


class RegisterRequest(BaseModel):
    username: str
    password: str
    inviteCode: str


class LoginRequest(BaseModel):
    username: str | None = None
    password: str


class UserPayload(BaseModel):
    id: int
    username: str
    isAdmin: bool


class SessionStatus(BaseModel):
    authenticated: bool
    user: UserPayload | None = None


class AuthSuccess(SessionStatus):
    pass


class AdminInviteItem(BaseModel):
    id: int
    code: str
    label: str
    isActive: bool
    maxUses: int | None
    usedCount: int
    expiresAt: datetime | None
    createdAt: datetime


class AdminInviteListResponse(BaseModel):
    items: list[AdminInviteItem]


class AdminInviteCreateRequest(BaseModel):
    code: str
    label: str = ""
    maxUses: int | None = None
    expiresAt: datetime | None = None
    isActive: bool = True

    @field_validator("maxUses")
    @classmethod
    def validate_max_uses(cls, value: int | None) -> int | None:
        if value is not None and value <= 0:
            raise ValueError("maxUses must be greater than 0")
        return value


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
    model: ChatModelId = "deepseek-v4-flash"
    conversationId: str | None = None
    zipContextId: str | None = None
    webSearch: bool = False


class UploadZipResponse(BaseModel):
    zipContextId: str
    archiveName: str
    entryCount: int
    extractedEntryCount: int
    inventoryOnlyCount: int
    skippedEntryCount: int
    supportedByCurrentModel: bool
    unsupportedReason: str | None = None


class UploadZipRequest(BaseModel):
    conversationId: str
    model: ChatModelId


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

