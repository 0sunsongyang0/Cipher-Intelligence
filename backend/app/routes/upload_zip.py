from __future__ import annotations

import ipaddress
from time import perf_counter

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from sqlalchemy.orm import Session

from app.attachments import AttachmentError
from app.auth import require_user_session
from app.database import SessionLocal, get_db
from app.models import Session as SessionModel
from app.observability import emit_event
from app.schemas import ChatModelId, UploadZipResponse
from app.usage_governance import organization_id_for_user
from app.zip_context_store import get_zip_model_support, zip_context_store
from app.zip_parser import parse_zip_upload


router = APIRouter(prefix="/api/upload_zip", tags=["upload-zip"])


NON_ZIP_UPLOAD_ERROR = "上传的文件必须是 ZIP 压缩包。"
ZIP_PENDING_ERROR = "ZIP 压缩包仍在解析中，请稍后再试。"


def model_supports_native_vision(model: str) -> bool:
    return model.startswith(("chatgpt-", "claude-"))


def should_eagerly_extract_zip_image_text(model: str) -> bool:
    # ChatGPT models can benefit from both the OCR text context and the image payload.
    # Claude ZIP flows keep only the image payload and defer any image understanding to the model.
    return not model.startswith("claude-")


def should_parse_zip_synchronously(request: Request | None) -> bool:
    host = request.client.host if request and request.client else ""
    if not host:
        return False

    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return host in {"localhost"}

    return address.is_loopback or address.is_private


@router.post("", response_model=UploadZipResponse)
async def upload_zip(
    request: Request,
    background_tasks: BackgroundTasks,
    conversationId: str = Form(...),
    model: ChatModelId = Form(...),
    file: UploadFile = File(...),
    current_session: SessionModel = Depends(require_user_session),
    db: Session = Depends(get_db),
) -> UploadZipResponse:
    filename = file.filename or "upload.zip"
    if not filename.lower().endswith(".zip"):
        emit_event(db, event_name="file.process", user_id=current_session.user_id,
                   organization_id=organization_id_for_user(db, current_session.user_id),
                   route="/api/upload_zip", error_type="InvalidFileType",
                   status_code=status.HTTP_400_BAD_REQUEST, metadata={"filename": filename})
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=NON_ZIP_UPLOAD_ERROR,
        )

    raw = await file.read()
    supported_by_current_model, unsupported_reason = get_zip_model_support(model)
    started = perf_counter()

    if should_parse_zip_synchronously(request):
        try:
            parsed = await parse_zip_upload(
                filename,
                raw,
                eager_image_ocr=should_eagerly_extract_zip_image_text(model),
            )
        except AttachmentError as exc:
            emit_event(db, event_name="file.process", user_id=current_session.user_id,
                       organization_id=organization_id_for_user(db, current_session.user_id),
                       route="/api/upload_zip", duration_ms=(perf_counter() - started) * 1000,
                       error_type=type(exc).__name__, status_code=status.HTTP_400_BAD_REQUEST,
                       metadata={"filename": filename, "bytes": len(raw), "mode": "sync"})
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

        stored = zip_context_store.save(
            owner_user_id=current_session.user_id,
            conversation_id=conversationId,
            parsed=parsed,
        )
        emit_event(db, event_name="file.process", user_id=current_session.user_id,
                   organization_id=organization_id_for_user(db, current_session.user_id),
                   route="/api/upload_zip", task_id=stored.zip_context_id,
                   duration_ms=(perf_counter() - started) * 1000, status_code=200,
                   metadata={"filename": filename, "bytes": len(raw), "mode": "sync",
                             "entry_count": stored.entry_count,
                             "extracted_entry_count": stored.extracted_entry_count,
                             "skipped_entry_count": stored.skipped_entry_count})
        db.commit()
        return UploadZipResponse(
            zipContextId=stored.zip_context_id,
            archiveName=stored.archive_name,
            entryCount=stored.entry_count,
            extractedEntryCount=stored.extracted_entry_count,
            inventoryOnlyCount=stored.inventory_only_count,
            skippedEntryCount=stored.skipped_entry_count,
            supportedByCurrentModel=supported_by_current_model,
            unsupportedReason=unsupported_reason,
            uploading=False,
            errorMessage=None,
        )

    pending = zip_context_store.save_pending(
        owner_user_id=current_session.user_id,
        conversation_id=conversationId,
        archive_name=filename,
    )
    emit_event(db, event_name="file.process", user_id=current_session.user_id,
               organization_id=organization_id_for_user(db, current_session.user_id),
               route="/api/upload_zip", task_id=pending.zip_context_id,
               duration_ms=(perf_counter() - started) * 1000, status_code=status.HTTP_202_ACCEPTED,
               metadata={"filename": filename, "bytes": len(raw), "mode": "async", "status": "queued"})
    db.commit()

    background_tasks.add_task(
        process_zip_upload_background,
        zip_context_id=pending.zip_context_id,
        owner_user_id=current_session.user_id,
        conversation_id=conversationId,
        archive_name=filename,
        raw=raw,
        model=model,
    )

    return UploadZipResponse(
        zipContextId=pending.zip_context_id,
        archiveName=pending.archive_name,
        entryCount=pending.entry_count,
        extractedEntryCount=pending.extracted_entry_count,
        inventoryOnlyCount=pending.inventory_only_count,
        skippedEntryCount=pending.skipped_entry_count,
        supportedByCurrentModel=supported_by_current_model,
        unsupportedReason=unsupported_reason,
        uploading=True,
        errorMessage=None,
    )


@router.get("/{zip_context_id}", response_model=UploadZipResponse)
async def get_upload_zip_status(
    zip_context_id: str,
    conversationId: str = Query(...),
    model: ChatModelId = Query(...),
    current_session: SessionModel = Depends(require_user_session),
) -> UploadZipResponse:
    stored = zip_context_store.get_for_scope(
        zip_context_id,
        owner_user_id=current_session.user_id,
        conversation_id=conversationId,
    )
    if stored is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ZIP context not found.")

    supported_by_current_model, unsupported_reason = get_zip_model_support(model)
    return UploadZipResponse(
        zipContextId=stored.zip_context_id,
        archiveName=stored.archive_name,
        entryCount=stored.entry_count,
        extractedEntryCount=stored.extracted_entry_count,
        inventoryOnlyCount=stored.inventory_only_count,
        skippedEntryCount=stored.skipped_entry_count,
        supportedByCurrentModel=supported_by_current_model,
        unsupportedReason=unsupported_reason,
        uploading=stored.uploading,
        errorMessage=stored.error_message,
    )


async def process_zip_upload_background(
    *,
    zip_context_id: str,
    owner_user_id: int,
    conversation_id: str,
    archive_name: str,
    raw: bytes,
    model: ChatModelId,
) -> None:
    started = perf_counter()
    try:
        parsed = await parse_zip_upload(
            archive_name,
            raw,
            eager_image_ocr=should_eagerly_extract_zip_image_text(model),
        )
    except AttachmentError as exc:
        zip_context_store.mark_failed(
            zip_context_id=zip_context_id,
            owner_user_id=owner_user_id,
            conversation_id=conversation_id,
            archive_name=archive_name,
            error_message=str(exc),
        )
        with SessionLocal() as db:
            emit_event(db, event_name="file.process", user_id=owner_user_id,
                       organization_id=organization_id_for_user(db, owner_user_id),
                       route="/api/upload_zip", task_id=zip_context_id,
                       duration_ms=(perf_counter() - started) * 1000,
                       error_type=type(exc).__name__, status_code=status.HTTP_400_BAD_REQUEST,
                       metadata={"filename": archive_name, "bytes": len(raw), "mode": "async",
                                 "status": "failed"})
            db.commit()
        return

    zip_context_store.mark_ready(
        zip_context_id=zip_context_id,
        owner_user_id=owner_user_id,
        conversation_id=conversation_id,
        parsed=parsed,
    )
    with SessionLocal() as db:
        emit_event(db, event_name="file.process", user_id=owner_user_id,
                   organization_id=organization_id_for_user(db, owner_user_id),
                   route="/api/upload_zip", task_id=zip_context_id,
                   duration_ms=(perf_counter() - started) * 1000, status_code=200,
                   metadata={"filename": archive_name, "bytes": len(raw), "mode": "async",
                             "status": "ready", "entry_count": parsed.entry_count,
                             "extracted_entry_count": parsed.extracted_entry_count,
                             "skipped_entry_count": parsed.skipped_entry_count})
        db.commit()
