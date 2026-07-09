from __future__ import annotations

from collections import Counter

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.admin_control import AdminActionResult, AdminControlManager
from app.attachments import MAX_FILE_COUNT
from app.auth import require_admin_user_session
from app.database import get_db
from app.deepseek import ChatModelId
from app.models import InviteCode
from app.models import Session as SessionModel
from app.prompt_config_store import load_prompt_config, reset_prompt_override, save_prompt_override
from app.schemas import AdminInviteCreateRequest, AdminInviteItem, AdminInviteListResponse
from app.zip_context_store import zip_context_store


router = APIRouter(prefix="/api/admin", tags=["admin"])

MODEL_PROVIDER_LABELS = {
    "deepseek": "DeepSeek",
    "openai": "OpenAI",
    "claude": "Claude",
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


def require_admin_session(
    request: Request,
    db: Session = Depends(get_db),
) -> SessionModel:
    return require_admin_user_session(request, db)


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
            "publicUrl": "https://[private-host]/chat",
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
    _session: SessionModel = Depends(require_admin_session),
) -> dict[str, object]:
    try:
        saved = save_prompt_override(payload.prompt)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

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
    _session: SessionModel = Depends(require_admin_session),
) -> dict[str, object]:
    payload = reset_prompt_override()
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
) -> AdminInviteListResponse:
    invite_codes = db.execute(select(InviteCode).order_by(InviteCode.created_at.desc())).scalars().all()
    return AdminInviteListResponse(items=[serialize_admin_invite(invite_code) for invite_code in invite_codes])


@router.post("/invites", response_model=AdminInviteItem, status_code=status.HTTP_201_CREATED)
def create_admin_invite(
    payload: AdminInviteCreateRequest,
    db: Session = Depends(get_db),
    _session: SessionModel = Depends(require_admin_session),
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
