from __future__ import annotations

from dataclasses import dataclass
import hashlib
from io import BytesIO
from pathlib import PurePosixPath
import zipfile

from app.attachments import (
    DOCX_EXTENSIONS,
    EVTX_EXTENSIONS,
    IMAGE_EXTENSIONS,
    BINARY_TEXT_FALLBACK_EXTENSIONS,
    MAX_FILE_CHARS,
    MAX_FILE_SIZE_BYTES,
    PDF_EXTENSIONS,
    PPTX_EXTENSIONS,
    PPT_EXTENSIONS,
    TEXT_EXTENSIONS,
    AttachmentError,
    ExtractedAttachment,
    VisionImageAttachment,
    build_image_data_url,
    decode_text_file,
    extract_docx_text,
    extract_binary_text,
    extract_evtx_text,
    extract_image_text,
    extract_pdf_text,
    extract_pptx_text,
    guess_image_media_type,
    normalize_text,
)


MAX_ZIP_PATH_DEPTH = 8
MAX_ZIP_NESTED_DEPTH = 4
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


@dataclass
class _ZipParseState:
    extracted_items: list[ExtractedAttachment]
    inventory_entries: list[ZipInventoryEntry]
    vision_images: list[VisionImageAttachment]
    skipped_filenames: list[str]
    entry_count: int = 0
    total_uncompressed_bytes: int = 0


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
        return "zip", extension
    if extension in TEXT_EXTENSIONS:
        return "text", extension
    if extension in PDF_EXTENSIONS:
        return "pdf", extension
    if extension in DOCX_EXTENSIONS:
        return "docx", extension
    if extension in PPTX_EXTENSIONS:
        return "pptx", extension
    if extension in PPT_EXTENSIONS:
        return "ppt", extension
    if extension in EVTX_EXTENSIONS:
        return "evtx", extension
    if extension in IMAGE_EXTENSIONS:
        return "image", extension
    if extension in BINARY_TEXT_FALLBACK_EXTENSIONS:
        return "binary-text", extension
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


def _build_nested_display_name(prefix: str | None, filename: str) -> str:
    if not prefix:
        return filename
    return f"{prefix}!/{filename}"


def _build_binary_summary_text(filename: str, raw: bytes) -> str:
    header = raw[:16]
    header_hex = " ".join(f"{byte:02x}" for byte in header) or "(empty)"
    header_ascii = "".join(chr(byte) if 32 <= byte <= 126 else "." for byte in header) or "(empty)"
    sha256 = hashlib.sha256(raw).hexdigest()

    return "\n".join(
        [
            "Binary file summary",
            f"File: {filename}",
            f"Size: {len(raw)} bytes",
            f"SHA256: {sha256}",
            f"Header bytes: {header_hex}",
            f"Header preview: {header_ascii}",
            "Readable strings were not found, so this metadata summary was extracted instead.",
        ]
    )


def _build_nested_zip_summary_text(
    filename: str,
    *,
    size_bytes: int,
    child_entry_count: int,
) -> str:
    return "\n".join(
        [
            "Nested ZIP archive",
            f"File: {filename}",
            f"Compressed entry size: {size_bytes} bytes",
            f"Recursively parsed entries: {child_entry_count}",
            "Child files from this nested archive were expanded into the same ZIP context.",
        ]
    )


def _append_inventory_entry(
    state: _ZipParseState,
    *,
    filename: str,
    category: str,
    extension: str,
    size_bytes: int,
    extracted: bool,
    warning: str | None = None,
) -> None:
    state.inventory_entries.append(
        ZipInventoryEntry(
            filename=filename,
            category=category,
            extension=extension,
            size_bytes=size_bytes,
            extracted=extracted,
            status="extracted" if extracted else "inventory-only",
            warning=warning,
        )
    )


def _append_extracted_item(
    state: _ZipParseState,
    extracted: ExtractedAttachment,
) -> ExtractedAttachment:
    state.extracted_items.append(extracted)
    return extracted


def _build_inventory_warning(message: str) -> str:
    normalized = normalize_text(message)
    if not normalized:
        return "This file could not be extracted, so only its inventory entry was kept."
    return normalized


def _parse_archive_entries(
    archive: zipfile.ZipFile,
    *,
    eager_image_ocr: bool,
    nested_prefix: str | None,
    nested_depth: int,
    state: _ZipParseState,
) -> None:
    for info in archive.infolist():
        state.entry_count += 1
        filename = info.filename
        path = _validate_zip_entry_name(filename)
        display_name = _build_nested_display_name(nested_prefix, filename)

        if info.is_dir():
            state.skipped_filenames.append(display_name)
            continue

        if _should_ignore_system_entry(path):
            state.skipped_filenames.append(display_name)
            continue

        if info.file_size > MAX_ZIP_ENTRY_BYTES:
            raise AttachmentError(f"File too large: {display_name}")

        state.total_uncompressed_bytes += info.file_size
        if state.total_uncompressed_bytes > MAX_ZIP_TOTAL_UNCOMPRESSED_BYTES:
            raise AttachmentError("ZIP archive is too large when extracted.")

        category, extension = _classify_zip_entry(filename)
        extracted: ExtractedAttachment | None = None
        warning: str | None = None

        try:
            if category == "zip":
                if nested_depth >= MAX_ZIP_NESTED_DEPTH:
                    raise AttachmentError(f"Nested ZIP depth is too deep: {display_name}")

                entry_raw = archive.read(info)
                if not zipfile.is_zipfile(BytesIO(entry_raw)):
                    raise AttachmentError(f"Invalid nested ZIP archive: {display_name}")

                child_entry_count_before = state.entry_count
                with zipfile.ZipFile(BytesIO(entry_raw)) as nested_archive:
                    _parse_archive_entries(
                    nested_archive,
                    eager_image_ocr=eager_image_ocr,
                    nested_prefix=display_name,
                    nested_depth=nested_depth + 1,
                    state=state,
                    )
                child_entry_count = state.entry_count - child_entry_count_before
                extracted = _normalize_extracted_attachment(
                    filename=display_name,
                    category="zip-summary",
                    text=_build_nested_zip_summary_text(
                        display_name,
                        size_bytes=info.file_size,
                        child_entry_count=child_entry_count,
                    ),
                )
            elif category == "text":
                entry_raw = archive.read(info)
                extracted = _normalize_extracted_attachment(
                    filename=display_name,
                    category="text",
                    text=decode_text_file(entry_raw),
                )
            elif category == "pdf":
                entry_raw = archive.read(info)
                extracted = _normalize_extracted_attachment(
                    filename=display_name,
                    category="pdf",
                    text=extract_pdf_text(entry_raw),
                )
            elif category == "docx":
                entry_raw = archive.read(info)
                extracted = _normalize_extracted_attachment(
                    filename=display_name,
                    category="docx",
                    text=extract_docx_text(entry_raw),
                )
            elif category == "pptx":
                entry_raw = archive.read(info)
                extracted = _normalize_extracted_attachment(
                    filename=display_name,
                    category="pptx",
                    text=extract_pptx_text(entry_raw),
                )
            elif category == "ppt":
                entry_raw = archive.read(info)
                extracted = _normalize_extracted_attachment(
                    filename=display_name,
                    category="ppt",
                    text=extract_binary_text(entry_raw),
                )
            elif category == "evtx":
                entry_raw = archive.read(info)
                extracted = _normalize_extracted_attachment(
                    filename=display_name,
                    category="evtx",
                    text=extract_evtx_text(entry_raw),
                )
            elif category == "binary-text":
                entry_raw = archive.read(info)
                extracted = _normalize_extracted_attachment(
                    filename=display_name,
                    category="binary-text",
                    text=extract_binary_text(entry_raw),
                )
            elif category == "binary":
                entry_raw = archive.read(info)
                try:
                    extracted = _normalize_extracted_attachment(
                        filename=display_name,
                        category="binary-text",
                        text=extract_binary_text(entry_raw),
                    )
                except AttachmentError:
                    extracted = _normalize_extracted_attachment(
                        filename=display_name,
                        category="binary-summary",
                        text=_build_binary_summary_text(display_name, entry_raw),
                    )
            elif category == "image":
                entry_raw = archive.read(info)
                media_type = guess_image_media_type(filename)
                state.vision_images.append(
                    VisionImageAttachment(
                        filename=display_name,
                        media_type=media_type,
                        data_url=build_image_data_url(entry_raw, media_type) if eager_image_ocr else "",
                        raw_bytes=None if eager_image_ocr else entry_raw,
                    )
                )
                if eager_image_ocr:
                    try:
                        image_text = normalize_text(extract_image_text(entry_raw))
                    except AttachmentError:
                        image_text = ""

                    if image_text:
                        extracted = _normalize_extracted_attachment(
                            filename=display_name,
                            category="image-ocr",
                            text=image_text,
                        )
        except AttachmentError as exc:
            warning = _build_inventory_warning(str(exc))

        was_extracted = False
        if extracted is not None:
            stored_extracted = _append_extracted_item(state, extracted)
            was_extracted = True
            warning = stored_extracted.warning

        _append_inventory_entry(
            state,
            filename=display_name,
            category=category,
            extension=extension,
            size_bytes=info.file_size,
            extracted=was_extracted,
            warning=warning,
        )


async def parse_zip_upload(
    archive_name: str,
    raw: bytes,
    *,
    eager_image_ocr: bool = True,
) -> ParsedZipUpload:
    if not zipfile.is_zipfile(BytesIO(raw)):
        raise AttachmentError(f"Invalid ZIP archive: {archive_name}")

    try:
        with zipfile.ZipFile(BytesIO(raw)) as archive:
            state = _ZipParseState(
                extracted_items=[],
                inventory_entries=[],
                vision_images=[],
                skipped_filenames=[],
            )
            _parse_archive_entries(
                archive,
                eager_image_ocr=eager_image_ocr,
                nested_prefix=None,
                nested_depth=0,
                state=state,
            )
    except zipfile.BadZipFile as exc:
        raise AttachmentError(f"Invalid ZIP archive: {archive_name}") from exc

    if not state.inventory_entries:
        raise AttachmentError("ZIP archive does not contain any usable supported files.")

    return ParsedZipUpload(
        archive_name=archive_name,
        entry_count=state.entry_count,
        skipped_entry_count=len(state.skipped_filenames),
        skipped_filenames=state.skipped_filenames,
        extracted_entry_count=len(state.extracted_items),
        inventory_only_count=sum(1 for entry in state.inventory_entries if not entry.extracted),
        extracted_items=state.extracted_items,
        inventory_entries=state.inventory_entries,
        vision_images=state.vision_images,
    )
