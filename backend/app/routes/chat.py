from json import JSONDecodeError
from collections.abc import AsyncIterator

from fastapi.encoders import jsonable_encoder
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.attachments import AttachmentError, build_attachment_block, extract_attachments
from app.auth import COOKIE_NAME, get_session_record
from app.database import get_db
from app.deepseek import DeepSeekConfigurationError, stream_chat_completion
from app.models import Session as SessionModel
from app.schemas import ChatRequest, parse_chat_request_json


router = APIRouter(prefix="/api/chat", tags=["chat"])


def attach_block_to_messages(
    messages: list[dict[str, str]],
    attachment_block: str,
) -> list[dict[str, str]]:
    if not attachment_block:
        return messages

    next_messages = [*messages]
    if next_messages and next_messages[-1]["role"] == "user":
        next_messages[-1] = {
            **next_messages[-1],
            "content": f'{next_messages[-1]["content"]}\n\n{attachment_block}'.strip(),
        }
        return next_messages

    next_messages.append({"role": "user", "content": attachment_block})
    return next_messages


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
    request: Request,
    current_session: SessionModel = Depends(require_chat_session),
) -> StreamingResponse:
    del current_session

    files = []
    content_type = request.headers.get("content-type", "")

    try:
        if content_type.startswith("multipart/form-data"):
            form = await request.form()
            raw_messages = form.get("messages")
            if not isinstance(raw_messages, str):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Missing messages field.",
                )
            payload = parse_chat_request_json(raw_messages)
            files = [item for item in form.getlist("files") if hasattr(item, "filename")]
        else:
            payload = ChatRequest.model_validate(await request.json())
    except JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Malformed JSON body.",
        ) from exc
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=jsonable_encoder(exc.errors()),
        ) from exc

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
        extracted_attachments = await extract_attachments(files)
        attachment_block = build_attachment_block(extracted_attachments)
        stream = stream_chat_completion(
            attach_block_to_messages(message_history, attachment_block)
        )
        first_chunk = await anext(stream)
    except StopAsyncIteration:
        first_chunk = ""
    except AttachmentError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except DeepSeekConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
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
