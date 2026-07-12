from __future__ import annotations

from dataclasses import dataclass
import secrets
from threading import Lock
from time import time

from app.attachments import (
    ExtractedAttachment,
    VisionImageAttachment,
    build_attachment_block,
)
from app.zip_parser import ParsedZipUpload, ZipInventoryEntry


ZIP_SUPPORTED_MODELS = {
    "deepseek-v4-flash",
    "deepseek-v4-pro",
    "chatgpt-5.5-official",
    "chatgpt-5.4-az",
    "chatgpt-5.5-backup",
    "chatgpt-5.4-backup",
    "claude-opus-4-7-official",
    "claude-opus-4-6-aws",
    "claude-sonnet-4-6-az",
    "claude-opus-4-7-backup",
    "claude-opus-4-6-backup",
    "claude-sonnet-4-6-backup",
}


@dataclass
class StoredZipContext:
    zip_context_id: str
    owner_user_id: int
    conversation_id: str
    uploaded_at: float
    archive_name: str
    entry_count: int
    extracted_entry_count: int
    inventory_only_count: int
    skipped_entry_count: int
    skipped_filenames: list[str]
    extracted_items: list[ExtractedAttachment]
    inventory_entries: list[ZipInventoryEntry]
    vision_images: list[VisionImageAttachment]
    attachment_block: str
    inventory_block: str
    uploading: bool = False
    error_message: str | None = None


def build_zip_inventory_block(entries: list[ZipInventoryEntry]) -> str:
    if not entries:
        return ""

    sections = [
        "[ZIP file inventory]",
        "| 文件 | 类型 | 大小 | 状态 | 备注 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for entry in entries:
        warning = entry.warning or ""
        sections.append(
            f"| {entry.filename} | {entry.category} | {entry.size_bytes} B | {entry.status} | {warning} |"
        )
    return "\n".join(sections)


class ZipContextStore:
    """Process-local ephemeral ZIP context store for the current app instance.

    This in-memory implementation is intentionally minimal for the current phase
    and can be replaced later when chat integration needs shared persistence.
    """

    def __init__(self) -> None:
        self._items_by_scope: dict[tuple[int, str], StoredZipContext] = {}
        self._items_by_id: dict[str, StoredZipContext] = {}
        self._lock = Lock()

    def save(
        self,
        *,
        owner_user_id: int,
        conversation_id: str,
        parsed: ParsedZipUpload,
        zip_context_id: str | None = None,
    ) -> StoredZipContext:
        zip_context_id = zip_context_id or secrets.token_urlsafe(16)
        stored = StoredZipContext(
            zip_context_id=zip_context_id,
            owner_user_id=owner_user_id,
            conversation_id=conversation_id,
            uploaded_at=time(),
            archive_name=parsed.archive_name,
            entry_count=parsed.entry_count,
            extracted_entry_count=parsed.extracted_entry_count,
            inventory_only_count=parsed.inventory_only_count,
            skipped_entry_count=parsed.skipped_entry_count,
            skipped_filenames=[*parsed.skipped_filenames],
            extracted_items=[*parsed.extracted_items],
            inventory_entries=[*parsed.inventory_entries],
            vision_images=[*parsed.vision_images],
            attachment_block=build_attachment_block(parsed.extracted_items),
            inventory_block=build_zip_inventory_block(parsed.inventory_entries),
        )

        with self._lock:
            scope = (owner_user_id, conversation_id)
            previous = self._items_by_scope.get(scope)
            if previous is not None:
                self._items_by_id.pop(previous.zip_context_id, None)

            self._items_by_scope[scope] = stored
            self._items_by_id[zip_context_id] = stored
        return stored

    def save_pending(
        self,
        *,
        owner_user_id: int,
        conversation_id: str,
        archive_name: str,
    ) -> StoredZipContext:
        return self._store_pending(
            zip_context_id=secrets.token_urlsafe(16),
            owner_user_id=owner_user_id,
            conversation_id=conversation_id,
            archive_name=archive_name,
        )

    def _store_pending(
        self,
        *,
        zip_context_id: str,
        owner_user_id: int,
        conversation_id: str,
        archive_name: str,
    ) -> StoredZipContext:
        stored = StoredZipContext(
            zip_context_id=zip_context_id,
            owner_user_id=owner_user_id,
            conversation_id=conversation_id,
            uploaded_at=time(),
            archive_name=archive_name,
            entry_count=0,
            extracted_entry_count=0,
            inventory_only_count=0,
            skipped_entry_count=0,
            skipped_filenames=[],
            extracted_items=[],
            inventory_entries=[],
            vision_images=[],
            attachment_block="",
            inventory_block="",
            uploading=True,
            error_message=None,
        )

        with self._lock:
            scope = (owner_user_id, conversation_id)
            previous = self._items_by_scope.get(scope)
            if previous is not None:
                self._items_by_id.pop(previous.zip_context_id, None)

            self._items_by_scope[scope] = stored
            self._items_by_id[zip_context_id] = stored
        return stored

    def mark_ready(
        self,
        *,
        zip_context_id: str,
        owner_user_id: int,
        conversation_id: str,
        parsed: ParsedZipUpload,
    ) -> StoredZipContext:
        return self.save(
            owner_user_id=owner_user_id,
            conversation_id=conversation_id,
            parsed=parsed,
            zip_context_id=zip_context_id,
        )

    def mark_failed(
        self,
        *,
        zip_context_id: str,
        owner_user_id: int,
        conversation_id: str,
        archive_name: str,
        error_message: str,
    ) -> StoredZipContext:
        stored = self._store_pending(
            zip_context_id=zip_context_id,
            owner_user_id=owner_user_id,
            conversation_id=conversation_id,
            archive_name=archive_name,
        )
        stored.uploading = False
        stored.error_message = error_message
        return stored

    def get_for_scope(
        self,
        zip_context_id: str,
        *,
        owner_user_id: int,
        conversation_id: str,
    ) -> StoredZipContext | None:
        with self._lock:
            stored = self._items_by_id.get(zip_context_id)
            if (
                stored is None
                or stored.owner_user_id != owner_user_id
                or stored.conversation_id != conversation_id
            ):
                return None
            return stored

    def clear_conversation(self, owner_user_id: int, conversation_id: str) -> None:
        with self._lock:
            stored = self._items_by_scope.pop((owner_user_id, conversation_id), None)
            if stored is not None:
                self._items_by_id.pop(stored.zip_context_id, None)


zip_context_store = ZipContextStore()


def get_zip_model_support(model: str) -> tuple[bool, str | None]:
    if model in ZIP_SUPPORTED_MODELS:
        return True, None
    return False, "当前模型不支持 ZIP 文件问答，请切换其他模型。"
