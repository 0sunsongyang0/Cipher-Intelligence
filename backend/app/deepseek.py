import json
from collections.abc import AsyncIterator, Sequence

import httpx

from app.config import settings


def parse_chunk_content(line: str) -> str | None:
    if not line.startswith("data:"):
        return None

    data = line[5:].strip()
    if not data or data == "[DONE]":
        return None

    chunk = json.loads(data)
    return chunk["choices"][0]["delta"].get("content")


async def stream_chat_completion(messages: Sequence[dict[str, str]]) -> AsyncIterator[str]:
    url = f"{settings.deepseek_base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": settings.deepseek_model,
        "messages": list(messages),
        "stream": True,
    }
    headers = {
        "Authorization": f"Bearer {settings.deepseek_api_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream("POST", url, headers=headers, json=payload) as response:
            response.raise_for_status()

            async for line in response.aiter_lines():
                content = parse_chunk_content(line)
                if content:
                    yield content