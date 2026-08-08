from app.database import SessionLocal
from app.models import CapeCase
from test_cases import login


def test_playbook_templates_order_failure_retry_and_approval(client, create_user, create_conversation_for_user):
    user = create_user(username="playbook-analyst", password="StrongPass123!")
    conversation = create_conversation_for_user(user=user, title="Malware triage")
    login(client, "playbook-analyst", "StrongPass123!")
    templates = client.get("/api/cases/playbook-templates")
    assert templates.status_code == 200
    assert {item["id"] for item in templates.json()} == {"malware-triage", "phishing-investigation", "code-security-review"}
    case_id = client.post("/api/cases", json={"title": "Playbook case", "conversationIds": [conversation.id]}).json()["id"]
    created = client.post(f"/api/cases/{case_id}/playbooks", json={"templateId": "malware-triage"})
    assert created.status_code == 201 and len(created.json()["steps"]) == 8
    playbook = created.json(); first, cape = playbook["steps"][:2]
    assert client.post(f"/api/cases/{case_id}/playbooks/{playbook['id']}/steps/{cape['id']}/execute", json={}).status_code == 409
    first_done = client.post(f"/api/cases/{case_id}/playbooks/{playbook['id']}/steps/{first['id']}/execute", json={"input": {"sample": "loader.exe"}})
    assert first_done.status_code == 200 and first_done.json()["steps"][0]["input"]["sample"] == "loader.exe"
    failed = client.post(f"/api/cases/{case_id}/playbooks/{playbook['id']}/steps/{cape['id']}/execute", json={})
    assert failed.status_code == 200 and failed.json()["steps"][1]["status"] == "failed"
    retried = client.post(f"/api/cases/{case_id}/playbooks/{playbook['id']}/steps/{cape['id']}/retry")
    assert retried.json()["steps"][1]["status"] == "pending"
    with SessionLocal() as db:
        db.add(CapeCase(conversation_id=conversation.id, owner_user_id=user.id, cape_task_id=91, sample_name="微信.svg", status="reported", sha256="c" * 64, summary_json='{"taskId":91,"status":"reported","score":8.1,"tactics":[{"technique":"T1059.001","signature":"powershell -enc","description":"Encoded PowerShell"}],"droppedFiles":[],"signatures":[{"name":"cipher-malware-marker"}],"iocs":{"domains":["evil.example"],"ips":[],"urls":[]}}')); db.commit()
    cape_done = client.post(f"/api/cases/{case_id}/playbooks/{playbook['id']}/steps/{cape['id']}/execute", json={}).json()
    assert cape_done["steps"][1]["status"] == "completed" and cape_done["steps"][1]["attemptCount"] == 2
    current = cape_done
    for step in current["steps"][2:-1]:
        response = client.post(f"/api/cases/{case_id}/playbooks/{playbook['id']}/steps/{step['id']}/execute", json={"output": {"reviewed": True}})
        assert response.status_code == 200
        current = response.json()
        assert current["steps"][step["position"] - 1]["status"] == "completed"
    rules_step = next(step for step in current["steps"] if step["key"] == "rules")
    validation_step = next(step for step in current["steps"] if step["key"] == "validate")
    assert rules_step["output"]["ruleCount"] == 2
    assert validation_step["output"]["validCount"] == 2


def test_playbook_can_complete_with_explicit_approval(client, create_user):
    user = create_user(username="audit-approver", password="StrongPass123!"); login(client, user.username, "StrongPass123!")
    case_id = client.post("/api/cases", json={"title": "Code audit"}).json()["id"]
    playbook = client.post(f"/api/cases/{case_id}/playbooks", json={"templateId": "code-security-review"}).json()
    for step in playbook["steps"][:-1]:
        playbook = client.post(f"/api/cases/{case_id}/playbooks/{playbook['id']}/steps/{step['id']}/execute", json={"output": {"result": "reviewed"}}).json()
    approval = playbook["steps"][-1]
    assert client.post(f"/api/cases/{case_id}/playbooks/{playbook['id']}/steps/{approval['id']}/execute", json={}).status_code == 409
    approved = client.post(f"/api/cases/{case_id}/playbooks/{playbook['id']}/steps/{approval['id']}/approve")
    assert approved.status_code == 200 and approved.json()["status"] == "completed" and approved.json()["progress"] == 100
