from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePosixPath
import zipfile

from app.attachments import (
    DOCX_EXTENSIONS,
    IMAGE_EXTENSIONS,
    MAX_FILE_CHARS,
    MAX_FILE_SIZE_BYTES,
    MAX_TOTAL_CHARS,
    PDF_EXTENSIONS,
    TEXT_EXTENSIONS,
    AttachmentError,
    ExtractedAttachment,
    VisionImageAttachment,
    build_image_data_url,
    decode_text_file,
    extract_docx_text,
    extract_image_text,
    extract_pdf_text,
    guess_image_media_type,
    normalize_text,
)


MAX_ZIP_PATH_DEPTH = 8
MAX_ZIP_ENTRY_BYTES = MAX_FILE_SIZE_BYTES
MAX_ZIP_TOTAL_UNCOMPRESSED_BYTES = MAX_FILE_SIZE_BYTES * 2
NESTED_ZIP_EXTENSIONS = {".zip"}
ZIP_AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}
ZIP_VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
ZIP_BINARY_DB_EXTENSIONS = {".db", ".sqlite", ".sqlite3"}


@dataclass
class ZipInventoryEntry:
    filename: str
    category: str
    extension: str
    size_bytes: int
    extracted: bool
    status: str
    warning: str | None = None


@dataclass
class ParsedZipUpload:
    archive_name: str
    entry_count: int
    skipped_entry_count: int
    skipped_filenames: list[str]
    extracted_entry_count: int
    inventory_only_count: int
    extracted_items: list[ExtractedAttachment]
    inventory_entries: list[ZipInventoryEntry]
    vision_images: list[VisionImageAttachment]


def _validate_zip_entry_name(filename: str) -> PurePosixPath:
    path = PurePosixPath(filename)
    parts = path.parts

    if not filename or path.is_absolute() or ":" in parts[0] or any(part == ".." for part in parts):
        raise AttachmentError(f"Unsafe ZIP entry path: {filename}")

    if len(parts) > MAX_ZIP_PATH_DEPTH:
        raise AttachmentError(f"ZIP entry path is too deeply nested: {filename}")

    return path


def _should_ignore_system_entry(path: PurePosixPath) -> bool:
    return "__MACOSX" in path.parts or path.name == ".DS_Store"


def _classify_zip_entry(filename: str) -> tuple[str, str]:
    extension = PurePosixPath(filename).suffix.lower()

    if extension in NESTED_ZIP_EXTENSIONS:
        raise AttachmentError(f"Nested ZIP archives are not supported: {filename}")
    if extension in TEXT_EXTENSIONS:
        return "text", extension
    if extension in PDF_EXTENSIONS:
        return "pdf", extension
    if extension in DOCX_EXTENSIONS:
        return "docx", extension
    if extension in IMAGE_EXTENSIONS:
        return "image", extension
    if extension in ZIP_AUDIO_EXTENSIONS:
        return "audio", extension
    if extension in ZIP_VIDEO_EXTENSIONS:
        return "video", extension
    if extension in ZIP_BINARY_DB_EXTENSIONS:
        return "binary-db", extension
    return "binary", extension


def _normalize_extracted_attachment(
    *,
    filename: str,
    category: str,
    text: str,
) -> ExtractedAttachment:
    normalized = normalize_text(text)
    warning = None
    if len(normalized) > MAX_FILE_CHARS:
        normalized = normalized[:MAX_FILE_CHARS].rstrip()
        warning = "Extracted content was truncated."

    return ExtractedAttachment(
        filename=filename,
        category=category,
        text=normalized,
        warning=warning,
    )


async def parse_zip_upload(archive_name: str, raw: bytes) -> ParsedZipUpload:
    if not zipfile.is_zipfile(BytesIO(raw)):
        raise AttachmentError(f"Invalid ZIP archive: {archive_name}")

    try:
        with zipfile.ZipFile(BytesIO(raw)) as archive:
            entries = archive.infolist()

            extracted_items: list[ExtractedAttachment] = []
            inventory_entries: list[ZipInventoryEntry] = []
            vision_images: list[VisionImageAttachment] = []
            skipped_filenames: list[str] = []
            total_chars = 0
            entry_count = 0
            total_uncompressed_bytes = 0

            for info in entries:
                entry_count += 1
                filename = info.filename
                path = _validate_zip_entry_name(filename)

                if info.is_dir():
                    skipped_filenames.append(filename)
                    continue

                if _should_ignore_system_entry(path):
                    skipped_filenames.append(filename)
                    continue

                if info.file_size > MAX_ZIP_ENTRY_BYTES:
                    raise AttachmentError(f"File too large: {filename}")

                total_uncompressed_bytes += info.file_size
                if total_uncompressed_bytes > MAX_ZIP_TOTAL_UNCOMPRESSED_BYTES:
                    raise AttachmentError("ZIP archive is too large when extracted.")

                category, extension = _classify_zip_entry(filename)
                extracted: ExtractedAttachment | None = None
                warning: str | None = None

                if category == "text":
                    entry_raw = archive.read(info)
                    extracted = _normalize_extracted_attachment(
                        filename=filename,
                        category="text",
                        text=decode_text_file(entry_raw),
                    )
                elif category == "pdf":
                    entry_raw = archive.read(info)
                    extracted = _normalize_extracted_attachment(
                        filename=filename,
                        category="pdf",
                        text=extract_pdf_text(entry_raw),
                    )
                elif category == "docx":
                    entry_raw = archive.read(info)
                    extracted = _normalize_extracted_attachment(
                        filename=filename,
                        category="docx",
                        text=extract_docx_text(entry_raw),
                    )
                elif category == "image":
                    entry_raw = archive.read(info)
                    media_type = guess_image_media_type(filename)
                    vision_images.append(
                        VisionImageAttachment(
                            filename=filename,
                            media_type=media_type,
                            data_url=build_image_data_url(entry_raw, media_type),
                        )
                    )
                    image_text = normalize_text(extract_image_text(entry_raw))
                    if image_text:
                        extracted = _normalize_extracted_attachment(
                            filename=filename,
                            category="image-ocr",
                            text=image_text,
                        )

                if extracted is not None:
                    total_chars += len(extracted.text)
                    if total_chars > MAX_TOTAL_CHARS:
                        raise AttachmentError("Total extracted attachment content is too large.")

                    extracted_items.append(extracted)
                    warning = extracted.warning

                inventory_entries.append(
                    ZipInventoryEntry(
                        filename=filename,
                        category=category,
                        extension=extension,
                        size_bytes=info.file_size,
                        extracted=extracted is not None,
                        status="extracted" if extracted is not None else "inventory-only",
                        warning=warning,
                    )
                )
    except zipfile.BadZipFile as exc:
        raise AttachmentError(f"Invalid ZIP archive: {archive_name}") from exc

    if not inventory_entries:
        raise AttachmentError("ZIP archive does not contain any usable supported files.")

    return ParsedZipUpload(
        archive_name=archive_name,
        entry_count=entry_count,
        skipped_entry_count=len(skipped_filenames),
        skipped_filenames=skipped_filenames,
        extracted_entry_count=len(extracted_items),
        inventory_only_count=sum(1 for entry in inventory_entries if not entry.extracted),
        extracted_items=extracted_items,
        inventory_entries=inventory_entries,
        vision_images=vision_images,
    )
