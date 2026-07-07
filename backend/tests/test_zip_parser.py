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


def inventory_by_filename(parsed) -> dict[str, object]:
    return {entry.filename: entry for entry in parsed.inventory_entries}


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
    inventory = inventory_by_filename(parsed)
    assert inventory["photo.png"].category == "image"
    assert inventory["photo.png"].extension == ".png"
    assert inventory["photo.png"].size_bytes == len(b"fake image bytes")
    assert inventory["photo.png"].extracted is False
    assert inventory["photo.png"].status == "inventory-only"
    assert inventory["photo.png"].warning is None
    assert inventory["notes.txt"].category == "text"
    assert inventory["notes.txt"].extension == ".txt"
    assert inventory["notes.txt"].size_bytes == len(b"kept")
    assert inventory["notes.txt"].extracted is True
    assert inventory["notes.txt"].status == "extracted"
    assert inventory["notes.txt"].warning is None


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
    assert all(entry.category == "text" for entry in parsed.inventory_entries)
    assert all(entry.extension == ".txt" for entry in parsed.inventory_entries)
    assert all(entry.size_bytes == len(b"ok") for entry in parsed.inventory_entries)
    assert all(entry.extracted is True for entry in parsed.inventory_entries)
    assert all(entry.status == "extracted" for entry in parsed.inventory_entries)
    assert all(entry.warning is None for entry in parsed.inventory_entries)


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
    inventory = inventory_by_filename(parsed)
    assert inventory["notes.txt"].category == "text"
    assert inventory["notes.txt"].extension == ".txt"
    assert inventory["notes.txt"].size_bytes == len(b"hello")
    assert inventory["notes.txt"].extracted is True
    assert inventory["notes.txt"].status == "extracted"
    assert inventory["notes.txt"].warning is None
    assert inventory["screens/snap.png"].category == "image"
    assert inventory["screens/snap.png"].extension == ".png"
    assert inventory["screens/snap.png"].size_bytes == len(b"fake-image")
    assert inventory["screens/snap.png"].extracted is True
    assert inventory["screens/snap.png"].status == "extracted"
    assert inventory["screens/snap.png"].warning is None
    assert inventory["audio/voice.mp3"].category == "audio"
    assert inventory["audio/voice.mp3"].extension == ".mp3"
    assert inventory["audio/voice.mp3"].size_bytes == len(b"fake-audio")
    assert inventory["audio/voice.mp3"].extracted is False
    assert inventory["audio/voice.mp3"].status == "inventory-only"
    assert inventory["audio/voice.mp3"].warning is None
    assert inventory["video/demo.mp4"].category == "video"
    assert inventory["video/demo.mp4"].extension == ".mp4"
    assert inventory["video/demo.mp4"].size_bytes == len(b"fake-video")
    assert inventory["video/demo.mp4"].extracted is False
    assert inventory["video/demo.mp4"].status == "inventory-only"
    assert inventory["video/demo.mp4"].warning is None
    assert inventory["db/cache.db"].category == "binary-db"
    assert inventory["db/cache.db"].extension == ".db"
    assert inventory["db/cache.db"].size_bytes == len(b"fake-db")
    assert inventory["db/cache.db"].extracted is False
    assert inventory["db/cache.db"].status == "inventory-only"
    assert inventory["db/cache.db"].warning is None


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
    inventory = inventory_by_filename(parsed)
    assert len(inventory) == 2
    assert inventory["audio/voice.mp3"].category == "audio"
    assert inventory["audio/voice.mp3"].extension == ".mp3"
    assert inventory["audio/voice.mp3"].size_bytes == len(b"fake-audio")
    assert inventory["audio/voice.mp3"].extracted is False
    assert inventory["audio/voice.mp3"].status == "inventory-only"
    assert inventory["audio/voice.mp3"].warning is None
    assert inventory["db/cache.db"].category == "binary-db"
    assert inventory["db/cache.db"].extension == ".db"
    assert inventory["db/cache.db"].size_bytes == len(b"fake-db")
    assert inventory["db/cache.db"].extracted is False
    assert inventory["db/cache.db"].status == "inventory-only"
    assert inventory["db/cache.db"].warning is None


@pytest.mark.anyio
async def test_parse_zip_upload_keeps_image_in_inventory_when_ocr_is_empty(
    monkeypatch,
) -> None:
    monkeypatch.setattr(zip_parser_module, "extract_image_text", lambda _raw: "")
    archive_bytes = make_zip({"screens/snap.png": b"fake-image"})

    parsed = await parse_zip_upload("images.zip", archive_bytes)

    assert parsed.extracted_items == []
    assert len(parsed.vision_images) == 1
    inventory = parsed.inventory_entries[0]
    assert inventory.filename == "screens/snap.png"
    assert inventory.category == "image"
    assert inventory.extension == ".png"
    assert inventory.size_bytes == len(b"fake-image")
    assert inventory.extracted is False
    assert inventory.status == "inventory-only"
    assert inventory.warning is None


@pytest.mark.anyio
async def test_parse_zip_upload_does_not_read_inventory_only_entries(monkeypatch) -> None:
    archive_bytes = make_zip(
        {
            "audio/voice.mp3": b"fake-audio",
            "notes.txt": b"hello",
        }
    )

    original_zip_file = zip_parser_module.zipfile.ZipFile

    class TrackingZipFile(original_zip_file):
        def read(self, name, pwd=None):
            info = name if isinstance(name, zipfile.ZipInfo) else self.getinfo(name)
            if info.filename == "audio/voice.mp3":
                raise AssertionError("inventory-only entry should not be read")
            return super().read(name, pwd=pwd)

    monkeypatch.setattr(zip_parser_module.zipfile, "ZipFile", TrackingZipFile)

    parsed = await parse_zip_upload("inventory-read.zip", archive_bytes)

    inventory = inventory_by_filename(parsed)
    assert inventory["audio/voice.mp3"].status == "inventory-only"
    assert inventory["notes.txt"].status == "extracted"


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
