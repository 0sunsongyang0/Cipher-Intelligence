import json

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis_templates import save_version, seed_builtins, slugify, snapshot, visible_query
from app.auth import require_admin_user_session, require_user_session
from app.database import get_db
from app.models import AnalysisTemplate, AnalysisTemplateVersion, OrganizationMember, Session as SessionModel

router = APIRouter(tags=["analysis-templates"])

class TemplatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    scenario: str = Field(min_length=1)
    systemPrompt: str = Field(min_length=1)
    checklist: list[str] = Field(min_length=1)
    requiredSkills: list[str] = Field(default_factory=list)
    outputFormat: str = Field(min_length=1)
    requiredEvidenceFields: list[str] = Field(min_length=1)
    recommendedModel: str = Field(min_length=1, max_length=120)
    organizationId: int | None = None
    slug: str | None = None

def apply_payload(item: AnalysisTemplate, payload: TemplatePayload) -> None:
    item.name = payload.name.strip(); item.scenario = payload.scenario.strip(); item.system_prompt = payload.systemPrompt.strip()
    item.checklist_json = json.dumps(payload.checklist, ensure_ascii=False); item.required_skills_json = json.dumps(payload.requiredSkills, ensure_ascii=False)
    item.output_format = payload.outputFormat.strip(); item.required_evidence_json = json.dumps(payload.requiredEvidenceFields, ensure_ascii=False)
    item.recommended_model = payload.recommendedModel.strip(); item.organization_id = payload.organizationId

def assert_org_admin(db: Session, user_id: int, organization_id: int | None) -> None:
    if organization_id is None: return
    role = db.execute(select(OrganizationMember.role).where(OrganizationMember.organization_id == organization_id, OrganizationMember.user_id == user_id)).scalar_one_or_none()
    if role not in {"owner", "admin"}: raise HTTPException(403, "Organization admin permission required")

@router.get("/api/analysis-templates")
def list_templates(session: SessionModel = Depends(require_user_session), db: Session = Depends(get_db)):
    seed_builtins(db, session.user_id)
    items = db.execute(visible_query(session.user_id).where(AnalysisTemplate.status == "published").order_by(AnalysisTemplate.name)).scalars().all()
    return {"items": [snapshot(item) for item in items]}

@router.get("/api/admin/analysis-templates")
def admin_list_templates(session: SessionModel = Depends(require_admin_user_session), db: Session = Depends(get_db)):
    seed_builtins(db, session.user_id)
    return {"items": [snapshot(item) for item in db.execute(select(AnalysisTemplate).order_by(AnalysisTemplate.updated_at.desc())).scalars()]}

@router.post("/api/admin/analysis-templates", status_code=status.HTTP_201_CREATED)
def create_template(payload: TemplatePayload, session: SessionModel = Depends(require_admin_user_session), db: Session = Depends(get_db)):
    assert_org_admin(db, session.user_id, payload.organizationId)
    base = slugify(payload.slug or payload.name); slug = base; suffix = 2
    while db.execute(select(AnalysisTemplate.id).where(AnalysisTemplate.slug == slug)).first(): slug, suffix = f"{base}-{suffix}", suffix + 1
    item = AnalysisTemplate(slug=slug, name=payload.name, scenario=payload.scenario, system_prompt=payload.systemPrompt,
        checklist_json="[]", required_skills_json="[]", output_format=payload.outputFormat, required_evidence_json="[]",
        recommended_model=payload.recommendedModel, organization_id=payload.organizationId, status="draft",
        created_by_user_id=session.user_id, updated_by_user_id=session.user_id)
    apply_payload(item, payload); db.add(item); db.flush(); save_version(db, item, session.user_id); db.commit(); db.refresh(item)
    return snapshot(item)

@router.put("/api/admin/analysis-templates/{template_id}")
def update_template(template_id: int, payload: TemplatePayload, session: SessionModel = Depends(require_admin_user_session), db: Session = Depends(get_db)):
    item = db.get(AnalysisTemplate, template_id)
    if item is None: raise HTTPException(404, "Template not found")
    assert_org_admin(db, session.user_id, payload.organizationId); apply_payload(item, payload); item.current_version += 1; item.updated_by_user_id = session.user_id
    save_version(db, item, session.user_id); db.commit(); db.refresh(item); return snapshot(item)

@router.post("/api/admin/analysis-templates/{template_id}/{action}")
def template_action(template_id: int, action: str, session: SessionModel = Depends(require_admin_user_session), db: Session = Depends(get_db)):
    item = db.get(AnalysisTemplate, template_id)
    if item is None: raise HTTPException(404, "Template not found")
    if action == "copy":
        data = snapshot(item); payload = TemplatePayload(name=f"{item.name}（副本）", scenario=item.scenario, systemPrompt=item.system_prompt,
            checklist=data["checklist"], requiredSkills=data["requiredSkills"], outputFormat=item.output_format,
            requiredEvidenceFields=data["requiredEvidenceFields"], recommendedModel=item.recommended_model, organizationId=item.organization_id)
        return create_template(payload, session, db)
    if action not in {"publish", "disable"}: raise HTTPException(400, "Unsupported action")
    item.status = "published" if action == "publish" else "disabled"; item.current_version += 1; item.updated_by_user_id = session.user_id
    save_version(db, item, session.user_id); db.commit(); return snapshot(item)

@router.get("/api/admin/analysis-templates/{template_id}/versions")
def list_versions(template_id: int, session: SessionModel = Depends(require_admin_user_session), db: Session = Depends(get_db)):
    versions = db.execute(select(AnalysisTemplateVersion).where(AnalysisTemplateVersion.template_id == template_id).order_by(AnalysisTemplateVersion.version.desc())).scalars().all()
    return {"items": [{**json.loads(item.snapshot_json), "createdAt": item.created_at} for item in versions]}
