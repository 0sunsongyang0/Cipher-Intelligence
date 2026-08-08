from __future__ import annotations

import httpx
import pytest

from app.cape_client import (
    CapeClient,
    CapeClientConfig,
    CapeUpstreamError,
    build_cape_headers,
)
from app.cape_service import CapeService


def build_mock_client(handler) -> httpx.AsyncClient:
    transport = httpx.MockTransport(handler)
    return httpx.AsyncClient(
        transport=transport,
        base_url="http://127.0.0.1:8080",
        headers={"Authorization": "Token test-token"},
    )


def test_build_cape_headers_includes_token_when_configured() -> None:
    assert build_cape_headers("abc123") == {
        "Accept": "application/json",
        "Authorization": "Token abc123",
    }


def test_build_cape_headers_skips_auth_when_token_missing() -> None:
    assert build_cape_headers("") == {"Accept": "application/json"}


@pytest.mark.anyio
async def test_cape_client_submit_file_posts_expected_form_fields() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/apiv2/tasks/create/file/"
        body = (await request.aread()).decode("utf-8", errors="ignore")
        assert 'name="machine"' in body
        assert 'name="tags"' in body
        assert 'name="route"' in body
        assert 'name="pcap"' in body
        assert "sample.exe" in body
        return httpx.Response(200, json={"data": {"task_id": 42}, "status": "ok"})

    client = CapeClient(
        config=CapeClientConfig(
            base_url="http://127.0.0.1:8080",
            api_token="test-token",
            submit_timeout_seconds=10.0,
            query_timeout_seconds=5.0,
        ),
        client=build_mock_client(handler),
    )

    payload = await client.submit_file(
        filename="sample.exe",
        content=b"MZ",
        machine="win10",
        tags=["trojan", "cape"],
        route="internet",
        is_pcap=True,
    )

    assert payload == {"data": {"task_id": 42}, "status": "ok"}
    await client._client.aclose()


@pytest.mark.anyio
async def test_cape_client_raises_readable_upstream_error_on_http_failure() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="Forbidden")

    client = CapeClient(
        config=CapeClientConfig(
            base_url="http://127.0.0.1:8080",
            api_token="test-token",
            submit_timeout_seconds=10.0,
            query_timeout_seconds=5.0,
        ),
        client=build_mock_client(handler),
    )

    with pytest.raises(CapeUpstreamError, match="Forbidden"):
        await client.get_task_status(7)

    await client._client.aclose()


@pytest.mark.anyio
async def test_cape_service_normalizes_submission_snapshot_and_report() -> None:
    submitted = False

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal submitted
        if request.url.path == "/apiv2/tasks/create/file/":
            submitted = True
            return httpx.Response(
                200,
                json={"data": {"task_ids": [81], "message": "Task ID 81 has been submitted"}, "status": "created"},
            )
        if request.url.path == "/apiv2/tasks/status/81/":
            return httpx.Response(200, json={"data": "reported"})
        if request.url.path == "/apiv2/tasks/view/81/":
            return httpx.Response(
                200,
                json={
                    "task": {
                        "status": "reported",
                        "score": 7.5,
                        "sample": {"file_name": "payload.exe"},
                        "machine": {"name": "win11"},
                    }
                },
            )
        if request.url.path == "/apiv2/tasks/get/report/81/json/":
            return httpx.Response(
                200,
                json={
                    "info": {"status": "reported", "score": 7.5},
                    "target": {"file": {"name": "payload.exe", "sha256": "abc"}},
                    "network": {
                        "domains": [{"domain": "evil.example"}],
                        "hosts": [{"ip": "10.0.0.5"}],
                        "http": [{"uri": "http://evil.example/payload", "host": "evil.example", "method": "GET", "pid": 402}],
                    },
                    "behavior": {"processes": [{"process_id": 402, "parent_id": 100, "process_name": "payload.exe", "command_line": "payload.exe -s", "first_seen": "2026-08-08T01:02:03Z"}]},
                    "dropped": [
                        {
                            "name": "stage2.dll",
                            "filepath": "C:/Users/Test/stage2.dll",
                            "type": "PE32 DLL",
                            "sha256": "def",
                        }
                    ],
                    "signatures": [
                        {
                            "name": "creates_run_key",
                            "description": "Persists via run key",
                            "ttps": [{"ttp": "T1547.001"}],
                        }
                    ],
                },
            )
        raise AssertionError(f"Unexpected path: {request.url.path}")

    service = CapeService(
        CapeClient(
            config=CapeClientConfig(
                base_url="http://127.0.0.1:8080",
                api_token="test-token",
                submit_timeout_seconds=10.0,
                query_timeout_seconds=5.0,
            ),
            client=build_mock_client(handler),
        )
    )

    submission = await service.submit_file(filename="payload.exe", content=b"MZ")
    snapshot = await service.get_task_snapshot(81)
    summary = await service.get_analysis_summary(81)

    assert submitted is True
    assert submission.task_id == 81
    assert snapshot.completed is True
    assert snapshot.target_filename == "payload.exe"
    assert snapshot.machine == "win11"
    assert summary.sha256 == "abc"
    assert summary.iocs["domains"] == ["evil.example"]
    assert summary.iocs["ips"] == ["10.0.0.5"]
    assert summary.iocs["urls"] == ["http://evil.example/payload"]
    assert summary.tactics == [
        {
            "technique": "T1547.001",
            "signature": "creates_run_key",
            "description": "Persists via run key",
        }
    ]
    assert summary.dropped_files == [
        {
            "name": "stage2.dll",
            "path": "C:/Users/Test/stage2.dll",
            "type": "PE32 DLL",
            "sha256": "def",
        }
    ]
    assert summary.processes[0]["pid"] == 402
    assert summary.processes[0]["commandLine"] == "payload.exe -s"
    assert summary.network_connections[0]["domain"] == "evil.example"
    assert summary.network_connections[0]["pid"] == 402

    await service._client._client.aclose()


def test_coerce_task_id_accepts_nested_data_task_ids() -> None:
    from app.cape_service import _coerce_task_id

    assert _coerce_task_id({"data": {"task_ids": [12], "message": "Task ID 12 has been submitted"}}) == 12


def test_coerce_task_id_accepts_cape_string_and_url_fallbacks() -> None:
    from app.cape_service import _coerce_task_id

    assert _coerce_task_id({"data": {"task_ids": ["15"]}}) == 15
    assert _coerce_task_id({"data": {"message": "Task ID 16 has been submitted"}}) == 16
    assert _coerce_task_id({"url": ["http://example.tld/submit/status/17/"]}) == 17


def test_coerce_task_id_surfaces_cape_business_errors() -> None:
    from app.cape_service import _coerce_task_id

    with pytest.raises(ValueError, match="Rate limit"):
        _coerce_task_id({"error": True, "error_value": "Rate limit exceeded"})


@pytest.mark.anyio
async def test_cape_service_reuses_existing_task_when_cape_database_insert_fails() -> None:
    sample_content = b"MZ duplicate sample"

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/apiv2/tasks/create/file/":
            return httpx.Response(200, json={"error": True, "error_value": "Error adding task to database"})
        if request.url.path == "/apiv2/tasks/list/":
            return httpx.Response(
                200,
                json={
                    "data": [
                            {
                                "id": 15,
                                "status": "running",
                                "sample": {
                                    "sha256": "76f9bce5a4e512b20f71210a39b4d5ae20087857ddae3d9e78b2fa32668ee232"
                                },
                            }
                    ]
                },
            )
        raise AssertionError(f"Unexpected path: {request.url.path}")

    service = CapeService(
        CapeClient(
            config=CapeClientConfig(
                base_url="http://127.0.0.1:8080",
                api_token="test-token",
                submit_timeout_seconds=10.0,
                query_timeout_seconds=5.0,
            ),
            client=build_mock_client(handler),
        )
    )

    submission = await service.submit_file(filename="payload.exe", content=sample_content)

    assert submission.task_id == 15
    assert submission.status == "running"
    assert submission.raw["reusedExistingTask"] is True

    await service._client._client.aclose()


@pytest.mark.anyio
async def test_cape_service_surfaces_report_not_ready_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/apiv2/tasks/get/report/7/json/":
            return httpx.Response(200, json={"error": True, "error_value": "Task is still being analyzed"})
        raise AssertionError(f"Unexpected path: {request.url.path}")

    service = CapeService(
        CapeClient(
            config=CapeClientConfig(
                base_url="http://127.0.0.1:8080",
                api_token="test-token",
                submit_timeout_seconds=10.0,
                query_timeout_seconds=5.0,
            ),
            client=build_mock_client(handler),
        )
    )

    with pytest.raises(ValueError, match="Task is still being analyzed"):
        await service.get_analysis_summary(7)

    await service._client._client.aclose()


@pytest.mark.anyio
async def test_cape_service_normalizes_string_status_payload() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/apiv2/tasks/status/7/":
            return httpx.Response(200, json={"error": False, "data": "pending"})
        if request.url.path == "/apiv2/tasks/view/7/":
            return httpx.Response(
                200,
                json={
                    "task": {
                        "status": "pending",
                        "score": 0,
                        "sample": {"file_name": "payload.exe"},
                        "machine": {"name": "win10-x64"},
                    }
                },
            )
        raise AssertionError(f"Unexpected path: {request.url.path}")

    service = CapeService(
        CapeClient(
            config=CapeClientConfig(
                base_url="http://127.0.0.1:8080",
                api_token="test-token",
                submit_timeout_seconds=10.0,
                query_timeout_seconds=5.0,
            ),
            client=build_mock_client(handler),
        )
    )

    snapshot = await service.get_task_snapshot(7)

    assert snapshot.status == "pending"
    assert snapshot.completed is False
    assert snapshot.target_filename == "payload.exe"
    assert snapshot.machine == "win10-x64"

    await service._client._client.aclose()
