from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile
from starlette.datastructures import Headers


UPLOAD_ROOT = Path(__file__).resolve().parents[1] / "data" / "uploads"
UPLOAD_TTL = timedelta(hours=24)
MAX_FILE_SIZE = 100 * 1024 * 1024
ALLOWED_EXTENSIONS = {
    ".txt", ".log", ".md", ".csv", ".json", ".xml", ".yaml", ".yml", ".sql",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".zip",
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".bmp", ".tif", ".tiff", ".heic",
    ".py", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts", ".java",
    ".c", ".cc", ".cpp", ".cxx", ".h", ".hpp", ".hh", ".hxx", ".html", ".htm",
    ".css", ".scss", ".sass", ".less", ".rar", ".7z", ".tar", ".gz", ".tgz", ".bz2", ".xz",
    ".mp4", ".mov", ".mkv", ".avi", ".webm", ".flv", ".mpg", ".mpeg", ".m4v",
    ".mp3", ".wav", ".aac", ".m4a", ".flac", ".ogg", ".oga", ".sqlite", ".sqlite3",
    ".db", ".mdb", ".accdb", ".pcap", ".cap", ".evtx",
}
_lock = threading.Lock()


@dataclass(frozen=True)
class UploadRecord:
    upload_id: str
    user_id: int
    name: str
    size: int
    sha256: str
    mime_type: str
    received: int
    complete: bool

    @property
    def directory(self) -> Path:
        return UPLOAD_ROOT / str(self.user_id) / self.upload_id

    @property
    def data_path(self) -> Path:
        return self.directory / "data"


def _meta_path(user_id: int, upload_id: str) -> Path:
    return UPLOAD_ROOT / str(user_id) / upload_id / "meta.json"


def _write(record: UploadRecord) -> None:
    record.directory.mkdir(parents=True, exist_ok=True)
    payload = {**record.__dict__, "updated_at": datetime.now(timezone.utc).isoformat()}
    temp = record.directory / "meta.tmp"
    temp.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(temp, record.directory / "meta.json")


def get_upload(user_id: int, upload_id: str) -> UploadRecord | None:
    path = _meta_path(user_id, upload_id)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return UploadRecord(**{key: payload[key] for key in UploadRecord.__dataclass_fields__})
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def create_upload(user_id: int, name: str, size: int, sha256: str, mime_type: str) -> tuple[UploadRecord, bool]:
    if size <= 0 or size > MAX_FILE_SIZE:
        raise ValueError(f"文件大小必须在 1 B 到 {MAX_FILE_SIZE // 1024 // 1024} MB 之间。")
    if Path(name).suffix.lower() not in ALLOWED_EXTENSIONS:
        raise ValueError("不支持此文件类型。")
    normalized_hash = sha256.lower()
    if len(normalized_hash) != 64 or any(character not in "0123456789abcdef" for character in normalized_hash):
        raise ValueError("文件 SHA-256 无效。")
    cleanup_expired_uploads()
    user_root = UPLOAD_ROOT / str(user_id)
    for meta_path in user_root.glob("*/meta.json"):
        existing = get_upload(user_id, meta_path.parent.name)
        if existing and existing.complete and existing.sha256 == normalized_hash and existing.size == size:
            return existing, True
    record = UploadRecord(uuid4().hex, user_id, Path(name).name, size, normalized_hash, mime_type, 0, False)
    _write(record)
    return record, False


def append_chunk(user_id: int, upload_id: str, offset: int, raw: bytes) -> UploadRecord:
    with _lock:
        record = get_upload(user_id, upload_id)
        if record is None:
            raise FileNotFoundError(upload_id)
        if record.complete:
            return record
        if offset != record.received:
            raise RuntimeError(str(record.received))
        if not raw or record.received + len(raw) > record.size:
            raise ValueError("分片为空或超出声明的文件大小。")
        record.directory.mkdir(parents=True, exist_ok=True)
        with record.data_path.open("ab") as handle:
            handle.write(raw)
        received = record.received + len(raw)
        complete = received == record.size
        next_record = UploadRecord(**{**record.__dict__, "received": received, "complete": complete})
        if complete:
            digest_builder = hashlib.sha256()
            with record.data_path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest_builder.update(chunk)
            digest = digest_builder.hexdigest()
            if digest != record.sha256:
                record.data_path.unlink(missing_ok=True)
                _write(record)
                raise ValueError("文件哈希校验失败，请重新上传。")
        _write(next_record)
        return next_record


def resolve_upload_files(user_id: int, upload_ids: list[str]) -> list[UploadFile]:
    files: list[UploadFile] = []
    for upload_id in upload_ids:
        record = get_upload(user_id, upload_id)
        if record is None or not record.complete or not record.data_path.is_file():
            raise FileNotFoundError(upload_id)
        files.append(UploadFile(filename=record.name, file=record.data_path.open("rb"), headers=Headers({"content-type": record.mime_type})))
    return files


def cleanup_expired_uploads() -> int:
    if not UPLOAD_ROOT.exists():
        return 0
    cutoff = datetime.now(timezone.utc) - UPLOAD_TTL
    removed = 0
    for meta_path in UPLOAD_ROOT.glob("*/*/meta.json"):
        try:
            updated = datetime.fromisoformat(json.loads(meta_path.read_text(encoding="utf-8"))["updated_at"])
        except (OSError, KeyError, ValueError, json.JSONDecodeError):
            updated = datetime.fromtimestamp(meta_path.stat().st_mtime, timezone.utc)
        if updated < cutoff:
            shutil.rmtree(meta_path.parent, ignore_errors=True)
            removed += 1
    return removed
