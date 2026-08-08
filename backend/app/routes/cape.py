from __future__ import annotations

from collections.abc import Iterable
import json
from time import perf_counter

from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_user_session
from app.cape_client import CapeConfigurationError, CapeUpstreamError
from app.cape_exports import (
    build_case_bundle,
    build_case_json,
    build_html_report,
    build_ioc_csv,
    build_markdown_report,
    build_pdf_report,
    build_sigma_starter,
    build_yara_starter,
)
from app.cape_service import CapeAnalysisSummary, CapeService, TERMINAL_TASK_STATUSES
from app.config import settings
from app.database import get_db
from app.models import CapeCase, Conversation, Job, Session as SessionModel, now_utc
from app.observability import emit_event
from app.schemas import (
    CapeAnalysisSummaryResponse,
    CapeCaseListResponse,
    CapeCaseResponse,
    CapeDroppedFileItem,
    CapeIocSummary,
    CapeSubmitResponse,
    CapeTacticItem,
    CapeTaskStatusResponse,
)
from app.usage_governance import add_ledger_entry, enforce_quota, organization_id_for_user


router = APIRouter(prefix="/api/cape", tags=["cape"])


def get_cape_service() -> CapeService:
    return CapeService()


def _get_owned_conversation(
    db: Session,
    conversation_id: int,
    current_session: SessionModel,
) -> Conversation | None:
    return db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.owner_user_id == current_session.user_id,
        )
    ).scalar_one_or_none()


def _summary_to_response(summary: CapeAnalysisSummary) -> CapeAnalysisSummaryResponse:
    return CapeAnalysisSummaryResponse(
        taskId=summary.task_id,
        status=summary.status,
        score=summary.score,
        submittedFilename=summary.submitted_filename,
        sha256=summary.sha256,
        iocs=CapeIocSummary(**summary.iocs),
        tactics=[CapeTacticItem(**item) for item in summary.tactics],
        droppedFiles=[CapeDroppedFileItem(**item) for item in summary.dropped_files],
        processes=getattr(summary, "processes", []),
        networkConnections=getattr(summary, "network_connections", []),
        signatures=summary.signatures,
    )


def _case_summary_response(cape_case: CapeCase) -> CapeAnalysisSummaryResponse | None:
    if not cape_case.summary_json:
        return None

    return CapeAnalysisSummaryResponse.model_validate(json.loads(cape_case.summary_json))


def _case_to_response(cape_case: CapeCase) -> CapeCaseResponse:
    return CapeCaseResponse(
        id=cape_case.id,
        conversationId=cape_case.conversation_id,
        taskId=cape_case.cape_task_id,
        sampleName=cape_case.sample_name,
        status=cape_case.status,
        completed=cape_case.status in TERMINAL_TASK_STATUSES,
        score=cape_case.score,
        targetFilename=cape_case.target_filename,
        machine=cape_case.machine,
        sha256=cape_case.sha256,
        reusedExistingTask=cape_case.reused_existing_task,
        summary=_case_summary_response(cape_case),
        createdAt=cape_case.created_at,
        updatedAt=cape_case.updated_at,
    )


def _infer_pe_architecture(content: bytes) -> str | None:
    if len(content) < 0x40 or content[:2] != b"MZ":
        return None

    pe_offset = int.from_bytes(content[0x3C:0x40], "little")
    if pe_offset <= 0 or pe_offset + 6 > len(content):
        return None
    if content[pe_offset : pe_offset + 4] != b"PE\x00\x00":
        return None

    machine = int.from_bytes(content[pe_offset + 4 : pe_offset + 6], "little")
    if machine == 0x8664:
        return "x64"
    if machine == 0x14C:
        return "x86"
    return None


def _infer_sample_tags(filename: str, content: bytes, requested_tags: Iterable[str] | None) -> list[str] | None:
    normalized_requested = [tag.strip() for tag in (requested_tags or []) if tag.strip()]
    if normalized_requested:
        return normalized_requested

    pe_arch = _infer_pe_architecture(content)
    if pe_arch:
        return [pe_arch]

    lowered_name = filename.lower()
    name_hints = {
        "x64": ("x64", "amd64", "win64", "64bit", "64-bit"),
        "x86": ("x86", "win32", "32bit", "32-bit", "i386"),
    }
    for tag, hints in name_hints.items():
        if any(hint in lowered_name for hint in hints):
            return [tag]

    return None


@router.post("/submit", response_model=CapeSubmitResponse)
async def submit_sample(
    file: UploadFile = File(...),
    machine: str | None = Query(default=None),
    platform: str | None = Query(default=None),
    tags: str | None = Query(default=None),
    route: str | None = Query(default=None),
    pcap: bool = Query(default=False),
    current_session: SessionModel = Depends(require_user_session),
    db: Session = Depends(get_db),
    cape_service: CapeService = Depends(get_cape_service),
) -> CapeSubmitResponse:
    filename = file.filename or "sample.bin"
    content = await file.read()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded sample is empty.",
        )
    enforce_quota(
        db,
        current_session.user_id,
        "cape",
        storage_bytes=len(content),
        projected_cost_microusd=settings.effective_cape_task_cost_microusd,
    )
    requested_tags = [item.strip() for item in tags.split(",")] if tags else None
    effective_tags = _infer_sample_tags(filename, content, requested_tags)
    started = perf_counter()

    try:
        submission = await cape_service.submit_file(
            filename=filename,
            content=content,
            machine=machine,
            platform=platform,
            tags=effective_tags,
            route=route,
            is_pcap=pcap,
        )
    except (CapeConfigurationError, ValueError) as exc:
        emit_event(db, event_name="cape.task", user_id=current_session.user_id,
                   organization_id=organization_id_for_user(db, current_session.user_id),
                   route="/api/cape/submit", duration_ms=(perf_counter() - started) * 1000,
                   error_type=type(exc).__name__, status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                   metadata={"filename": filename, "bytes": len(content), "stage": "submit"})
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except CapeUpstreamError as exc:
        emit_event(db, event_name="cape.task", user_id=current_session.user_id,
                   organization_id=organization_id_for_user(db, current_session.user_id),
                   route="/api/cape/submit", duration_ms=(perf_counter() - started) * 1000,
                   error_type=type(exc).__name__, status_code=status.HTTP_502_BAD_GATEWAY,
                   metadata={"filename": filename, "bytes": len(content), "stage": "submit"})
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    reused_existing_task = bool(submission.raw.get("reusedExistingTask"))
    add_ledger_entry(db, key=f"cape-task:{submission.task_id}:user:{current_session.user_id}",
        user_id=current_session.user_id, resource_type="cape", resource_id=str(submission.task_id),
        storage_bytes=len(content),
        cost_microusd=0 if reused_existing_task else settings.effective_cape_task_cost_microusd)
    if not reused_existing_task:
        db.add(Job(owner_user_id=current_session.user_id, task_type="cape_analysis",
                   payload_json=json.dumps({"taskId": submission.task_id}),
                   idempotency_key=f"cape:{submission.task_id}"))
    emit_event(db, event_name="cape.task", user_id=current_session.user_id,
               organization_id=organization_id_for_user(db, current_session.user_id),
               route="/api/cape/submit", task_id=str(submission.task_id),
               duration_ms=(perf_counter() - started) * 1000, status_code=200,
               metadata={"filename": filename, "bytes": len(content), "status": submission.status,
                         "reused_existing_task": reused_existing_task})
    db.commit()
    return CapeSubmitResponse(
        taskId=submission.task_id,
        status=submission.status,
        reusedExistingTask=reused_existing_task,
    )


@router.post("/cases", response_model=CapeCaseResponse, status_code=status.HTTP_201_CREATED)
async def create_case(
    file: UploadFile = File(...),
    conversation_id: int = Query(alias="conversationId"),
    machine: str | None = Query(default=None),
    platform: str | None = Query(default=None),
    tags: str | None = Query(default=None),
    route: str | None = Query(default=None),
    pcap: bool = Query(default=False),
    current_session: SessionModel = Depends(require_user_session),
    db: Session = Depends(get_db),
    cape_service: CapeService = Depends(get_cape_service),
) -> CapeCaseResponse:
    conversation = _get_owned_conversation(db, conversation_id, current_session)
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    filename = file.filename or "sample.bin"
    content = await file.read()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded sample is empty.",
        )

    enforce_quota(
        db,
        current_session.user_id,
        "cape",
        storage_bytes=len(content),
        projected_cost_microusd=settings.effective_cape_task_cost_microusd,
    )

    requested_tags = [item.strip() for item in tags.split(",")] if tags else None
    effective_tags = _infer_sample_tags(filename, content, requested_tags)
    started = perf_counter()

    try:
        submission = await cape_service.submit_file(
            filename=filename,
            content=content,
            machine=machine,
            platform=platform,
            tags=effective_tags,
            route=route,
            is_pcap=pcap,
        )
    except (CapeConfigurationError, ValueError) as exc:
        emit_event(db, event_name="cape.task", user_id=current_session.user_id,
                   organization_id=organization_id_for_user(db, current_session.user_id),
                   route="/api/cape/cases", duration_ms=(perf_counter() - started) * 1000,
                   error_type=type(exc).__name__, status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                   metadata={"filename": filename, "bytes": len(content), "conversation_id": conversation.id,
                             "stage": "submit"})
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except CapeUpstreamError as exc:
        emit_event(db, event_name="cape.task", user_id=current_session.user_id,
                   organization_id=organization_id_for_user(db, current_session.user_id),
                   route="/api/cape/cases", duration_ms=(perf_counter() - started) * 1000,
                   error_type=type(exc).__name__, status_code=status.HTTP_502_BAD_GATEWAY,
                   metadata={"filename": filename, "bytes": len(content), "conversation_id": conversation.id,
                             "stage": "submit"})
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    reused_existing_task = bool(submission.raw.get("reusedExistingTask"))
    cape_case = CapeCase(
        conversation_id=conversation.id,
        owner_user_id=current_session.user_id,
        cape_task_id=submission.task_id,
        sample_name=filename,
        status=submission.status,
        reused_existing_task=reused_existing_task,
    )
    db.add(cape_case)
    db.flush()
    if not reused_existing_task:
        db.add(Job(owner_user_id=current_session.user_id, task_type="cape_analysis",
                   payload_json=json.dumps({"taskId": submission.task_id, "capeCaseId": cape_case.id}),
                   idempotency_key=f"cape:{submission.task_id}"))
    add_ledger_entry(db, key=f"cape-case:{conversation.id}:task:{submission.task_id}",
        user_id=current_session.user_id, resource_type="cape", resource_id=str(submission.task_id),
        storage_bytes=len(content),
        cost_microusd=0 if reused_existing_task else settings.effective_cape_task_cost_microusd)
    conversation.updated_at = now_utc()
    emit_event(db, event_name="cape.task", user_id=current_session.user_id,
               organization_id=organization_id_for_user(db, current_session.user_id),
               route="/api/cape/cases", task_id=str(submission.task_id),
               duration_ms=(perf_counter() - started) * 1000, status_code=status.HTTP_201_CREATED,
               metadata={"filename": filename, "bytes": len(content), "conversation_id": conversation.id,
                         "cape_case_id": cape_case.id, "status": submission.status,
                         "reused_existing_task": reused_existing_task})
    db.commit()
    db.refresh(cape_case)
    return _case_to_response(cape_case)


@router.get("/tasks/{task_id}", response_model=CapeTaskStatusResponse)
async def get_task_status(
    task_id: int,
    _current_session: SessionModel = Depends(require_user_session),
    cape_service: CapeService = Depends(get_cape_service),
) -> CapeTaskStatusResponse:
    try:
        snapshot = await cape_service.get_task_snapshot(task_id)
    except ValueError as exc:
        error_message = str(exc)
        if "still being analyzed" in error_message.lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=error_message,
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=error_message,
        ) from exc
    except CapeConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except CapeUpstreamError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    return CapeTaskStatusResponse(
        taskId=snapshot.task_id,
        status=snapshot.status,
        completed=snapshot.completed,
        score=snapshot.score,
        targetFilename=snapshot.target_filename,
        machine=snapshot.machine,
    )


@router.get("/tasks/{task_id}/summary", response_model=CapeAnalysisSummaryResponse)
async def get_task_summary(
    task_id: int,
    _current_session: SessionModel = Depends(require_user_session),
    cape_service: CapeService = Depends(get_cape_service),
) -> CapeAnalysisSummaryResponse:
    try:
        summary = await cape_service.get_analysis_summary(task_id)
    except ValueError as exc:
        error_message = str(exc)
        if "still being analyzed" in error_message.lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=error_message,
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=error_message,
        ) from exc
    except CapeConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except CapeUpstreamError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    return _summary_to_response(summary)


@router.get("/cases/conversation/{conversation_id}", response_model=CapeCaseListResponse)
def list_cases_for_conversation(
    conversation_id: int,
    current_session: SessionModel = Depends(require_user_session),
    db: Session = Depends(get_db),
) -> CapeCaseListResponse:
    conversation = _get_owned_conversation(db, conversation_id, current_session)
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    cases = db.execute(
        select(CapeCase)
        .where(CapeCase.conversation_id == conversation_id)
        .order_by(CapeCase.created_at.asc(), CapeCase.id.asc())
    ).scalars().all()
    return CapeCaseListResponse(items=[_case_to_response(cape_case) for cape_case in cases])


@router.get("/cases/{case_id}", response_model=CapeCaseResponse)
async def get_case(
    case_id: int,
    current_session: SessionModel = Depends(require_user_session),
    db: Session = Depends(get_db),
    cape_service: CapeService = Depends(get_cape_service),
) -> CapeCaseResponse:
    cape_case = db.execute(
        select(CapeCase).where(
            CapeCase.id == case_id,
            CapeCase.owner_user_id == current_session.user_id,
        )
    ).scalar_one_or_none()
    if cape_case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="CAPE case not found")

    try:
        snapshot = await cape_service.get_task_snapshot(cape_case.cape_task_id)
        cape_case.status = snapshot.status
        cape_case.score = snapshot.score
        cape_case.target_filename = snapshot.target_filename
        cape_case.machine = snapshot.machine
        cape_case.updated_at = now_utc()

        if snapshot.completed and not cape_case.summary_json:
            try:
                summary = await cape_service.get_analysis_summary(cape_case.cape_task_id)
                summary_response = _summary_to_response(summary)
                cape_case.summary_json = summary_response.model_dump_json()
                cape_case.sha256 = summary.sha256
                cape_case.score = summary.score if summary.score is not None else cape_case.score
                cape_case.status = summary.status or cape_case.status
            except ValueError as exc:
                if "still being analyzed" not in str(exc).lower():
                    raise
        db.commit()
        db.refresh(cape_case)
    except (CapeConfigurationError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except CapeUpstreamError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    return _case_to_response(cape_case)


@router.get("/cases/{case_id}/export")
def export_case(
    case_id: int,
    format: Literal["bundle", "json", "markdown", "html", "pdf", "ioc-csv", "sigma", "yara"] = Query(default="bundle"),
    current_session: SessionModel = Depends(require_user_session),
    db: Session = Depends(get_db),
) -> Response:
    cape_case = db.execute(
        select(CapeCase).where(
            CapeCase.id == case_id,
            CapeCase.owner_user_id == current_session.user_id,
        )
    ).scalar_one_or_none()
    if cape_case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="CAPE case not found")
    if not cape_case.summary_json:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="CAPE case report is not ready for export.",
        )

    exporters = {
        "bundle": (build_case_bundle, "zip", "application/zip"),
        "json": (build_case_json, "json", "application/json"),
        "markdown": (build_markdown_report, "md", "text/markdown; charset=utf-8"),
        "html": (build_html_report, "html", "text/html; charset=utf-8"),
        "pdf": (build_pdf_report, "pdf", "application/pdf"),
        "ioc-csv": (build_ioc_csv, "csv", "text/csv; charset=utf-8"),
        "sigma": (build_sigma_starter, "yml", "application/yaml; charset=utf-8"),
        "yara": (build_yara_starter, "yar", "text/plain; charset=utf-8"),
    }
    exporter, extension, media_type = exporters[format]
    try:
        content = exporter(cape_case)
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    filename = f"cipher-cape-case-{cape_case.id}.{extension}"
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
