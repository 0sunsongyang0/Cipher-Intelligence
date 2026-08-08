from __future__ import annotations

import csv
from datetime import datetime, timezone
import hashlib
from io import StringIO
import json
import ipaddress
import re
from urllib.parse import urlsplit, urlunsplit

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_user_session
from app.audit import record_audit_event
from app.deepseek import DeepSeekConfigurationError, StreamedUpstreamError, stream_chat_completion
from app.database import get_db
from app.cape_exports import build_sigma_starter, build_yara_starter
from app.case_analysis import build_case_analysis
from app.case_reports import EXPORT_FORMATS, REPORT_TYPES, build_report_data, export_report
from app.detection_rules import build_rule_report_html, build_rule_report_pdf, test_rule, validate_rule
from app.models import CapeCase, CaseAccess, CaseComment, CaseConclusion, CaseConclusionEvidence, CaseConversation, CaseEvent, CaseFollower, CaseIndicator, CaseSignature, Conversation, DetectionRule, DetectionRuleTestRun, DetectionRuleVersion, InvestigationCase, InvestigationPlaybook, InvestigationPlaybookStep, Message, MessageAttachment, MessageEvidence, OrganizationMember, Session as SessionModel, User, Workspace, now_utc
from app.notifications import NotificationEvent, notify
from app.schemas import CaseAccessUpsert, CaseCommentCreate, CaseConclusionCreate, CaseConclusionUpdate, ConclusionCrossCheckRequest, CaseConversationAdd, CaseEvidenceReview, CaseIndicatorBulkUpdate, CaseIndicatorEnrichRequest, CaseIndicatorItem, CaseIndicatorList, CaseIndicatorUpdate, CaseMergeRequest, CaseSignRequest, DetectionRuleCreate, DetectionRuleGenerateRequest, DetectionRuleItem, DetectionRuleList, DetectionRuleTestRunItem, DetectionRuleUpdate, DetectionRuleVersionItem, InvestigationCaseCreate, InvestigationCaseItem, InvestigationCaseList, InvestigationCaseUpdate, PlaybookCreate, PlaybookItem, PlaybookList, PlaybookStepAction, PlaybookStepItem, PlaybookTemplateItem
from app.tenancy import accessible_case_query, ensure_personal_workspace, require_case_access, require_organization_role
from app.threat_intel import threat_intel_service
from app.routes.cape import _case_to_response
from app.analysis_templates import resolve_template

router = APIRouter(prefix="/api/cases", tags=["cases"])

STATUS_TRANSITIONS = {
    "open": {"triage", "investigating"}, "triage": {"investigating", "closed"},
    "investigating": {"review", "confirmed", "triage"}, "review": {"confirmed", "investigating"},
    "confirmed": {"contained", "remediating"}, "contained": {"remediating", "closed"},
    "remediating": {"closed", "review"}, "closed": set(),
}

PLAYBOOK_TEMPLATES = {
    "malware-triage": ("恶意样本研判", "从样本分析到检测规则与 SOC 审批的完整研判链路", [
        ("collect", "上传样本", False), ("cape", "CAPE 分析", False), ("ioc", "IOC 提取与富化", False),
        ("attack", "ATT&CK 映射", False), ("rules", "生成 Sigma / YARA", False),
        ("validate", "规则验证", False), ("report", "生成 SOC 报告", False), ("approval", "人工审批", True),
    ]),
    "phishing-investigation": ("钓鱼邮件调查", "提取邮件证据、富化 IOC 并形成可处置结论", [
        ("collect", "收集邮件与附件", False), ("extract", "提取 URL / 域名 / Hash", False),
        ("ioc", "IOC 富化", False), ("analyze", "附件与链接风险分析", False),
        ("attack", "ATT&CK 映射", False), ("rules", "生成检测规则", False),
        ("report", "生成调查报告", False), ("approval", "人工审批", True),
    ]),
    "code-security-review": ("代码安全审计", "整理代码风险证据、修复建议与审计结论", [
        ("collect", "提交代码或仓库材料", False), ("analyze", "静态风险分析", False),
        ("evidence", "风险分级与证据整理", False), ("remediation", "修复建议", False),
        ("rules", "生成检测 / 审计规则", False), ("validate", "验证规则", False),
        ("report", "生成审计报告", False), ("approval", "人工审批", True),
    ]),
}


def _json_object(raw: str) -> dict:
    try:
        value = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _playbook_item(playbook: InvestigationPlaybook) -> PlaybookItem:
    steps = sorted(playbook.steps, key=lambda item: item.position)
    completed = sum(item.status == "completed" for item in steps)
    return PlaybookItem(id=playbook.id, caseId=playbook.case_id, templateId=playbook.template_id,
        title=playbook.title, status=playbook.status, progress=round(completed * 100 / len(steps)) if steps else 0,
        steps=[PlaybookStepItem(id=item.id, key=item.step_key, position=item.position, title=item.title,
            status=item.status, input=_json_object(item.input_json), output=_json_object(item.output_json),
            error=item.error_message, attemptCount=item.attempt_count, requiresApproval=item.requires_approval,
            approvedAt=item.approved_at, approvedBy=item.approved_by, startedAt=item.started_at,
            completedAt=item.completed_at) for item in steps], createdAt=playbook.created_at,
        updatedAt=playbook.updated_at, completedAt=playbook.completed_at)


def _owned_playbook(db: Session, case: InvestigationCase, playbook_id: int) -> InvestigationPlaybook:
    item = db.execute(select(InvestigationPlaybook).where(InvestigationPlaybook.id == playbook_id,
        InvestigationPlaybook.case_id == case.id)).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Playbook not found")
    return item


def _playbook_step(db: Session, playbook: InvestigationPlaybook, step_id: int) -> InvestigationPlaybookStep:
    step = db.execute(select(InvestigationPlaybookStep).where(InvestigationPlaybookStep.id == step_id,
        InvestigationPlaybookStep.playbook_id == playbook.id)).scalar_one_or_none()
    if step is None:
        raise HTTPException(status_code=404, detail="Playbook step not found")
    return step


def _assert_step_ready(playbook: InvestigationPlaybook, step: InvestigationPlaybookStep) -> None:
    if any(item.position < step.position and item.status != "completed" for item in playbook.steps):
        raise HTTPException(status_code=409, detail="Complete previous steps first")


def _finish_playbook(playbook: InvestigationPlaybook) -> None:
    if playbook.steps and all(item.status == "completed" for item in playbook.steps):
        playbook.status, playbook.completed_at = "completed", now_utc()
    else:
        playbook.status, playbook.completed_at = "active", None


def _owned_case(db: Session, case_id: int, session: SessionModel) -> InvestigationCase:
    return require_case_access(db, case_id, session.user_id, write=True)


def _readable_case(db: Session, case_id: int, session: SessionModel) -> InvestigationCase:
    return require_case_access(db, case_id, session.user_id)


def _add_event(db: Session, case: InvestigationCase, event_type: str, title: str, *, detail: str | None = None, metadata: dict | None = None, actor: str | None = None) -> None:
    db.add(CaseEvent(case_id=case.id, event_type=event_type, title=title, detail=detail, metadata_json=json.dumps(metadata or {}, ensure_ascii=False), actor=actor))


def _actor(db: Session, session: SessionModel) -> str:
    user = db.get(User, session.user_id)
    return (user.display_name or user.username) if user else f"user:{session.user_id}"


def _case_evidence(db: Session, case: InvestigationCase) -> list[MessageEvidence]:
    return list(db.execute(
        select(MessageEvidence)
        .join(Message, Message.id == MessageEvidence.message_id)
        .join(CaseConversation, CaseConversation.conversation_id == Message.conversation_id)
        .where(CaseConversation.case_id == case.id)
        .order_by(MessageEvidence.id)
    ).scalars().unique().all())


def _evidence_item(item: MessageEvidence) -> dict:
    return {
        "id": item.id, "messageId": item.message_id, "sourceType": item.source_type,
        "citation": item.citation, "title": item.title, "url": item.url, "locator": item.locator,
        "snippet": item.snippet, "reviewStatus": item.review_status, "sourceTrust": item.source_trust,
        "confidence": item.confidence, "acquiredAt": item.acquired_at, "contentHash": item.content_hash,
        "snapshotUrl": item.snapshot_url, "reviewNote": item.review_note,
        "reviewedBy": item.reviewed_by, "reviewedAt": item.reviewed_at,
    }


def _invalidate_signatures(db: Session, case: InvestigationCase, actor: str) -> None:
    changed = False
    for signature in db.execute(select(CaseSignature).where(CaseSignature.case_id == case.id, CaseSignature.is_valid.is_(True))).scalars():
        signature.is_valid = False
        signature.invalidated_at = now_utc()
        changed = True
    if changed:
        _add_event(db, case, "signature_invalidated", "研判签署已失效", detail="证据或结论发生实质变更", actor=actor)


def _chain_digest(db: Session, case: InvestigationCase) -> str:
    conclusions = db.execute(select(CaseConclusion).where(CaseConclusion.case_id == case.id).order_by(CaseConclusion.id)).scalars().all()
    evidence = _case_evidence(db, case)
    links = db.execute(
        select(CaseConclusionEvidence).join(CaseConclusion).where(CaseConclusion.case_id == case.id).order_by(CaseConclusionEvidence.conclusion_id, CaseConclusionEvidence.evidence_id)
    ).scalars().all()
    payload = {
        "caseId": case.id,
        "conclusions": [{"id": c.id, "statement": c.statement, "status": c.status, "confidence": c.confidence, "claimType": c.claim_type, "confidenceRationale": c.confidence_rationale, "conflictEvidenceIds": json.loads(c.conflict_evidence_ids_json or "[]"), "crossChecks": json.loads(c.cross_checks_json or "[]"), "reviewedBy": c.reviewed_by, "reviewedAt": c.reviewed_at.isoformat() if c.reviewed_at else None} for c in conclusions],
        "evidence": [{"id": e.id, "status": e.review_status, "trust": e.source_trust, "confidence": e.confidence, "hash": e.content_hash, "acquiredAt": e.acquired_at.isoformat() if e.acquired_at else None} for e in evidence],
        "links": [[link.conclusion_id, link.evidence_id] for link in links],
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _evidence_chain(db: Session, case: InvestigationCase) -> dict:
    evidence = _case_evidence(db, case)
    evidence_ids = {item.id for item in evidence}
    conclusions = db.execute(select(CaseConclusion).where(CaseConclusion.case_id == case.id).order_by(CaseConclusion.created_at)).scalars().all()
    signatures = db.execute(select(CaseSignature).where(CaseSignature.case_id == case.id).order_by(CaseSignature.signed_at.desc())).scalars().all()
    events = db.execute(select(CaseEvent).where(CaseEvent.case_id == case.id).order_by(CaseEvent.created_at, CaseEvent.id)).scalars().all()
    groups: dict[str, list[MessageEvidence]] = {}
    for item in evidence:
        key = item.url or item.locator or item.content_hash
        if key:
            groups.setdefault(key, []).append(item)
    contradictions = []
    for source, items in groups.items():
        statuses = {item.review_status for item in items}
        snippets = {" ".join((item.snippet or "").split()).lower() for item in items if item.snippet}
        if len(statuses - {"pending"}) > 1 or len(snippets) > 1:
            contradictions.append({"source": source, "evidenceIds": [item.id for item in items], "reason": "同一来源存在不同内容或相反审核结果"})
    return {
        "case": {"id": case.id, "title": case.title, "status": case.status, "severity": case.severity, "assignee": case.assignee, "updatedAt": case.updated_at},
        "evidence": [_evidence_item(item) for item in evidence],
        "conclusions": [{"id": item.id, "statement": item.statement, "status": item.status, "confidence": item.confidence, "claimType": item.claim_type, "confidenceRationale": item.confidence_rationale, "evidenceIds": [link.evidence_id for link in item.evidence_links if link.evidence_id in evidence_ids], "conflictEvidenceIds": [evidence_id for evidence_id in json.loads(item.conflict_evidence_ids_json or "[]") if evidence_id in evidence_ids], "crossChecks": json.loads(item.cross_checks_json or "[]"), "createdBy": item.created_by, "reviewedBy": item.reviewed_by, "reviewedAt": item.reviewed_at, "createdAt": item.created_at, "updatedAt": item.updated_at} for item in conclusions],
        "contradictions": contradictions,
        "signatures": [{"id": item.id, "signer": item.signer, "digest": item.digest, "note": item.note, "isValid": item.is_valid, "signedAt": item.signed_at, "invalidatedAt": item.invalidated_at} for item in signatures],
        "auditTrail": [{"id": item.id, "eventType": item.event_type, "title": item.title, "detail": item.detail, "metadata": json.loads(item.metadata_json or "{}"), "actor": item.actor, "createdAt": item.created_at} for item in events],
        "currentDigest": _chain_digest(db, case),
    }


def _normalize_indicator(indicator_type: str, value: str) -> str:
    value = value.strip()
    if indicator_type == "domain":
        return value.rstrip(".").lower()
    if indicator_type == "ip":
        try:
            return str(ipaddress.ip_address(value))
        except ValueError:
            return value.lower()
    if indicator_type == "url":
        parts = urlsplit(value)
        host = (parts.hostname or "").lower()
        port = f":{parts.port}" if parts.port else ""
        netloc = f"{host}{port}"
        return urlunsplit((parts.scheme.lower(), netloc, parts.path or "/", parts.query, ""))
    return value.lower()


def _sync_indicators(db: Session, case: InvestigationCase) -> tuple[int, int]:
    conversation_ids = db.execute(select(CaseConversation.conversation_id).where(CaseConversation.case_id == case.id)).scalars().all()
    cape_cases = db.execute(select(CapeCase).where(CapeCase.conversation_id.in_(conversation_ids))).scalars().all() if conversation_ids else []
    existing = {(item.indicator_type, item.normalized_value): item for item in db.execute(select(CaseIndicator).where(CaseIndicator.case_id == case.id)).scalars().all()}
    discovered: dict[tuple[str, str], tuple[str, CapeCase]] = {}
    for cape in cape_cases:
        raw_iocs: dict = {}
        if cape.summary_json:
            try:
                raw_iocs = json.loads(cape.summary_json).get("iocs", {}) or {}
            except (json.JSONDecodeError, AttributeError):
                pass
        for indicator_type, key in (("domain", "domains"), ("ip", "ips"), ("url", "urls")):
            for raw_value in raw_iocs.get(key, []) or []:
                value = str(raw_value).strip()
                if value:
                    discovered.setdefault((indicator_type, _normalize_indicator(indicator_type, value)), (value, cape))
        if cape.sha256:
            discovered.setdefault(("sha256", cape.sha256.lower()), (cape.sha256, cape))
    added = 0
    now = now_utc()
    for key, (value, cape) in discovered.items():
        item = existing.get(key)
        if item:
            item.last_seen_at = max(item.last_seen_at, cape.updated_at)
            item.sample_name = item.sample_name or cape.sample_name
            item.updated_at = now
        else:
            db.add(CaseIndicator(case_id=case.id, indicator_type=key[0], value=value, normalized_value=key[1], cape_case_id=cape.id, sample_name=cape.sample_name, first_seen_at=cape.created_at, last_seen_at=cape.updated_at))
            added += 1
    return added, len(discovered)


def _indicator_item(item: CaseIndicator) -> CaseIndicatorItem:
    try:
        enrichment = json.loads(item.enrichment_json or "{}")
    except json.JSONDecodeError:
        enrichment = {}
    return CaseIndicatorItem(id=item.id, type=item.indicator_type, value=item.value, riskLevel=item.risk_level, confidence=item.confidence, status=item.status, sourceType=item.source_type, capeCaseId=item.cape_case_id, sampleName=item.sample_name, firstSeenAt=item.first_seen_at, lastSeenAt=item.last_seen_at, expiresAt=item.expires_at, enrichment=enrichment)


def _rule_item(rule: DetectionRule) -> DetectionRuleItem:
    try:
        validation = json.loads(rule.validation_json or "{}")
    except json.JSONDecodeError:
        validation = {}
    versions = sorted(rule.versions, key=lambda item: item.version, reverse=True)
    test_runs = sorted(rule.test_runs, key=lambda item: (item.created_at, item.id), reverse=True)
    return DetectionRuleItem(
        id=rule.id,
        caseId=rule.case_id,
        sourceCapeCaseId=rule.source_cape_case_id,
        ruleType=rule.rule_type,
        title=rule.title,
        content=rule.content,
        status=rule.status,
        version=rule.version,
        validationStatus=rule.validation_status,
        validation=validation,
        lastValidatedAt=rule.last_validated_at,
        approvedAt=rule.approved_at,
        deployedAt=rule.deployed_at,
        versions=[
            DetectionRuleVersionItem(
                id=item.id,
                version=item.version,
                validationStatus=item.validation_status,
                actor=item.actor,
                createdAt=item.created_at,
            )
            for item in versions
        ],
        testRuns=[
            DetectionRuleTestRunItem(
                id=item.id,
                totalArtifacts=item.total_artifacts,
                matchedArtifacts=item.matched_artifacts,
                falsePositiveCount=item.false_positive_count,
                results=json.loads(item.result_json or "{}").get("results", []),
                createdAt=item.created_at,
            )
            for item in test_runs
        ],
        createdAt=rule.created_at,
        updatedAt=rule.updated_at,
    )


def _owned_rule(db: Session, case: InvestigationCase, rule_id: int) -> DetectionRule:
    rule = db.execute(
        select(DetectionRule).where(
            DetectionRule.id == rule_id,
            DetectionRule.case_id == case.id,
        )
    ).scalar_one_or_none()
    if rule is None:
        raise HTTPException(status_code=404, detail="Detection rule not found")
    return rule


def _save_rule_version(db: Session, rule: DetectionRule, actor: str | None) -> None:
    version = db.execute(
        select(DetectionRuleVersion).where(
            DetectionRuleVersion.rule_id == rule.id,
            DetectionRuleVersion.version == rule.version,
        )
    ).scalar_one_or_none()
    if version is None:
        version = DetectionRuleVersion(
            rule_id=rule.id,
            version=rule.version,
            content=rule.content,
        )
        db.add(version)
    version.content = rule.content
    version.validation_status = rule.validation_status
    version.validation_json = rule.validation_json
    version.actor = actor


def _serialize(db: Session, case: InvestigationCase, *, detailed: bool = False) -> InvestigationCaseItem:
    conversation_ids = db.execute(select(CaseConversation.conversation_id).where(CaseConversation.case_id == case.id)).scalars().all()
    conversations = db.execute(select(Conversation).where(Conversation.id.in_(conversation_ids)).order_by(Conversation.updated_at.desc())).scalars().all() if conversation_ids else []
    cape_cases = db.execute(select(CapeCase).where(CapeCase.conversation_id.in_(conversation_ids)).order_by(CapeCase.updated_at.desc())).scalars().all() if conversation_ids else []
    child_ids = db.execute(select(InvestigationCase.id).where(InvestigationCase.parent_case_id == case.id, InvestigationCase.owner_user_id == case.owner_user_id)).scalars().all()
    message_counts = dict(db.query(Message.conversation_id, __import__('sqlalchemy').func.count(Message.id)).filter(Message.conversation_id.in_(conversation_ids)).group_by(Message.conversation_id).all()) if conversation_ids else {}
    sample_counts = dict(db.query(CapeCase.conversation_id, __import__('sqlalchemy').func.count(CapeCase.id)).filter(CapeCase.conversation_id.in_(conversation_ids)).group_by(CapeCase.conversation_id).all()) if conversation_ids else {}
    ioc_count = len(db.execute(select(CaseIndicator.id).where(CaseIndicator.case_id == case.id)).scalars().all())
    events = db.execute(select(CaseEvent).where(CaseEvent.case_id == case.id).order_by(CaseEvent.created_at.desc(), CaseEvent.id.desc())).scalars().all() if detailed else []
    due = case.sla_due_at
    due_utc = due.replace(tzinfo=timezone.utc) if due and due.tzinfo is None else due
    return InvestigationCaseItem(
        id=case.id, title=case.title, status=case.status, severity=case.severity, assignee=case.assignee,
        organizationId=case.organization_id, workspaceId=case.workspace_id, assigneeUserId=case.assignee_user_id,
        tags=case.tags, summary=case.summary, priority=case.priority, slaDueAt=due,
        analysisTemplateId=case.analysis_template_id, analysisTemplateVersion=case.analysis_template_version,
        analysisConfig=json.loads(case.analysis_config_json) if case.analysis_config_json else None,
        overdue=bool(due_utc and due_utc < datetime.now(timezone.utc) and case.status != "closed"),
        parentCaseId=case.parent_case_id, mergedIntoCaseId=case.merged_into_case_id, childCaseIds=list(child_ids),
        conversationCount=len(conversations), sampleCount=len(cape_cases), capeTaskCount=len(cape_cases), iocCount=ioc_count,
        createdAt=case.created_at, updatedAt=case.updated_at, closedAt=case.closed_at,
        conversations=[{"id": c.id, "title": c.title, "updatedAt": c.updated_at, "messageCount": message_counts.get(c.id, 0), "sampleCount": sample_counts.get(c.id, 0)} for c in conversations] if detailed else [],
        capeCases=[_case_to_response(item) for item in cape_cases] if detailed else [],
        timeline=[{"id": event.id, "eventType": event.event_type, "title": event.title, "detail": event.detail, "metadata": json.loads(event.metadata_json or "{}"), "actor": event.actor, "createdAt": event.created_at} for event in events],
    )


def _validate_related(db: Session, owner_id: int, related_id: int | None, current_id: int | None = None) -> None:
    if related_id is None:
        return
    if related_id == current_id:
        raise HTTPException(status_code=400, detail="A case cannot be its own parent")
    exists = db.execute(select(InvestigationCase.id).where(InvestigationCase.id == related_id, InvestigationCase.owner_user_id == owner_id, InvestigationCase.merged_into_case_id.is_(None))).scalar_one_or_none()
    if exists is None:
        raise HTTPException(status_code=400, detail="Related case not found")


@router.get("/playbook-templates", response_model=list[PlaybookTemplateItem])
def list_playbook_templates(_: SessionModel = Depends(require_user_session)):
    return [PlaybookTemplateItem(id=key, title=value[0], description=value[1], steps=[step[1] for step in value[2]]) for key, value in PLAYBOOK_TEMPLATES.items()]


@router.get("/{case_id}/playbooks", response_model=PlaybookList)
def list_case_playbooks(case_id: int, session: SessionModel = Depends(require_user_session), db: Session = Depends(get_db)):
    case = _owned_case(db, case_id, session)
    items = db.execute(select(InvestigationPlaybook).where(InvestigationPlaybook.case_id == case.id).order_by(InvestigationPlaybook.created_at.desc())).scalars().all()
    return PlaybookList(items=[_playbook_item(item) for item in items])


@router.post("/{case_id}/playbooks", response_model=PlaybookItem, status_code=201)
def create_case_playbook(payload: PlaybookCreate, case_id: int, session: SessionModel = Depends(require_user_session), db: Session = Depends(get_db)):
    case = _owned_case(db, case_id, session)
    template = PLAYBOOK_TEMPLATES.get(payload.templateId)
    if template is None:
        raise HTTPException(status_code=400, detail="Unknown playbook template")
    playbook = InvestigationPlaybook(case_id=case.id, template_id=payload.templateId, title=template[0])
    db.add(playbook); db.flush()
    for position, (key, title, approval) in enumerate(template[2], start=1):
        db.add(InvestigationPlaybookStep(playbook_id=playbook.id, step_key=key, position=position, title=title, requires_approval=approval))
    _add_event(db, case, "playbook_started", f"启动 Playbook：{template[0]}", actor=f"user:{session.user_id}")
    db.commit(); db.refresh(playbook)
    return _playbook_item(playbook)


@router.post("/{case_id}/playbooks/{playbook_id}/steps/{step_id}/execute", response_model=PlaybookItem)
def execute_playbook_step(payload: PlaybookStepAction, case_id: int, playbook_id: int, step_id: int, session: SessionModel = Depends(require_user_session), db: Session = Depends(get_db)):
    case = _owned_case(db, case_id, session); playbook = _owned_playbook(db, case, playbook_id); step = _playbook_step(db, playbook, step_id)
    _assert_step_ready(playbook, step)
    if step.requires_approval:
        raise HTTPException(status_code=409, detail="This step requires explicit approval")
    if step.status == "completed":
        raise HTTPException(status_code=409, detail="Step is already completed")
    now = now_utc(); step.status = "running"; step.started_at = step.started_at or now
    step.attempt_count += 1; step.input_json = json.dumps(payload.input, ensure_ascii=False)
    output = dict(payload.output)
    if payload.error:
        step.status, step.error_message = "failed", payload.error.strip()[:2000]
    else:
        if step.step_key == "cape":
            conversation_ids = db.execute(select(CaseConversation.conversation_id).where(CaseConversation.case_id == case.id)).scalars().all()
            cape_cases = db.execute(select(CapeCase).where(CapeCase.conversation_id.in_(conversation_ids))).scalars().all() if conversation_ids else []
            if not cape_cases:
                step.status, step.error_message = "failed", "当前 Case 尚未关联 CAPE 分析任务"
            else:
                output.update({"taskCount": len(cape_cases), "reportedCount": sum(item.status in {"reported", "completed"} for item in cape_cases)})
        elif step.step_key in {"ioc", "extract"}:
            added, discovered = _sync_indicators(db, case); output.update({"discovered": discovered, "added": added})
        elif step.step_key == "rules":
            rules = list(db.execute(select(DetectionRule).where(DetectionRule.case_id == case.id)).scalars().all())
            if not rules and playbook.template_id == "malware-triage":
                conversation_ids = db.execute(select(CaseConversation.conversation_id).where(CaseConversation.case_id == case.id)).scalars().all()
                cape_cases = list(db.execute(select(CapeCase).where(CapeCase.conversation_id.in_(conversation_ids), CapeCase.summary_json.is_not(None))).scalars().all()) if conversation_ids else []
                if not cape_cases:
                    step.status, step.error_message = "failed", "没有已完成的 CAPE 报告，无法生成检测规则"
                else:
                    for cape_case in cape_cases:
                        for rule_type in ("sigma", "yara"):
                            content = (build_sigma_starter(cape_case) if rule_type == "sigma" else build_yara_starter(cape_case)).decode("utf-8")
                            rule = DetectionRule(case_id=case.id, source_cape_case_id=cape_case.id, rule_type=rule_type, title=f"{cape_case.sample_name} · {rule_type.upper()} starter", content=content)
                            db.add(rule); db.flush(); _save_rule_version(db, rule, case.assignee); rules.append(rule)
                    _add_event(db, case, "rules_generated", f"Playbook 生成了 {len(rules)} 条检测规则", metadata={"ruleIds": [rule.id for rule in rules]})
            output.update({"ruleCount": len(rules), "ruleIds": [rule.id for rule in rules]})
        elif step.step_key == "validate":
            rules = list(db.execute(select(DetectionRule).where(DetectionRule.case_id == case.id)).scalars().all())
            if not rules and not payload.output:
                step.status, step.error_message = "failed", "尚无可验证的检测规则"
            elif rules:
                errors: list[str] = []
                for rule in rules:
                    if rule.rule_type == "yara" and rule.validation_status == "invalid" and "Starter rule generated from CAPE task" in rule.content and rule.source_cape_case_id:
                        source = db.get(CapeCase, rule.source_cape_case_id)
                        if source is not None:
                            refreshed = build_yara_starter(source).decode("utf-8")
                            if refreshed != rule.content:
                                rule.version += 1; rule.content = refreshed
                    result = validate_rule(rule.rule_type, rule.content)
                    rule.validation_status = "valid" if result.valid else "invalid"; rule.validation_json = json.dumps(result.as_dict(), ensure_ascii=False); rule.last_validated_at = now; rule.updated_at = now
                    rule.status = "validated" if result.valid else "draft"; _save_rule_version(db, rule, case.assignee)
                    errors.extend(f"{rule.title}: {message}" for message in result.errors)
                output.update({"ruleCount": len(rules), "validCount": sum(item.validation_status == "valid" for item in rules), "ruleIds": [rule.id for rule in rules]})
                if errors:
                    step.status, step.error_message = "failed", "；".join(errors)[:2000]
        elif step.step_key == "report":
            output.update({"caseId": case.id, "summary": case.summary or "", "generatedAt": now.isoformat()})
        if step.status != "failed":
            step.status, step.completed_at, step.error_message = "completed", now, None
    step.output_json = json.dumps(output, ensure_ascii=False); _finish_playbook(playbook)
    _add_event(db, case, "playbook_step", f"{step.title}：{'失败' if step.status == 'failed' else '完成'}", detail=step.error_message, metadata={"playbookId": playbook.id, "stepId": step.id}, actor=f"user:{session.user_id}")
    db.commit(); db.refresh(playbook)
    return _playbook_item(playbook)


@router.post("/{case_id}/playbooks/{playbook_id}/steps/{step_id}/retry", response_model=PlaybookItem)
def retry_playbook_step(case_id: int, playbook_id: int, step_id: int, session: SessionModel = Depends(require_user_session), db: Session = Depends(get_db)):
    case = _owned_case(db, case_id, session); playbook = _owned_playbook(db, case, playbook_id); step = _playbook_step(db, playbook, step_id)
    if step.status != "failed":
        raise HTTPException(status_code=409, detail="Only failed steps can be retried")
    step.status, step.error_message, step.completed_at = "pending", None, None; _finish_playbook(playbook)
    _add_event(db, case, "playbook_retry", f"重试步骤：{step.title}", actor=f"user:{session.user_id}")
    db.commit(); db.refresh(playbook)
    return _playbook_item(playbook)


@router.post("/{case_id}/playbooks/{playbook_id}/steps/{step_id}/approve", response_model=PlaybookItem)
def approve_playbook_step(case_id: int, playbook_id: int, step_id: int, request: Request, session: SessionModel = Depends(require_user_session), db: Session = Depends(get_db)):
    case = _owned_case(db, case_id, session); playbook = _owned_playbook(db, case, playbook_id); step = _playbook_step(db, playbook, step_id)
    _assert_step_ready(playbook, step)
    if not step.requires_approval:
        raise HTTPException(status_code=409, detail="Step does not require approval")
    actor = f"user:{session.user_id}"; now = now_utc(); step.status, step.approved_at, step.approved_by, step.completed_at = "completed", now, actor, now
    step.attempt_count += 1; step.output_json = json.dumps({"decision": "approved", "actor": actor}, ensure_ascii=False)
    _finish_playbook(playbook); _add_event(db, case, "playbook_approved", f"审批通过：{playbook.title}", actor=actor)
    record_audit_event(db, event_type="case.approval", action="playbook_step.approve", request=request,
                       actor_user_id=session.user_id, organization_id=case.organization_id,
                       workspace_id=case.workspace_id, resource_type="playbook_step", resource_id=step.id,
                       detail={"caseId": case.id, "playbookId": playbook.id})
    db.commit(); db.refresh(playbook)
    return _playbook_item(playbook)


@router.get("", response_model=InvestigationCaseList)
def list_cases(status_filter: str | None = Query(None, alias="status"), severity: str | None = None, assignee: str | None = None, tag: str | None = None, updated_after: datetime | None = Query(None, alias="updatedAfter"), overdue: bool | None = None, sort: str = "priority", current_session: SessionModel = Depends(require_user_session), db: Session = Depends(get_db)) -> InvestigationCaseList:
    query = accessible_case_query(current_session.user_id).where(InvestigationCase.merged_into_case_id.is_(None))
    if status_filter: query = query.where(InvestigationCase.status == status_filter)
    if severity: query = query.where(InvestigationCase.severity == severity)
    if assignee: query = query.where(InvestigationCase.assignee == assignee)
    if updated_after: query = query.where(InvestigationCase.updated_at >= updated_after)
    cases = list(db.execute(query).scalars().all())
    if tag: cases = [case for case in cases if tag in case.tags]
    if overdue is not None: cases = [case for case in cases if _serialize(db, case).overdue is overdue]
    if sort == "sla": cases.sort(key=lambda c: (c.sla_due_at is None, c.sla_due_at or datetime.max))
    elif sort == "updated": cases.sort(key=lambda c: c.updated_at, reverse=True)
    else: cases.sort(key=lambda c: (c.priority, c.sla_due_at is None, c.sla_due_at or datetime.max, -c.id))
    all_statuses = [item.status for item in db.execute(accessible_case_query(current_session.user_id).where(InvestigationCase.merged_into_case_id.is_(None))).scalars().all()]
    counts = {key: all_statuses.count(key) for key in ("open", "triage", "investigating", "review", "confirmed", "contained", "remediating", "closed")}
    return InvestigationCaseList(items=[_serialize(db, case) for case in cases], counts=counts)


@router.post("", response_model=InvestigationCaseItem, status_code=201)
def create_case(payload: InvestigationCaseCreate, current_session: SessionModel = Depends(require_user_session), db: Session = Depends(get_db)) -> InvestigationCaseItem:
    _validate_related(db, current_session.user_id, payload.parentCaseId)
    conversations = db.execute(select(Conversation).where(Conversation.id.in_(payload.conversationIds), Conversation.owner_user_id == current_session.user_id)).scalars().all() if payload.conversationIds else []
    if len(conversations) != len(set(payload.conversationIds)): raise HTTPException(status_code=400, detail="One or more conversations were not found")
    organization, default_workspace = ensure_personal_workspace(db, current_session.user_id)
    workspace = db.get(Workspace, payload.workspaceId) if payload.workspaceId else default_workspace
    if workspace is None: raise HTTPException(status_code=400, detail="Workspace not found")
    require_organization_role(db, workspace.organization_id, current_session.user_id, "analyst")
    assignee_user = db.get(User, payload.assigneeUserId) if payload.assigneeUserId else None
    if assignee_user and db.execute(select(OrganizationMember.id).where(OrganizationMember.organization_id == workspace.organization_id, OrganizationMember.user_id == assignee_user.id)).scalar_one_or_none() is None:
        raise HTTPException(status_code=400, detail="Assignee must be an organization member")
    template, config = resolve_template(db, payload.templateId, current_session.user_id)
    case = InvestigationCase(owner_user_id=current_session.user_id, organization_id=workspace.organization_id, workspace_id=workspace.id, assignee_user_id=assignee_user.id if assignee_user else None, title=payload.title, status=payload.status, severity=payload.severity, assignee=(assignee_user.display_name or assignee_user.username) if assignee_user else payload.assignee, tags_json=json.dumps(payload.tags, ensure_ascii=False), summary=payload.summary, priority=payload.priority, sla_due_at=payload.slaDueAt, parent_case_id=payload.parentCaseId, analysis_template_id=template.id if template else None, analysis_template_version=template.current_version if template else None, analysis_config_json=json.dumps(config, ensure_ascii=False) if config else None)
    db.add(case); db.flush()
    for conversation in conversations: db.add(CaseConversation(case_id=case.id, conversation_id=conversation.id))
    db.flush()
    _sync_indicators(db, case)
    _add_event(db, case, "created", "Case 已创建", metadata={"conversationIds": payload.conversationIds, "templateId": payload.templateId})
    db.commit(); db.refresh(case)
    return _serialize(db, case, detailed=True)


@router.get("/{case_id}", response_model=InvestigationCaseItem)
def get_case(case_id: int, request: Request, current_session: SessionModel = Depends(require_user_session), db: Session = Depends(get_db)) -> InvestigationCaseItem:
    case = _readable_case(db, case_id, current_session)
    payload = _serialize(db, case, detailed=True)
    record_audit_event(db, event_type="case.access", action="case.view", request=request,
                       actor_user_id=current_session.user_id, organization_id=case.organization_id,
                       workspace_id=case.workspace_id, resource_type="case", resource_id=case.id)
    db.commit()
    return payload


@router.get("/{case_id}/analysis")
def get_case_analysis(case_id: int, current_session: SessionModel = Depends(require_user_session), db: Session = Depends(get_db)) -> dict:
    case = _readable_case(db, case_id, current_session)
    conversation_ids = db.execute(select(CaseConversation.conversation_id).where(CaseConversation.case_id == case.id)).scalars().all()
    cape_cases = list(db.execute(select(CapeCase).where(CapeCase.conversation_id.in_(conversation_ids)).order_by(CapeCase.created_at)).scalars().all()) if conversation_ids else []
    indicators = list(db.execute(select(CaseIndicator).where(CaseIndicator.case_id == case.id).order_by(CaseIndicator.first_seen_at)).scalars().all())
    audit_events = list(db.execute(select(CaseEvent).where(CaseEvent.case_id == case.id).order_by(CaseEvent.created_at)).scalars().all())
    return build_case_analysis(case, cape_cases, indicators, audit_events)


@router.get("/{case_id}/collaboration")
def get_case_collaboration(case_id: int, current_session: SessionModel = Depends(require_user_session), db: Session = Depends(get_db)) -> dict:
    case = _readable_case(db, case_id, current_session)
    accesses = db.execute(select(CaseAccess).where(CaseAccess.case_id == case.id)).scalars().all()
    followers = db.execute(select(CaseFollower).where(CaseFollower.case_id == case.id)).scalars().all()
    comments = db.execute(select(CaseComment).where(CaseComment.case_id == case.id).order_by(CaseComment.created_at)).scalars().all()
    def user_item(user_id: int) -> dict:
        user = db.get(User, user_id)
        return {"userId": user_id, "username": user.username if user else "unknown", "displayName": user.display_name if user else None}
    return {
        "access": [{**user_item(item.user_id), "permission": item.permission} for item in accesses],
        "followers": [user_item(item.user_id) for item in followers],
        "comments": [{"id": item.id, "content": item.content, "author": user_item(item.author_user_id), "createdAt": item.created_at, "updatedAt": item.updated_at} for item in comments],
    }


@router.put("/{case_id}/access")
def share_case(case_id: int, payload: CaseAccessUpsert, current_session: SessionModel = Depends(require_user_session), db: Session = Depends(get_db)) -> dict:
    case = require_case_access(db, case_id, current_session.user_id, manage=True)
    user = db.execute(select(User).where(__import__('sqlalchemy').func.lower(User.username) == payload.username.strip().lower())).scalar_one_or_none()
    if user is None: raise HTTPException(status_code=404, detail="User not found")
    item = db.execute(select(CaseAccess).where(CaseAccess.case_id == case.id, CaseAccess.user_id == user.id)).scalar_one_or_none()
    if item is None:
        item = CaseAccess(case_id=case.id, user_id=user.id, created_by_user_id=current_session.user_id)
        db.add(item)
    item.permission = payload.permission
    if case.organization_id is not None:
        notify(db, NotificationEvent(organization_id=case.organization_id, user_id=user.id,
            notification_type="case_shared", title=f"案件已与你共享：{case.title}", case_id=case.id,
            actor_user_id=current_session.user_id, resource_type="case", resource_id=str(case.id),
            resource_url=f"/cases?case={case.id}", idempotency_key=f"case:{case.id}:shared:{user.id}:{payload.permission}"))
    _add_event(db, case, "case_shared", f"案件已共享给 {user.username}", metadata={"userId": user.id, "permission": payload.permission}, actor=_actor(db, current_session))
    db.commit()
    return {"userId": user.id, "username": user.username, "displayName": user.display_name, "permission": item.permission}


@router.put("/{case_id}/follow")
def follow_case(case_id: int, current_session: SessionModel = Depends(require_user_session), db: Session = Depends(get_db)) -> dict:
    case = _readable_case(db, case_id, current_session)
    item = db.execute(select(CaseFollower).where(CaseFollower.case_id == case.id, CaseFollower.user_id == current_session.user_id)).scalar_one_or_none()
    if item is None: db.add(CaseFollower(case_id=case.id, user_id=current_session.user_id))
    db.commit(); return {"following": True}


@router.delete("/{case_id}/follow")
def unfollow_case(case_id: int, current_session: SessionModel = Depends(require_user_session), db: Session = Depends(get_db)) -> dict:
    case = _readable_case(db, case_id, current_session)
    item = db.execute(select(CaseFollower).where(CaseFollower.case_id == case.id, CaseFollower.user_id == current_session.user_id)).scalar_one_or_none()
    if item: db.delete(item); db.commit()
    return {"following": False}


@router.post("/{case_id}/comments", status_code=201)
def add_case_comment(case_id: int, payload: CaseCommentCreate, current_session: SessionModel = Depends(require_user_session), db: Session = Depends(get_db)) -> dict:
    case = require_case_access(db, case_id, current_session.user_id, write=True)
    comment = CaseComment(case_id=case.id, author_user_id=current_session.user_id, content=payload.content.strip())
    db.add(comment); db.flush()
    usernames = set(re.findall(r"(?<![\w@])@([A-Za-z0-9_.-]{1,64})", comment.content))
    mentioned = db.execute(select(User).where(__import__('sqlalchemy').func.lower(User.username).in_([name.lower() for name in usernames]))).scalars().all() if usernames else []
    follower_ids = set(db.execute(select(CaseFollower.user_id).where(CaseFollower.case_id == case.id)).scalars().all())
    for user_id in (follower_ids | {user.id for user in mentioned}) - {current_session.user_id}:
        kind = "mention" if any(user.id == user_id for user in mentioned) else "case_comment"
        if case.organization_id is not None:
            notify(db, NotificationEvent(organization_id=case.organization_id, user_id=user_id,
                notification_type=kind, title=f"{_actor(db, current_session)} 评论了案件：{case.title}",
                body=comment.content, case_id=case.id, actor_user_id=current_session.user_id,
                resource_type="case", resource_id=str(case.id), resource_url=f"/cases?case={case.id}",
                idempotency_key=f"case:{case.id}:comment:{comment.id}:{kind}:{user_id}"))
    _add_event(db, case, "comment_added", "添加了案件评论", metadata={"commentId": comment.id, "mentions": list(usernames)}, actor=_actor(db, current_session))
    db.commit(); db.refresh(comment)
    return {"id": comment.id, "content": comment.content, "createdAt": comment.created_at}


@router.get("/{case_id}/evidence-chain")
def get_evidence_chain(case_id: int, current_session: SessionModel = Depends(require_user_session), db: Session = Depends(get_db)) -> dict:
    return _evidence_chain(db, _readable_case(db, case_id, current_session))


@router.patch("/{case_id}/evidence/{evidence_id}")
def review_case_evidence(case_id: int, evidence_id: int, payload: CaseEvidenceReview, current_session: SessionModel = Depends(require_user_session), db: Session = Depends(get_db)) -> dict:
    case = _owned_case(db, case_id, current_session)
    evidence = next((item for item in _case_evidence(db, case) if item.id == evidence_id), None)
    if evidence is None:
        raise HTTPException(status_code=404, detail="Evidence not found in this case")
    actor = _actor(db, current_session)
    changes = payload.model_dump()
    mapping = {"reviewStatus": "review_status", "sourceTrust": "source_trust", "acquiredAt": "acquired_at", "contentHash": "content_hash", "snapshotUrl": "snapshot_url", "reviewNote": "review_note"}
    for key, value in changes.items():
        setattr(evidence, mapping.get(key, key), value.lower() if key == "contentHash" and value else value)
    evidence.reviewed_by = actor
    evidence.reviewed_at = now_utc()
    case.updated_at = now_utc()
    _invalidate_signatures(db, case, actor)
    _add_event(db, case, "evidence_reviewed", f"证据 {evidence.citation} 已审核", detail=evidence.review_note, metadata={"evidenceId": evidence.id, "status": evidence.review_status, "sourceTrust": evidence.source_trust, "confidence": evidence.confidence}, actor=actor)
    db.commit(); db.refresh(evidence)
    return _evidence_item(evidence)


@router.post("/{case_id}/conclusions", status_code=201)
def create_case_conclusion(case_id: int, payload: CaseConclusionCreate, current_session: SessionModel = Depends(require_user_session), db: Session = Depends(get_db)) -> dict:
    case = _owned_case(db, case_id, current_session)
    allowed_ids = {item.id for item in _case_evidence(db, case)}
    if not (set(payload.evidenceIds) | set(payload.conflictEvidenceIds)).issubset(allowed_ids):
        raise HTTPException(status_code=400, detail="Conclusion evidence must belong to this case")
    actor = _actor(db, current_session)
    cross_checks = [check.model_dump(mode="json") for check in payload.crossChecks]
    item = CaseConclusion(case_id=case.id, statement=payload.statement.strip(), status=payload.status, confidence=payload.confidence, claim_type=payload.claimType, confidence_rationale=payload.confidenceRationale, conflict_evidence_ids_json=json.dumps(list(dict.fromkeys(payload.conflictEvidenceIds))), cross_checks_json=json.dumps(cross_checks, ensure_ascii=False), created_by=actor, reviewed_by=actor if payload.status != "draft" else None, reviewed_at=now_utc() if payload.status != "draft" else None)
    db.add(item); db.flush()
    for evidence_id in dict.fromkeys(payload.evidenceIds):
        db.add(CaseConclusionEvidence(conclusion_id=item.id, evidence_id=evidence_id))
    case.updated_at = now_utc(); _invalidate_signatures(db, case, actor)
    _add_event(db, case, "conclusion_created", "新增研判结论", detail=item.statement, metadata={"conclusionId": item.id, "claimType": item.claim_type, "evidenceIds": payload.evidenceIds, "conflictEvidenceIds": payload.conflictEvidenceIds, "crossCheckModels": [check["modelId"] for check in cross_checks]}, actor=actor)
    db.commit()
    return _evidence_chain(db, case)


@router.patch("/{case_id}/conclusions/{conclusion_id}")
def update_case_conclusion(case_id: int, conclusion_id: int, payload: CaseConclusionUpdate, current_session: SessionModel = Depends(require_user_session), db: Session = Depends(get_db)) -> dict:
    case = _owned_case(db, case_id, current_session)
    item = db.execute(select(CaseConclusion).where(CaseConclusion.id == conclusion_id, CaseConclusion.case_id == case.id)).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Conclusion not found")
    changes = payload.model_dump(exclude_unset=True)
    evidence_changes = set(changes.get("evidenceIds") or []) | set(changes.get("conflictEvidenceIds") or [])
    if evidence_changes:
        allowed_ids = {e.id for e in _case_evidence(db, case)}
        if not evidence_changes.issubset(allowed_ids):
            raise HTTPException(status_code=400, detail="Conclusion evidence must belong to this case")
    if "evidenceIds" in changes:
        for link in list(item.evidence_links): db.delete(link)
        for evidence_id in dict.fromkeys(changes.pop("evidenceIds") or []): db.add(CaseConclusionEvidence(conclusion_id=item.id, evidence_id=evidence_id))
    mapping = {"claimType": "claim_type", "confidenceRationale": "confidence_rationale"}
    if "conflictEvidenceIds" in changes:
        item.conflict_evidence_ids_json = json.dumps(list(dict.fromkeys(changes.pop("conflictEvidenceIds") or [])))
    if "crossChecks" in changes:
        item.cross_checks_json = json.dumps(changes.pop("crossChecks") or [], ensure_ascii=False, default=str)
    for key, value in changes.items(): setattr(item, mapping.get(key, key), value.strip() if key == "statement" else value)
    actor = _actor(db, current_session)
    if "status" in changes:
        item.reviewed_by = actor if item.status != "draft" else None
        item.reviewed_at = now_utc() if item.status != "draft" else None
    item.updated_at = now_utc(); case.updated_at = now_utc()
    _invalidate_signatures(db, case, actor)
    _add_event(db, case, "conclusion_updated", "更新研判结论", detail=item.statement, metadata={"conclusionId": item.id}, actor=actor)
    db.commit()
    return _evidence_chain(db, case)


def _parse_cross_check_response(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines and lines[-1].strip() == "```" else lines[1:])
    try:
        result = json.loads(text)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail="复核模型未返回有效 JSON") from exc
    verdict = result.get("verdict") if isinstance(result, dict) else None
    rationale = str(result.get("rationale", "")).strip() if isinstance(result, dict) else ""
    confidence = result.get("confidence") if isinstance(result, dict) else None
    if verdict not in {"supports", "contradicts", "inconclusive"} or not rationale or not isinstance(confidence, (int, float)):
        raise HTTPException(status_code=502, detail="复核模型返回结果缺少必要字段")
    return {"verdict": verdict, "confidence": max(0, min(100, round(confidence))), "rationale": rationale[:2000]}


@router.post("/{case_id}/conclusions/{conclusion_id}/cross-check")
async def cross_check_case_conclusion(case_id: int, conclusion_id: int, payload: ConclusionCrossCheckRequest, current_session: SessionModel = Depends(require_user_session), db: Session = Depends(get_db)) -> dict:
    case = _owned_case(db, case_id, current_session)
    item = db.execute(select(CaseConclusion).where(CaseConclusion.id == conclusion_id, CaseConclusion.case_id == case.id)).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Conclusion not found")
    evidence_by_id = {evidence.id: evidence for evidence in _case_evidence(db, case)}
    support_ids = [link.evidence_id for link in item.evidence_links]
    conflict_ids = json.loads(item.conflict_evidence_ids_json or "[]")
    def evidence_lines(ids: list[int]) -> list[str]:
        return [f"[{evidence_by_id[evidence_id].citation}] {evidence_by_id[evidence_id].title}: {evidence_by_id[evidence_id].snippet or evidence_by_id[evidence_id].locator or '无摘要'} (审核={evidence_by_id[evidence_id].review_status}, 来源可信度={evidence_by_id[evidence_id].source_trust}, 置信度={evidence_by_id[evidence_id].confidence})" for evidence_id in ids if evidence_id in evidence_by_id]
    prompt = "\n".join([
        "你是独立的安全研判复核模型。只能依据下列材料判断结论是否成立，不得补充未提供的事实。",
        f"结论类型: {item.claim_type}", f"待复核结论: {item.statement}",
        f"原置信度: {item.confidence}", f"原置信度依据: {item.confidence_rationale or '未提供'}",
        "支撑证据:", *(evidence_lines(support_ids) or ["无"]), "冲突证据:", *(evidence_lines(conflict_ids) or ["无"]),
        '只返回 JSON，不要 Markdown：{"verdict":"supports|contradicts|inconclusive","confidence":0到100的整数,"rationale":"说明关键依据、冲突和不确定性"}',
    ])
    try:
        chunks = []
        async for chunk in stream_chat_completion([{"role": "user", "content": prompt}], payload.modelId):
            chunks.append(chunk)
            if sum(len(part) for part in chunks) > 12000:
                raise HTTPException(status_code=502, detail="复核模型返回内容过长")
    except DeepSeekConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except StreamedUpstreamError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    result = _parse_cross_check_response("".join(chunks))
    checks = json.loads(item.cross_checks_json or "[]")
    check = {"modelId": payload.modelId, **result, "checkedAt": now_utc().isoformat()}
    checks.append(check)
    item.cross_checks_json = json.dumps(checks[-12:], ensure_ascii=False)
    actor = _actor(db, current_session); item.updated_at = now_utc(); case.updated_at = now_utc()
    _invalidate_signatures(db, case, actor)
    _add_event(db, case, "conclusion_cross_checked", "结论已完成跨模型复核", detail=result["rationale"], metadata={"conclusionId": item.id, "modelId": payload.modelId, "verdict": result["verdict"], "confidence": result["confidence"]}, actor=actor)
    db.commit()
    return _evidence_chain(db, case)


@router.post("/{case_id}/signatures", status_code=201)
def sign_case(case_id: int, payload: CaseSignRequest, current_session: SessionModel = Depends(require_user_session), db: Session = Depends(get_db)) -> dict:
    case = _owned_case(db, case_id, current_session)
    conclusion_count = len(db.execute(select(CaseConclusion.id).where(CaseConclusion.case_id == case.id)).scalars().all())
    if not conclusion_count:
        raise HTTPException(status_code=400, detail="At least one conclusion is required before signing")
    actor = _actor(db, current_session)
    _invalidate_signatures(db, case, actor)
    signature = CaseSignature(case_id=case.id, signer=payload.signer.strip(), digest=_chain_digest(db, case), note=payload.note)
    db.add(signature); db.flush()
    _add_event(db, case, "case_signed", "研判结论已签署", detail=payload.note, metadata={"signatureId": signature.id, "digest": signature.digest}, actor=actor)
    db.commit()
    return _evidence_chain(db, case)


@router.get("/{case_id}/evidence-chain/export")
def export_evidence_chain(case_id: int, request: Request, current_session: SessionModel = Depends(require_user_session), db: Session = Depends(get_db)) -> Response:
    case = _owned_case(db, case_id, current_session)
    actor = _actor(db, current_session)
    _add_event(db, case, "evidence_chain_exported", "导出了证据链", actor=actor)
    record_audit_event(db, event_type="case.export", action="evidence_chain.export", request=request,
                       actor_user_id=current_session.user_id, organization_id=case.organization_id,
                       workspace_id=case.workspace_id, resource_type="case", resource_id=case.id,
                       detail={"format": "json"})
    db.commit()
    content = json.dumps(_evidence_chain(db, case), ensure_ascii=False, indent=2, default=str)
    return Response(content=content, media_type="application/json", headers={"Content-Disposition": f'attachment; filename="case-{case.id}-evidence-chain.json"'})


@router.get("/{case_id}/report/export")
def export_case_report(
    case_id: int,
    request: Request,
    format: str = "pdf",
    report_type: str = Query("technical_zh", alias="reportType"),
    watermark: str | None = Query(None, max_length=120),
    current_session: SessionModel = Depends(require_user_session),
    db: Session = Depends(get_db),
) -> Response:
    case = _readable_case(db, case_id, current_session)
    normalized_format = {"md": "markdown", "stix2": "stix", "navigator": "attack_navigator", "attack-navigator": "attack_navigator"}.get(format.lower(), format.lower())
    normalized_type = {"zh": "technical_zh", "en": "technical_en", "management": "executive", "executive_summary": "executive"}.get(report_type.lower(), report_type.lower())
    if normalized_format not in EXPORT_FORMATS:
        raise HTTPException(status_code=400, detail="Unsupported report export format")
    if normalized_type not in REPORT_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported report type")
    data = build_report_data(db, case, report_type=normalized_type, watermark=watermark.strip() if watermark else None)
    try:
        content, media_type, suffix = export_report(data, normalized_format)
    except ImportError as exc:
        raise HTTPException(status_code=503, detail="Report export dependency is unavailable") from exc
    record_audit_event(db, event_type="case.export", action="case_report.export", request=request,
                       actor_user_id=current_session.user_id, organization_id=case.organization_id,
                       workspace_id=case.workspace_id, resource_type="case", resource_id=case.id,
                       detail={"caseId": case.id, "format": normalized_format, "reportType": normalized_type,
                               "version": data["version"], "watermark": bool(data.get("watermark"))})
    db.commit()
    filename = f"case-{case.id}-{normalized_type}-v{data['version']}.{suffix}"
    return Response(content=content, media_type=media_type, headers={
        "Content-Disposition": f'attachment; filename="{filename}"',
        "X-Cipher-Report-Version": data["version"], "X-Cipher-Case-ID": str(case.id),
        "X-Cipher-Generated-At": data["generatedAt"],
    })


@router.get("/{case_id}/reports/export", include_in_schema=False)
def export_case_report_compat(
    case_id: int,
    request: Request,
    format: str = "pdf",
    report_type: str = Query("technical_zh", alias="reportType"),
    watermark: str | None = Query(None, max_length=120),
    current_session: SessionModel = Depends(require_user_session),
    db: Session = Depends(get_db),
) -> Response:
    return export_case_report(case_id, request, format, report_type, watermark, current_session, db)


@router.get("/{case_id}/iocs", response_model=CaseIndicatorList)
def list_case_indicators(case_id: int, indicator_type: str | None = Query(None, alias="type"), indicator_status: str | None = Query(None, alias="status"), risk: str | None = None, query: str | None = None, current_session: SessionModel = Depends(require_user_session), db: Session = Depends(get_db)) -> CaseIndicatorList:
    case = _readable_case(db, case_id, current_session)
    statement = select(CaseIndicator).where(CaseIndicator.case_id == case.id)
    if indicator_type: statement = statement.where(CaseIndicator.indicator_type == indicator_type)
    if indicator_status: statement = statement.where(CaseIndicator.status == indicator_status)
    if risk: statement = statement.where(CaseIndicator.risk_level == risk)
    if query: statement = statement.where(CaseIndicator.value.ilike(f"%{query}%"))
    items = list(db.execute(statement.order_by(CaseIndicator.last_seen_at.desc(), CaseIndicator.id.desc())).scalars().all())
    all_items = list(db.execute(select(CaseIndicator).where(CaseIndicator.case_id == case.id)).scalars().all())
    return CaseIndicatorList(items=[_indicator_item(item) for item in items], total=len(all_items), counts={"type": {key: sum(item.indicator_type == key for item in all_items) for key in ("domain", "ip", "url", "md5", "sha1", "sha256")}, "status": {key: sum(item.status == key for item in all_items) for key in ("pending", "malicious", "suspicious", "false_positive", "blocked")}})


@router.post("/{case_id}/iocs/sync", response_model=CaseIndicatorList)
def sync_case_indicators(case_id: int, current_session: SessionModel = Depends(require_user_session), db: Session = Depends(get_db)) -> CaseIndicatorList:
    case = _owned_case(db, case_id, current_session)
    added, discovered = _sync_indicators(db, case)
    case.updated_at = now_utc()
    _add_event(db, case, "iocs_synced", "IOC 已同步", detail=f"发现 {discovered} 项，新增 {added} 项", metadata={"discovered": discovered, "added": added})
    db.commit()
    return list_case_indicators(case_id, indicator_type=None, indicator_status=None, risk=None, query=None, current_session=current_session, db=db)


@router.get("/{case_id}/ioc-providers")
def list_ioc_providers(case_id: int, current_session: SessionModel = Depends(require_user_session), db: Session = Depends(get_db)) -> dict:
    _readable_case(db, case_id, current_session)
    return {"items": threat_intel_service.public_status()}


@router.post("/{case_id}/iocs/{indicator_id}/enrich", response_model=CaseIndicatorItem)
async def enrich_case_indicator(case_id: int, indicator_id: int, payload: CaseIndicatorEnrichRequest,
        request: Request, current_session: SessionModel = Depends(require_user_session), db: Session = Depends(get_db)) -> CaseIndicatorItem:
    case = _owned_case(db, case_id, current_session)
    item = db.execute(select(CaseIndicator).where(CaseIndicator.id == indicator_id, CaseIndicator.case_id == case.id)).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="IOC not found")
    enrichment = await threat_intel_service.enrich(db, item.indicator_type, item.normalized_value,
        provider_keys=payload.providers, force=payload.force)
    item.enrichment_json = json.dumps(enrichment, ensure_ascii=False)
    malicious_results = [result for result in enrichment["results"] if result.get("malicious") is True]
    if enrichment["results"]:
        item.confidence = max(item.confidence, max(int(result.get("confidence", 0)) for result in enrichment["results"]))
    if malicious_results and item.status == "pending":
        item.status = "malicious" if len(malicious_results) >= 2 else "suspicious"
        item.risk_level = "critical" if item.confidence >= 90 else "high" if item.confidence >= 70 else "medium"
    item.updated_at = now_utc(); case.updated_at = now_utc()
    _add_event(db, case, "ioc_enriched", f"IOC 情报已查询：{item.value}",
        metadata={"indicatorId": item.id, "providers": [result["provider"] for result in enrichment["results"]], "errors": enrichment["errors"]}, actor=_actor(db, current_session))
    record_audit_event(db, event_type="case.ioc_enrich", action="ioc.enrich", request=request,
        actor_user_id=current_session.user_id, organization_id=case.organization_id, workspace_id=case.workspace_id,
        resource_type="case_indicator", resource_id=item.id,
        detail={"caseId": case.id, "providers": [result["provider"] for result in enrichment["results"]]})
    db.commit(); db.refresh(item)
    return _indicator_item(item)


@router.patch("/{case_id}/iocs/{indicator_id}", response_model=CaseIndicatorItem)
def update_case_indicator(case_id: int, indicator_id: int, payload: CaseIndicatorUpdate, current_session: SessionModel = Depends(require_user_session), db: Session = Depends(get_db)) -> CaseIndicatorItem:
    case = _owned_case(db, case_id, current_session)
    item = db.execute(select(CaseIndicator).where(CaseIndicator.id == indicator_id, CaseIndicator.case_id == case.id)).scalar_one_or_none()
    if item is None: raise HTTPException(status_code=404, detail="IOC not found")
    mapping = {"riskLevel": "risk_level", "expiresAt": "expires_at"}
    for key, value in payload.model_dump(exclude_unset=True).items(): setattr(item, mapping.get(key, key), value)
    item.updated_at = now_utc(); case.updated_at = now_utc()
    _add_event(db, case, "ioc_updated", f"IOC 已更新：{item.value}", metadata=payload.model_dump(exclude_unset=True))
    db.commit(); db.refresh(item)
    return _indicator_item(item)


@router.post("/{case_id}/iocs/bulk-status", response_model=CaseIndicatorList)
def bulk_update_case_indicators(case_id: int, payload: CaseIndicatorBulkUpdate, current_session: SessionModel = Depends(require_user_session), db: Session = Depends(get_db)) -> CaseIndicatorList:
    case = _owned_case(db, case_id, current_session)
    items = list(db.execute(select(CaseIndicator).where(CaseIndicator.case_id == case.id, CaseIndicator.id.in_(payload.ids))).scalars().all())
    if len(items) != len(set(payload.ids)): raise HTTPException(status_code=400, detail="One or more IOCs were not found")
    for item in items: item.status = payload.status; item.updated_at = now_utc()
    case.updated_at = now_utc(); _add_event(db, case, "iocs_bulk_updated", f"批量更新 {len(items)} 项 IOC", metadata={"ids": payload.ids, "status": payload.status})
    db.commit()
    return list_case_indicators(case_id, indicator_type=None, indicator_status=None, risk=None, query=None, current_session=current_session, db=db)


@router.get("/{case_id}/iocs/export")
def export_case_indicators(case_id: int, format: str = "csv", current_session: SessionModel = Depends(require_user_session), db: Session = Depends(get_db)) -> Response:
    case = _owned_case(db, case_id, current_session)
    statement = select(CaseIndicator).where(CaseIndicator.case_id == case.id)
    if format != "csv": statement = statement.where(CaseIndicator.status.in_(("malicious", "suspicious", "blocked")))
    items = list(db.execute(statement.order_by(CaseIndicator.indicator_type, CaseIndicator.value)).scalars().all())
    if format == "csv":
        output = StringIO(); writer = csv.writer(output); writer.writerow(["type", "value", "risk", "confidence", "status", "sample", "first_seen", "last_seen"])
        for item in items: writer.writerow([item.indicator_type, item.value, item.risk_level, item.confidence, item.status, item.sample_name or "", item.first_seen_at.isoformat(), item.last_seen_at.isoformat()])
        content, media_type, suffix = output.getvalue(), "text/csv; charset=utf-8", "csv"
    elif format == "dns":
        content = "\n".join(f"0.0.0.0 {item.normalized_value}" for item in items if item.indicator_type == "domain") + "\n"; media_type, suffix = "text/plain; charset=utf-8", "hosts"
    elif format == "firewall":
        content = "\n".join(item.normalized_value for item in items if item.indicator_type in {"ip", "domain"}) + "\n"; media_type, suffix = "text/plain; charset=utf-8", "txt"
    elif format == "edr":
        content = json.dumps({"caseId": case.id, "indicators": [{"type": item.indicator_type, "value": item.normalized_value, "action": "block"} for item in items]}, ensure_ascii=False, indent=2); media_type, suffix = "application/json", "json"
    else:
        raise HTTPException(status_code=400, detail="Unsupported export format")
    return Response(content=content, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="case-{case.id}-iocs.{suffix}"'})


@router.get("/{case_id}/rules", response_model=DetectionRuleList)
def list_detection_rules(case_id: int, current_session: SessionModel = Depends(require_user_session), db: Session = Depends(get_db)) -> DetectionRuleList:
    case = _owned_case(db, case_id, current_session)
    rules = list(db.execute(select(DetectionRule).where(DetectionRule.case_id == case.id).order_by(DetectionRule.updated_at.desc(), DetectionRule.id.desc())).scalars().all())
    return DetectionRuleList(
        items=[_rule_item(rule) for rule in rules],
        counts={status_name: sum(rule.status == status_name for rule in rules) for status_name in ("draft", "validated", "approved", "deployed")},
    )


@router.post("/{case_id}/rules", response_model=DetectionRuleItem, status_code=201)
def create_detection_rule(case_id: int, payload: DetectionRuleCreate, current_session: SessionModel = Depends(require_user_session), db: Session = Depends(get_db)) -> DetectionRuleItem:
    case = _owned_case(db, case_id, current_session)
    if payload.sourceCapeCaseId is not None:
        conversation_ids = db.execute(select(CaseConversation.conversation_id).where(CaseConversation.case_id == case.id)).scalars().all()
        source_exists = db.execute(select(CapeCase.id).where(CapeCase.id == payload.sourceCapeCaseId, CapeCase.conversation_id.in_(conversation_ids))).scalar_one_or_none()
        if source_exists is None:
            raise HTTPException(status_code=400, detail="CAPE source is not linked to this Case")
    rule = DetectionRule(case_id=case.id, source_cape_case_id=payload.sourceCapeCaseId, rule_type=payload.ruleType, title=payload.title, content=payload.content)
    db.add(rule); db.flush(); _save_rule_version(db, rule, case.assignee)
    case.updated_at = now_utc(); _add_event(db, case, "rule_created", f"创建了 {payload.ruleType.upper()} 规则", detail=payload.title, metadata={"ruleId": rule.id, "version": 1})
    db.commit(); db.refresh(rule)
    return _rule_item(rule)


@router.post("/{case_id}/rules/generate", response_model=DetectionRuleList)
def generate_detection_rules(case_id: int, payload: DetectionRuleGenerateRequest, current_session: SessionModel = Depends(require_user_session), db: Session = Depends(get_db)) -> DetectionRuleList:
    case = _owned_case(db, case_id, current_session)
    conversation_ids = db.execute(select(CaseConversation.conversation_id).where(CaseConversation.case_id == case.id)).scalars().all()
    statement = select(CapeCase).where(CapeCase.conversation_id.in_(conversation_ids), CapeCase.summary_json.is_not(None))
    if payload.capeCaseIds:
        statement = statement.where(CapeCase.id.in_(payload.capeCaseIds))
    cape_cases = list(db.execute(statement.order_by(CapeCase.updated_at.desc())).scalars().all())
    if not cape_cases:
        raise HTTPException(status_code=409, detail="No completed CAPE reports are linked to this Case")
    created: list[DetectionRule] = []
    for cape_case in cape_cases:
        for rule_type in dict.fromkeys(payload.ruleTypes):
            content = (build_sigma_starter(cape_case) if rule_type == "sigma" else build_yara_starter(cape_case)).decode("utf-8")
            rule = DetectionRule(case_id=case.id, source_cape_case_id=cape_case.id, rule_type=rule_type, title=f"{cape_case.sample_name} · {rule_type.upper()} starter", content=content)
            db.add(rule); db.flush(); _save_rule_version(db, rule, case.assignee); created.append(rule)
    case.updated_at = now_utc(); _add_event(db, case, "rules_generated", f"生成了 {len(created)} 条检测规则", metadata={"ruleIds": [rule.id for rule in created]})
    db.commit()
    return list_detection_rules(case_id, current_session=current_session, db=db)


@router.patch("/{case_id}/rules/{rule_id}", response_model=DetectionRuleItem)
def update_detection_rule(case_id: int, rule_id: int, payload: DetectionRuleUpdate, current_session: SessionModel = Depends(require_user_session), db: Session = Depends(get_db)) -> DetectionRuleItem:
    case = _owned_case(db, case_id, current_session); rule = _owned_rule(db, case, rule_id)
    changes = payload.model_dump(exclude_unset=True)
    if "title" in changes:
        title = (changes["title"] or "").strip()
        if not title: raise HTTPException(status_code=400, detail="Rule title cannot be blank")
        rule.title = title
    if "content" in changes:
        content = (changes["content"] or "").strip()
        if not content: raise HTTPException(status_code=400, detail="Rule content cannot be blank")
        if content != rule.content:
            rule.version += 1; rule.content = content; rule.status = "draft"; rule.validation_status = "not_validated"; rule.validation_json = "{}"; rule.last_validated_at = None; rule.approved_at = None; rule.deployed_at = None
    if "status" in changes:
        next_status = changes["status"]
        if next_status in {"validated", "approved", "deployed"} and rule.validation_status != "valid":
            raise HTTPException(status_code=409, detail="Only valid rules can advance beyond draft")
        if next_status == "deployed" and rule.status != "approved":
            raise HTTPException(status_code=409, detail="A rule must be approved before deployment")
        rule.status = next_status
        if next_status == "approved": rule.approved_at = now_utc()
        if next_status == "deployed": rule.deployed_at = now_utc()
    rule.updated_at = now_utc(); case.updated_at = now_utc(); _save_rule_version(db, rule, case.assignee)
    _add_event(db, case, "rule_updated", f"更新了规则：{rule.title}", metadata={"ruleId": rule.id, "version": rule.version, "changes": list(changes)})
    db.commit(); db.refresh(rule)
    return _rule_item(rule)


@router.post("/{case_id}/rules/{rule_id}/validate", response_model=DetectionRuleItem)
def validate_detection_rule(case_id: int, rule_id: int, current_session: SessionModel = Depends(require_user_session), db: Session = Depends(get_db)) -> DetectionRuleItem:
    case = _owned_case(db, case_id, current_session); rule = _owned_rule(db, case, rule_id)
    result = validate_rule(rule.rule_type, rule.content)
    rule.validation_status = "valid" if result.valid else "invalid"; rule.validation_json = json.dumps(result.as_dict(), ensure_ascii=False); rule.last_validated_at = now_utc(); rule.updated_at = now_utc()
    if result.valid and rule.status == "draft": rule.status = "validated"
    elif not result.valid: rule.status = "draft"; rule.approved_at = None; rule.deployed_at = None
    _save_rule_version(db, rule, case.assignee); case.updated_at = now_utc()
    _add_event(db, case, "rule_validated", f"规则验证{'通过' if result.valid else '失败'}：{rule.title}", detail="；".join(result.errors or result.warnings[:3]), metadata={"ruleId": rule.id, "version": rule.version, "valid": result.valid})
    db.commit(); db.refresh(rule)
    return _rule_item(rule)


@router.post("/{case_id}/rules/{rule_id}/test", response_model=DetectionRuleTestRunItem)
async def test_detection_rule(case_id: int, rule_id: int, files: list[UploadFile] = File(...), current_session: SessionModel = Depends(require_user_session), db: Session = Depends(get_db)) -> DetectionRuleTestRunItem:
    case = _owned_case(db, case_id, current_session); rule = _owned_rule(db, case, rule_id)
    if rule.validation_status != "valid": raise HTTPException(status_code=409, detail="Validate the rule before testing")
    artifacts: list[tuple[str, bytes]] = []
    for upload in files:
        content = await upload.read()
        if len(content) > 20 * 1024 * 1024: raise HTTPException(status_code=413, detail=f"Test artifact is too large: {upload.filename}")
        artifacts.append((upload.filename or "artifact", content))
    try: result = test_rule(rule.rule_type, rule.content, artifacts)
    except Exception as exc: raise HTTPException(status_code=409, detail=str(exc)) from exc
    run = DetectionRuleTestRun(rule_id=rule.id, total_artifacts=result["totalArtifacts"], matched_artifacts=result["matchedArtifacts"], false_positive_count=result["falsePositiveCount"], result_json=json.dumps(result, ensure_ascii=False))
    db.add(run); case.updated_at = now_utc(); _add_event(db, case, "rule_tested", f"测试了规则：{rule.title}", detail=f"命中 {run.matched_artifacts}/{run.total_artifacts}", metadata={"ruleId": rule.id})
    db.commit(); db.refresh(run)
    return DetectionRuleTestRunItem(id=run.id, totalArtifacts=run.total_artifacts, matchedArtifacts=run.matched_artifacts, falsePositiveCount=run.false_positive_count, results=result["results"], createdAt=run.created_at)


@router.get("/{case_id}/rules/{rule_id}/export")
def export_detection_rule(case_id: int, rule_id: int, format: str = "html", current_session: SessionModel = Depends(require_user_session), db: Session = Depends(get_db)) -> Response:
    case = _owned_case(db, case_id, current_session); rule = _owned_rule(db, case, rule_id); payload = _rule_item(rule).model_dump(mode="json")
    if format == "html": content, media_type, suffix = build_rule_report_html(payload), "text/html; charset=utf-8", "html"
    elif format == "pdf":
        try: content = build_rule_report_pdf(payload)
        except ImportError as exc: raise HTTPException(status_code=503, detail="PDF export dependency is unavailable") from exc
        media_type, suffix = "application/pdf", "pdf"
    elif format == "raw": content, media_type, suffix = rule.content.encode("utf-8"), "text/plain; charset=utf-8", "yml" if rule.rule_type == "sigma" else "yar"
    else: raise HTTPException(status_code=400, detail="Unsupported rule export format")
    return Response(content=content, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="case-{case.id}-rule-{rule.id}-v{rule.version}.{suffix}"'})


@router.patch("/{case_id}", response_model=InvestigationCaseItem)
def update_case(case_id: int, payload: InvestigationCaseUpdate, current_session: SessionModel = Depends(require_user_session), db: Session = Depends(get_db)) -> InvestigationCaseItem:
    case = _owned_case(db, case_id, current_session); changes = payload.model_dump(exclude_unset=True)
    status_reason = changes.pop("statusReason", None)
    old_status = case.status
    if "status" in changes and changes["status"] != old_status:
        if changes["status"] not in STATUS_TRANSITIONS.get(old_status, set()):
            raise HTTPException(status_code=409, detail=f"非法状态流转：{old_status} -> {changes['status']}")
        status_reason = status_reason.strip() if status_reason else "兼容旧版 API 的状态更新（未提供原因）"
    if "parentCaseId" in changes: _validate_related(db, current_session.user_id, changes["parentCaseId"], case.id)
    if "assigneeUserId" in changes:
        user = db.get(User, changes["assigneeUserId"]) if changes["assigneeUserId"] else None
        if user and db.execute(select(OrganizationMember.id).where(OrganizationMember.organization_id == case.organization_id, OrganizationMember.user_id == user.id)).scalar_one_or_none() is None:
            raise HTTPException(status_code=400, detail="Assignee must be an organization member")
        changes["assignee"] = (user.display_name or user.username) if user else None
        if user and user.id != current_session.user_id:
            if case.organization_id is not None:
                notify(db, NotificationEvent(organization_id=case.organization_id, user_id=user.id,
                    notification_type="case_assigned", title=f"案件已分配给你：{case.title}", case_id=case.id,
                    actor_user_id=current_session.user_id, resource_type="case", resource_id=str(case.id),
                    resource_url=f"/cases?case={case.id}", idempotency_key=f"case:{case.id}:assigned:{user.id}"))
    mapping = {"slaDueAt": "sla_due_at", "parentCaseId": "parent_case_id", "assigneeUserId": "assignee_user_id"}
    for key, value in changes.items():
        if key == "tags": case.tags_json = json.dumps(value or [], ensure_ascii=False)
        else: setattr(case, mapping.get(key, key), value.strip() if isinstance(value, str) else value)
    if case.status == "closed" and old_status != "closed": case.closed_at = now_utc()
    elif case.status != "closed": case.closed_at = None
    case.updated_at = now_utc()
    event_type = "status_changed" if "status" in changes else "updated"
    metadata = {**changes}
    if event_type == "status_changed": metadata = {"fromStatus": old_status, "toStatus": case.status, "reason": status_reason, **metadata}
    _add_event(db, case, event_type, "状态已变更" if event_type == "status_changed" else "Case 信息已更新", detail=status_reason if event_type == "status_changed" else None, metadata=metadata, actor=_actor(db, current_session))
    db.commit(); db.refresh(case)
    return _serialize(db, case, detailed=True)


@router.post("/{case_id}/conversations", response_model=InvestigationCaseItem)
def add_conversations(case_id: int, payload: CaseConversationAdd, current_session: SessionModel = Depends(require_user_session), db: Session = Depends(get_db)) -> InvestigationCaseItem:
    case = _owned_case(db, case_id, current_session)
    conversations = db.execute(select(Conversation).where(Conversation.id.in_(payload.conversationIds), Conversation.owner_user_id == current_session.user_id)).scalars().all()
    if len(conversations) != len(set(payload.conversationIds)): raise HTTPException(status_code=400, detail="One or more conversations were not found")
    existing = set(db.execute(select(CaseConversation.conversation_id).where(CaseConversation.case_id == case.id)).scalars().all())
    added = [item for item in conversations if item.id not in existing]
    for conversation in added: db.add(CaseConversation(case_id=case.id, conversation_id=conversation.id))
    db.flush(); _sync_indicators(db, case)
    case.updated_at = now_utc(); _add_event(db, case, "conversation_linked", "关联了对话", detail="、".join(item.title for item in added), metadata={"conversationIds": [item.id for item in added]})
    db.commit(); db.refresh(case)
    return _serialize(db, case, detailed=True)


@router.delete("/{case_id}/conversations/{conversation_id}", status_code=204)
def remove_conversation(case_id: int, conversation_id: int, current_session: SessionModel = Depends(require_user_session), db: Session = Depends(get_db)) -> Response:
    case = _owned_case(db, case_id, current_session)
    link = db.execute(select(CaseConversation).where(CaseConversation.case_id == case.id, CaseConversation.conversation_id == conversation_id)).scalar_one_or_none()
    if link is None: raise HTTPException(status_code=404, detail="Conversation link not found")
    db.delete(link); case.updated_at = now_utc(); _add_event(db, case, "conversation_unlinked", "移除了关联对话", metadata={"conversationId": conversation_id}); db.commit()
    return Response(status_code=204)


@router.post("/{case_id}/merge", response_model=InvestigationCaseItem)
def merge_case(case_id: int, payload: CaseMergeRequest, current_session: SessionModel = Depends(require_user_session), db: Session = Depends(get_db)) -> InvestigationCaseItem:
    source = _owned_case(db, case_id, current_session); target = _owned_case(db, payload.targetCaseId, current_session)
    if source.id == target.id: raise HTTPException(status_code=400, detail="A case cannot be merged into itself")
    if source.merged_into_case_id or target.merged_into_case_id: raise HTTPException(status_code=400, detail="Merged cases cannot be merged again")
    target_ids = set(db.execute(select(CaseConversation.conversation_id).where(CaseConversation.case_id == target.id)).scalars().all())
    for link in list(db.execute(select(CaseConversation).where(CaseConversation.case_id == source.id)).scalars().all()):
        if link.conversation_id in target_ids: db.delete(link)
        else: link.case_id = target.id
    for child in db.execute(select(InvestigationCase).where(InvestigationCase.parent_case_id == source.id)).scalars().all(): child.parent_case_id = target.id
    source.merged_into_case_id = target.id; source.status = "closed"; source.closed_at = now_utc(); source.updated_at = now_utc(); target.updated_at = now_utc()
    _add_event(db, target, "merged", f"合并了 Case #{source.id}", metadata={"sourceCaseId": source.id}); _add_event(db, source, "merged_into", f"已合并至 Case #{target.id}", metadata={"targetCaseId": target.id})
    db.commit(); db.refresh(target)
    return _serialize(db, target, detailed=True)
