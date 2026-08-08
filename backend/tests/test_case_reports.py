from __future__ import annotations

import json

from app.database import SessionLocal
from app.models import CapeCase, Message, MessageEvidence


def login(client, username: str, password: str) -> None:
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200


def create_report_case(client, create_user, create_conversation_for_user) -> tuple[int, object]:
    owner = create_user(username="report-owner", password="StrongPass123!")
    conversation = create_conversation_for_user(user=owner, title="Malware investigation", messages=[("user", "analyze sample")])
    with SessionLocal() as db:
        message = db.query(Message).filter(Message.conversation_id == conversation.id).one()
        db.add(MessageEvidence(message_id=message.id, source_type="cape", citation="C1", title="CAPE behavior report",
                               locator="task:991", snippet="Run key persistence observed", review_status="verified",
                               source_trust=95, confidence=93, content_hash="b" * 64))
        db.add(CapeCase(conversation_id=conversation.id, owner_user_id=owner.id, cape_task_id=991,
                        sample_name="invoice.exe", status="reported", score=9.1, sha256="a" * 64,
                        summary_json=json.dumps({"taskId": 991, "status": "reported", "score": 9.1,
                                                 "submittedFilename": "invoice.exe", "sha256": "a" * 64,
                                                 "iocs": {"domains": ["evil.example"], "ips": ["203.0.113.9"], "urls": []},
                                                 "tactics": [{"technique": "T1547.001", "signature": "Registry Run Keys", "description": "Persistence via Run key"}],
                                                 "droppedFiles": [], "signatures": []})))
        db.commit()
    login(client, owner.username, "StrongPass123!")
    created = client.post("/api/cases", json={"title": "Invoice malware", "summary": "Malicious persistence and callback activity.",
                                               "severity": "critical", "priority": 1, "conversationIds": [conversation.id]})
    assert created.status_code == 201
    case_id = created.json()["id"]
    assert client.post(f"/api/cases/{case_id}/iocs/sync").status_code == 200
    evidence_id = client.get(f"/api/cases/{case_id}/evidence-chain").json()["evidence"][0]["id"]
    assert client.post(f"/api/cases/{case_id}/conclusions", json={"statement": "Sample is malicious", "status": "verified", "confidence": 96, "evidenceIds": [evidence_id]}).status_code == 201
    assert client.post(f"/api/cases/{case_id}/signatures", json={"signer": "SOC Lead", "note": "Approved"}).status_code == 201
    return case_id, owner


def test_report_types_metadata_and_watermark(client, create_user, create_conversation_for_user) -> None:
    case_id, _ = create_report_case(client, create_user, create_conversation_for_user)

    zh = client.get(f"/api/cases/{case_id}/report/export?format=markdown&reportType=technical_zh&watermark=CONFIDENTIAL")
    en = client.get(f"/api/cases/{case_id}/report/export?format=md&reportType=en")
    executive = client.get(f"/api/cases/{case_id}/reports/export?format=markdown&reportType=management")

    assert zh.status_code == en.status_code == executive.status_code == 200
    assert "事件概述" in zh.text and "CONFIDENTIAL" in zh.text and "分析员签名" in zh.text
    assert "Incident Overview" in en.text and "Response Recommendations" in en.text
    assert "管理层事件摘要" in executive.text
    assert zh.headers["x-cipher-report-version"] == "1.0"
    assert zh.headers["x-cipher-case-id"] == str(case_id)
    assert "v1.0.md" in zh.headers["content-disposition"]


def test_structured_report_export_formats(client, create_user, create_conversation_for_user) -> None:
    case_id, _ = create_report_case(client, create_user, create_conversation_for_user)

    report = client.get(f"/api/cases/{case_id}/report/export?format=json&watermark=INTERNAL").json()
    stix = client.get(f"/api/cases/{case_id}/report/export?format=stix").json()
    misp = client.get(f"/api/cases/{case_id}/report/export?format=misp").json()
    navigator = client.get(f"/api/cases/{case_id}/report/export?format=navigator").json()
    pdf = client.get(f"/api/cases/{case_id}/report/export?format=pdf&watermark=INTERNAL")

    assert report["version"] == "1.0" and report["caseId"] == case_id and report["watermark"] == "INTERNAL"
    assert report["samples"][0]["sha256"] == "a" * 64
    assert report["attackTechniques"][0]["techniqueId"] == "T1547.001"
    assert report["evidence"][0]["citation"] == "C1"
    assert report["analystSignature"]["signer"] == "SOC Lead"
    assert stix["type"] == "bundle" and stix["x_cipher_export"]["case_id"] == case_id
    assert any(item["type"] == "indicator" for item in stix["objects"])
    assert misp["Event"]["cipher_export"]["caseId"] == case_id
    assert any(item["value"] == "evil.example" for item in misp["Event"]["Attribute"])
    assert navigator["domain"] == "enterprise-attack" and navigator["techniques"][0]["techniqueID"] == "T1547.001"
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")


def test_report_export_format_validation_and_read_permissions(client, create_user, create_conversation_for_user) -> None:
    case_id, owner = create_report_case(client, create_user, create_conversation_for_user)
    viewer = create_user(username="report-viewer", password="StrongPass123!")
    stranger = create_user(username="report-stranger", password="StrongPass123!")

    assert client.get(f"/api/cases/{case_id}/report/export?format=xml").status_code == 400
    assert client.get(f"/api/cases/{case_id}/report/export?reportType=forensic").status_code == 400
    assert client.put(f"/api/cases/{case_id}/access", json={"username": viewer.username, "permission": "viewer"}).status_code == 200

    client.post("/api/auth/logout"); login(client, viewer.username, "StrongPass123!")
    assert client.get(f"/api/cases/{case_id}/report/export?format=json").status_code == 200
    assert client.patch(f"/api/cases/{case_id}", json={"summary": "not allowed"}).status_code == 403

    client.post("/api/auth/logout"); login(client, stranger.username, "StrongPass123!")
    assert client.get(f"/api/cases/{case_id}/report/export?format=json").status_code == 404
