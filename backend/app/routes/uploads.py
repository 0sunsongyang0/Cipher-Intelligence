from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from app.auth import require_user_session
from app.models import Session as SessionModel
from app.upload_sessions import append_chunk, create_upload, get_upload


router = APIRouter(prefix="/api/uploads", tags=["uploads"])


class UploadCreate(BaseModel):
    name: str
    size: int
    sha256: str
    mimeType: str = "application/octet-stream"


def serialize(record, deduplicated: bool = False) -> dict:
    return {"uploadId": record.upload_id, "name": record.name, "size": record.size, "received": record.received,
            "complete": record.complete, "deduplicated": deduplicated, "expiresInSeconds": 86400}


@router.post("", status_code=status.HTTP_201_CREATED)
def start_upload(payload: UploadCreate, session: SessionModel = Depends(require_user_session)) -> dict:
    try:
        record, deduplicated = create_upload(session.user_id, payload.name, payload.size, payload.sha256, payload.mimeType)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return serialize(record, deduplicated)


@router.get("/{upload_id}")
def upload_status(upload_id: str, session: SessionModel = Depends(require_user_session)) -> dict:
    record = get_upload(session.user_id, upload_id)
    if record is None:
        raise HTTPException(status_code=404, detail="上传会话不存在或已过期。")
    return serialize(record)


@router.put("/{upload_id}/chunks")
async def upload_chunk(upload_id: str, request: Request, offset: int, session: SessionModel = Depends(require_user_session)) -> dict:
    try:
        record = append_chunk(session.user_id, upload_id, offset, await request.body())
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="上传会话不存在或已过期。") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail={"message": "分片偏移冲突。", "expectedOffset": int(str(exc))}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return serialize(record)
