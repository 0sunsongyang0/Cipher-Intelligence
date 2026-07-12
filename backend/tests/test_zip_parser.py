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
async def test_parse_zip_upload_extracts_xml_log_and_evtx_entries(monkeypatch) -> None:
    monkeypatch.setattr(
        zip_parser_module,
        "extract_evtx_text",
        lambda _raw: "<Event><System>Sysmon</System></Event>",
        raising=False,
    )
    archive_bytes = make_zip(
        {
            "events/sysmon.xml": b"<Events><Event>alpha</Event></Events>",
            "logs/analysis.log": b"first line\nsecond line\n",
            "logs/system.evtx": b"fake-evtx-binary",
        }
    )

    parsed = await parse_zip_upload("bundle.zip", archive_bytes)

    assert [item.filename for item in parsed.extracted_items] == [
        "events/sysmon.xml",
        "logs/analysis.log",
        "logs/system.evtx",
    ]
    assert [item.category for item in parsed.extracted_items] == ["text", "text", "evtx"]
    assert parsed.extracted_items[0].text == "<Events><Event>alpha</Event></Events>"
    assert parsed.extracted_items[1].text == "first line\nsecond line"
    assert parsed.extracted_items[2].text == "<Event><System>Sysmon</System></Event>"

    inventory = inventory_by_filename(parsed)
    assert inventory["events/sysmon.xml"].category == "text"
    assert inventory["events/sysmon.xml"].status == "extracted"
    assert inventory["logs/analysis.log"].category == "text"
    assert inventory["logs/analysis.log"].status == "extracted"
    assert inventory["logs/system.evtx"].category == "evtx"
    assert inventory["logs/system.evtx"].status == "extracted"


@pytest.mark.anyio
async def test_parse_zip_upload_extracts_binary_fallback_strings_for_supported_and_extensionless_files() -> None:
    archive_bytes = make_zip(
        {
            "net/capture.pcap": b"\x00GET /index.html HTTP/1.1\r\nHost: example.com\r\n\x00",
            "db/record.bson": b"\x00mongodb://localhost:27017/sample\x00",
            "bin/no-extension": b"\x00cmd.exe /c whoami\x00powershell -enc AAAA\x00",
        }
    )

    parsed = await parse_zip_upload("bundle.zip", archive_bytes)

    assert [item.filename for item in parsed.extracted_items] == [
        "net/capture.pcap",
        "db/record.bson",
        "bin/no-extension",
    ]
    assert [item.category for item in parsed.extracted_items] == [
        "binary-text",
        "binary-text",
        "binary-text",
    ]
    assert "GET /index.html HTTP/1.1" in parsed.extracted_items[0].text
    assert "mongodb://localhost:27017/sample" in parsed.extracted_items[1].text
    assert "cmd.exe /c whoami" in parsed.extracted_items[2].text

    inventory = inventory_by_filename(parsed)
    assert inventory["net/capture.pcap"].status == "extracted"
    assert inventory["db/record.bson"].status == "extracted"
    assert inventory["bin/no-extension"].status == "extracted"


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
async def test_parse_zip_upload_skips_system_entries_and_extracts_zip_image_ocr_when_available(
    monkeypatch,
) -> None:
    monkeypatch.setattr(zip_parser_module, "extract_image_text", lambda _raw: "image body text")
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
    assert [item.filename for item in parsed.extracted_items] == ["photo.png", "notes.txt"]
    assert [item.category for item in parsed.extracted_items] == ["image-ocr", "text"]
    assert parsed.extracted_items[0].text == "image body text"
    assert parsed.extracted_items[1].text == "kept"
    assert len(parsed.vision_images) == 1
    inventory = inventory_by_filename(parsed)
    assert inventory["photo.png"].category == "image"
    assert inventory["photo.png"].extension == ".png"
    assert inventory["photo.png"].size_bytes == len(b"fake image bytes")
    assert inventory["photo.png"].extracted is True
    assert inventory["photo.png"].status == "extracted"
    assert inventory["photo.png"].warning is None
    assert inventory["notes.txt"].category == "text"
    assert inventory["notes.txt"].extension == ".txt"
    assert inventory["notes.txt"].size_bytes == len(b"kept")
    assert inventory["notes.txt"].extracted is True
    assert inventory["notes.txt"].status == "extracted"
    assert inventory["notes.txt"].warning is None


@pytest.mark.anyio
async def test_parse_zip_upload_recursively_expands_nested_zip_entries() -> None:
    inner_zip_bytes = make_zip(
        {
            "inside.txt": b"nested",
            "audio/voice.mp3": b"audio",
        }
    )
    archive_bytes = make_zip(
        {
            "notes.txt": b"kept",
            "inner.zip": inner_zip_bytes,
        }
    )

    parsed = await parse_zip_upload("bundle.zip", archive_bytes)

    assert parsed.entry_count == 4
    assert parsed.extracted_entry_count == 3
    assert parsed.inventory_only_count == 1
    extracted_by_filename = {item.filename: item for item in parsed.extracted_items}
    assert set(extracted_by_filename) == {
        "notes.txt",
        "inner.zip",
        "inner.zip!/inside.txt",
    }
    assert extracted_by_filename["notes.txt"].text == "kept"
    assert extracted_by_filename["inner.zip!/inside.txt"].text == "nested"
    assert "Nested ZIP archive" in extracted_by_filename["inner.zip"].text
    assert "Recursively parsed entries: 2" in extracted_by_filename["inner.zip"].text

    inventory = inventory_by_filename(parsed)
    assert inventory["notes.txt"].category == "text"
    assert inventory["notes.txt"].status == "extracted"
    assert inventory["inner.zip"].category == "zip"
    assert inventory["inner.zip"].status == "extracted"
    assert inventory["inner.zip!/inside.txt"].category == "text"
    assert inventory["inner.zip!/inside.txt"].status == "extracted"
    assert inventory["inner.zip!/audio/voice.mp3"].category == "audio"
    assert inventory["inner.zip!/audio/voice.mp3"].status == "inventory-only"


@pytest.mark.anyio
async def test_parse_zip_upload_rejects_oversized_entry_before_extraction(monkeypatch) -> None:
    monkeypatch.setattr(zip_parser_module, "MAX_ZIP_ENTRY_BYTES", 4)
    archive_bytes = make_zip({"notes.txt": b"12345"})

    with pytest.raises(AttachmentError, match=r"^File too large: notes\.txt$"):
        await parse_zip_upload("bundle.zip", archive_bytes)


@pytest.mark.anyio
async def test_parse_zip_upload_has_no_total_text_budget_limit(monkeypatch) -> None:
    monkeypatch.setattr(zip_parser_module, "MAX_FILE_CHARS", 2)
    archive_bytes = make_zip(
        {
            "one.txt": b"abc",
            "two.txt": b"def",
            "three.txt": b"ghi",
        }
    )

    parsed = await parse_zip_upload("bundle.zip", archive_bytes)

    assert [item.filename for item in parsed.extracted_items] == [
        "one.txt",
        "two.txt",
        "three.txt",
    ]
    assert [item.text for item in parsed.extracted_items] == ["ab", "de", "gh"]
    inventory = inventory_by_filename(parsed)
    assert inventory["one.txt"].status == "extracted"
    assert inventory["one.txt"].warning == "Extracted content was truncated."
    assert inventory["two.txt"].status == "extracted"
    assert inventory["two.txt"].warning == "Extracted content was truncated."
    assert inventory["three.txt"].status == "extracted"
    assert inventory["three.txt"].warning == "Extracted content was truncated."
    assert parsed.extracted_entry_count == 3
    assert parsed.inventory_only_count == 0


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
    monkeypatch.setattr(zip_parser_module, "extract_image_text", lambda _raw: "screen body text")
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
    assert [item.filename for item in parsed.extracted_items] == ["notes.txt", "screens/snap.png"]
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
async def test_parse_zip_upload_extracts_pptx_entries(monkeypatch) -> None:
    monkeypatch.setattr(zip_parser_module, "extract_pptx_text", lambda _raw: "pptx slide text")
    archive_bytes = make_zip({"slides/deck.pptx": b"fake-pptx"})

    parsed = await parse_zip_upload("slides.zip", archive_bytes)

    assert [item.filename for item in parsed.extracted_items] == ["slides/deck.pptx"]
    assert [item.category for item in parsed.extracted_items] == ["pptx"]
    assert [item.text for item in parsed.extracted_items] == ["pptx slide text"]
    inventory = inventory_by_filename(parsed)
    assert inventory["slides/deck.pptx"].category == "pptx"
    assert inventory["slides/deck.pptx"].status == "extracted"


@pytest.mark.anyio
async def test_parse_zip_upload_extracts_ppt_entries_via_binary_fallback(monkeypatch) -> None:
    monkeypatch.setattr(zip_parser_module, "extract_binary_text", lambda _raw: "ppt binary text")
    archive_bytes = make_zip({"slides/deck.ppt": b"fake-ppt"})

    parsed = await parse_zip_upload("slides.zip", archive_bytes)

    assert [item.filename for item in parsed.extracted_items] == ["slides/deck.ppt"]
    assert [item.category for item in parsed.extracted_items] == ["ppt"]
    assert [item.text for item in parsed.extracted_items] == ["ppt binary text"]
    inventory = inventory_by_filename(parsed)
    assert inventory["slides/deck.ppt"].category == "ppt"
    assert inventory["slides/deck.ppt"].status == "extracted"


@pytest.mark.anyio
async def test_parse_zip_upload_keeps_inventory_when_single_pptx_entry_cannot_be_extracted(monkeypatch) -> None:
    monkeypatch.setattr(
        zip_parser_module,
        "extract_pptx_text",
        lambda _raw: (_ for _ in ()).throw(AttachmentError("Unable to extract text from PPTX attachment.")),
    )
    archive_bytes = make_zip({"slides/deck.pptx": b"bad-pptx"})

    parsed = await parse_zip_upload("slides.zip", archive_bytes)

    assert parsed.extracted_items == []
    assert parsed.inventory_only_count == 1
    inventory = inventory_by_filename(parsed)
    assert inventory["slides/deck.pptx"].category == "pptx"
    assert inventory["slides/deck.pptx"].status == "inventory-only"
    assert inventory["slides/deck.pptx"].warning == "Unable to extract text from PPTX attachment."


@pytest.mark.anyio
async def test_parse_zip_upload_keeps_inventory_for_invalid_nested_zip_entry() -> None:
    archive_bytes = make_zip({"broken.zip": b"not-a-real-zip"})

    parsed = await parse_zip_upload("bundle.zip", archive_bytes)

    assert parsed.extracted_items == []
    assert parsed.inventory_only_count == 1
    inventory = inventory_by_filename(parsed)
    assert inventory["broken.zip"].category == "zip"
    assert inventory["broken.zip"].status == "inventory-only"
    assert inventory["broken.zip"].warning == "Invalid nested ZIP archive: broken.zip"


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
async def test_parse_zip_upload_extracts_zip_image_ocr_and_still_stores_vision_payload(
    monkeypatch,
) -> None:
    monkeypatch.setattr(zip_parser_module, "extract_image_text", lambda _raw: "visible zip text")
    archive_bytes = make_zip({"screens/snap.png": b"fake-image"})

    parsed = await parse_zip_upload("images.zip", archive_bytes)

    assert len(parsed.extracted_items) == 1
    assert parsed.extracted_items[0].filename == "screens/snap.png"
    assert parsed.extracted_items[0].category == "image-ocr"
    assert parsed.extracted_items[0].text == "visible zip text"
    assert len(parsed.vision_images) == 1
    inventory = parsed.inventory_entries[0]
    assert inventory.filename == "screens/snap.png"
    assert inventory.category == "image"
    assert inventory.extension == ".png"
    assert inventory.size_bytes == len(b"fake-image")
    assert inventory.extracted is True
    assert inventory.status == "extracted"
    assert inventory.warning is None


@pytest.mark.anyio
async def test_parse_zip_upload_can_skip_eager_image_ocr_and_keep_vision_payload(monkeypatch) -> None:
    def fail_if_ocr_called(_raw):
        raise AssertionError("image OCR should be skipped")

    monkeypatch.setattr(zip_parser_module, "extract_image_text", fail_if_ocr_called)
    archive_bytes = make_zip({"screens/snap.png": b"fake-image"})

    parsed = await parse_zip_upload("images.zip", archive_bytes, eager_image_ocr=False)

    assert parsed.extracted_items == []
    assert len(parsed.vision_images) == 1
    inventory = parsed.inventory_entries[0]
    assert inventory.filename == "screens/snap.png"
    assert inventory.category == "image"
    assert inventory.extracted is False
    assert inventory.status == "inventory-only"


@pytest.mark.anyio
async def test_parse_zip_upload_falls_back_to_binary_summary_when_no_strings_found() -> None:
    archive_bytes = make_zip({"samples/cape.bin": b"\x7fELF\x02\x01\x01\x00\x00\x00\x00\x00"})

    parsed = await parse_zip_upload("samples.zip", archive_bytes)

    assert len(parsed.extracted_items) == 1
    assert parsed.extracted_items[0].filename == "samples/cape.bin"
    assert parsed.extracted_items[0].category == "binary-summary"
    assert "Binary file summary" in parsed.extracted_items[0].text
    assert "SHA256:" in parsed.extracted_items[0].text
    assert "Header bytes:" in parsed.extracted_items[0].text

    inventory = inventory_by_filename(parsed)
    assert inventory["samples/cape.bin"].category == "binary"
    assert inventory["samples/cape.bin"].status == "extracted"


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
