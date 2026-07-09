from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from app.attachments import AttachmentError
from app.auth import require_user_session
from app.models import Session as SessionModel
from app.schemas import ChatModelId, UploadZipResponse
from app.zip_context_store import get_zip_model_support, zip_context_store
from app.zip_parser import parse_zip_upload


router = APIRouter(prefix="/api/upload_zip", tags=["upload-zip"])


NON_ZIP_UPLOAD_ERROR = "上传的文件必须是 ZIP 压缩包。"

@router.post("", response_model=UploadZipResponse)
async def upload_zip(
    conversationId: str = Form(...),
    model: ChatModelId = Form(...),
    file: UploadFile = File(...),
    current_session: SessionModel = Depends(require_user_session),
) -> UploadZipResponse:
    filename = file.filename or "upload.zip"
    if not filename.lower().endswith(".zip"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=NON_ZIP_UPLOAD_ERROR,
        )

    raw = await file.read()

    try:
        parsed = await parse_zip_upload(filename, raw)
    except AttachmentError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    stored = zip_context_store.save(
        owner_user_id=current_session.user_id,
        conversation_id=conversationId,
        parsed=parsed,
    )
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
    )
