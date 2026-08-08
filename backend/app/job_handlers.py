from __future__ import annotations

import asyncio
import base64
from dataclasses import asdict
from typing import Any

from app.cape_service import CapeService
from app.deepseek import stream_chat_completion
from app.jobs import JobContext, register_job_handler
from app.zip_parser import parse_zip_upload


async def cape_analysis(context: JobContext, payload: dict[str, Any]) -> dict[str, Any]:
    task_id = int(payload["taskId"])
    service = CapeService()
    await context.update(5, "正在等待 CAPE 分析")
    while True:
        await context.checkpoint()
        snapshot = await service.get_task_snapshot(task_id)
        if snapshot.completed:
            break
        await context.update(min(85, 10 + int(payload.get("pollCount", 0))), f"CAPE 状态: {snapshot.status}")
        await asyncio.sleep(float(payload.get("pollInterval", 2)))
    await context.update(90, "正在提取 CAPE 报告")
    summary = await service.get_analysis_summary(task_id)
    value = asdict(summary)
    value.pop("raw", None)
    return value


async def file_parse(context: JobContext, payload: dict[str, Any]) -> dict[str, Any]:
    filename = str(payload.get("filename") or "upload.zip")
    encoded = payload.get("contentBase64")
    if not isinstance(encoded, str):
        raise ValueError("file_parse requires contentBase64")
    await context.update(10, "正在校验文件")
    raw = base64.b64decode(encoded, validate=True)
    parsed = await parse_zip_upload(filename, raw, eager_image_ocr=bool(payload.get("eagerImageOcr", True)))
    await context.update(90, "文件解析完成")
    return {
        "archiveName": parsed.archive_name,
        "entryCount": parsed.entry_count,
        "extractedEntryCount": parsed.extracted_entry_count,
        "inventoryOnlyCount": parsed.inventory_only_count,
        "skippedEntryCount": parsed.skipped_entry_count,
    }


async def model_inference(context: JobContext, payload: dict[str, Any]) -> dict[str, Any]:
    messages = payload.get("messages")
    if not isinstance(messages, list) or not messages:
        raise ValueError("model_inference requires messages")
    model = str(payload.get("model") or "deepseek-chat")
    chunks: list[str] = []
    await context.update(5, "模型请求已发送")
    async for chunk in stream_chat_completion(messages, model):
        await context.checkpoint()
        chunks.append(str(chunk))
        await context.update(min(95, 5 + len(chunks)), "模型正在生成")
    return {"content": "".join(chunks), "model": model}


async def report_generation(context: JobContext, payload: dict[str, Any]) -> dict[str, Any]:
    # Report generation is model-backed but has a distinct task type for UI and retry policy.
    result = await model_inference(context, payload)
    result["format"] = str(payload.get("format") or "markdown")
    return result


register_job_handler("cape_analysis", cape_analysis)
register_job_handler("file_parse", file_parse)
register_job_handler("model_inference", model_inference)
register_job_handler("report_generation", report_generation)
