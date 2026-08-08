from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from app.config import settings


class CapeConfigurationError(RuntimeError):
    pass


class CapeUpstreamError(RuntimeError):
    pass


@dataclass(frozen=True)
class CapeClientConfig:
    base_url: str
    api_token: str
    submit_timeout_seconds: float
    query_timeout_seconds: float


def build_cape_client_config() -> CapeClientConfig:
    base_url = settings.cape_base_url.strip().rstrip("/")
    if not base_url:
        raise CapeConfigurationError("CAPE base URL is not configured.")

    return CapeClientConfig(
        base_url=base_url,
        api_token=settings.cape_api_token.strip(),
        submit_timeout_seconds=settings.cape_submit_timeout_seconds,
        query_timeout_seconds=settings.cape_query_timeout_seconds,
    )


def build_cape_headers(api_token: str) -> dict[str, str]:
    headers = {
        "Accept": "application/json",
    }
    if api_token:
        headers["Authorization"] = f"Token {api_token}"
    return headers


def _normalize_upstream_error(exc: httpx.HTTPError) -> CapeUpstreamError:
    if isinstance(exc, httpx.HTTPStatusError):
        response_text = exc.response.text.strip()
        message = response_text or f"CAPE request failed with status {exc.response.status_code}."
        return CapeUpstreamError(message)

    return CapeUpstreamError(str(exc) or "CAPE request failed.")


class CapeClient:
    def __init__(
        self,
        *,
        config: CapeClientConfig | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._config = config or build_cape_client_config()
        self._client = client

    async def submit_file(
        self,
        *,
        filename: str,
        content: bytes,
        machine: str | None = None,
        platform: str | None = None,
        tags: list[str] | None = None,
        route: str | None = None,
        is_pcap: bool = False,
    ) -> dict[str, Any]:
        form_data: dict[str, Any] = {}
        if machine:
            form_data["machine"] = machine
        if platform:
            form_data["platform"] = platform
        if tags:
            form_data["tags"] = ",".join(tag.strip() for tag in tags if tag.strip())
        if route:
            form_data["route"] = route
        if is_pcap:
            form_data["pcap"] = "1"

        files = {
            "file": (filename, content, "application/octet-stream"),
        }
        return await self._request(
            "POST",
            "/apiv2/tasks/create/file/",
            timeout_seconds=self._config.submit_timeout_seconds,
            data=form_data,
            files=files,
        )

    async def get_task_status(self, task_id: int) -> dict[str, Any]:
        return await self._request(
            "GET",
            f"/apiv2/tasks/status/{task_id}/",
            timeout_seconds=self._config.query_timeout_seconds,
        )

    async def get_task_view(self, task_id: int) -> dict[str, Any]:
        return await self._request(
            "GET",
            f"/apiv2/tasks/view/{task_id}/",
            timeout_seconds=self._config.query_timeout_seconds,
        )

    async def get_task_report(self, task_id: int) -> dict[str, Any]:
        return await self._request(
            "GET",
            f"/apiv2/tasks/get/report/{task_id}/json/",
            timeout_seconds=self._config.query_timeout_seconds,
        )

    async def list_tasks(self, *, limit: int = 10, offset: int = 0) -> dict[str, Any]:
        return await self._request(
            "GET",
            "/apiv2/tasks/list/",
            timeout_seconds=self._config.query_timeout_seconds,
            params={"limit": limit, "offset": offset},
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        timeout_seconds: float,
        **kwargs: Any,
    ) -> dict[str, Any]:
        client = self._client or httpx.AsyncClient(
            base_url=self._config.base_url,
            headers=build_cape_headers(self._config.api_token),
            timeout=httpx.Timeout(timeout_seconds, connect=min(timeout_seconds, 10.0)),
        )
        owns_client = self._client is None

        try:
            response = await client.request(method, path, **kwargs)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise CapeUpstreamError("CAPE returned a non-object JSON payload.")
            return payload
        except httpx.HTTPError as exc:
            raise _normalize_upstream_error(exc) from exc
        finally:
            if owns_client:
                await client.aclose()
