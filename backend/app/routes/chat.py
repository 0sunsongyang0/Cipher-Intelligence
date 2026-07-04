from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.auth import COOKIE_NAME, get_session_record
from app.database import get_db
from app.deepseek import stream_chat_completion
from app.models import Session as SessionModel
from app.schemas import ChatRequest


router = APIRouter(prefix="/api/chat", tags=["chat"])


def require_chat_session(
    request: Request,
    db: Session = Depends(get_db),
) -> SessionModel:
    session = get_session_record(db, request.cookies.get(COOKIE_NAME))
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return session


@router.post("")
async def chat(
    payload: ChatRequest,
    current_session: SessionModel = Depends(require_chat_session),
) -> StreamingResponse:
    del current_session
    if not payload.messages:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one message is required",
        )

    message_history = [
        {"role": message.role, "content": message.content}
        for message in payload.messages
    ]

    try:
        stream = stream_chat_completion(message_history)
        first_chunk = await anext(stream)
    except StopAsyncIteration:
        first_chunk = ""
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc) or "DeepSeek request failed",
        ) from exc

    async def stream_response() -> AsyncIterator[str]:
        if first_chunk:
            yield first_chunk

        async for chunk in stream:
            if chunk:
                yield chunk

    return StreamingResponse(
        stream_response(),
        media_type="text/plain; charset=utf-8",
    )
