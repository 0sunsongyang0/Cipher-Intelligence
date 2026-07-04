import json
from collections.abc import AsyncIterator, Sequence

import httpx

from app.config import settings


class DeepSeekConfigurationError(RuntimeError):
    pass


def parse_chunk_content(line: str) -> str | None:
    if not line.startswith("data:"):
        return None

    data = line[5:].strip()
    if not data or data == "[DONE]":
        return None

    chunk = json.loads(data)
    return chunk["choices"][0]["delta"].get("content")


async def stream_chat_completion(messages: Sequence[dict[str, str]]) -> AsyncIterator[str]:
    api_key = settings.deepseek_api_key.strip()
    if not api_key or api_key == "unset":
        raise DeepSeekConfigurationError("DeepSeek API key is not configured.")

    url = f"{settings.deepseek_base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": settings.deepseek_model,
        "messages": list(messages),
        "stream": True,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("POST", url, headers=headers, json=payload) as response:
                response.raise_for_status()

                async for line in response.aiter_lines():
                    content = parse_chunk_content(line)
                    if content:
                        yield content
    except httpx.HTTPStatusError as exc:
        response = exc.response
        raise RuntimeError(
            f"DeepSeek upstream returned {response.status_code} {response.reason_phrase}"
        ) from exc
    except httpx.HTTPError as exc:
        raise RuntimeError("DeepSeek request failed before streaming completed.") from exc
