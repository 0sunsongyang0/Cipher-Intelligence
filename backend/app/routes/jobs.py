from __future__ import annotations

import json
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import require_user_session
from app.database import get_db
from app.jobs import TERMINAL_STATUSES, job_runner
from app.models import Job, Session as SessionModel


router = APIRouter(prefix="/api/jobs", tags=["jobs"])


class JobCreate(BaseModel):
    task_type: str = Field(alias="taskType", min_length=1, max_length=64)
    payload: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int = Field(default=900, alias="timeoutSeconds", ge=1, le=86400)
    max_retries: int = Field(default=3, alias="maxRetries", ge=0, le=20)


def job_response(job: Job) -> dict[str, Any]:
    return {
        "id": job.id, "taskType": job.task_type, "status": job.status,
        "progress": job.progress, "progressMessage": job.progress_message,
        "result": json.loads(job.result_json) if job.result_json else None,
        "errorMessage": job.error_message, "retryCount": job.retry_count,
        "maxRetries": job.max_retries, "timeoutSeconds": job.timeout_seconds,
        "startedAt": job.started_at, "completedAt": job.completed_at,
        "createdAt": job.created_at, "updatedAt": job.updated_at,
    }


def owned_job(db: Session, job_id: int, user_id: int) -> Job:
    job = db.execute(select(Job).where(Job.id == job_id, Job.owner_user_id == user_id)).scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return job


@router.post("", status_code=status.HTTP_202_ACCEPTED)
def create_job(
    request: JobCreate,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_session: SessionModel = Depends(require_user_session),
    db: Session = Depends(get_db),
):
    if idempotency_key and len(idempotency_key) > 128:
        raise HTTPException(status_code=400, detail="Idempotency-Key is too long")
    if idempotency_key:
        existing = db.execute(select(Job).where(Job.owner_user_id == current_session.user_id, Job.task_type == request.task_type, Job.idempotency_key == idempotency_key)).scalar_one_or_none()
        if existing:
            return job_response(existing)
    job = Job(owner_user_id=current_session.user_id, task_type=request.task_type,
              payload_json=json.dumps(request.payload, ensure_ascii=False), idempotency_key=idempotency_key,
              timeout_seconds=request.timeout_seconds, max_retries=request.max_retries)
    db.add(job)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.execute(select(Job).where(Job.owner_user_id == current_session.user_id, Job.task_type == request.task_type, Job.idempotency_key == idempotency_key)).scalar_one()
        return job_response(existing)
    db.refresh(job)
    job_runner.wake()
    return job_response(job)


@router.get("")
def list_jobs(status_filter: Literal["queued", "running", "succeeded", "failed", "cancelled"] | None = Query(default=None, alias="status"), limit: int = Query(50, ge=1, le=200), current_session: SessionModel = Depends(require_user_session), db: Session = Depends(get_db)):
    statement = select(Job).where(Job.owner_user_id == current_session.user_id)
    if status_filter:
        statement = statement.where(Job.status == status_filter)
    items = db.execute(statement.order_by(Job.created_at.desc()).limit(limit)).scalars().all()
    return {"items": [job_response(item) for item in items]}


@router.get("/{job_id}")
def get_job(job_id: int, current_session: SessionModel = Depends(require_user_session), db: Session = Depends(get_db)):
    return job_response(owned_job(db, job_id, current_session.user_id))


@router.post("/{job_id}/cancel")
def cancel_job(job_id: int, current_session: SessionModel = Depends(require_user_session), db: Session = Depends(get_db)):
    job = owned_job(db, job_id, current_session.user_id)
    if job.status in TERMINAL_STATUSES:
        raise HTTPException(status_code=409, detail=f"Cannot cancel a {job.status} task")
    job.cancel_requested = True
    if job.status == "queued":
        from app.models import now_utc
        job.status, job.completed_at, job.progress_message = "cancelled", now_utc(), "已取消"
    db.commit(); db.refresh(job)
    return job_response(job)


@router.post("/{job_id}/retry", status_code=status.HTTP_202_ACCEPTED)
def retry_job(job_id: int, current_session: SessionModel = Depends(require_user_session), db: Session = Depends(get_db)):
    job = owned_job(db, job_id, current_session.user_id)
    if job.status not in {"failed", "cancelled"}:
        raise HTTPException(status_code=409, detail="Only failed or cancelled tasks can be retried")
    if job.retry_count >= job.max_retries:
        raise HTTPException(status_code=409, detail="Task retry limit reached")
    job.status, job.progress, job.progress_message = "queued", 0, "重新排队"
    job.error_message = job.result_json = None
    job.cancel_requested = False
    job.started_at = job.completed_at = None
    job.retry_count += 1
    db.commit(); db.refresh(job); job_runner.wake()
    return job_response(job)
