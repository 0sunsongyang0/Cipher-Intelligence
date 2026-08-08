from collections.abc import AsyncIterator
from typing import Any

from app.deepseek import StreamUsage, stream_chat_completion
from app.evidence import build_evidence_marker
from app.prompt_config_store import get_effective_prompt
from app.web_search import build_web_search_context, search_web

WEB_SEARCH_SYSTEM_INSTRUCTION = (
    "\u4f60\u5df2\u7ecf\u83b7\u5f97\u4e86\u6700\u65b0\u7684\u8054\u7f51\u641c\u7d22\u7ed3\u679c\uff0c"
    "\u5b83\u4eec\u4f1a\u4ee5 [Web search results] \u533a\u5757\u51fa\u73b0\u5728\u7528\u6237\u6d88\u606f\u4e2d\u3002\n"
    "\u5f53\u8be5\u533a\u5757\u5b58\u5728\u65f6\uff0c\u5fc5\u987b\u628a\u8fd9\u4e9b\u7ed3\u679c\u89c6\u4e3a\u53ef\u7528\u7684\u5916\u90e8\u4fe1\u606f\u6765\u6e90\uff0c"
    "\u5e76\u57fa\u4e8e\u5b83\u4eec\u56de\u7b54\u3002\n"
    "\u4e0d\u8981\u518d\u58f0\u79f0\u4f60\u65e0\u6cd5\u8054\u7f51\u3001\u4e0d\u80fd\u8bbf\u95ee\u5b9e\u65f6\u4fe1\u606f\uff0c"
    "\u6216\u8981\u6c42\u7528\u6237\u81ea\u5df1\u53bb\u641c\u7d22\u3002\n"
    "\u5982\u679c\u641c\u7d22\u7ed3\u679c\u4e0d\u8db3\uff0c\u5c31\u660e\u786e\u8bf4\u660e"
    "\u201c\u5f53\u524d\u63d0\u4f9b\u7684\u641c\u7d22\u7ed3\u679c\u4e0d\u8db3\u4ee5\u652f\u6491\u66f4\u786e\u5b9a\u7684\u7ed3\u8bba\u201d\u3002\n"
    "\u5f15\u7528\u8054\u7f51\u641c\u7d22\u4e8b\u5b9e\u65f6\uff0c\u8bf7\u5728\u76f8\u5173\u53e5\u5b50\u540e\u4f7f\u7528 [W1]\u3001[W2] \u8fd9\u6837\u7684\u6765\u6e90\u7f16\u53f7\uff0c\u4e0d\u8981\u7f16\u9020\u4e0d\u5b58\u5728\u7684\u7f16\u53f7\u3002"
)

FORBIDDEN_WEB_SEARCH_DISCLAIMER_PATTERNS = (
    "\u65e0\u6cd5\u81ea\u52a8\u83b7\u53d6",
    "\u65e0\u6cd5\u76f4\u63a5\u8054\u7f51",
    "\u65e0\u6cd5\u8054\u7f51",
    "\u4e0d\u80fd\u8bbf\u95ee\u5b9e\u65f6\u4fe1\u606f",
    "\u65e0\u6cd5\u8bbf\u95ee\u5b9e\u65f6\u4fe1\u606f",
    "\u8bf7\u628a\u65b0\u95fb\u5185\u5bb9\u8d34\u7ed9\u6211",
    "\u628a\u65b0\u95fb\u5185\u5bb9\u8d34\u7ed9\u6211",
    "\u4e0a\u4f20\u65b0\u95fb\u7f51\u9875\u6587\u672c",
    "\u6ca1\u6709\u8054\u7f51",
    "\u6ca1\u6709\u8054\u7f51\u6216\u8bbf\u95ee\u5b9e\u65f6\u6570\u636e\u7684\u80fd\u529b",
    "\u6211\u65e0\u6cd5\u67e5\u8be2\u5b9e\u65f6\u5929\u6c14\u4fe1\u606f",
    "\u6211\u6ca1\u6709\u8054\u7f51\u6216\u8bbf\u95ee\u5b9e\u65f6\u6570\u636e\u7684\u80fd\u529b",
)


def attach_block_to_messages(
    messages: list[dict[str, Any]],
    attachment_block: str,
) -> list[dict[str, Any]]:
    if not attachment_block:
        return messages

    next_messages = [*messages]
    if next_messages and next_messages[-1]["role"] == "user":
        if not isinstance(next_messages[-1]["content"], str):
            raise RuntimeError("Cannot append search context to a non-text user message.")
        next_messages[-1] = {
            **next_messages[-1],
            "content": f'{next_messages[-1]["content"]}\n\n{attachment_block}'.strip(),
        }
        return next_messages

    next_messages.append({"role": "user", "content": attachment_block})
    return next_messages


def apply_backend_system_prompt(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    existing_system_content = "\n\n".join(
        str(message.get("content", "")).strip()
        for message in messages
        if str(message.get("role", "")).strip().lower() == "system"
        and str(message.get("content", "")).strip()
    )
    non_system_messages = [
        message
        for message in messages
        if str(message.get("role", "")).strip().lower() != "system"
    ]
    prompt = get_effective_prompt().strip()
    combined_prompt = "\n\n".join(
        part for part in (prompt, existing_system_content) if part
    )
    if not combined_prompt:
        return non_system_messages
    return [{"role": "system", "content": combined_prompt}, *non_system_messages]


def apply_web_search_system_instruction(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not messages:
        return [{"role": "system", "content": WEB_SEARCH_SYSTEM_INSTRUCTION}]

    first_message = messages[0]
    if str(first_message.get("role", "")).strip().lower() == "system":
        content = str(first_message.get("content", "")).strip()
        next_content = (
            f"{WEB_SEARCH_SYSTEM_INSTRUCTION}\n\n{content}".strip()
            if content
            else WEB_SEARCH_SYSTEM_INSTRUCTION
        )
        return [{**first_message, "content": next_content}, *messages[1:]]

    return [{"role": "system", "content": WEB_SEARCH_SYSTEM_INSTRUCTION}, *messages]


def extract_last_user_text(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if str(message.get("role", "")).strip().lower() != "user":
            continue
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()

    raise RuntimeError("Web search requires a text user message.")


def is_news_summary_request(query: str) -> bool:
    lowered = query.lower()
    return any(
        token in lowered
        for token in (
            "\u65b0\u95fb",
            "\u8981\u95fb",
            "\u8d44\u8baf",
            "\u70ed\u70b9",
            "\u5feb\u8baf",
        )
    )


def should_replace_web_search_reply(reply: str) -> bool:
    text = reply.strip()
    if not text:
        return False
    return any(pattern in text for pattern in FORBIDDEN_WEB_SEARCH_DISCLAIMER_PATTERNS)


def build_web_search_guardrail_reply(query: str, results: list[dict[str, str]]) -> str:
    if not results:
        return (
            f"\u5df2\u4e3a\u4f60\u6267\u884c\u8054\u7f51\u641c\u7d22\uff0c\u4f46\u5f53\u524d\u56f4\u7ed5\u201c{query}\u201d"
            "\u6ca1\u6709\u62ff\u5230\u8db3\u591f\u53ef\u9760\u7684\u7ed3\u679c\u3002"
            "\u8bf7\u628a\u95ee\u9898\u518d\u5177\u4f53\u4e00\u70b9\uff0c\u6bd4\u5982\u9650\u5b9a\u4e3b\u9898\u3001\u5730\u533a\u6216\u65f6\u95f4\u8303\u56f4\uff0c"
            "\u6211\u4f1a\u7ee7\u7eed\u6309\u641c\u7d22\u7ed3\u679c\u5e2e\u4f60\u6574\u7406\u3002"
        )

    lines = [f"\u5df2\u8054\u7f51\u641c\u7d22\u201c{query}\u201d\uff0c\u5148\u57fa\u4e8e\u5f53\u524d\u7ed3\u679c\u7ed9\u4f60\u6574\u7406\u3002", ""]
    if is_news_summary_request(query):
        lines.append("\u5f53\u524d\u68c0\u7d22\u5230\u7684\u7ed3\u679c\u4ee5\u6743\u5a01\u65b0\u95fb\u5165\u53e3\u548c\u65b0\u95fb\u805a\u5408\u9875\u4e3a\u4e3b\uff1a")
    else:
        lines.append("\u5f53\u524d\u68c0\u7d22\u5230\u7684\u76f8\u5173\u7ed3\u679c\u5982\u4e0b\uff1a")

    for index, item in enumerate(results[:5], start=1):
        lines.extend(
            [
                f"{index}. {item['title']}",
                f"   {item['url']}",
            ]
        )
        snippet = item["snippet"].strip()
        if snippet:
            lines.append(f"   {snippet}")

    if is_news_summary_request(query):
        lines.extend(
            [
                "",
                "\u8fd9\u4e9b\u7ed3\u679c\u8bf4\u660e\u5f53\u524d\u5df2\u7ecf\u68c0\u7d22\u5230\u65b0\u95fb\u6765\u6e90\uff0c\u4f46\u591a\u6570\u4ecd\u662f\u7ad9\u70b9\u5165\u53e3\uff0c\u4e0d\u662f\u5355\u6761\u65b0\u95fb\u6b63\u6587\u3002",
                "\u5982\u679c\u4f60\u8981\u6211\u7ee7\u7eed\u6574\u7406\u201c\u4eca\u65e5\u65b0\u95fb\u6458\u8981\u201d\uff0c\u4e0b\u4e00\u6b65\u66f4\u9002\u5408\u6309\u66f4\u5177\u4f53\u7684\u65b9\u5411\u7ee7\u7eed\u641c\uff0c"
                "\u6bd4\u5982\u56fd\u5185\u3001\u56fd\u9645\u3001\u79d1\u6280\u3001\u8d22\u7ecf\uff0c\u6216\u8005\u76f4\u63a5\u6307\u5b9a 3-5 \u6761\u91cd\u70b9\u3002",
            ]
        )

    return "\n".join(lines).strip()


async def stream_search_chat(
    *,
    messages: list[dict[str, Any]],
    model: str,
    web_search: bool,
    usage_tracker: StreamUsage | None = None,
) -> AsyncIterator[str]:
    effective_messages = [*messages]
    query = ""
    results: list[dict[str, str]] = []

    if web_search:
        query = extract_last_user_text(effective_messages)
        results = await search_web(query)
        search_block = build_web_search_context(query, results)
        effective_messages = attach_block_to_messages(effective_messages, search_block)
        evidence_marker = build_evidence_marker(
            [
                {
                    "sourceType": "web",
                    "citation": f"W{index}",
                    "title": item["title"],
                    "url": item["url"],
                    "locator": f"\u8054\u7f51\u641c\u7d22\u7ed3\u679c {index}",
                    "snippet": item["snippet"],
                }
                for index, item in enumerate(results, start=1)
            ]
        )
        if evidence_marker:
            yield evidence_marker

    effective_messages = apply_backend_system_prompt(effective_messages)
    if web_search:
        effective_messages = apply_web_search_system_instruction(effective_messages)

    if web_search:
        buffered_chunks: list[str] = []
        upstream_stream = (
            stream_chat_completion(effective_messages, model=model, usage_tracker=usage_tracker)
            if usage_tracker is not None
            else stream_chat_completion(effective_messages, model=model)
        )
        async for chunk in upstream_stream:
            buffered_chunks.append(chunk)

        reply = "".join(buffered_chunks)
        if should_replace_web_search_reply(reply):
            yield build_web_search_guardrail_reply(query, results)
            return

        for chunk in buffered_chunks:
            yield chunk
        return

    upstream_stream = (
        stream_chat_completion(effective_messages, model=model, usage_tracker=usage_tracker)
        if usage_tracker is not None
        else stream_chat_completion(effective_messages, model=model)
    )
    async for chunk in upstream_stream:
        yield chunk
