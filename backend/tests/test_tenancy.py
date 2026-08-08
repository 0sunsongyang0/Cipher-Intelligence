from app.database import SessionLocal
from app.models import Organization, OrganizationMember, UsageLedgerEntry, Workspace, WorkspaceMember
from app.tenancy import sync_casdoor_tenancy


def login(client, username: str, password: str) -> None:
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200


def test_organization_admin_can_view_aggregate_usage_and_ledger(client, create_user) -> None:
    owner = create_user(username="usage-owner", password="StrongPass123!")
    login(client, owner.username, "StrongPass123!")
    organization_id = client.post(
        "/api/organizations", json={"name": "Usage Org", "slug": "usage-org"}
    ).json()["id"]
    with SessionLocal() as db:
        db.add(UsageLedgerEntry(
            idempotency_key="org-usage-model-1",
            user_id=owner.id,
            organization_id=organization_id,
            resource_type="model",
            model_id="deepseek-v4-flash",
            input_tokens=120,
            output_tokens=30,
            cost_microusd=250,
        ))
        db.add(UsageLedgerEntry(
            idempotency_key="org-usage-cape-1",
            user_id=owner.id,
            organization_id=organization_id,
            resource_type="cape",
            storage_bytes=2048,
            cost_microusd=1000,
        ))
        db.commit()

    summary = client.get(f"/api/organizations/{organization_id}/usage/summary")
    ledger = client.get(f"/api/organizations/{organization_id}/usage/ledger")

    assert summary.status_code == 200
    assert summary.json()["usage"]["tokens"] == 150
    assert summary.json()["usage"]["modelCostMicrousd"] == 250
    assert summary.json()["usage"]["capeCostMicrousd"] == 1000
    assert ledger.status_code == 200
    assert {item["resourceType"] for item in ledger.json()["items"]} == {"model", "cape"}


def test_organization_roles_shared_cases_comments_mentions_and_assignment(client, create_user) -> None:
    owner = create_user(username="tenant-owner", password="StrongPass123!")
    analyst = create_user(username="tenant-analyst", password="StrongPass123!")
    viewer = create_user(username="tenant-viewer", password="StrongPass123!")

    login(client, owner.username, "StrongPass123!")
    organization = client.post("/api/organizations", json={"name": "Cipher SOC", "slug": "cipher-soc"})
    assert organization.status_code == 201
    organization_id = organization.json()["id"]
    workspace_id = organization.json()["defaultWorkspaceId"]
    assert client.put(f"/api/organizations/{organization_id}/members", json={"username": analyst.username, "role": "analyst"}).status_code == 200
    assert client.put(f"/api/organizations/{organization_id}/members", json={"username": viewer.username, "role": "viewer"}).status_code == 200

    created = client.post("/api/cases", json={"title": "Shared incident", "workspaceId": workspace_id, "assigneeUserId": analyst.id})
    assert created.status_code == 201
    case_id = created.json()["id"]
    assert created.json()["organizationId"] == organization_id
    assert created.json()["assigneeUserId"] == analyst.id

    client.post("/api/auth/logout")
    login(client, analyst.username, "StrongPass123!")
    assert client.get(f"/api/cases/{case_id}").status_code == 200
    assert client.patch(f"/api/cases/{case_id}", json={"severity": "high"}).status_code == 200
    assert client.put(f"/api/cases/{case_id}/follow").json() == {"following": True}
    comment = client.post(f"/api/cases/{case_id}/comments", json={"content": f"请 @{viewer.username} 协助复核"})
    assert comment.status_code == 201

    client.post("/api/auth/logout")
    login(client, viewer.username, "StrongPass123!")
    assert client.get(f"/api/cases/{case_id}").status_code == 200
    assert client.patch(f"/api/cases/{case_id}", json={"severity": "low"}).status_code == 403
    notifications = client.get("/api/notifications?unread_only=true").json()
    assert any(item["type"] == "mention" and item["caseId"] == case_id for item in notifications["items"])


def test_case_level_share_grants_external_read_or_edit(client, create_user) -> None:
    owner = create_user(username="case-owner", password="StrongPass123!")
    guest = create_user(username="case-guest", password="StrongPass123!")
    login(client, owner.username, "StrongPass123!")
    case_id = client.post("/api/cases", json={"title": "Private case"}).json()["id"]
    shared = client.put(f"/api/cases/{case_id}/access", json={"username": guest.username, "permission": "viewer"})
    assert shared.status_code == 200

    client.post("/api/auth/logout"); login(client, guest.username, "StrongPass123!")
    assert client.get(f"/api/cases/{case_id}").status_code == 200
    assert client.patch(f"/api/cases/{case_id}", json={"summary": "unauthorized"}).status_code == 403

    client.post("/api/auth/logout"); login(client, owner.username, "StrongPass123!")
    assert client.put(f"/api/cases/{case_id}/access", json={"username": guest.username, "permission": "editor"}).status_code == 200
    client.post("/api/auth/logout"); login(client, guest.username, "StrongPass123!")
    assert client.patch(f"/api/cases/{case_id}", json={"summary": "authorized"}).status_code == 200


def test_casdoor_roles_and_groups_sync_to_cipher_tenancy(client, create_user, monkeypatch) -> None:
    user = create_user(username="casdoor-analyst", password="StrongPass123!")
    monkeypatch.setattr("app.config.settings.casdoor_role_mapping", '{"blue-team":"analyst","approver":"reviewer"}')
    monkeypatch.setattr("app.config.settings.casdoor_sync_groups_as_workspaces", True)
    with SessionLocal() as db:
        managed_user = db.get(type(user), user.id)
        organization, default_workspace, role = sync_casdoor_tenancy(db, managed_user, {
            "sub": "cipher/casdoor-analyst-id", "owner": "cipher-enterprise",
            "roles": ["blue-team"], "groups": ["SOC 上海", "恶意软件组"],
        })
        db.commit()
        assert role == "analyst"
        assert organization.identity_source == "casdoor"
        membership = db.query(OrganizationMember).filter_by(organization_id=organization.id, user_id=user.id).one()
        assert membership.role == "analyst" and membership.identity_source == "casdoor"
        workspaces = db.query(Workspace).filter_by(organization_id=organization.id).all()
        assert {item.name for item in workspaces} == {"默认工作空间", "SOC 上海", "恶意软件组"}
        assert db.query(WorkspaceMember).filter_by(user_id=user.id, identity_source="casdoor").count() == 3

        sync_casdoor_tenancy(db, managed_user, {
            "sub": "cipher/casdoor-analyst-id", "owner": "cipher-enterprise",
            "roles": ["approver"], "groups": ["SOC 上海"],
        })
        db.commit()
        membership = db.query(OrganizationMember).filter_by(organization_id=organization.id, user_id=user.id).one()
        assert membership.role == "reviewer"
        group_memberships = db.query(WorkspaceMember).join(Workspace).filter(WorkspaceMember.user_id == user.id, WorkspaceMember.identity_source == "casdoor").all()
        assert len(group_memberships) == 2
