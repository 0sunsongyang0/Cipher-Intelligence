import inspect
from json import JSONDecodeError
from collections.abc import AsyncIterator
from typing import Any

from fastapi.encoders import jsonable_encoder
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.attachments import (
    AttachmentError,
    VisionImageAttachment,
    build_image_data_url,
    build_attachment_block,
    extract_attachments,
    prepare_attachments,
)
from app.auth import require_user_session
from app.database import get_db
from app.deepseek import DeepSeekConfigurationError, stream_chat_completion
from app.models import Conversation, Message, MessageAttachment, Session as SessionModel, now_utc
from app.search_chat import stream_search_chat
from app.schemas import ChatRequest, parse_chat_request_json
from app.zip_context_store import get_zip_model_support, zip_context_store


router = APIRouter(prefix="/api/chat", tags=["chat"])


MISSING_ZIP_CONTEXT_ERROR = "ZIP \u4e0a\u4e0b\u6587\u4e0d\u5b58\u5728\u6216\u5df2\u8fc7\u671f\uff0c\u8bf7\u91cd\u65b0\u4e0a\u4f20\u538b\u7f29\u5305\u3002"
PENDING_ZIP_CONTEXT_ERROR = "ZIP 压缩包仍在解析中，请稍后再试。"
STREAM_KEEPALIVE_MARKER = "\u001e__CIPHER_KEEPALIVE__\u001e"
STREAM_ERROR_PREFIX = "\u001e__CIPHER_ERROR__:"
STREAM_MARKER_SUFFIX = "\u001e"


def build_stream_error_marker(message: str) -> str:
    return f"{STREAM_ERROR_PREFIX}{message}{STREAM_MARKER_SUFFIX}"


def build_chat_stream(
    messages: list[dict[str, Any]],
    model: str,
    *,
    web_search: bool = False,
):
    if web_search:
        return stream_search_chat(messages=messages, model=model, web_search=True)

    stream_signature = inspect.signature(stream_chat_completion)
    accepts_model = len(stream_signature.parameters) > 1 or any(
        parameter.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
        for parameter in stream_signature.parameters.values()
    )

    if accepts_model:
        return stream_chat_completion(messages, model)

    return stream_chat_completion(messages)


def prefix_validation_error_locations(errors: list[dict]) -> list[dict]:
    normalized_errors: list[dict] = []

    for error in errors:
        location = error.get("loc")
        if isinstance(location, (list, tuple)) and (len(location) == 0 or location[0] != "body"):
            normalized_errors.append({
                **error,
                "loc": ["body", *location],
            })
            continue

        normalized_errors.append(error)

    return normalized_errors


def attach_block_to_messages(
    messages: list[dict[str, Any]],
    attachment_block: str,
) -> list[dict[str, Any]]:
    if not attachment_block:
        return messages

    next_messages = [*messages]
    if next_messages and next_messages[-1]["role"] == "user":
        if not isinstance(next_messages[-1]["content"], str):
            raise AttachmentError("Cannot append text attachments to a non-text user message.")
        next_messages[-1] = {
            **next_messages[-1],
            "content": f'{next_messages[-1]["content"]}\n\n{attachment_block}'.strip(),
        }
        return next_messages

    next_messages.append({"role": "user", "content": attachment_block})
    return next_messages


def build_zip_context_block(
    archive_name: str,
    attachment_block: str,
    inventory_block: str,
) -> str:
    if not attachment_block and not inventory_block:
        return ""

    sections = ["[ZIP context]", f"Archive: {archive_name}"]
    if attachment_block:
        sections.extend(["", attachment_block])
    if inventory_block:
        sections.extend(["", inventory_block])
    return "\n".join(sections)


def model_supports_native_vision(model: str) -> bool:
    return model.startswith(("chatgpt-", "claude-"))


def as_multimodal_text_blocks(content: Any) -> list[dict[str, Any]]:
    if isinstance(content, list):
        return [dict(item) for item in content]

    normalized = str(content).strip()
    if not normalized:
        return []
    return [{"type": "text", "text": normalized}]


def attach_vision_content_to_messages(
    messages: list[dict[str, Any]],
    *,
    text_block: str,
    vision_images: list[VisionImageAttachment],
) -> list[dict[str, Any]]:
    if not text_block and not vision_images:
        return messages

    next_messages = [*messages]
    if next_messages and next_messages[-1]["role"] == "user":
        user_message = dict(next_messages[-1])
        content_blocks = as_multimodal_text_blocks(user_message.get("content", ""))
    else:
        user_message = {"role": "user", "content": ""}
        content_blocks = []

    if text_block:
        if content_blocks and content_blocks[-1].get("type") == "text":
            existing_text = str(content_blocks[-1].get("text", "")).strip()
            content_blocks[-1]["text"] = f"{existing_text}\n\n{text_block}".strip()
        else:
            content_blocks.append({"type": "text", "text": text_block})

    for image in vision_images:
        image_url = image.data_url
        if not image_url and image.raw_bytes is not None:
            image_url = build_image_data_url(image.raw_bytes, image.media_type)
        content_blocks.append(
            {
                "type": "image_url",
                "image_url": {"url": image_url},
            }
        )

    user_message["content"] = content_blocks

    if next_messages and next_messages[-1]["role"] == "user":
        next_messages[-1] = user_message
    else:
        next_messages.append(user_message)

    return next_messages


def get_owned_conversation(
    db: Session,
    conversation_id: int,
    current_session: SessionModel,
) -> Conversation | None:
    return db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.owner_user_id == current_session.user_id,
        )
    ).scalar_one_or_none()


def persist_conversation_messages(
    db: Session,
    *,
    current_session: SessionModel,
    conversation_id: str | None,
    user_message_content: str | None,
    user_attachments: list[dict[str, Any]] | None,
    assistant_content: str,
) -> None:
    if conversation_id is None or current_session.user_id is None:
        return

    try:
        parsed_conversation_id = int(conversation_id)
    except ValueError:
        return

    conversation = get_owned_conversation(db, parsed_conversation_id, current_session)
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )

    if user_message_content:
        user_message = Message(
            conversation_id=conversation.id,
            role="user",
            content=user_message_content,
        )
        db.add(user_message)
        db.flush()

        for attachment in user_attachments or []:
            db.add(
                MessageAttachment(
                    message_id=user_message.id,
                    attachment_id=str(attachment["id"]),
                    name=str(attachment["name"]),
                    type=str(attachment["type"]),
                    size=int(attachment["size"]),
                    meta=(
                        str(attachment["meta"])
                        if attachment.get("meta") is not None
                        else None
                    ),
                )
            )

    if assistant_content:
        db.add(
            Message(
                conversation_id=conversation.id,
                role="assistant",
                content=assistant_content,
            )
        )

    conversation.updated_at = now_utc()
    db.commit()


@router.post("")
async def chat(
    request: Request,
    current_session: SessionModel = Depends(require_user_session),
    db: Session = Depends(get_db),
) -> StreamingResponse:
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
            detail=jsonable_encoder(prefix_validation_error_locations(exc.errors())),
        ) from exc

    if not payload.messages:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one message is required",
        )

    message_history: list[dict[str, Any]] = [
        {"role": message.role, "content": message.content}
        for message in payload.messages
    ]

    zip_context_block = ""
    zip_context_vision_images: list[VisionImageAttachment] = []
    if payload.zipContextId:
        supported_by_current_model, unsupported_reason = get_zip_model_support(payload.model)
        if not supported_by_current_model:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=unsupported_reason,
            )

        stored_zip_context = zip_context_store.get_for_scope(
            payload.zipContextId,
            owner_user_id=current_session.user_id,
            conversation_id=payload.conversationId or "",
        )
        if stored_zip_context is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=MISSING_ZIP_CONTEXT_ERROR,
            )
        if stored_zip_context.uploading:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=PENDING_ZIP_CONTEXT_ERROR,
            )
        if stored_zip_context.error_message:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=stored_zip_context.error_message,
            )
        zip_context_block = build_zip_context_block(
            stored_zip_context.archive_name,
            stored_zip_context.attachment_block,
            stored_zip_context.inventory_block,
        )
        zip_context_vision_images = [*stored_zip_context.vision_images]

    try:
        if model_supports_native_vision(payload.model):
            prepared_attachments = await prepare_attachments(files, enable_native_vision=True)
            attachment_block = build_attachment_block(prepared_attachments.extracted)
            combined_vision_images = [
                *prepared_attachments.vision_images,
                *zip_context_vision_images,
            ]
            if combined_vision_images:
                combined_text_blocks = "\n\n".join(
                    block for block in (attachment_block, zip_context_block) if block
                )
                message_history = attach_vision_content_to_messages(
                    message_history,
                    text_block=combined_text_blocks,
                    vision_images=combined_vision_images,
                )
            else:
                message_history = attach_block_to_messages(message_history, attachment_block)
                message_history = attach_block_to_messages(message_history, zip_context_block)
        else:
            extracted_attachments = await extract_attachments(files)
            attachment_block = build_attachment_block(extracted_attachments)
            message_history = attach_block_to_messages(message_history, attachment_block)
            message_history = attach_block_to_messages(message_history, zip_context_block)
        stream = build_chat_stream(
            message_history,
            payload.model,
            web_search=payload.webSearch,
        )
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

    last_user_message_content = payload.messages[-1].content if payload.messages[-1].role == "user" else None
    last_user_message_attachments = (
        [
            {
                "id": attachment.id,
                "name": attachment.name,
                "type": attachment.type,
                "size": attachment.size,
                "meta": attachment.meta,
            }
            for attachment in payload.messages[-1].attachments
        ]
        if payload.messages and payload.messages[-1].role == "user"
        else []
    )

    async def stream_response() -> AsyncIterator[str]:
        assistant_content = ""
        yield STREAM_KEEPALIVE_MARKER

        try:
            async for chunk in stream:
                if chunk:
                    assistant_content += chunk
                    yield chunk
        except Exception as exc:
            yield build_stream_error_marker(str(exc) or "DeepSeek request failed")
            return

        persist_conversation_messages(
            db,
            current_session=current_session,
            conversation_id=payload.conversationId,
            user_message_content=last_user_message_content,
            user_attachments=last_user_message_attachments,
            assistant_content=assistant_content,
        )

    return StreamingResponse(
        stream_response(),
        media_type="text/plain; charset=utf-8",
    )
