from __future__ import annotations

import asyncio
from datetime import timedelta

from sqlalchemy import select

from app.database import SessionLocal
from app.models import ThreatIntelCache, now_utc
from app.threat_intel import ProviderConfig, ProviderError, ThreatIntelProvider, ThreatIntelService


class FakeProvider(ThreatIntelProvider):
    key, display_name = "fake", "Fake Intel"

    def __init__(self, *, fail: bool = False):
        super().__init__(ProviderConfig(enabled=True, base_url="https://intel.test", cache_ttl_seconds=60, stale_ttl_seconds=300))
        self.fail = fail
        self.calls = 0

    async def lookup(self, indicator_type: str, value: str):
        self.calls += 1
        if self.fail:
            raise ProviderError("fake unavailable")
        return self.normalize(confidence=88, malicious=True, tags=["c2"], external_url="https://intel.test/result")


def test_threat_intel_cache_hit_and_stale_fallback(client, monkeypatch) -> None:
    service = ThreatIntelService(); provider = FakeProvider()
    monkeypatch.setattr(service, "providers", lambda: {"fake": provider})
    with SessionLocal() as db:
        first = asyncio.run(service.enrich(db, "domain", "cache-test.example")); db.commit()
        second = asyncio.run(service.enrich(db, "domain", "cache-test.example"))
        assert first["results"][0]["cached"] is False
        assert second["results"][0]["cached"] is True
        assert provider.calls == 1

        cache = db.execute(select(ThreatIntelCache).where(ThreatIntelCache.normalized_value == "cache-test.example")).scalar_one()
        cache.expires_at = now_utc() - timedelta(seconds=1); cache.stale_until = now_utc() + timedelta(minutes=5); db.commit()
        failing = FakeProvider(fail=True); monkeypatch.setattr(service, "providers", lambda: {"fake": failing})
        degraded = asyncio.run(service.enrich(db, "domain", "cache-test.example"))
        assert degraded["results"][0]["stale"] is True
        assert degraded["errors"][0]["provider"] == "fake"


def test_ioc_enrichment_requires_write_access_and_hides_keys(client, create_user, create_conversation_for_user, monkeypatch) -> None:
    from app.threat_intel import threat_intel_service
    from app.models import CapeCase, CaseAccess

    def login(username: str, password: str) -> None:
        assert client.post("/api/auth/login", json={"username": username, "password": password}).status_code == 200

    owner = create_user(username="intel-owner", password="StrongPass123!")
    viewer = create_user(username="intel-viewer", password="StrongPass123!")
    conversation = create_conversation_for_user(user=owner, title="Intel")
    with SessionLocal() as db:
        db.add(CapeCase(conversation_id=conversation.id, owner_user_id=owner.id, cape_task_id=991, sample_name="intel.exe", status="reported", summary_json='{"taskId":991,"status":"reported","score":8.0,"tactics":[],"droppedFiles":[],"signatures":[],"iocs":{"domains":["intel.example"],"ips":[],"urls":[]}}'))
        db.commit()
    login("intel-owner", "StrongPass123!")
    case_id = client.post("/api/cases", json={"title": "Intel case", "conversationIds": [conversation.id]}).json()["id"]
    indicator = client.post(f"/api/cases/{case_id}/iocs/sync").json()["items"][0]
    with SessionLocal() as db:
        db.add(CaseAccess(case_id=case_id, user_id=viewer.id, permission="viewer", created_by_user_id=owner.id)); db.commit()
    login("intel-viewer", "StrongPass123!")
    assert client.get(f"/api/cases/{case_id}/iocs").status_code == 200
    assert client.post(f"/api/cases/{case_id}/iocs/{indicator['id']}/enrich", json={}).status_code == 403
    response = client.get(f"/api/cases/{case_id}/ioc-providers")
    assert response.status_code == 200
    assert "apiKey" not in response.text and "api_key" not in response.text
