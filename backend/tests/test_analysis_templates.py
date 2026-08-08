from app.database import SessionLocal
from app.models import AnalysisTemplate, Organization, OrganizationMember, User


def login(client, username: str, password: str) -> None:
    assert client.post("/api/auth/login", json={"username": username, "password": password}).status_code == 200


def test_builtin_templates_initialize_conversation_and_case(client, create_user):
    create_user(username="analyst", password="StrongPass123!")
    login(client, "analyst", "StrongPass123!")
    response = client.get("/api/analysis-templates")
    assert response.status_code == 200
    assert {item["slug"] for item in response.json()["items"]} == {"malicious-office", "powershell", "phishing-email", "webshell", "ransomware-triage", "linux-elf"}
    template = response.json()["items"][0]

    conversation = client.post("/api/conversations", json={"title": "样本分析", "templateId": template["id"]})
    assert conversation.status_code == 201
    assert conversation.json()["analysis_template_version"] == template["version"]
    assert conversation.json()["analysis_config"]["systemPrompt"]

    case = client.post("/api/cases", json={"title": "事件调查", "templateId": template["id"]})
    assert case.status_code == 201
    assert case.json()["analysisTemplateId"] == template["id"]
    assert case.json()["analysisConfig"]["requiredEvidenceFields"]


def test_admin_lifecycle_keeps_versions_and_visibility(client, create_user):
    admin = create_user(username="admin", password="StrongPass123!", is_admin=True)
    member = create_user(username="member", password="StrongPass123!")
    outsider = create_user(username="outsider", password="StrongPass123!")
    with SessionLocal() as db:
        org = Organization(name="SOC", slug="soc", created_by_user_id=admin.id); db.add(org); db.flush()
        db.add_all([OrganizationMember(organization_id=org.id, user_id=admin.id, role="owner"), OrganizationMember(organization_id=org.id, user_id=member.id, role="analyst")]); db.commit(); org_id = org.id
    login(client, "admin", "StrongPass123!")
    payload = {"name":"组织模板","scenario":"内部事件","systemPrompt":"只做防御分析","checklist":["校验证据"],"requiredSkills":["ioc-extractor"],"outputFormat":"JSON","requiredEvidenceFields":["sha256"],"recommendedModel":"chatgpt-5.4-az","organizationId":org_id}
    created = client.post("/api/admin/analysis-templates", json=payload)
    assert created.status_code == 201 and created.json()["status"] == "draft"
    template_id = created.json()["id"]
    assert client.post(f"/api/admin/analysis-templates/{template_id}/publish").status_code == 200
    payload["scenario"] = "更新后的内部事件"
    assert client.put(f"/api/admin/analysis-templates/{template_id}", json=payload).json()["version"] == 3
    assert len(client.get(f"/api/admin/analysis-templates/{template_id}/versions").json()["items"]) == 3
    assert client.post(f"/api/admin/analysis-templates/{template_id}/copy").status_code == 200

    client.post("/api/auth/logout"); login(client, "member", "StrongPass123!")
    assert template_id in {item["id"] for item in client.get("/api/analysis-templates").json()["items"]}
    client.post("/api/auth/logout"); login(client, "outsider", "StrongPass123!")
    assert template_id not in {item["id"] for item in client.get("/api/analysis-templates").json()["items"]}
