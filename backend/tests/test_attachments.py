from io import BytesIO
import sys
import types

import pytest
from fastapi import UploadFile
from pypdf.errors import FileNotDecryptedError

from app.attachments import (
    AttachmentError,
    decode_text_file,
    extract_attachments,
    extract_docx_text,
    extract_image_text,
    extract_pdf_text,
)


def make_upload_file(filename: str, content: bytes) -> UploadFile:
    return UploadFile(filename=filename, file=BytesIO(content))


def test_decode_text_file_handles_utf8_bom_cleanly() -> None:
    assert decode_text_file(b"\xef\xbb\xbfhello") == "hello"


def test_decode_text_file_falls_back_to_gbk() -> None:
    assert decode_text_file("中文内容".encode("gbk")) == "中文内容"


@pytest.mark.anyio
async def test_extract_attachments_truncates_long_text_with_warning(monkeypatch) -> None:
    monkeypatch.setattr("app.attachments.MAX_FILE_CHARS", 5)

    extracted = await extract_attachments(
        [make_upload_file("notes.txt", b"abcdefghij")]
    )

    assert extracted[0].text == "abcde"
    assert extracted[0].warning == "Extracted content was truncated."


@pytest.mark.anyio
async def test_extract_attachments_rejects_empty_ocr_output(monkeypatch) -> None:
    monkeypatch.setattr("app.attachments.extract_image_text", lambda _raw: "")

    with pytest.raises(
        AttachmentError,
        match=r"^No readable text could be extracted from image: shot\.png$",
    ):
        await extract_attachments([make_upload_file("shot.png", b"fake-image")])


def test_extract_pdf_text_wraps_parser_errors(monkeypatch) -> None:
    class BrokenPdfReader:
        def __init__(self, _stream, strict=True):
            raise ValueError("parser exploded")

    monkeypatch.setitem(sys.modules, "pypdf", types.SimpleNamespace(PdfReader=BrokenPdfReader))

    with pytest.raises(
        AttachmentError,
        match=r"^Unable to extract text from PDF attachment\.$",
    ):
        extract_pdf_text(b"%PDF-bad")


def test_extract_pdf_text_reports_missing_dependency(monkeypatch) -> None:
    original_import = __import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "pypdf":
            raise ImportError("No module named 'pypdf'")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", fake_import)

    with pytest.raises(
        AttachmentError,
        match=r"^PDF attachment support is unavailable on this server\. Missing dependency: pypdf\.$",
    ):
        extract_pdf_text(b"%PDF-bad")


def test_extract_pdf_text_rejects_password_protected_pdf(monkeypatch) -> None:
    class EncryptedPdfReader:
        is_encrypted = True
        pages = []

        def __init__(self, _stream, strict=True):
            pass

        def decrypt(self, _password: str) -> int:
            return 0

    monkeypatch.setitem(sys.modules, "pypdf", types.SimpleNamespace(PdfReader=EncryptedPdfReader))

    with pytest.raises(
        AttachmentError,
        match=r"^PDF attachment is encrypted and cannot be read by the server\.$",
    ):
        extract_pdf_text(b"%PDF-encrypted")


def test_extract_pdf_text_uses_non_strict_mode_and_empty_password_for_accessible_encrypted_pdf(
    monkeypatch,
) -> None:
    calls: list[object] = []

    class EncryptedPdfReader:
        is_encrypted = True

        def __init__(self, _stream, strict=True):
            calls.append(("strict", strict))
            self.pages = [types.SimpleNamespace(extract_text=lambda: "hello pdf")]

        def decrypt(self, password: str) -> int:
            calls.append(("decrypt", password))
            return 1

    monkeypatch.setitem(sys.modules, "pypdf", types.SimpleNamespace(PdfReader=EncryptedPdfReader))

    assert extract_pdf_text(b"%PDF-encrypted") == "hello pdf"
    assert calls == [("strict", False), ("decrypt", "")]


def test_extract_docx_text_wraps_parser_errors(monkeypatch) -> None:
    def broken_document(_stream):
        raise ValueError("docx parser exploded")

    monkeypatch.setitem(sys.modules, "docx", types.SimpleNamespace(Document=broken_document))

    with pytest.raises(
        AttachmentError,
        match=r"^Unable to extract text from DOCX attachment\.$",
    ):
        extract_docx_text(b"bad-docx")


def test_extract_docx_text_reports_missing_dependency(monkeypatch) -> None:
    original_import = __import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "docx":
            raise ImportError("No module named 'docx'")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", fake_import)

    with pytest.raises(
        AttachmentError,
        match=r"^DOCX attachment support is unavailable on this server\. Missing dependency: python-docx\.$",
    ):
        extract_docx_text(b"bad-docx")


def test_extract_image_text_wraps_parser_errors(monkeypatch) -> None:
    def broken_open(_stream):
        raise ValueError("image parser exploded")

    class FakeRapidOCR:
        def __call__(self, _image):
            return ([], None)

    pil_image_module = types.SimpleNamespace(open=broken_open)
    pil_module = types.SimpleNamespace(Image=pil_image_module)
    rapidocr_module = types.SimpleNamespace(RapidOCR=FakeRapidOCR)

    monkeypatch.setitem(sys.modules, "PIL", pil_module)
    monkeypatch.setitem(sys.modules, "rapidocr_onnxruntime", rapidocr_module)

    with pytest.raises(
        AttachmentError,
        match=r"^Unable to extract text from image attachment\.$",
    ):
        extract_image_text(b"bad-image")


def test_extract_image_text_reports_missing_ocr_dependency(monkeypatch) -> None:
    original_import = __import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "rapidocr_onnxruntime":
            raise ImportError("No module named 'rapidocr_onnxruntime'")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", fake_import)

    with pytest.raises(
        AttachmentError,
        match=r"^Image attachment support is unavailable on this server\. Missing dependency: rapidocr-onnxruntime\.$",
    ):
        extract_image_text(b"bad-image")
