import json
from collections.abc import AsyncIterator, Sequence

import httpx

from app.config import settings


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
                if not line.startswith("data:"):
                    continue

                data = line[5:].strip()
                if not data or data == "[DONE]":
                    continue

                chunk = json.loads(data)
                content = chunk["choices"][0]["delta"].get("content")
                if content:
                    yield content