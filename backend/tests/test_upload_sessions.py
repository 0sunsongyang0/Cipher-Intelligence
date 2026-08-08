import hashlib

import pytest

from app import upload_sessions


def test_chunk_upload_resumes_and_deduplicates(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(upload_sessions, "UPLOAD_ROOT", tmp_path)
    content = b"abcdefghij"
    digest = hashlib.sha256(content).hexdigest()
    record, deduplicated = upload_sessions.create_upload(7, "evidence.txt", len(content), digest, "text/plain")
    assert deduplicated is False

    partial = upload_sessions.append_chunk(7, record.upload_id, 0, content[:4])
    assert partial.received == 4
    assert partial.complete is False

    resumed = upload_sessions.append_chunk(7, record.upload_id, 4, content[4:])
    assert resumed.complete is True
    duplicate, deduplicated = upload_sessions.create_upload(7, "renamed.txt", len(content), digest, "text/plain")
    assert deduplicated is True
    assert duplicate.upload_id == record.upload_id


def test_chunk_upload_reports_expected_offset(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(upload_sessions, "UPLOAD_ROOT", tmp_path)
    content = b"weak-network"
    record, _ = upload_sessions.create_upload(2, "trace.log", len(content), hashlib.sha256(content).hexdigest(), "text/plain")
    upload_sessions.append_chunk(2, record.upload_id, 0, content[:3])
    with pytest.raises(RuntimeError, match="3"):
        upload_sessions.append_chunk(2, record.upload_id, 0, content[3:])


def test_upload_rejects_size_type_and_bad_hash(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(upload_sessions, "UPLOAD_ROOT", tmp_path)
    with pytest.raises(ValueError, match="文件大小"):
        upload_sessions.create_upload(1, "empty.txt", 0, "0" * 64, "text/plain")
    with pytest.raises(ValueError, match="文件类型"):
        upload_sessions.create_upload(1, "payload.exe", 1, "0" * 64, "application/octet-stream")
    with pytest.raises(ValueError, match="SHA-256"):
        upload_sessions.create_upload(1, "notes.txt", 1, "bad", "text/plain")
