from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_session
from app.database import SessionLocal, get_db
from app.deepseek import stream_chat_completion
from app.models import Conversation, Message, Session as SessionModel, now_utc
from app.schemas import ChatRequest


router = APIRouter(prefix="/api/chat", tags=["chat"])


def get_owned_conversation(
    db: Session, conversation_id: int, current_session: SessionModel
) -> Conversation | None:
    return db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.owner_session_id == current_session.id,
        )
    ).scalar_one_or_none()


def persist_assistant_progress(
    conversation_id: int, assistant_message_id: int, assistant_content: str
) -> None:
    with SessionLocal() as stream_db:
        conversation = stream_db.get(Conversation, conversation_id)
        assistant_message = stream_db.get(Message, assistant_message_id)
        if conversation is None or assistant_message is None:
            return

        conversation.updated_at = now_utc()
        assistant_message.content = assistant_content
        stream_db.commit()


@router.post("")
async def chat(
    payload: ChatRequest,
    current_session: SessionModel = Depends(require_session),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    conversation = get_owned_conversation(db, payload.conversation_id, current_session)
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    conversation.updated_at = now_utc()
    user_message = Message(
        conversation_id=payload.conversation_id,
        role="user",
        content=payload.content,
    )
    db.add(user_message)
    db.commit()

    messages = db.execute(
        select(Message)
        .where(Message.conversation_id == payload.conversation_id)
        .order_by(Message.created_at.asc(), Message.id.asc())
    ).scalars().all()
    message_history = [{"role": message.role, "content": message.content} for message in messages]

    assistant_message = Message(
        conversation_id=payload.conversation_id,
        role="assistant",
        content="",
    )
    db.add(assistant_message)
    db.commit()
    db.refresh(assistant_message)

    async def stream_response() -> AsyncIterator[str]:
        assistant_content = ""

        try:
            async for chunk in stream_chat_completion(message_history):
                if not chunk:
                    continue

                assistant_content += chunk
                persist_assistant_progress(
                    payload.conversation_id,
                    assistant_message.id,
                    assistant_content,
                )
                yield chunk
        except Exception:
            persist_assistant_progress(
                payload.conversation_id,
                assistant_message.id,
                assistant_content,
            )
            raise

        persist_assistant_progress(
            payload.conversation_id,
            assistant_message.id,
            assistant_content,
        )

    return StreamingResponse(stream_response(), media_type="text/plain")