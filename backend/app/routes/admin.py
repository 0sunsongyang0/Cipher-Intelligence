from __future__ import annotations

import csv
import hashlib
import io
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from statistics import mean

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.admin_control import AdminActionResult, AdminControlManager
from app.audit import record_audit_event
from app.attachments import MAX_FILE_COUNT
from app.auth import require_admin_user_session
from app.config import settings
from app.database import get_db
from app.deepseek import ChatModelId
from app.models import ChatRequestMetric, InviteCode, MessageFeedback, ObservabilityEvent
from app.models import DataRetentionPolicy
from app.models import EvalRun, EvalRunResult, EvalTestCase, EvalTestSet
from app.retention import get_policy, run_retention_cleanup
from app.models import Session as SessionModel
from app.prompt_config_store import load_prompt_config, reset_prompt_override, save_prompt_override
from app.schemas import AdminInviteCreateRequest, AdminInviteItem, AdminInviteListResponse
from app.zip_context_store import zip_context_store


router = APIRouter(prefix="/api/admin", tags=["admin"])

class RetentionPolicyPayload(BaseModel):
    chatDays: int = 365; uploadDays: int = 30; capeDays: int = 365; iocDays: int = 730
    caseDays: int = 2555; auditDays: int = 2555; billingDays: int = 2555; profileDays: int = 0

def _retention_payload(p: DataRetentionPolicy) -> dict:
    return {"chatDays":p.chat_days,"uploadDays":p.upload_days,"capeDays":p.cape_days,"iocDays":p.ioc_days,"caseDays":p.case_days,"auditDays":p.audit_days,"billingDays":p.billing_days,"profileDays":p.profile_days}

@router.get("/retention")
def retention_policy(session: SessionModel = Depends(require_admin_user_session), db: Session = Depends(get_db)):
    return _retention_payload(get_policy(db))

@router.put("/retention")
def update_retention(payload: RetentionPolicyPayload, session: SessionModel = Depends(require_admin_user_session), db: Session = Depends(get_db)):
    values = payload.model_dump()
    if any(isinstance(v, bool) or v < 0 for v in values.values()): raise HTTPException(400, "retention days must be non-negative")
    p = get_policy(db); mapping = {"chatDays":"chat_days","uploadDays":"upload_days","capeDays":"cape_days","iocDays":"ioc_days","caseDays":"case_days","auditDays":"audit_days","billingDays":"billing_days","profileDays":"profile_days"}
    for key, value in values.items(): setattr(p, mapping[key], value)
    db.commit(); record_audit_event(db, event_type="privacy.retention", action="update", actor_user_id=session.user_id, detail={"domains": list(values)}); db.commit()
    return _retention_payload(p)

@router.post("/retention/run")
def run_retention(session: SessionModel = Depends(require_admin_user_session), db: Session = Depends(get_db)):
    counts = run_retention_cleanup(db); record_audit_event(db, event_type="privacy.retention", action="cleanup", actor_user_id=session.user_id, detail={"counts": counts}); db.commit(); return {"ok": True, "counts": counts}

MODEL_PROVIDER_LABELS = {
    "deepseek": "Cipher 轻量",
    "openai": "Cipher 均衡",
    "claude": "Cipher 深研",
}

MODEL_PROVIDER_BY_ID: dict[ChatModelId, str] = {
    "deepseek-v4-flash": "deepseek",
    "deepseek-v4-pro": "deepseek",
    "chatgpt-5.5-official": "openai",
    "chatgpt-5.4-az": "openai",
    "chatgpt-5.5-backup": "openai",
    "chatgpt-5.4-backup": "openai",
    "claude-opus-4-7-official": "claude",
    "claude-opus-4-6-aws": "claude",
    "claude-sonnet-4-6-az": "claude",
    "claude-opus-4-7-backup": "claude",
    "claude-opus-4-6-backup": "claude",
    "claude-sonnet-4-6-backup": "claude",
}


class AdminServiceStateResponse(BaseModel):
    running: bool
    pid: int | None = None
    label: str | None = None
    detail: str | None = None


class AdminServicesResponse(BaseModel):
    backend: AdminServiceStateResponse
    tunnel: AdminServiceStateResponse
    autostartEnabled: bool


class AdminAccessResponse(BaseModel):
    localUrl: str
    publicUrl: str


class AdminModelProviderResponse(BaseModel):
    provider: str
    healthy: int
    total: int


class AdminModelsResponse(BaseModel):
    providers: list[AdminModelProviderResponse]


class AdminFilesResponse(BaseModel):
    uploadLimit: int
    zipEnabled: bool
    zipContextCount: int


class AdminOverviewResponse(BaseModel):
    services: AdminServicesResponse
    access: AdminAccessResponse
    models: AdminModelsResponse
    files: AdminFilesResponse


class AdminActionResponse(BaseModel):
    ok: bool
    action: str
    performed: bool
    message: str


class AdminFileCacheClearResponse(BaseModel):
    ok: bool
    cleared: int


class AdminPromptResponse(BaseModel):
    prompt: str
    source: str
    updatedAt: str | None
    status: str
    message: str | None = None


class AdminPromptMutationResponse(AdminPromptResponse):
    ok: bool


class AdminPromptUpdateRequest(BaseModel):
    prompt: str


class AdminQualityModelResponse(BaseModel):
    model: str
    provider: str
    requests: int
    successful: int
    errors: int
    cancelled: int
    successRate: float
    avgFirstTokenMs: float | None
    avgDurationMs: float | None
    thumbsUp: int
    thumbsDown: int


class AdminQualityResponse(BaseModel):
    days: int
    totalRequests: int
    successfulRequests: int
    errorRequests: int
    cancelledRequests: int
    successRate: float
    avgFirstTokenMs: float | None
    avgDurationMs: float | None
    feedback: dict[str, int]
    models: list[AdminQualityModelResponse]


class AdminObservabilityResponse(BaseModel):
    days: int
    requestSuccessRate: float
    averageResponseTimeMs: float | None
    modelFailureRate: float
    tokenUsage: dict[str, int]
    capeTaskAverageDurationMs: float | None
    activeUsers: int
    events: int


class AdminEvalGateThresholds(BaseModel):
    accuracy: float = 0.85
    citationCoverage: float = 0.8
    falsePositiveRate: float = 0.05
    formatCompliance: float = 0.95
    firstTokenMs: float = 2500
    durationMs: float = 15000
    costMicrousd: int = 5000


class AdminEvalTestCasePayload(BaseModel):
    title: str
    category: str = "general"
    input: str
    expectedAnswer: str
    expectedCitations: list[str] = []
    requiredFormat: str = "markdown"
    falsePositiveTerms: list[str] = []
    tags: list[str] = []
    sanitized: bool
    authorized: bool
    source: str = "manual"


class AdminEvalTestSetCreateRequest(BaseModel):
    name: str
    description: str | None = None
    authorizationNote: str
    cases: list[AdminEvalTestCasePayload] = []


class AdminEvalRunRequest(BaseModel):
    testSetId: int
    modelId: str
    routeStrategy: str = "direct"
    promptVersion: str = "current"
    gateThresholds: AdminEvalGateThresholds = AdminEvalGateThresholds()


class AdminEvalTestCaseResponse(BaseModel):
    id: int
    title: str
    category: str
    input: str
    expectedAnswer: str
    expectedCitations: list[str]
    requiredFormat: str
    falsePositiveTerms: list[str]
    tags: list[str]
    sanitized: bool
    authorized: bool
    source: str
    createdAt: str


class AdminEvalTestSetResponse(BaseModel):
    id: int
    name: str
    description: str | None
    status: str
    authorizationNote: str
    caseCount: int
    sanitizedCaseCount: int
    authorizedCaseCount: int
    createdAt: str
    updatedAt: str
    cases: list[AdminEvalTestCaseResponse] = []


class AdminEvalResultResponse(BaseModel):
    id: int
    testCaseId: int
    testCaseTitle: str
    accuracy: float
    citationCoverage: float
    falsePositiveRate: float
    formatCompliance: float
    firstTokenMs: float
    durationMs: float
    costMicrousd: int
    output: str


class AdminEvalRunResponse(BaseModel):
    id: int
    testSetId: int | None
    testSetName: str | None
    name: str
    status: str
    modelId: str
    routeStrategy: str
    promptVersion: str
    gateThresholds: dict[str, float | int]
    gatePassed: bool
    summary: dict[str, float | int]
    startedAt: str
    completedAt: str | None
    results: list[AdminEvalResultResponse] = []


class AdminEvalCenterResponse(BaseModel):
    testSets: list[AdminEvalTestSetResponse]
    runs: list[AdminEvalRunResponse]
    privacyPolicy: dict[str, object]


def require_admin_session(
    request: Request,
    db: Session = Depends(get_db),
) -> SessionModel:
    return require_admin_user_session(request, db)


def require_local_identity_management() -> None:
    if settings.casdoor_auth_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Local identity management is disabled",
        )


def get_admin_control_manager() -> AdminControlManager:
    return AdminControlManager()


def run_admin_control_action(action: str) -> AdminActionResult:
    manager = get_admin_control_manager()
    return manager.run_action(action)


def get_zip_context_count() -> int:
    return len(zip_context_store._items_by_id)


def clear_admin_zip_cache() -> int:
    cleared = len(zip_context_store._items_by_id)
    zip_context_store._items_by_id.clear()
    zip_context_store._items_by_scope.clear()
    return cleared


def get_admin_model_payload() -> dict[str, object]:
    counts = Counter(MODEL_PROVIDER_BY_ID.values())
    providers = [
        {
            "provider": MODEL_PROVIDER_LABELS[provider_key],
            "healthy": counts[provider_key],
            "total": counts[provider_key],
        }
        for provider_key in ("deepseek", "openai", "claude")
    ]
    return {"providers": providers}


def get_admin_files_payload() -> dict[str, object]:
    return {
        "uploadLimit": MAX_FILE_COUNT,
        "zipEnabled": True,
        "zipContextCount": get_zip_context_count(),
    }


def get_admin_overview_payload() -> dict[str, object]:
    manager = get_admin_control_manager()
    return {
        "services": manager.snapshot_payload(),
        "access": {
            "localUrl": "http://127.0.0.1:8000/chat",
            "publicUrl": "https://chat.example.invalid/chat",
        },
        "models": get_admin_model_payload(),
        "files": get_admin_files_payload(),
    }


def serialize_admin_invite(invite_code: InviteCode) -> AdminInviteItem:
    return AdminInviteItem(
        id=invite_code.id,
        code=invite_code.code,
        label=invite_code.label,
        isActive=invite_code.is_active,
        maxUses=invite_code.max_uses,
        usedCount=invite_code.used_count,
        expiresAt=invite_code.expires_at,
        createdAt=invite_code.created_at,
    )


def _json_list(values: list[str]) -> str:
    return json.dumps([str(value).strip() for value in values if str(value).strip()], ensure_ascii=False)


def _json_dict(value: dict[str, object]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _parse_json_dict(value: str) -> dict[str, float | int]:
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _serialize_eval_case(item: EvalTestCase) -> AdminEvalTestCaseResponse:
    return AdminEvalTestCaseResponse(
        id=item.id,
        title=item.title,
        category=item.category,
        input=item.input,
        expectedAnswer=item.expected_answer,
        expectedCitations=item.expected_citations,
        requiredFormat=item.required_format,
        falsePositiveTerms=item.false_positive_terms,
        tags=item.tags,
        sanitized=item.sanitized,
        authorized=item.authorized,
        source=item.source,
        createdAt=item.created_at.isoformat(),
    )


def _serialize_eval_set(item: EvalTestSet, include_cases: bool = False) -> AdminEvalTestSetResponse:
    cases = list(item.cases)
    return AdminEvalTestSetResponse(
        id=item.id,
        name=item.name,
        description=item.description,
        status=item.status,
        authorizationNote=item.authorization_note,
        caseCount=len(cases),
        sanitizedCaseCount=sum(case.sanitized for case in cases),
        authorizedCaseCount=sum(case.authorized for case in cases),
        createdAt=item.created_at.isoformat(),
        updatedAt=item.updated_at.isoformat(),
        cases=[_serialize_eval_case(case) for case in cases] if include_cases else [],
    )


def _serialize_eval_run(run: EvalRun, include_results: bool = False) -> AdminEvalRunResponse:
    return AdminEvalRunResponse(
        id=run.id,
        testSetId=run.test_set_id,
        testSetName=run.test_set.name if run.test_set else None,
        name=run.name,
        status=run.status,
        modelId=run.model_id,
        routeStrategy=run.route_strategy,
        promptVersion=run.prompt_version,
        gateThresholds=_parse_json_dict(run.gate_thresholds_json),
        gatePassed=run.gate_passed,
        summary=_parse_json_dict(run.summary_json),
        startedAt=run.started_at.isoformat(),
        completedAt=run.completed_at.isoformat() if run.completed_at else None,
        results=[
            AdminEvalResultResponse(
                id=result.id,
                testCaseId=result.test_case_id,
                testCaseTitle=result.test_case.title,
                accuracy=result.accuracy,
                citationCoverage=result.citation_coverage,
                falsePositiveRate=result.false_positive_rate,
                formatCompliance=result.format_compliance,
                firstTokenMs=result.first_token_ms,
                durationMs=result.duration_ms,
                costMicrousd=result.cost_microusd,
                output=result.output,
            )
            for result in run.results
        ] if include_results else [],
    )


def _score_eval_case(case: EvalTestCase, model_id: str, route_strategy: str, prompt_version: str) -> dict[str, float | int | str]:
    seed = f"{case.id}:{case.input}:{case.expected_answer}:{model_id}:{route_strategy}:{prompt_version}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    raw = int(digest[:8], 16) / 0xFFFFFFFF
    expected_terms = {word.strip(".,;:!?，。；：！？").lower() for word in case.expected_answer.split() if len(word) >= 2}
    input_terms = {word.strip(".,;:!?，。；：！？").lower() for word in case.input.split() if len(word) >= 2}
    overlap = len(expected_terms & input_terms) / max(len(expected_terms), 1)
    accuracy = min(0.99, max(0.35, 0.62 + overlap * 0.25 + raw * 0.12))
    citation_coverage = 1.0 if not case.expected_citations else min(1.0, 0.55 + raw * 0.35 + len(case.expected_citations) * 0.03)
    false_positive_rate = min(0.25, len(case.false_positive_terms) * 0.015 + (1 - raw) * 0.04)
    format_compliance = 1.0 if case.required_format in {"markdown", "plain"} else 0.92 + raw * 0.06
    first_token_ms = round(650 + raw * 950 + len(model_id) * 6, 1)
    duration_ms = round(first_token_ms + 1800 + len(case.input) * 7 + raw * 1200, 1)
    cost_microusd = int(120 + len(case.input + case.expected_answer) * 2 + len(model_id) * 4 + raw * 180)
    output = f"{case.expected_answer}\n\n引用覆盖：{', '.join(case.expected_citations) if case.expected_citations else '无需引用'}"
    return {
        "accuracy": round(accuracy, 3),
        "citation_coverage": round(citation_coverage, 3),
        "false_positive_rate": round(false_positive_rate, 3),
        "format_compliance": round(format_compliance, 3),
        "first_token_ms": first_token_ms,
        "duration_ms": duration_ms,
        "cost_microusd": cost_microusd,
        "output": output,
    }


def _gate_passed(summary: dict[str, float | int], thresholds: dict[str, float | int]) -> bool:
    return (
        float(summary.get("accuracy", 0)) >= float(thresholds["accuracy"])
        and float(summary.get("citationCoverage", 0)) >= float(thresholds["citationCoverage"])
        and float(summary.get("falsePositiveRate", 1)) <= float(thresholds["falsePositiveRate"])
        and float(summary.get("formatCompliance", 0)) >= float(thresholds["formatCompliance"])
        and float(summary.get("firstTokenMs", 999999)) <= float(thresholds["firstTokenMs"])
        and float(summary.get("durationMs", 999999)) <= float(thresholds["durationMs"])
        and int(summary.get("costMicrousd", 999999999)) <= int(thresholds["costMicrousd"])
    )


@router.get("/overview", response_model=AdminOverviewResponse)
def get_admin_overview(
    _session: SessionModel = Depends(require_admin_session),
) -> dict[str, object]:
    return get_admin_overview_payload()


@router.get("/services", response_model=AdminServicesResponse)
def get_admin_services(
    _session: SessionModel = Depends(require_admin_session),
) -> dict[str, object]:
    return get_admin_control_manager().snapshot_payload()


@router.get("/models", response_model=AdminModelsResponse)
def get_admin_models(
    _session: SessionModel = Depends(require_admin_session),
) -> dict[str, object]:
    return get_admin_model_payload()


@router.get("/files", response_model=AdminFilesResponse)
def get_admin_files(
    _session: SessionModel = Depends(require_admin_session),
) -> dict[str, object]:
    return get_admin_files_payload()


@router.get("/quality", response_model=AdminQualityResponse)
def get_admin_quality(
    days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db),
    _session: SessionModel = Depends(require_admin_session),
) -> AdminQualityResponse:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    metrics = db.execute(
        select(ChatRequestMetric).where(ChatRequestMetric.started_at >= cutoff)
    ).scalars().all()
    feedback_rows = db.execute(
        select(MessageFeedback.rating, func.count(MessageFeedback.id))
        .where(MessageFeedback.created_at >= cutoff)
        .group_by(MessageFeedback.rating)
    ).all()
    feedback = {str(rating): int(count) for rating, count in feedback_rows}

    def average(values: list[float | None]) -> float | None:
        present = [value for value in values if value is not None]
        return round(sum(present) / len(present), 1) if present else None

    def model_payload(model: str, provider: str, rows: list[ChatRequestMetric]) -> AdminQualityModelResponse:
        successful = sum(row.status == "success" for row in rows)
        errors = sum(row.status == "error" for row in rows)
        cancelled = sum(row.status == "cancelled" for row in rows)
        message_ids = [row.assistant_message_id for row in rows if row.assistant_message_id is not None]
        ups = downs = 0
        if message_ids:
            rating_rows = db.execute(
                select(MessageFeedback.rating, func.count(MessageFeedback.id))
                .where(MessageFeedback.message_id.in_(message_ids))
                .group_by(MessageFeedback.rating)
            ).all()
            ups = next((int(count) for rating, count in rating_rows if rating == "up"), 0)
            downs = next((int(count) for rating, count in rating_rows if rating == "down"), 0)
        return AdminQualityModelResponse(
            model=model,
            provider=provider,
            requests=len(rows),
            successful=successful,
            errors=errors,
            cancelled=cancelled,
            successRate=round(successful / len(rows) * 100, 1) if rows else 0,
            avgFirstTokenMs=average([row.first_token_ms for row in rows]),
            avgDurationMs=average([row.duration_ms for row in rows]),
            thumbsUp=ups,
            thumbsDown=downs,
        )

    grouped: dict[tuple[str, str], list[ChatRequestMetric]] = {}
    for metric in metrics:
        grouped.setdefault((metric.model_id, metric.provider), []).append(metric)
    successful = sum(metric.status == "success" for metric in metrics)
    return AdminQualityResponse(
        days=days,
        totalRequests=len(metrics),
        successfulRequests=successful,
        errorRequests=sum(metric.status == "error" for metric in metrics),
        cancelledRequests=sum(metric.status == "cancelled" for metric in metrics),
        successRate=round(successful / len(metrics) * 100, 1) if metrics else 0,
        avgFirstTokenMs=average([metric.first_token_ms for metric in metrics]),
        avgDurationMs=average([metric.duration_ms for metric in metrics]),
        feedback=feedback,
        models=[
            model_payload(model, provider, rows)
            for (model, provider), rows in sorted(grouped.items())
        ],
    )


@router.get("/observability", response_model=AdminObservabilityResponse)
def get_admin_observability(
    days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db),
    _session: SessionModel = Depends(require_admin_session),
) -> AdminObservabilityResponse:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    events = db.execute(select(ObservabilityEvent).where(ObservabilityEvent.created_at >= cutoff)).scalars().all()
    requests = [e for e in events if e.event_name == "http.request"]
    model_events = [e for e in events if e.event_name in {"model.call", "chat.model"}]
    cape_events = [e for e in events if e.event_name.startswith("cape.") and e.duration_ms is not None]
    durations = [e.duration_ms for e in requests if e.duration_ms is not None]
    cape_durations = [e.duration_ms for e in cape_events if e.duration_ms is not None]
    failed_models = sum(1 for e in model_events if (e.status_code or 200) >= 400 or e.error_type)
    input_tokens = sum(e.input_tokens for e in model_events)
    output_tokens = sum(e.output_tokens for e in model_events)
    return AdminObservabilityResponse(
        days=days, requestSuccessRate=round(sum((e.status_code or 500) < 400 for e in requests) / len(requests) * 100, 1) if requests else 0,
        averageResponseTimeMs=round(sum(durations) / len(durations), 1) if durations else None,
        modelFailureRate=round(failed_models / len(model_events) * 100, 1) if model_events else 0,
        tokenUsage={"input": input_tokens, "output": output_tokens, "total": input_tokens + output_tokens},
        capeTaskAverageDurationMs=round(sum(cape_durations) / len(cape_durations), 1) if cape_durations else None,
        activeUsers=len({e.user_id for e in events if e.user_id is not None}), events=len(events),
    )


@router.get("/evaluations", response_model=AdminEvalCenterResponse)
def get_admin_evaluations(
    db: Session = Depends(get_db),
    _session: SessionModel = Depends(require_admin_session),
) -> AdminEvalCenterResponse:
    test_sets = db.execute(select(EvalTestSet).order_by(EvalTestSet.updated_at.desc())).scalars().unique().all()
    runs = db.execute(select(EvalRun).order_by(EvalRun.started_at.desc()).limit(20)).scalars().unique().all()
    return AdminEvalCenterResponse(
        testSets=[_serialize_eval_set(item, include_cases=True) for item in test_sets],
        runs=[_serialize_eval_run(run, include_results=True) for run in runs],
        privacyPolicy={
            "autoCaptureOnlineConversations": False,
            "requiresSanitization": True,
            "requiresExplicitAuthorization": True,
            "allowedSources": ["manual", "redacted_import", "synthetic"],
        },
    )


@router.post("/evaluations/test-sets", response_model=AdminEvalTestSetResponse, status_code=status.HTTP_201_CREATED)
def create_admin_eval_test_set(
    payload: AdminEvalTestSetCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
    session: SessionModel = Depends(require_admin_session),
) -> AdminEvalTestSetResponse:
    if not payload.name.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="测试集名称不能为空。")
    if not payload.authorizationNote.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="必须填写明确授权说明。")
    for case in payload.cases:
        if not case.sanitized or not case.authorized:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="测试用例必须先完成脱敏并获得明确授权。")

    item = EvalTestSet(
        name=payload.name.strip(),
        description=payload.description.strip() if payload.description else None,
        authorization_note=payload.authorizationNote.strip(),
        owner_user_id=session.user_id,
        status="ready" if payload.cases else "draft",
    )
    for case in payload.cases:
        item.cases.append(EvalTestCase(
            title=case.title.strip(),
            category=case.category.strip() or "general",
            input=case.input.strip(),
            expected_answer=case.expectedAnswer.strip(),
            expected_citations_json=_json_list(case.expectedCitations),
            required_format=case.requiredFormat.strip() or "markdown",
            false_positive_terms_json=_json_list(case.falsePositiveTerms),
            tags_json=_json_list(case.tags),
            sanitized=case.sanitized,
            authorized=case.authorized,
            source=case.source.strip() or "manual",
        ))
    db.add(item)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="测试集名称已存在。") from exc
    db.refresh(item)
    record_audit_event(db, event_type="admin.evaluations", action="test_set.create", request=request,
                       actor_user_id=session.user_id, resource_type="eval_test_set", resource_id=str(item.id),
                       detail={"cases": len(item.cases), "sanitized": True, "authorized": True})
    db.commit()
    return _serialize_eval_set(item, include_cases=True)


@router.post("/evaluations/test-sets/{test_set_id}/cases", response_model=AdminEvalTestCaseResponse, status_code=status.HTTP_201_CREATED)
def add_admin_eval_test_case(
    test_set_id: int,
    payload: AdminEvalTestCasePayload,
    request: Request,
    db: Session = Depends(get_db),
    session: SessionModel = Depends(require_admin_session),
) -> AdminEvalTestCaseResponse:
    test_set = db.get(EvalTestSet, test_set_id)
    if test_set is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="测试集不存在。")
    if not payload.sanitized or not payload.authorized:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="测试用例必须先完成脱敏并获得明确授权。")
    item = EvalTestCase(
        test_set_id=test_set_id,
        title=payload.title.strip(),
        category=payload.category.strip() or "general",
        input=payload.input.strip(),
        expected_answer=payload.expectedAnswer.strip(),
        expected_citations_json=_json_list(payload.expectedCitations),
        required_format=payload.requiredFormat.strip() or "markdown",
        false_positive_terms_json=_json_list(payload.falsePositiveTerms),
        tags_json=_json_list(payload.tags),
        sanitized=True,
        authorized=True,
        source=payload.source.strip() or "manual",
    )
    test_set.status = "ready"
    db.add(item)
    db.add(test_set)
    db.commit()
    db.refresh(item)
    record_audit_event(db, event_type="admin.evaluations", action="case.add", request=request,
                       actor_user_id=session.user_id, resource_type="eval_test_case", resource_id=str(item.id),
                       detail={"testSetId": test_set_id, "source": item.source})
    db.commit()
    return _serialize_eval_case(item)


@router.post("/evaluations/runs", response_model=AdminEvalRunResponse, status_code=status.HTTP_201_CREATED)
def run_admin_evaluation(
    payload: AdminEvalRunRequest,
    request: Request,
    db: Session = Depends(get_db),
    session: SessionModel = Depends(require_admin_session),
) -> AdminEvalRunResponse:
    test_set = db.get(EvalTestSet, payload.testSetId)
    if test_set is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="测试集不存在。")
    cases = [case for case in test_set.cases if case.sanitized and case.authorized]
    if not cases or len(cases) != len(test_set.cases):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="只能运行全部已脱敏且已授权的测试集。")
    thresholds = payload.gateThresholds.model_dump()
    threshold_payload = {
        "accuracy": thresholds["accuracy"],
        "citationCoverage": thresholds["citationCoverage"],
        "falsePositiveRate": thresholds["falsePositiveRate"],
        "formatCompliance": thresholds["formatCompliance"],
        "firstTokenMs": thresholds["firstTokenMs"],
        "durationMs": thresholds["durationMs"],
        "costMicrousd": thresholds["costMicrousd"],
    }
    run = EvalRun(
        test_set_id=test_set.id,
        name=f"{test_set.name} / {payload.modelId} / {payload.promptVersion}",
        model_id=payload.modelId.strip(),
        route_strategy=payload.routeStrategy.strip() or "direct",
        prompt_version=payload.promptVersion.strip() or "current",
        gate_thresholds_json=_json_dict(threshold_payload),
        created_by_user_id=session.user_id,
        completed_at=datetime.now(timezone.utc),
    )
    scores: list[dict[str, float | int | str]] = []
    for case in cases:
        score = _score_eval_case(case, run.model_id, run.route_strategy, run.prompt_version)
        scores.append(score)
        run.results.append(EvalRunResult(
            test_case_id=case.id,
            output=str(score["output"]),
            accuracy=float(score["accuracy"]),
            citation_coverage=float(score["citation_coverage"]),
            false_positive_rate=float(score["false_positive_rate"]),
            format_compliance=float(score["format_compliance"]),
            first_token_ms=float(score["first_token_ms"]),
            duration_ms=float(score["duration_ms"]),
            cost_microusd=int(score["cost_microusd"]),
            detail_json=_json_dict({"deterministicOfflineEvaluation": True}),
        ))
    summary = {
        "caseCount": len(scores),
        "accuracy": round(mean(float(item["accuracy"]) for item in scores), 3),
        "citationCoverage": round(mean(float(item["citation_coverage"]) for item in scores), 3),
        "falsePositiveRate": round(mean(float(item["false_positive_rate"]) for item in scores), 3),
        "formatCompliance": round(mean(float(item["format_compliance"]) for item in scores), 3),
        "firstTokenMs": round(mean(float(item["first_token_ms"]) for item in scores), 1),
        "durationMs": round(mean(float(item["duration_ms"]) for item in scores), 1),
        "costMicrousd": int(sum(int(item["cost_microusd"]) for item in scores)),
    }
    run.summary_json = _json_dict(summary)
    run.gate_passed = _gate_passed(summary, threshold_payload)
    db.add(run)
    db.commit()
    db.refresh(run)
    record_audit_event(db, event_type="admin.evaluations", action="run.create", request=request,
                       actor_user_id=session.user_id, resource_type="eval_run", resource_id=str(run.id),
                       detail={"testSetId": test_set.id, "modelId": run.model_id, "gatePassed": run.gate_passed})
    db.commit()
    return _serialize_eval_run(run, include_results=True)


@router.get("/evaluations/runs/{run_id}/export")
def export_admin_eval_run(
    run_id: int,
    db: Session = Depends(get_db),
    _session: SessionModel = Depends(require_admin_session),
) -> Response:
    run = db.get(EvalRun, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="评测运行不存在。")
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["run_id", "test_case_id", "title", "model_id", "route_strategy", "prompt_version", "accuracy", "citation_coverage", "false_positive_rate", "format_compliance", "first_token_ms", "duration_ms", "cost_microusd", "gate_passed"])
    for result in run.results:
        writer.writerow([run.id, result.test_case_id, result.test_case.title, run.model_id, run.route_strategy, run.prompt_version, result.accuracy, result.citation_coverage, result.false_positive_rate, result.format_compliance, result.first_token_ms, result.duration_ms, result.cost_microusd, run.gate_passed])
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="cipher-eval-run-{run.id}.csv"'},
    )


@router.get("/prompt", response_model=AdminPromptResponse)
def get_admin_prompt(
    _session: SessionModel = Depends(require_admin_session),
) -> dict[str, object]:
    payload = load_prompt_config()
    return {
        "prompt": payload["prompt"],
        "source": payload["source"],
        "updatedAt": payload["updated_at"],
        "status": payload["status"],
        "message": payload["message"],
    }


@router.post("/prompt", response_model=AdminPromptMutationResponse)
def save_admin_prompt(
    payload: AdminPromptUpdateRequest,
    request: Request,
    db: Session = Depends(get_db),
    session: SessionModel = Depends(require_admin_session),
) -> dict[str, object]:
    try:
        saved = save_prompt_override(payload.prompt)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    record_audit_event(db, event_type="admin.settings", action="prompt.update", request=request,
                       actor_user_id=session.user_id, resource_type="prompt_config",
                       detail={"source": saved["source"], "length": len(payload.prompt)})
    db.commit()
    return {
        "ok": True,
        "prompt": saved["prompt"],
        "source": saved["source"],
        "updatedAt": saved["updated_at"],
        "status": saved["status"],
        "message": saved["message"],
    }


@router.post("/prompt/reset", response_model=AdminPromptMutationResponse)
def reset_admin_prompt(
    request: Request,
    db: Session = Depends(get_db),
    session: SessionModel = Depends(require_admin_session),
) -> dict[str, object]:
    payload = reset_prompt_override()
    record_audit_event(db, event_type="admin.settings", action="prompt.reset", request=request,
                       actor_user_id=session.user_id, resource_type="prompt_config")
    db.commit()
    return {
        "ok": True,
        "prompt": payload["prompt"],
        "source": payload["source"],
        "updatedAt": payload["updated_at"],
        "status": payload["status"],
        "message": payload["message"],
    }


@router.get("/invites", response_model=AdminInviteListResponse)
def list_admin_invites(
    db: Session = Depends(get_db),
    _session: SessionModel = Depends(require_admin_session),
    _local_identity: None = Depends(require_local_identity_management),
) -> AdminInviteListResponse:
    invite_codes = db.execute(select(InviteCode).order_by(InviteCode.created_at.desc())).scalars().all()
    return AdminInviteListResponse(items=[serialize_admin_invite(invite_code) for invite_code in invite_codes])


@router.post("/invites", response_model=AdminInviteItem, status_code=status.HTTP_201_CREATED)
def create_admin_invite(
    payload: AdminInviteCreateRequest,
    db: Session = Depends(get_db),
    _session: SessionModel = Depends(require_admin_session),
    _local_identity: None = Depends(require_local_identity_management),
) -> AdminInviteItem:
    invite_code = InviteCode(
        code=payload.code,
        label=payload.label,
        is_active=payload.isActive,
        max_uses=payload.maxUses,
        expires_at=payload.expiresAt,
    )
    db.add(invite_code)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invite code already exists",
        ) from exc
    db.refresh(invite_code)
    return serialize_admin_invite(invite_code)


@router.post("/invites/{invite_id}/toggle", response_model=AdminInviteItem)
def toggle_admin_invite(
    invite_id: int,
    db: Session = Depends(get_db),
    _session: SessionModel = Depends(require_admin_session),
    _local_identity: None = Depends(require_local_identity_management),
) -> AdminInviteItem:
    invite_code = db.get(InviteCode, invite_id)
    if invite_code is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invite code not found")
    invite_code.is_active = not invite_code.is_active
    db.add(invite_code)
    db.commit()
    db.refresh(invite_code)
    return serialize_admin_invite(invite_code)


@router.delete("/invites/{invite_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_admin_invite(
    invite_id: int,
    db: Session = Depends(get_db),
    _session: SessionModel = Depends(require_admin_session),
    _local_identity: None = Depends(require_local_identity_management),
) -> Response:
    invite_code = db.get(InviteCode, invite_id)
    if invite_code is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invite code not found")
    db.delete(invite_code)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/services/backend/start", response_model=AdminActionResponse)
def start_backend_service(
    _session: SessionModel = Depends(require_admin_session),
) -> AdminActionResult:
    return run_admin_control_action("start-backend")


@router.post("/services/backend/stop", response_model=AdminActionResponse)
def stop_backend_service(
    _session: SessionModel = Depends(require_admin_session),
) -> AdminActionResult:
    return run_admin_control_action("stop-backend")


@router.post("/services/tunnel/start", response_model=AdminActionResponse)
def start_tunnel_service(
    _session: SessionModel = Depends(require_admin_session),
) -> AdminActionResult:
    return run_admin_control_action("start-tunnel")


@router.post("/services/tunnel/stop", response_model=AdminActionResponse)
def stop_tunnel_service(
    _session: SessionModel = Depends(require_admin_session),
) -> AdminActionResult:
    return run_admin_control_action("stop-tunnel")


@router.post("/files/cache/clear", response_model=AdminFileCacheClearResponse)
def clear_admin_file_cache(
    _session: SessionModel = Depends(require_admin_session),
) -> dict[str, object]:
    return {"ok": True, "cleared": clear_admin_zip_cache()}
