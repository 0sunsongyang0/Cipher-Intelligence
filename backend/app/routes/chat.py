import inspect
from json import JSONDecodeError
from collections.abc import AsyncIterator
from typing import Any

from fastapi.encoders import jsonable_encoder
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from app.attachments import (
    AttachmentError,
    VisionImageAttachment,
    build_attachment_block,
    extract_attachments,
    prepare_attachments,
)
from app.auth import require_user_session
from app.deepseek import DeepSeekConfigurationError, stream_chat_completion
from app.models import Session as SessionModel
from app.schemas import ChatRequest, parse_chat_request_json
from app.zip_context_store import get_zip_model_support, zip_context_store


router = APIRouter(prefix="/api/chat", tags=["chat"])


MISSING_ZIP_CONTEXT_ERROR = "ZIP \u4e0a\u4e0b\u6587\u4e0d\u5b58\u5728\u6216\u5df2\u8fc7\u671f\uff0c\u8bf7\u91cd\u65b0\u4e0a\u4f20\u538b\u7f29\u5305\u3002"


def build_chat_stream(
    messages: list[dict[str, Any]],
    model: str,
):
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
        content_blocks.append(
            {
                "type": "image_url",
                "image_url": {"url": image.data_url},
            }
        )

    user_message["content"] = content_blocks

    if next_messages and next_messages[-1]["role"] == "user":
        next_messages[-1] = user_message
    else:
        next_messages.append(user_message)

    return next_messages


@router.post("")
async def chat(
    request: Request,
    current_session: SessionModel = Depends(require_user_session),
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
