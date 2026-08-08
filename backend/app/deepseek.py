import json
import time
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Any

import httpx

from app.attachments import (
    AttachmentError,
    ExtractedAttachment,
    build_attachment_block,
    decode_image_data_url,
    extract_image_text,
    normalize_text,
)
from app.config import settings
from app.schemas import ChatModelId

_MODEL_CATALOG_CACHE_TTL_SECONDS = 60.0

_model_catalog_cache: dict[tuple[str, str], tuple[float, set[str]]] = {}
_CLAUDE_BACKUP_MODEL_IDS = {
    "claude-opus-4-7-backup",
    "claude-opus-4-6-backup",
    "claude-sonnet-4-6-backup",
}


class DeepSeekConfigurationError(RuntimeError):
    pass


class StreamedUpstreamError(RuntimeError):
    pass


@dataclass
class StreamUsage:
    """Exact token usage reported by a compatible streaming upstream."""

    input_tokens: int | None = None
    output_tokens: int | None = None
    model_id: str | None = None

    @property
    def is_exact(self) -> bool:
        return self.input_tokens is not None and self.output_tokens is not None


def _capture_chunk_usage(chunk: dict[str, Any], tracker: StreamUsage | None) -> None:
    if tracker is None:
        return
    usage = chunk.get("usage")
    if not isinstance(usage, dict):
        return
    input_tokens = usage.get("prompt_tokens", usage.get("input_tokens"))
    output_tokens = usage.get("completion_tokens", usage.get("output_tokens"))
    if isinstance(input_tokens, int) and input_tokens >= 0:
        tracker.input_tokens = input_tokens
    if isinstance(output_tokens, int) and output_tokens >= 0:
        tracker.output_tokens = output_tokens


def parse_chunk_content(line: str, usage_tracker: StreamUsage | None = None) -> str | None:
    if not line.startswith("data:"):
        return None

    data = line[5:].strip()
    if not data or data == "[DONE]":
        return None

    chunk = json.loads(data)
    _capture_chunk_usage(chunk, usage_tracker)

    error = chunk.get("error")
    if isinstance(error, dict):
        message = str(error.get("message", "")).strip()
        raise StreamedUpstreamError(message or "Model upstream returned a streamed error event.")

    choices = chunk.get("choices")
    if not isinstance(choices, list) or not choices:
        return None

    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        return None

    delta = first_choice.get("delta")
    if not isinstance(delta, dict):
        return None

    content = delta.get("content")
    return content if isinstance(content, str) and content else None


def iter_message_content_blocks(message: dict[str, Any]) -> list[dict[str, Any]]:
    content = message.get("content")
    if not isinstance(content, list):
        return []

    return [dict(item) for item in content if isinstance(item, dict)]


def is_claude_model(upstream_model: str) -> bool:
    return upstream_model.startswith("claude-")


def parse_data_url(data_url: str) -> tuple[str, str]:
    if not data_url.startswith("data:") or "," not in data_url:
        raise AttachmentError("Invalid image attachment payload.")

    metadata, encoded = data_url.split(",", 1)
    media_type = metadata[5:].split(";", 1)[0].strip()
    if not media_type:
        raise AttachmentError("Invalid image attachment payload.")
    return media_type, encoded


def convert_claude_content_block(item: dict[str, Any]) -> dict[str, Any]:
    block_type = item.get("type")
    if block_type == "text":
        return {
            "type": "text",
            "text": str(item.get("text", "")),
        }

    if block_type == "image_url":
        image_url = item.get("image_url")
        if not isinstance(image_url, dict):
            raise AttachmentError("Invalid image attachment payload.")
        data_url = image_url.get("url")
        if not isinstance(data_url, str):
            raise AttachmentError("Invalid image attachment payload.")
        media_type, encoded = parse_data_url(data_url)
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": encoded,
            },
        }

    return dict(item)


def extract_claude_system_message(
    messages: Sequence[dict[str, Any]],
) -> tuple[str | None, list[dict[str, Any]]]:
    system_parts: list[str] = []
    normalized_messages: list[dict[str, Any]] = []

    for message in messages:
        if str(message.get("role", "")).strip().lower() == "system":
            content_blocks = iter_message_content_blocks(message)
            if content_blocks:
                for item in content_blocks:
                    if item.get("type") == "text":
                        text = str(item.get("text", "")).strip()
                        if text:
                            system_parts.append(text)
                continue

            content = str(message.get("content", "")).strip()
            if content:
                system_parts.append(content)
            continue

        content_blocks = iter_message_content_blocks(message)
        if not content_blocks:
            normalized_messages.append(dict(message))
            continue

        normalized_messages.append(
            {
                **message,
                "content": [convert_claude_content_block(item) for item in content_blocks],
            }
        )

    system_message = "\n\n".join(part for part in system_parts if part).strip()
    return (system_message or None, normalized_messages)


def message_has_image_blocks(message: dict[str, Any]) -> bool:
    return any(item.get("type") == "image_url" for item in iter_message_content_blocks(message))


def should_retry_claude_vision_with_ocr_fallback(
    exc: httpx.HTTPStatusError,
    *,
    upstream_model: str,
    messages: Sequence[dict[str, Any]],
) -> bool:
    if not is_claude_model(upstream_model):
        return False
    if exc.response.status_code != 400:
        return False
    return any(message_has_image_blocks(message) for message in messages)


def infer_embedded_image_filename(media_type: str, index: int) -> str:
    extension = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/webp": ".webp",
        "image/bmp": ".bmp",
    }.get(media_type, ".bin")
    return f"embedded-image-{index}{extension}"


def build_ocr_fallback_messages(messages: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    fallback_messages: list[dict[str, Any]] = []

    for message in messages:
        content_blocks = iter_message_content_blocks(message)
        if not content_blocks:
            fallback_messages.append(dict(message))
            continue

        text_parts: list[str] = []
        image_items: list[ExtractedAttachment] = []
        image_index = 0

        for item in content_blocks:
            if item.get("type") == "text":
                text = str(item.get("text", "")).strip()
                if text:
                    text_parts.append(text)
                continue

            if item.get("type") != "image_url":
                continue

            image_url = item.get("image_url")
            if not isinstance(image_url, dict):
                raise AttachmentError("Invalid image attachment payload.")
            data_url = image_url.get("url")
            if not isinstance(data_url, str):
                raise AttachmentError("Invalid image attachment payload.")

            image_index += 1
            media_type, _encoded = parse_data_url(data_url)
            ocr_text = normalize_text(extract_image_text(decode_image_data_url(data_url)))
            if not ocr_text:
                continue

            image_items.append(
                ExtractedAttachment(
                    filename=infer_embedded_image_filename(media_type, image_index),
                    category="image-ocr",
                    text=ocr_text,
                )
            )

        if any(item.get("type") == "image_url" for item in content_blocks) and not image_items:
            raise AttachmentError("Unable to extract text from image attachment.")

        attachment_block = build_attachment_block(image_items)
        combined_text = "\n\n".join(
            part for part in ("\n\n".join(text_parts), attachment_block) if part
        ).strip()
        fallback_messages.append(
            {
                **message,
                "content": combined_text,
            }
        )

    return fallback_messages


def resolve_upstream(model: ChatModelId | None) -> tuple[str, str, str, str]:
    requested_model = model or settings.deepseek_model

    def preferred_key(primary: str, fallback: str) -> str:
        return primary if primary.strip() and primary.strip().casefold() != "unset" else fallback

    if requested_model in {"deepseek-v4-flash", "deepseek-v4-pro"}:
        return (
            settings.deepseek_base_url,
            settings.deepseek_api_key,
            requested_model,
            "DeepSeek API key is not configured.",
        )

    proxy_base_url = settings.openai_proxy_base_url
    provider_upstreams: dict[ChatModelId, tuple[str, str, str, str]] = {
        "chatgpt-5.5-official": (
            proxy_base_url,
            settings.openai_official_api_key,
            "gpt-5.5",
            "OpenAI official API key is not configured.",
        ),
        "chatgpt-5.4-az": (
            proxy_base_url,
            settings.openai_az_api_key,
            "gpt-5.4",
            "OpenAI Azure API key is not configured.",
        ),
        "chatgpt-5.5-backup": (
            proxy_base_url,
            settings.openai_backup_api_key,
            "gpt-5.5",
            "OpenAI backup API key is not configured.",
        ),
        "chatgpt-5.4-backup": (
            proxy_base_url,
            settings.openai_backup_api_key,
            "gpt-5.4",
            "OpenAI backup API key is not configured.",
        ),
        "claude-opus-4-7-official": (
            proxy_base_url,
            preferred_key(settings.claude_official_api_key, settings.openai_official_api_key),
            "claude-opus-4-7",
            "Claude official API key is not configured.",
        ),
        "claude-opus-4-6-aws": (
            proxy_base_url,
            settings.openai_aws_api_key,
            "claude-opus-4-6",
            "Claude AWS API key is not configured.",
        ),
        "claude-sonnet-4-6-az": (
            proxy_base_url,
            preferred_key(settings.claude_az_api_key, settings.openai_az_api_key),
            "claude-sonnet-4-6",
            "Claude Azure API key is not configured.",
        ),
        "claude-opus-4-7-backup": (
            proxy_base_url,
            preferred_key(settings.claude_backup_api_key, settings.openai_backup_api_key),
            "claude-opus-4-7",
            "Claude backup API key is not configured.",
        ),
        "claude-opus-4-6-backup": (
            proxy_base_url,
            settings.claude_backup_api_key,
            "claude-opus-4-6",
            "Claude backup API key is not configured.",
        ),
        "claude-sonnet-4-6-backup": (
            proxy_base_url,
            settings.claude_backup_api_key,
            "claude-sonnet-4-6",
            "Claude backup API key is not configured.",
        ),
    }

    if requested_model in provider_upstreams:
        return provider_upstreams[requested_model]

    raise DeepSeekConfigurationError(f'Unsupported model "{requested_model}".')


def resolve_failover_model(model: ChatModelId | None) -> ChatModelId | None:
    failover_models: dict[ChatModelId, ChatModelId] = {
        "chatgpt-5.5-official": "chatgpt-5.4-az",
        "chatgpt-5.4-az": "chatgpt-5.4-backup",
        "chatgpt-5.5-backup": "chatgpt-5.4-az",
        "chatgpt-5.4-backup": "chatgpt-5.4-az",
        "claude-opus-4-7-official": "claude-opus-4-7-backup",
        "claude-opus-4-6-aws": "claude-opus-4-6-backup",
        "claude-sonnet-4-6-az": "claude-sonnet-4-6-backup",
    }

    if model is None or model not in failover_models:
        return None

    return failover_models[model]


def resolve_failover_upstream(
    model: ChatModelId | None,
    *,
    exc: Exception | None = None,
    stream_error: Exception | None = None,
) -> tuple[ChatModelId, str, str, str] | None:
    del exc, stream_error

    failover_model = resolve_failover_model(model)
    if failover_model is None:
        return None

    base_url, api_key, upstream_model, _missing_key_message = resolve_upstream(failover_model)
    normalized_api_key = api_key.strip()
    if not normalized_api_key or normalized_api_key == "unset":
        return None

    return failover_model, base_url, normalized_api_key, upstream_model


async def fetch_upstream_model_catalog(
    client: httpx.AsyncClient,
    base_url: str,
    headers: dict[str, str],
) -> set[str] | None:
    cache_key = (base_url.rstrip("/"), headers.get("Authorization", ""))
    cached = _model_catalog_cache.get(cache_key)
    now = time.monotonic()
    if cached and now - cached[0] < _MODEL_CATALOG_CACHE_TTL_SECONDS:
        return cached[1]

    try:
        response = await client.get(f"{base_url.rstrip('/')}/models", headers=headers)
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        return None

    data = payload.get("data")
    if not isinstance(data, list):
        return None

    catalog = {
        model_id
        for item in data
        if isinstance(item, dict)
        for model_id in [str(item.get("id", "")).strip()]
        if model_id
    }
    _model_catalog_cache[cache_key] = (now, catalog)
    return catalog


def should_validate_upstream_catalog(base_url: str, upstream_model: str) -> bool:
    del base_url
    return upstream_model.startswith("gpt-")


async def stream_upstream_response(
    client: httpx.AsyncClient,
    *,
    url: str,
    headers: dict[str, str],
    payload: dict[str, object],
    usage_tracker: StreamUsage | None = None,
) -> AsyncIterator[str]:
    async with client.stream("POST", url, headers=headers, json=payload) as response:
        response.raise_for_status()

        async for line in response.aiter_lines():
            content = parse_chunk_content(line, usage_tracker)
            if content:
                yield content


def build_upstream_payload(
    messages: Sequence[dict[str, Any]],
    upstream_model: str,
    *,
    include_usage: bool = False,
) -> dict[str, object]:
    system_message: str | None = None
    normalized_messages = list(messages)
    if is_claude_model(upstream_model):
        system_message, normalized_messages = extract_claude_system_message(messages)
    payload: dict[str, object] = {
        "model": upstream_model,
        "messages": normalized_messages,
        "stream": True,
    }
    if include_usage and not is_claude_model(upstream_model):
        payload["stream_options"] = {"include_usage": True}
    if system_message is not None:
        payload["system"] = system_message

    return payload


def extract_upstream_error_message(response: httpx.Response) -> str | None:
    try:
        payload = response.json()
    except ValueError:
        return None

    error = payload.get("error")
    if isinstance(error, dict):
        message = str(error.get("message", "")).strip()
        if message:
            return message

    detail = payload.get("detail")
    if isinstance(detail, str) and detail.strip():
        return detail.strip()

    return None


async def stream_chat_completion(
    messages: Sequence[dict[str, Any]],
    model: ChatModelId | None = None,
    usage_tracker: StreamUsage | None = None,
) -> AsyncIterator[str]:
    active_model = model
    base_url, api_key, upstream_model, missing_key_message = resolve_upstream(active_model)
    api_key = api_key.strip()
    if not api_key or api_key == "unset":
        raise DeepSeekConfigurationError(missing_key_message)

    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        timeout = httpx.Timeout(settings.smart_model_routing_timeout_seconds, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            effective_messages = list(messages)
            payload = build_upstream_payload(
                effective_messages,
                upstream_model,
                include_usage=usage_tracker is not None,
            )
            if usage_tracker is not None:
                usage_tracker.model_id = active_model or upstream_model
            catalog_failovers_attempted: set[ChatModelId] = set()
            while should_validate_upstream_catalog(base_url, upstream_model):
                catalog = await fetch_upstream_model_catalog(client, base_url, headers)
                if catalog is None or upstream_model in catalog:
                    break

                if active_model is None:
                    raise DeepSeekConfigurationError(
                        f'Selected source does not expose model "{upstream_model}".'
                    )
                if active_model in catalog_failovers_attempted:
                    raise DeepSeekConfigurationError(
                        f'Selected source does not expose model "{upstream_model}".'
                    )

                catalog_failovers_attempted.add(active_model)
                failover_upstream = resolve_failover_upstream(active_model)
                if failover_upstream is None:
                    raise DeepSeekConfigurationError(
                        f'Selected source does not expose model "{upstream_model}".'
                    )

                active_model, base_url, api_key, upstream_model = failover_upstream
                url = f"{base_url.rstrip('/')}/chat/completions"
                payload = build_upstream_payload(
                    effective_messages,
                    upstream_model,
                    include_usage=usage_tracker is not None,
                )
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                }
                if usage_tracker is not None:
                    usage_tracker.model_id = active_model or upstream_model

            try:
                async for content in stream_upstream_response(
                    client,
                    url=url,
                    headers=headers,
                    payload=payload,
                    usage_tracker=usage_tracker,
                ):
                    yield content
                return
            except httpx.HTTPStatusError as exc:
                if should_retry_claude_vision_with_ocr_fallback(
                    exc,
                    upstream_model=upstream_model,
                    messages=effective_messages,
                ):
                    fallback_payload = build_upstream_payload(
                        build_ocr_fallback_messages(effective_messages),
                        upstream_model,
                        include_usage=usage_tracker is not None,
                    )
                    async for content in stream_upstream_response(
                        client,
                        url=url,
                        headers=headers,
                        payload=fallback_payload,
                        usage_tracker=usage_tracker,
                    ):
                        yield content
                    return

                failover_upstream = resolve_failover_upstream(active_model, exc=exc)
                if failover_upstream is not None:
                    (
                        active_model,
                        failover_base_url,
                        failover_api_key,
                        failover_model,
                    ) = failover_upstream
                    failover_url = f"{failover_base_url.rstrip('/')}/chat/completions"
                    failover_payload = build_upstream_payload(
                        effective_messages,
                        failover_model,
                        include_usage=usage_tracker is not None,
                    )
                    failover_headers = {
                        "Authorization": f"Bearer {failover_api_key}",
                        "Content-Type": "application/json",
                    }
                    if usage_tracker is not None:
                        usage_tracker.model_id = active_model or failover_model
                    async for content in stream_upstream_response(
                        client,
                        url=failover_url,
                        headers=failover_headers,
                        payload=failover_payload,
                        usage_tracker=usage_tracker,
                    ):
                        yield content
                    return

                raise
            except StreamedUpstreamError as exc:
                failover_upstream = resolve_failover_upstream(active_model, stream_error=exc)
                if failover_upstream is not None:
                    (
                        active_model,
                        failover_base_url,
                        failover_api_key,
                        failover_model,
                    ) = failover_upstream
                    failover_url = f"{failover_base_url.rstrip('/')}/chat/completions"
                    failover_payload = build_upstream_payload(
                        effective_messages,
                        failover_model,
                        include_usage=usage_tracker is not None,
                    )
                    failover_headers = {
                        "Authorization": f"Bearer {failover_api_key}",
                        "Content-Type": "application/json",
                    }
                    if usage_tracker is not None:
                        usage_tracker.model_id = active_model or failover_model
                    async for content in stream_upstream_response(
                        client,
                        url=failover_url,
                        headers=failover_headers,
                        payload=failover_payload,
                        usage_tracker=usage_tracker,
                    ):
                        yield content
                    return

                raise
            except httpx.HTTPError:
                failover_upstream = resolve_failover_upstream(active_model)
                if failover_upstream is not None:
                    (
                        active_model,
                        failover_base_url,
                        failover_api_key,
                        failover_model,
                    ) = failover_upstream
                    failover_url = f"{failover_base_url.rstrip('/')}/chat/completions"
                    failover_payload = build_upstream_payload(
                        effective_messages,
                        failover_model,
                        include_usage=usage_tracker is not None,
                    )
                    failover_headers = {
                        "Authorization": f"Bearer {failover_api_key}",
                        "Content-Type": "application/json",
                    }
                    if usage_tracker is not None:
                        usage_tracker.model_id = active_model or failover_model
                    async for content in stream_upstream_response(
                        client,
                        url=failover_url,
                        headers=failover_headers,
                        payload=failover_payload,
                        usage_tracker=usage_tracker,
                    ):
                        yield content
                    return

                raise
    except httpx.HTTPStatusError as exc:
        response = exc.response
        error_message = extract_upstream_error_message(response)
        if error_message:
            raise RuntimeError(
                f"Model upstream returned {response.status_code} {response.reason_phrase}: {error_message}"
            ) from exc
        raise RuntimeError(
            f"Model upstream returned {response.status_code} {response.reason_phrase}"
        ) from exc
    except StreamedUpstreamError as exc:
        raise RuntimeError(str(exc)) from exc
    except httpx.HTTPError as exc:
        raise RuntimeError("Model upstream request failed before streaming completed.") from exc
