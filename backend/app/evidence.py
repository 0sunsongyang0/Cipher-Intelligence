from __future__ import annotations

import json
from typing import Any


STREAM_EVIDENCE_PREFIX = "\u001e__CIPHER_EVIDENCE__:"
STREAM_MARKER_SUFFIX = "\u001e"


def build_evidence_marker(items: list[dict[str, Any]]) -> str:
    if not items:
        return ""
    payload = json.dumps(items, ensure_ascii=False, separators=(",", ":"))
    return f"{STREAM_EVIDENCE_PREFIX}{payload}{STREAM_MARKER_SUFFIX}"


def parse_evidence_marker(value: str) -> list[dict[str, Any]] | None:
    if not value.startswith(STREAM_EVIDENCE_PREFIX) or not value.endswith(STREAM_MARKER_SUFFIX):
        return None

    raw_payload = value[len(STREAM_EVIDENCE_PREFIX) : -len(STREAM_MARKER_SUFFIX)]
    try:
        payload = json.loads(raw_payload)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, list):
        return None
    return [item for item in payload if isinstance(item, dict)]


def normalize_evidence_item(item: dict[str, Any]) -> dict[str, str | None] | None:
    source_type = str(item.get("sourceType", "")).strip()
    citation = str(item.get("citation", "")).strip()
    title = str(item.get("title", "")).strip()
    if not source_type or not citation or not title:
        return None

    def optional_text(key: str, *, limit: int) -> str | None:
        raw = item.get(key)
        if raw is None:
            return None
        normalized = str(raw).strip()
        return normalized[:limit] or None

    return {
        "sourceType": source_type[:32],
        "citation": citation[:16],
        "title": title[:255],
        "url": optional_text("url", limit=4000),
        "locator": optional_text("locator", limit=255),
        "snippet": optional_text("snippet", limit=4000),
    }


def merge_evidence_items(*groups: list[dict[str, Any]]) -> list[dict[str, str | None]]:
    merged: list[dict[str, str | None]] = []
    seen: set[tuple[str | None, str | None, str | None]] = set()
    for group in groups:
        for item in group:
            normalized = normalize_evidence_item(item)
            if normalized is None:
                continue
            key = (normalized["citation"], normalized["url"], normalized["title"])
            if key in seen:
                continue
            seen.add(key)
            merged.append(normalized)
    return merged
