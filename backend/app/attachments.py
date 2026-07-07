from __future__ import annotations

import base64
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from fastapi import UploadFile


MAX_FILE_COUNT = 10
MAX_FILE_SIZE_BYTES = 100 * 1024 * 1024
MAX_FILE_CHARS = 12_000
MAX_TOTAL_CHARS = 40_000

TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".json",
    ".csv",
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".html",
    ".css",
    ".yml",
    ".yaml",
}
PDF_EXTENSIONS = {".pdf"}
DOCX_EXTENSIONS = {".docx"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


@dataclass
class ExtractedAttachment:
    filename: str
    category: str
    text: str
    warning: str | None = None


@dataclass
class VisionImageAttachment:
    filename: str
    media_type: str
    data_url: str


@dataclass
class PreparedAttachments:
    extracted: list[ExtractedAttachment]
    vision_images: list[VisionImageAttachment]


class AttachmentError(ValueError):
    pass


def normalize_text(value: str) -> str:
    return "\n".join(
        line.rstrip()
        for line in value.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    ).strip()


def decode_text_file(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise AttachmentError("Unable to decode text attachment.")


def extract_pdf_text(raw: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise AttachmentError(
            "PDF attachment support is unavailable on this server. Missing dependency: pypdf."
        ) from exc

    try:
        reader = PdfReader(BytesIO(raw), strict=False)
        if reader.is_encrypted and reader.decrypt("") == 0:
            raise AttachmentError("PDF attachment is encrypted and cannot be read by the server.")
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    except AttachmentError:
        raise
    except Exception as exc:
        raise AttachmentError("Unable to extract text from PDF attachment.") from exc


def extract_docx_text(raw: bytes) -> str:
    try:
        from docx import Document
    except ImportError as exc:
        raise AttachmentError(
            "DOCX attachment support is unavailable on this server. Missing dependency: python-docx."
        ) from exc

    try:
        document = Document(BytesIO(raw))
        return "\n".join(paragraph.text for paragraph in document.paragraphs)
    except AttachmentError:
        raise
    except Exception as exc:
        raise AttachmentError("Unable to extract text from DOCX attachment.") from exc


def extract_image_text(raw: bytes) -> str:
    try:
        from PIL import Image
    except ImportError as exc:
        raise AttachmentError(
            "Image attachment support is unavailable on this server. Missing dependency: pillow."
        ) from exc

    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as exc:
        raise AttachmentError(
            "Image attachment support is unavailable on this server. Missing dependency: rapidocr-onnxruntime."
        ) from exc

    try:
        image = Image.open(BytesIO(raw)).convert("RGB")
        engine = RapidOCR()
        result, _ = engine(image)
        if not result:
            return ""
        return "\n".join(item[1] for item in result if len(item) > 1 and item[1])
    except AttachmentError:
        raise
    except Exception as exc:
        raise AttachmentError("Unable to extract text from image attachment.") from exc


def build_image_data_url(raw: bytes, media_type: str) -> str:
    encoded = base64.b64encode(raw).decode("ascii")
    return f"data:{media_type};base64,{encoded}"


def guess_image_media_type(filename: str, fallback: str | None = None) -> str:
    if fallback and fallback.startswith("image/"):
        return fallback

    extension = Path(filename).suffix.lower()
    if extension == ".png":
        return "image/png"
    if extension in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if extension == ".webp":
        return "image/webp"
    if extension == ".bmp":
        return "image/bmp"
    return "application/octet-stream"


async def prepare_attachments(
    files: list[UploadFile],
    *,
    enable_native_vision: bool = False,
) -> PreparedAttachments:
    if len(files) > MAX_FILE_COUNT:
        raise AttachmentError("Too many files. Maximum 10 files are allowed per request.")

    extracted: list[ExtractedAttachment] = []
    vision_images: list[VisionImageAttachment] = []
    total_chars = 0

    for file in files:
        filename = file.filename or "unnamed"
        extension = Path(filename).suffix.lower()
        raw = await file.read()

        if len(raw) > MAX_FILE_SIZE_BYTES:
            raise AttachmentError(f"File too large: {filename}")

        if extension in TEXT_EXTENSIONS:
            text = decode_text_file(raw)
            category = "text"
        elif extension in PDF_EXTENSIONS:
            text = extract_pdf_text(raw)
            category = "pdf"
        elif extension in DOCX_EXTENSIONS:
            text = extract_docx_text(raw)
            category = "docx"
        elif extension in IMAGE_EXTENSIONS:
            if enable_native_vision:
                media_type = guess_image_media_type(filename, file.content_type)
                vision_images.append(
                    VisionImageAttachment(
                        filename=filename,
                        media_type=media_type,
                        data_url=build_image_data_url(raw, media_type),
                    )
                )
                continue

            text = extract_image_text(raw)
            category = "image-ocr"
        else:
            raise AttachmentError(f"Unsupported file type: {filename}")

        normalized = normalize_text(text)
        warning = None
        if len(normalized) > MAX_FILE_CHARS:
            normalized = normalized[:MAX_FILE_CHARS].rstrip()
            warning = "Extracted content was truncated."

        if category == "image-ocr" and not normalized:
            raise AttachmentError(
                f"No readable text could be extracted from image: {filename}"
            )

        total_chars += len(normalized)
        if total_chars > MAX_TOTAL_CHARS:
            raise AttachmentError("Total extracted attachment content is too large.")

        extracted.append(
            ExtractedAttachment(
                filename=filename,
                category=category,
                text=normalized,
                warning=warning,
            )
        )

    return PreparedAttachments(extracted=extracted, vision_images=vision_images)


async def extract_attachments(files: list[UploadFile]) -> list[ExtractedAttachment]:
    return (await prepare_attachments(files)).extracted


def build_attachment_block(items: list[ExtractedAttachment]) -> str:
    if not items:
        return ""

    sections = ["[Attached files]"]
    for item in items:
        sections.append(f"File: {item.filename}")
        sections.append(f"Type: {item.category}")
        if item.warning:
            sections.append(f"Warning: {item.warning}")
        sections.append("Content:")
        sections.append(item.text)
        sections.append("")

    return "\n".join(sections).strip()
