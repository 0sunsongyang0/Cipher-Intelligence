from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_session
from app.database import get_db
from app.deepseek import stream_chat_completion
from app.models import Conversation, Message, now_utc
from app.schemas import ChatRequest


router = APIRouter(prefix="/api/chat", tags=["chat"], dependencies=[Depends(require_session)])


@router.post("")
async def chat(payload: ChatRequest, db: Session = Depends(get_db)) -> StreamingResponse:
    conversation = db.get(Conversation, payload.conversation_id)
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    conversation.updated_at = now_utc()
    db.add(
        Message(
            conversation_id=payload.conversation_id,
            role="user",
            content=payload.message,
        )
    )
    db.commit()

    messages = db.execute(
        select(Message)
        .where(Message.conversation_id == payload.conversation_id)
        .order_by(Message.created_at.asc(), Message.id.asc())
    ).scalars().all()
    message_history = [{"role": message.role, "content": message.content} for message in messages]

    async def stream_response() -> AsyncIterator[str]:
        chunks: list[str] = []

        async for chunk in stream_chat_completion(message_history):
            if not chunk:
                continue

            chunks.append(chunk)
            yield chunk

        conversation.updated_at = now_utc()
        db.add(
            Message(
                conversation_id=payload.conversation_id,
                role="assistant",
                content="".join(chunks),
            )
        )
        db.commit()

    return StreamingResponse(stream_response(), media_type="text/plain")