from datetime import datetime, timedelta, timezone

from app.database import SessionLocal
from app.models import CapeCase, Message, MessageEvidence


def login(client, username: str, password: str) -> None:
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200


def test_case_lifecycle_filters_timeline_and_multiple_conversations(client, create_user, create_conversation_for_user) -> None:
    user = create_user(username="analyst", password="StrongPass123!")
    first = create_conversation_for_user(user=user, title="Initial triage", messages=[("user", "inspect")])
    second = create_conversation_for_user(user=user, title="Reverse engineering")
    with SessionLocal() as db:
        db.add(CapeCase(conversation_id=second.id, owner_user_id=user.id, cape_task_id=44, sample_name="dropper.exe", status="reported"))
        db.commit()
    login(client, "analyst", "StrongPass123!")

    created = client.post("/api/cases", json={
        "title": "Suspicious endpoint activity", "severity": "high", "priority": 1,
        "tags": ["endpoint", "malware"], "assignee": "SOC-L1",
        "slaDueAt": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
        "conversationIds": [first.id, second.id],
    })
    assert created.status_code == 201
    case = created.json()
    assert case["conversationCount"] == 2
    assert case["capeTaskCount"] == 1
    assert case["overdue"] is True
    assert case["timeline"][0]["eventType"] == "created"

    case_id = case["id"]
    updated = client.patch(f"/api/cases/{case_id}", json={"status": "investigating", "summary": "Confirmed malicious behavior."})
    assert updated.status_code == 200
    assert updated.json()["status"] == "investigating"
    assert updated.json()["timeline"][0]["eventType"] == "status_changed"

    filtered = client.get("/api/cases?status=investigating&severity=high&tag=malware&overdue=true")
    assert filtered.status_code == 200
    assert [item["id"] for item in filtered.json()["items"]] == [case_id]
    assert filtered.json()["counts"]["investigating"] == 1


def test_cases_are_owner_scoped_and_support_parent_merge(client, create_user, create_conversation_for_user) -> None:
    alice = create_user(username="alice-cases", password="StrongPass123!")
    bob = create_user(username="bob-cases", password="StrongPass123!")
    conversation = create_conversation_for_user(user=alice, title="Alice evidence")
    login(client, "alice-cases", "StrongPass123!")
    parent = client.post("/api/cases", json={"title": "Campaign"}).json()
    child = client.post("/api/cases", json={"title": "Duplicate alert", "parentCaseId": parent["id"], "conversationIds": [conversation.id]}).json()
    assert child["parentCaseId"] == parent["id"]
    assert client.post(f"/api/cases/{child['id']}/merge", json={"targetCaseId": child["id"]}).status_code == 400

    merged = client.post(f"/api/cases/{child['id']}/merge", json={"targetCaseId": parent["id"]})
    assert merged.status_code == 200
    assert merged.json()["conversationCount"] == 1
    assert client.get("/api/cases").json()["items"][0]["id"] == parent["id"]

    client.post("/api/auth/logout")
    login(client, "bob-cases", "StrongPass123!")
    assert client.get(f"/api/cases/{parent['id']}").status_code == 404
    assert client.post("/api/cases", json={"title": "Stolen link", "conversationIds": [conversation.id]}).status_code == 400


def test_case_evidence_review_conclusion_signature_and_export(client, create_user, create_conversation_for_user, monkeypatch) -> None:
    user = create_user(username="evidence-analyst", password="StrongPass123!")
    linked = create_conversation_for_user(user=user, title="Linked evidence", messages=[("assistant", "Finding [W1]")])
    unrelated = create_conversation_for_user(user=user, title="Other evidence", messages=[("assistant", "Other [W2]")])
    with SessionLocal() as db:
        linked_message = db.query(Message).filter(Message.conversation_id == linked.id).one()
        other_message = db.query(Message).filter(Message.conversation_id == unrelated.id).one()
        linked_evidence = MessageEvidence(message_id=linked_message.id, source_type="web", citation="W1", title="Threat report", url="https://example.test/report", snippet="Malicious activity observed")
        other_evidence = MessageEvidence(message_id=other_message.id, source_type="web", citation="W2", title="Unrelated report", url="https://other.test/report")
        db.add_all([linked_evidence, other_evidence]); db.commit(); db.refresh(linked_evidence); db.refresh(other_evidence)
        linked_evidence_id, other_evidence_id = linked_evidence.id, other_evidence.id
    login(client, "evidence-analyst", "StrongPass123!")
    case_id = client.post("/api/cases", json={"title": "Evidence case", "conversationIds": [linked.id]}).json()["id"]

    assert client.patch(f"/api/cases/{case_id}/evidence/{linked_evidence_id}", json={"reviewStatus": "verified", "sourceTrust": 101, "confidence": 90}).status_code == 422
    reviewed = client.patch(f"/api/cases/{case_id}/evidence/{linked_evidence_id}", json={"reviewStatus": "verified", "sourceTrust": 88, "confidence": 92, "contentHash": "a" * 64, "snapshotUrl": "https://archive.test/report", "reviewNote": "Cross-checked with telemetry"})
    assert reviewed.status_code == 200
    assert reviewed.json()["reviewStatus"] == "verified"
    assert client.patch(f"/api/cases/{case_id}/evidence/{other_evidence_id}", json={"reviewStatus": "rejected", "sourceTrust": 20, "confidence": 10}).status_code == 404

    assert client.post(f"/api/cases/{case_id}/conclusions", json={"statement": "Bad link", "evidenceIds": [other_evidence_id]}).status_code == 400
    conclusion = client.post(f"/api/cases/{case_id}/conclusions", json={"statement": "Activity is malicious", "status": "verified", "confidence": 94, "claimType": "inference", "confidenceRationale": "Telemetry and threat reporting agree", "evidenceIds": [linked_evidence_id], "conflictEvidenceIds": [], "crossChecks": [{"modelId": "review-model", "verdict": "supports", "confidence": 91, "rationale": "Independent review reached the same attribution"}]})
    assert conclusion.status_code == 201
    assert conclusion.json()["conclusions"][0]["evidenceIds"] == [linked_evidence_id]
    explainable = conclusion.json()["conclusions"][0]
    assert explainable["claimType"] == "inference"
    assert explainable["confidenceRationale"] == "Telemetry and threat reporting agree"
    assert explainable["crossChecks"][0]["verdict"] == "supports"
    assert explainable["reviewedBy"] == "evidence-analyst"

    async def fake_cross_check(messages, model):
        assert model == "claude-sonnet-4-6-az"
        assert "Malicious activity observed" in messages[0]["content"]
        yield '{"verdict":"supports","confidence":89,"rationale":"The verified source directly supports the conclusion."}'

    monkeypatch.setattr("app.routes.cases.stream_chat_completion", fake_cross_check)
    checked = client.post(f"/api/cases/{case_id}/conclusions/{explainable['id']}/cross-check", json={"modelId": "claude-sonnet-4-6-az"})
    assert checked.status_code == 200
    assert checked.json()["conclusions"][0]["crossChecks"][-1]["modelId"] == "claude-sonnet-4-6-az"
    assert checked.json()["conclusions"][0]["crossChecks"][-1]["confidence"] == 89
    assert any(event["eventType"] == "conclusion_cross_checked" for event in checked.json()["auditTrail"])

    signed = client.post(f"/api/cases/{case_id}/signatures", json={"signer": "SOC Lead", "note": "Approved"})
    assert signed.status_code == 201
    digest = signed.json()["signatures"][0]["digest"]
    assert signed.json()["signatures"][0]["isValid"] is True
    changed = client.patch(f"/api/cases/{case_id}/evidence/{linked_evidence_id}", json={"reviewStatus": "verified", "sourceTrust": 90, "confidence": 95, "contentHash": "a" * 64})
    assert changed.status_code == 200
    chain = client.get(f"/api/cases/{case_id}/evidence-chain").json()
    assert chain["signatures"][0]["isValid"] is False
    assert chain["currentDigest"] != digest

    exported = client.get(f"/api/cases/{case_id}/evidence-chain/export")
    assert exported.status_code == 200
    assert "attachment" in exported.headers["content-disposition"]
    assert any(event["eventType"] == "evidence_chain_exported" for event in exported.json()["auditTrail"])


def test_case_iocs_sync_deduplicate_update_bulk_and_export(client, create_user, create_conversation_for_user) -> None:
    user = create_user(username="ioc-analyst", password="StrongPass123!")
    conversation = create_conversation_for_user(user=user, title="IOC evidence")
    with SessionLocal() as db:
        db.add_all([
            CapeCase(conversation_id=conversation.id, owner_user_id=user.id, cape_task_id=101, sample_name="first.exe", status="reported", sha256="A" * 64, summary_json='{"taskId":101,"status":"reported","score":8.0,"tactics":[],"droppedFiles":[],"signatures":[],"iocs":{"domains":["Evil.Example.","evil.example"],"ips":["1.2.3.4"],"urls":["HTTP://evil.example/a#fragment"]}}'),
            CapeCase(conversation_id=conversation.id, owner_user_id=user.id, cape_task_id=102, sample_name="second.exe", status="reported", summary_json='{"taskId":102,"status":"reported","score":7.0,"tactics":[],"droppedFiles":[],"signatures":[],"iocs":{"domains":["evil.example"],"ips":["1.2.3.4"],"urls":[]}}'),
        ])
        db.commit()
    login(client, "ioc-analyst", "StrongPass123!")
    case_id = client.post("/api/cases", json={"title": "IOC case", "conversationIds": [conversation.id]}).json()["id"]
    synced = client.post(f"/api/cases/{case_id}/iocs/sync")
    assert synced.status_code == 200
    assert synced.json()["total"] == 4
    domain = next(item for item in synced.json()["items"] if item["type"] == "domain")

    updated = client.patch(f"/api/cases/{case_id}/iocs/{domain['id']}", json={"riskLevel": "critical", "confidence": 91, "status": "malicious"})
    assert updated.status_code == 200
    assert updated.json()["confidence"] == 91
    assert client.post(f"/api/cases/{case_id}/iocs/sync").json()["total"] == 4
    assert client.get(f"/api/cases/{case_id}/iocs?risk=critical").json()["items"][0]["status"] == "malicious"

    ip_item = next(item for item in synced.json()["items"] if item["type"] == "ip")
    bulk = client.post(f"/api/cases/{case_id}/iocs/bulk-status", json={"ids": [ip_item["id"]], "status": "blocked"})
    assert bulk.status_code == 200
    exported = client.get(f"/api/cases/{case_id}/iocs/export?format=firewall")
    assert exported.status_code == 200
    assert "1.2.3.4" in exported.text and "evil.example" in exported.text

    case_detail = client.get(f"/api/cases/{case_id}").json()
    assert case_detail["iocCount"] == 4


def test_case_analysis_unifies_cape_iocs_process_network_and_uncertain_times(client, create_user, create_conversation_for_user) -> None:
    user = create_user(username="timeline-analyst", password="StrongPass123!")
    conversation = create_conversation_for_user(user=user, title="Behavior evidence")
    summary = {
        "taskId": 601, "status": "reported", "score": 8.4,
        "iocs": {"domains": ["command.example"], "ips": ["203.0.113.8"], "urls": []},
        "processes": [{"pid": 1440, "name": "powershell.exe", "commandLine": "powershell -enc AAA", "startedAt": "2026-08-08T01:02:03Z"}],
        "networkConnections": [{"pid": 1440, "domain": "command.example", "protocol": "https"}],
        "droppedFiles": [{"name": "stage.dll", "path": "C:\\Users\\Public\\stage.dll", "type": "PE32", "sha256": "c" * 64}],
        "tactics": [{"technique": "T1059.001", "signature": "PowerShell", "description": "Encoded command"}],
        "signatures": [{"name": "encoded_powershell", "description": "Encoded PowerShell execution"}],
    }
    with SessionLocal() as db:
        db.add(CapeCase(conversation_id=conversation.id, owner_user_id=user.id, cape_task_id=601, sample_name="loader.exe", status="reported", score=8.4, sha256="b" * 64, summary_json=__import__("json").dumps(summary)))
        db.commit()
    login(client, "timeline-analyst", "StrongPass123!")
    case_id = client.post("/api/cases", json={"title": "Unified analysis", "severity": "high", "conversationIds": [conversation.id]}).json()["id"]

    response = client.get(f"/api/cases/{case_id}/analysis")
    assert response.status_code == 200
    payload = response.json()
    assert {"events", "graph", "coverage"} <= payload.keys()
    assert {event["type"] for event in payload["events"]} >= {"sample", "process", "network", "file", "attack", "behavior", "ioc"}
    assert {node["type"] for node in payload["graph"]["nodes"]} >= {"case", "sample", "process", "domain", "file", "attack"}
    assert any(edge["relation"] == "connects_to" for edge in payload["graph"]["edges"])
    process_event = next(event for event in payload["events"] if event["type"] == "process")
    network_event = next(event for event in payload["events"] if event["type"] == "network")
    assert process_event["timeAccuracy"] == "exact"
    assert network_event["timeAccuracy"] == "estimated"
    assert network_event["timeNote"]
    assert payload["coverage"]["estimatedTimes"] > 0


def test_case_analysis_is_access_scoped(client, create_user) -> None:
    alice = create_user(username="analysis-owner", password="StrongPass123!")
    create_user(username="analysis-outsider", password="StrongPass123!")
    login(client, "analysis-owner", "StrongPass123!")
    case_id = client.post("/api/cases", json={"title": "Private graph"}).json()["id"]
    client.post("/api/auth/logout")
    login(client, "analysis-outsider", "StrongPass123!")
    assert client.get(f"/api/cases/{case_id}/analysis").status_code == 404


def test_detection_rule_validation_lifecycle_testing_and_reports(client, create_user, create_conversation_for_user) -> None:
    user = create_user(username="rule-analyst", password="StrongPass123!")
    conversation = create_conversation_for_user(user=user, title="Detection engineering")
    with SessionLocal() as db:
        db.add(CapeCase(
            conversation_id=conversation.id,
            owner_user_id=user.id,
            cape_task_id=501,
            sample_name="loader.exe",
            status="reported",
            sha256="b" * 64,
            summary_json='{"taskId":501,"status":"reported","score":8.8,"tactics":[{"technique":"T1059.001","signature":"powershell -enc","description":"Encoded PowerShell"}],"droppedFiles":[],"signatures":[{"name":"cipher-malware-marker"}],"iocs":{"domains":[],"ips":[],"urls":[]}}',
        ))
        db.commit()
    login(client, "rule-analyst", "StrongPass123!")
    case_id = client.post("/api/cases", json={"title": "Rule case", "conversationIds": [conversation.id]}).json()["id"]

    generated = client.post(f"/api/cases/{case_id}/rules/generate", json={"ruleTypes": ["sigma", "yara"]})
    assert generated.status_code == 200
    assert len(generated.json()["items"]) == 2
    sigma_rule = next(item for item in generated.json()["items"] if item["ruleType"] == "sigma")

    validated = client.post(f"/api/cases/{case_id}/rules/{sigma_rule['id']}/validate")
    assert validated.status_code == 200
    assert validated.json()["status"] == "validated"
    assert "splunk" in validated.json()["validation"]["conversions"]

    tested = client.post(
        f"/api/cases/{case_id}/rules/{sigma_rule['id']}/test",
        files=[("files", ("positive.log", b"cmd.exe /c powershell -enc AAA", "text/plain"))],
    )
    assert tested.status_code == 200
    assert tested.json()["matchedArtifacts"] == 1

    approved = client.patch(f"/api/cases/{case_id}/rules/{sigma_rule['id']}", json={"status": "approved"})
    assert approved.status_code == 200
    deployed = client.patch(f"/api/cases/{case_id}/rules/{sigma_rule['id']}", json={"status": "deployed"})
    assert deployed.status_code == 200

    html = client.get(f"/api/cases/{case_id}/rules/{sigma_rule['id']}/export?format=html")
    pdf = client.get(f"/api/cases/{case_id}/rules/{sigma_rule['id']}/export?format=pdf")
    assert html.status_code == 200 and "Splunk" in html.text
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
