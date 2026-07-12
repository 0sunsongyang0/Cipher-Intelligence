from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, TypedDict

from app.config import DEFAULT_CHAT_SYSTEM_PROMPT, settings

PromptSource = Literal["default", "override"]


class PromptConfigPayload(TypedDict):
    prompt: str
    source: PromptSource
    updated_at: str | None
    status: str
    message: str | None


PROMPT_CONFIG_PATH = Path(settings.prompt_config_path)


def _default_payload(*, message: str | None = None, status: str = "ready") -> PromptConfigPayload:
    return {
        "prompt": DEFAULT_CHAT_SYSTEM_PROMPT,
        "source": "default",
        "updated_at": None,
        "status": status,
        "message": message,
    }


def load_prompt_config() -> PromptConfigPayload:
    if not PROMPT_CONFIG_PATH.is_file():
        return _default_payload()

    try:
        payload = json.loads(PROMPT_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return _default_payload(
            message="系统提示词配置文件无效，已回退到内置默认值。",
            status="fallback",
        )

    try:
        prompt = str(payload["chat_system_prompt"]).strip()
    except (KeyError, TypeError, ValueError):
        return _default_payload(
            message="系统提示词配置文件无效，已回退到内置默认值。",
            status="fallback",
        )

    if not prompt:
        return _default_payload(
            message="系统提示词为空，已回退到内置默认值。",
            status="fallback",
        )

    updated_at = payload.get("updated_at")
    return {
        "prompt": prompt,
        "source": "override",
        "updated_at": updated_at if isinstance(updated_at, str) else None,
        "status": "ready",
        "message": None,
    }


def save_prompt_override(prompt: str) -> PromptConfigPayload:
    normalized = prompt.strip()
    if not normalized:
        raise ValueError("系统提示词不能为空。")

    PROMPT_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    updated_at = datetime.now(timezone.utc).isoformat()
    PROMPT_CONFIG_PATH.write_text(
        json.dumps(
            {
                "chat_system_prompt": normalized,
                "source": "override",
                "updated_at": updated_at,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return {
        "prompt": normalized,
        "source": "override",
        "updated_at": updated_at,
        "status": "ready",
        "message": "系统提示词已保存，新对话会使用最新配置。",
    }


def reset_prompt_override() -> PromptConfigPayload:
    if PROMPT_CONFIG_PATH.exists():
        PROMPT_CONFIG_PATH.unlink()
    return _default_payload(message="系统提示词已恢复为内置默认值。")


def get_effective_prompt() -> str:
    return load_prompt_config()["prompt"]
