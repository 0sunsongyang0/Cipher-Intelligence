from __future__ import annotations

from io import BytesIO
import zipfile

import pytest

from app.attachments import AttachmentError
import app.zip_parser as zip_parser_module
from app.zip_parser import parse_zip_upload


def make_zip(entries: dict[str, bytes]) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for filename, content in entries.items():
            archive.writestr(filename, content)
    return buffer.getvalue()


@pytest.mark.anyio
async def test_parse_zip_upload_extracts_supported_text_entries() -> None:
    archive_bytes = make_zip(
        {
            "notes.txt": b"hello text",
            "nested/report.md": b"## heading",
        }
    )

    parsed = await parse_zip_upload("bundle.zip", archive_bytes)

    assert parsed.archive_name == "bundle.zip"
    assert parsed.entry_count == 2
    assert parsed.skipped_entry_count == 0
    assert parsed.skipped_filenames == []
    assert [item.filename for item in parsed.extracted_items] == [
        "notes.txt",
        "nested/report.md",
    ]
    assert [item.category for item in parsed.extracted_items] == ["text", "text"]
    assert [item.text for item in parsed.extracted_items] == ["hello text", "## heading"]


@pytest.mark.anyio
async def test_parse_zip_upload_extracts_supported_code_extension() -> None:
    archive_bytes = make_zip({"script.py": b"print('hello')\n"})

    parsed = await parse_zip_upload("bundle.zip", archive_bytes)

    assert [item.filename for item in parsed.extracted_items] == ["script.py"]
    assert [item.category for item in parsed.extracted_items] == ["text"]
    assert [item.text for item in parsed.extracted_items] == ["print('hello')"]


@pytest.mark.anyio
async def test_parse_zip_upload_rejects_path_traversal() -> None:
    archive_bytes = make_zip({"../escape.txt": b"boom"})

    with pytest.raises(AttachmentError, match=r"^Unsafe ZIP entry path: \.\./escape\.txt$"):
        await parse_zip_upload("bundle.zip", archive_bytes)


@pytest.mark.anyio
async def test_parse_zip_upload_rejects_windows_style_unsafe_path() -> None:
    archive_bytes = make_zip({"C:/escape.txt": b"boom"})

    with pytest.raises(AttachmentError, match=r"^Unsafe ZIP entry path: C:/escape\.txt$"):
        await parse_zip_upload("bundle.zip", archive_bytes)


@pytest.mark.anyio
async def test_parse_zip_upload_rejects_posix_absolute_path() -> None:
    archive_bytes = make_zip({"/escape.txt": b"boom"})

    with pytest.raises(AttachmentError, match=r"^Unsafe ZIP entry path: /escape\.txt$"):
        await parse_zip_upload("bundle.zip", archive_bytes)


@pytest.mark.anyio
async def test_parse_zip_upload_skips_system_entries_and_keeps_images_in_inventory(
    monkeypatch,
) -> None:
    monkeypatch.setattr(zip_parser_module, "extract_image_text", lambda _raw: "")
    archive_bytes = make_zip(
        {
            "__MACOSX/ignored.txt": b"ignore me",
            ".DS_Store": b"ignore me too",
            "photo.png": b"fake image bytes",
            "notes.txt": b"kept",
        }
    )

    parsed = await parse_zip_upload("bundle.zip", archive_bytes)

    assert parsed.entry_count == 4
    assert parsed.skipped_entry_count == 2
    assert parsed.skipped_filenames == [
        "__MACOSX/ignored.txt",
        ".DS_Store",
    ]
    assert [item.filename for item in parsed.extracted_items] == ["notes.txt"]
    assert parsed.extracted_items[0].text == "kept"
    assert len(parsed.vision_images) == 1
    assert {entry.filename: entry.status for entry in parsed.inventory_entries} == {
        "photo.png": "inventory-only",
        "notes.txt": "extracted",
    }


@pytest.mark.anyio
async def test_parse_zip_upload_rejects_nested_zip_entries() -> None:
    inner_zip_bytes = make_zip({"inside.txt": b"nested"})
    archive_bytes = make_zip(
        {
            "notes.txt": b"kept",
            "inner.zip": inner_zip_bytes,
        }
    )

    with pytest.raises(
        AttachmentError,
        match=r"^Nested ZIP archives are not supported: inner\.zip$",
    ):
        await parse_zip_upload("bundle.zip", archive_bytes)


@pytest.mark.anyio
async def test_parse_zip_upload_rejects_oversized_entry_before_extraction(monkeypatch) -> None:
    monkeypatch.setattr(zip_parser_module, "MAX_ZIP_ENTRY_BYTES", 4)
    archive_bytes = make_zip({"notes.txt": b"12345"})

    with pytest.raises(AttachmentError, match=r"^File too large: notes\.txt$"):
        await parse_zip_upload("bundle.zip", archive_bytes)


@pytest.mark.anyio
async def test_parse_zip_upload_rejects_total_extracted_text_budget_overflow(monkeypatch) -> None:
    monkeypatch.setattr(zip_parser_module, "MAX_TOTAL_CHARS", 5)
    archive_bytes = make_zip(
        {
            "one.txt": b"abc",
            "two.txt": b"def",
        }
    )

    with pytest.raises(
        AttachmentError,
        match=r"^Total extracted attachment content is too large\.$",
    ):
        await parse_zip_upload("bundle.zip", archive_bytes)


@pytest.mark.anyio
async def test_parse_zip_upload_allows_many_entries_when_budgets_are_safe() -> None:
    archive_bytes = make_zip({f"note-{index}.txt": b"ok" for index in range(30)})

    parsed = await parse_zip_upload("many.zip", archive_bytes)

    assert parsed.entry_count == 30
    assert parsed.extracted_entry_count == 30
    assert parsed.inventory_only_count == 0


@pytest.mark.anyio
async def test_parse_zip_upload_accepts_mixed_content_and_tracks_inventory(
    monkeypatch,
) -> None:
    monkeypatch.setattr(zip_parser_module, "extract_image_text", lambda _raw: "whiteboard")
    archive_bytes = make_zip(
        {
            "notes.txt": b"hello",
            "screens/snap.png": b"fake-image",
            "audio/voice.mp3": b"fake-audio",
            "video/demo.mp4": b"fake-video",
            "db/cache.db": b"fake-db",
        }
    )

    parsed = await parse_zip_upload("mixed.zip", archive_bytes)

    assert parsed.entry_count == 5
    assert parsed.extracted_entry_count == 2
    assert parsed.inventory_only_count == 3
    assert [item.filename for item in parsed.extracted_items] == [
        "notes.txt",
        "screens/snap.png",
    ]
    assert len(parsed.vision_images) == 1
    assert {entry.filename: entry.status for entry in parsed.inventory_entries} == {
        "notes.txt": "extracted",
        "screens/snap.png": "extracted",
        "audio/voice.mp3": "inventory-only",
        "video/demo.mp4": "inventory-only",
        "db/cache.db": "inventory-only",
    }


@pytest.mark.anyio
async def test_parse_zip_upload_accepts_inventory_only_archives() -> None:
    archive_bytes = make_zip(
        {
            "audio/voice.mp3": b"fake-audio",
            "db/cache.db": b"fake-db",
        }
    )

    parsed = await parse_zip_upload("inventory-only.zip", archive_bytes)

    assert parsed.entry_count == 2
    assert parsed.extracted_entry_count == 0
    assert parsed.inventory_only_count == 2
    assert parsed.extracted_items == []
    assert len(parsed.inventory_entries) == 2


@pytest.mark.anyio
async def test_parse_zip_upload_keeps_image_in_inventory_when_ocr_is_empty(
    monkeypatch,
) -> None:
    monkeypatch.setattr(zip_parser_module, "extract_image_text", lambda _raw: "")
    archive_bytes = make_zip({"screens/snap.png": b"fake-image"})

    parsed = await parse_zip_upload("images.zip", archive_bytes)

    assert parsed.extracted_items == []
    assert len(parsed.vision_images) == 1
    assert parsed.inventory_entries[0].filename == "screens/snap.png"
    assert parsed.inventory_entries[0].status == "inventory-only"


@pytest.mark.anyio
async def test_parse_zip_upload_rejects_total_uncompressed_byte_overflow(monkeypatch) -> None:
    monkeypatch.setattr(zip_parser_module, "MAX_ZIP_TOTAL_UNCOMPRESSED_BYTES", 5)
    archive_bytes = make_zip(
        {
            "one.txt": b"abc",
            "two.txt": b"def",
        }
    )

    with pytest.raises(
        AttachmentError,
        match=r"^ZIP archive is too large when extracted\.$",
    ):
        await parse_zip_upload("bundle.zip", archive_bytes)


@pytest.mark.anyio
async def test_parse_zip_upload_rejects_archives_with_no_usable_inventory_entries() -> None:
    archive_bytes = make_zip(
        {
            "__MACOSX/ignored.txt": b"ignore me",
            ".DS_Store": b"ignore me too",
        }
    )

    with pytest.raises(
        AttachmentError,
        match=r"^ZIP archive does not contain any usable supported files\.$",
    ):
        await parse_zip_upload("bundle.zip", archive_bytes)
