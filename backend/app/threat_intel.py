from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from typing import Any
from urllib.parse import quote

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import ThreatIntelCache


SUPPORTED_TYPES = {"domain", "ip", "url", "md5", "sha1", "sha256"}


@dataclass(frozen=True)
class ProviderConfig:
    enabled: bool = False
    api_key: str = ""
    base_url: str = ""
    timeout_seconds: float = 10.0
    rate_limit_per_minute: int = 30
    cache_ttl_seconds: int = 3600
    stale_ttl_seconds: int = 86400
    headers: dict[str, str] | None = None
    type_map: dict[str, str] | None = None


class ProviderError(RuntimeError):
    pass


class ProviderRateLimited(ProviderError):
    pass


class ThreatIntelProvider(ABC):
    key: str
    display_name: str
    supported_types: set[str] = SUPPORTED_TYPES

    def __init__(self, config: ProviderConfig):
        self.config = config

    @abstractmethod
    async def lookup(self, indicator_type: str, value: str) -> dict[str, Any]: ...

    def normalize(self, *, confidence: int, malicious: bool | None, tags: list[str], external_url: str | None,
                  updated_at: str | None = None, raw: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "provider": self.key, "source": self.display_name, "confidence": max(0, min(100, confidence)),
            "malicious": malicious, "tags": list(dict.fromkeys(str(tag)[:80] for tag in tags if tag))[:20],
            "externalUrl": external_url, "updatedAt": updated_at, "raw": raw or {},
        }

    async def request_json(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
                response = await client.request(method, url, **kwargs)
            if response.status_code == 429:
                raise ProviderRateLimited(f"{self.display_name} rate limit exceeded")
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ProviderError(f"{self.display_name} returned an invalid payload")
            return payload
        except ProviderError:
            raise
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise ProviderError(f"{self.display_name} lookup failed") from exc


class VirusTotalProvider(ThreatIntelProvider):
    key, display_name = "virustotal", "VirusTotal"

    async def lookup(self, indicator_type: str, value: str) -> dict[str, Any]:
        object_type = {"domain": "domains", "ip": "ip_addresses", "md5": "files", "sha1": "files", "sha256": "files", "url": "urls"}[indicator_type]
        object_id = hashlib.sha256(value.encode()).hexdigest() if indicator_type == "url" else quote(value, safe="")
        payload = await self.request_json("GET", f"{self.config.base_url.rstrip('/')}/api/v3/{object_type}/{object_id}", headers={"x-apikey": self.config.api_key})
        attributes = payload.get("data", {}).get("attributes", {})
        stats = attributes.get("last_analysis_stats", {})
        malicious_count = int(stats.get("malicious", 0)) + int(stats.get("suspicious", 0))
        total = sum(int(item) for item in stats.values() if isinstance(item, (int, float)))
        confidence = round(malicious_count * 100 / total) if total else 0
        return self.normalize(confidence=confidence, malicious=malicious_count > 0 if total else None,
            tags=attributes.get("tags", []) or attributes.get("categories", {}).values(),
            external_url=f"https://www.virustotal.com/gui/{object_type[:-1]}/{object_id}",
            updated_at=_timestamp(attributes.get("last_analysis_date")), raw={"analysisStats": stats})


class AbuseIPDBProvider(ThreatIntelProvider):
    key, display_name, supported_types = "abuseipdb", "AbuseIPDB", {"ip"}

    async def lookup(self, indicator_type: str, value: str) -> dict[str, Any]:
        payload = await self.request_json("GET", f"{self.config.base_url.rstrip('/')}/api/v2/check",
            headers={"Key": self.config.api_key, "Accept": "application/json"}, params={"ipAddress": value, "maxAgeInDays": 90})
        data = payload.get("data", {})
        confidence = int(data.get("abuseConfidenceScore", 0))
        tags = ["public" if data.get("isPublic") else "private", data.get("usageType"), data.get("countryCode")]
        return self.normalize(confidence=confidence, malicious=confidence >= 50, tags=tags,
            external_url=f"https://www.abuseipdb.com/check/{quote(value, safe='')}", updated_at=data.get("lastReportedAt"),
            raw={"reports": data.get("totalReports", 0), "distinctUsers": data.get("numDistinctUsers", 0)})


class OTXProvider(ThreatIntelProvider):
    key, display_name = "otx", "AlienVault OTX"

    async def lookup(self, indicator_type: str, value: str) -> dict[str, Any]:
        section = {"domain": "domain", "ip": "IPv4", "url": "url", "md5": "file", "sha1": "file", "sha256": "file"}[indicator_type]
        payload = await self.request_json("GET", f"{self.config.base_url.rstrip('/')}/api/v1/indicators/{section}/{quote(value, safe='')}/general", headers={"X-OTX-API-KEY": self.config.api_key})
        pulse = payload.get("pulse_info", {})
        count = int(pulse.get("count", 0))
        tags = [tag for item in pulse.get("pulses", []) for tag in item.get("tags", [])]
        return self.normalize(confidence=min(100, count * 20), malicious=count > 0, tags=tags,
            external_url=f"https://otx.alienvault.com/indicator/{section}/{quote(value, safe='')}",
            updated_at=pulse.get("pulses", [{}])[0].get("modified") if pulse.get("pulses") else None, raw={"pulseCount": count})


class MISPProvider(ThreatIntelProvider):
    key, display_name = "misp", "MISP"

    async def lookup(self, indicator_type: str, value: str) -> dict[str, Any]:
        payload = await self.request_json("POST", f"{self.config.base_url.rstrip('/')}/attributes/restSearch",
            headers={"Authorization": self.config.api_key, "Accept": "application/json", "Content-Type": "application/json"},
            json={"returnFormat": "json", "value": value, "type": {"domain": "domain", "ip": "ip-dst", "url": "url", "md5": "md5", "sha1": "sha1", "sha256": "sha256"}[indicator_type], "limit": 50})
        attributes = payload.get("response", {}).get("Attribute", payload.get("Attribute", []))
        if not isinstance(attributes, list): attributes = []
        tags = [tag.get("name") for item in attributes for tag in item.get("Tag", []) if isinstance(tag, dict)]
        confidence = min(100, len(attributes) * 20)
        event_id = attributes[0].get("event_id") if attributes else None
        return self.normalize(confidence=confidence, malicious=bool(attributes), tags=tags,
            external_url=f"{self.config.base_url.rstrip('/')}/events/view/{event_id}" if event_id else self.config.base_url,
            updated_at=_timestamp(max((int(item.get("timestamp", 0)) for item in attributes), default=0)), raw={"attributeCount": len(attributes)})


class GreyNoiseProvider(ThreatIntelProvider):
    key, display_name, supported_types = "greynoise", "GreyNoise", {"ip"}

    async def lookup(self, indicator_type: str, value: str) -> dict[str, Any]:
        payload = await self.request_json("GET", f"{self.config.base_url.rstrip('/')}/v3/community/{quote(value, safe='')}", headers={"key": self.config.api_key, "Accept": "application/json"})
        classification = payload.get("classification")
        malicious = True if classification == "malicious" else False if classification in {"benign", "unknown"} else None
        return self.normalize(confidence=90 if malicious else 20, malicious=malicious,
            tags=[classification, payload.get("name"), "riot" if payload.get("riot") else "noise" if payload.get("noise") else None],
            external_url=f"https://viz.greynoise.io/ip/{quote(value, safe='')}", updated_at=payload.get("last_seen"), raw={"message": payload.get("message")})


class CustomHTTPProvider(ThreatIntelProvider):
    def __init__(self, key: str, config: ProviderConfig):
        self.key, self.display_name = key, key
        self.supported_types = set((config.type_map or {}).keys()) or SUPPORTED_TYPES
        super().__init__(config)

    async def lookup(self, indicator_type: str, value: str) -> dict[str, Any]:
        url = self.config.base_url.format(type=quote(indicator_type), value=quote(value, safe=""))
        headers = {str(key): str(item).replace("{api_key}", self.config.api_key) for key, item in (self.config.headers or {}).items()}
        payload = await self.request_json("GET", url, headers=headers)
        return self.normalize(confidence=int(payload.get("confidence", 0)), malicious=payload.get("malicious"),
            tags=payload.get("tags", []), external_url=payload.get("externalUrl"), updated_at=payload.get("updatedAt"), raw=payload.get("raw", {}))


class MinuteRateLimiter:
    def __init__(self): self._calls: dict[str, deque[float]] = defaultdict(deque); self._lock = asyncio.Lock()
    async def acquire(self, key: str, limit: int) -> None:
        async with self._lock:
            now = asyncio.get_running_loop().time(); calls = self._calls[key]
            while calls and calls[0] <= now - 60: calls.popleft()
            if len(calls) >= limit: raise ProviderRateLimited(f"{key} local rate limit exceeded")
            calls.append(now)


def _timestamp(value: Any) -> str | None:
    if not value: return None
    if isinstance(value, (int, float)): return datetime.fromtimestamp(value, timezone.utc).isoformat()
    return str(value)


def _configs() -> dict[str, ProviderConfig]:
    try: raw = json.loads(settings.ioc_provider_config_json or "{}")
    except (ValueError, TypeError): raw = {}
    if not isinstance(raw, dict): raw = {}
    defaults = {
        "virustotal": {"apiKey": settings.virustotal_api_key, "baseUrl": "https://www.virustotal.com"},
        "abuseipdb": {"baseUrl": "https://api.abuseipdb.com"}, "otx": {"baseUrl": "https://otx.alienvault.com"},
        "misp": {"apiKey": settings.misp_api_key, "baseUrl": settings.misp_url}, "greynoise": {"baseUrl": "https://api.greynoise.io"},
    }
    result = {}
    for key, supplied in {**defaults, **raw}.items():
        merged = {**defaults.get(key, {}), **(supplied if isinstance(supplied, dict) else {})}
        result[key] = ProviderConfig(enabled=bool(merged.get("enabled", False)), api_key=str(merged.get("apiKey", "")),
            base_url=str(merged.get("baseUrl", "")), timeout_seconds=float(merged.get("timeoutSeconds", 10)),
            rate_limit_per_minute=max(1, int(merged.get("rateLimitPerMinute", 30))), cache_ttl_seconds=max(1, int(merged.get("cacheTtlSeconds", 3600))),
            stale_ttl_seconds=max(0, int(merged.get("staleTtlSeconds", 86400))), headers=merged.get("headers"), type_map=merged.get("typeMap"))
    return result


class ThreatIntelService:
    def __init__(self): self.rate_limiter = MinuteRateLimiter()

    def providers(self) -> dict[str, ThreatIntelProvider]:
        configs = _configs(); classes = {"virustotal": VirusTotalProvider, "abuseipdb": AbuseIPDBProvider, "otx": OTXProvider, "misp": MISPProvider, "greynoise": GreyNoiseProvider}
        return {key: classes[key](config) if key in classes else CustomHTTPProvider(key, config) for key, config in configs.items() if config.enabled and config.base_url}

    def public_status(self) -> list[dict[str, Any]]:
        configs = _configs()
        return [{"key": key, "enabled": config.enabled, "configured": bool(config.base_url and (config.api_key or key.startswith("custom"))),
                 "supportedTypes": sorted((self.providers().get(key) or CustomHTTPProvider(key, config)).supported_types)} for key, config in configs.items()]

    async def enrich(self, db: Session, indicator_type: str, value: str, *, provider_keys: list[str] | None = None, force: bool = False) -> dict[str, Any]:
        providers = self.providers()
        if provider_keys is not None: providers = {key: item for key, item in providers.items() if key in provider_keys}
        now = datetime.now(timezone.utc); results, errors = [], []
        if not providers:
            errors.append({"provider": "system", "message": "No IOC providers are enabled"})
        for key, provider in providers.items():
            if indicator_type not in provider.supported_types: continue
            cache = db.execute(select(ThreatIntelCache).where(ThreatIntelCache.provider == key, ThreatIntelCache.indicator_type == indicator_type, ThreatIntelCache.normalized_value == value)).scalar_one_or_none()
            if cache and not force and _aware(cache.expires_at) > now:
                item = json.loads(cache.result_json); item.update({"cached": True, "stale": False}); results.append(item); continue
            try:
                await self.rate_limiter.acquire(key, provider.config.rate_limit_per_minute)
                item = await provider.lookup(indicator_type, value); fetched_at = now.isoformat()
                item["updatedAt"] = item.get("updatedAt") or fetched_at; item.update({"fetchedAt": fetched_at, "cached": False, "stale": False})
                expires = now + timedelta(seconds=provider.config.cache_ttl_seconds); stale_until = expires + timedelta(seconds=provider.config.stale_ttl_seconds)
                if cache is None:
                    cache = ThreatIntelCache(provider=key, indicator_type=indicator_type, normalized_value=value, result_json="{}", fetched_at=now, expires_at=expires, stale_until=stale_until); db.add(cache)
                cache.result_json, cache.fetched_at, cache.expires_at, cache.stale_until = json.dumps(item, ensure_ascii=False), now, expires, stale_until
                results.append(item)
            except ProviderError as exc:
                errors.append({"provider": key, "message": str(exc)})
                if cache and _aware(cache.stale_until) > now:
                    item = json.loads(cache.result_json); item.update({"cached": True, "stale": True}); results.append(item)
        db.flush()
        return {"results": results, "errors": errors, "queriedAt": now.isoformat()}


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


threat_intel_service = ThreatIntelService()
