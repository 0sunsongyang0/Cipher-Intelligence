from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import datetime, timezone
import json
from typing import Any

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Job, OrganizationMember, now_utc
from app.observability import emit_event
from app.notifications import NotificationEvent, notify


TERMINAL_STATUSES = {"succeeded", "failed", "cancelled"}
JobHandler = Callable[["JobContext", dict[str, Any]], Awaitable[dict[str, Any] | None]]
_handlers: dict[str, JobHandler] = {}


class JobCancelled(Exception):
    pass


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


class JobContext:
    def __init__(self, job_id: int) -> None:
        self.job_id = job_id

    async def update(self, progress: int, message: str | None = None) -> None:
        with SessionLocal() as db:
            job = db.get(Job, self.job_id)
            if job is None or job.cancel_requested:
                raise JobCancelled()
            job.progress = max(job.progress, min(99, max(0, progress)))
            job.progress_message = message
            db.commit()

    async def checkpoint(self) -> None:
        with SessionLocal() as db:
            job = db.get(Job, self.job_id)
            if job is None or job.cancel_requested:
                raise JobCancelled()


def register_job_handler(task_type: str, handler: JobHandler) -> None:
    _handlers[task_type] = handler


class JobRunner:
    def __init__(self, poll_interval: float = 0.2) -> None:
        self.poll_interval = poll_interval
        self._loop_task: asyncio.Task[None] | None = None
        self._active: dict[int, asyncio.Task[None]] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

    def start(self) -> None:
        loop = asyncio.get_running_loop()
        # A runner may be reused by lifespan tests or embedding applications
        # that create a fresh event loop. Never retain tasks from the old loop.
        if self._loop_task is not None and self._loop is not loop:
            self._loop_task = None
            self._active.clear()
        if self._loop_task is None or self._loop_task.done():
            self._recover_interrupted_jobs()
            self._loop = loop
            self._loop_task = loop.create_task(self._run_loop())

    async def stop(self) -> None:
        current_loop = asyncio.get_running_loop()
        if self._loop_task is not None and self._loop is current_loop:
            self._loop_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._loop_task
        elif self._loop_task is not None:
            self._loop_task.cancel()
        self._loop_task = None
        for task in list(self._active.values()):
            task.cancel()
        same_loop_tasks = [task for task in self._active.values() if task.get_loop() is current_loop]
        if same_loop_tasks:
            await asyncio.gather(*same_loop_tasks, return_exceptions=True)
        self._active.clear()
        self._loop = None

    def wake(self) -> None:
        # The polling interval is deliberately short; no extra broker primitive is needed.
        return None

    def _recover_interrupted_jobs(self) -> None:
        with SessionLocal() as db:
            jobs = db.execute(select(Job).where(Job.status == "running")).scalars().all()
            for job in jobs:
                job.status = "queued"
                job.progress_message = "服务重启，任务已重新排队"
                job.started_at = None
            db.commit()

    async def _run_loop(self) -> None:
        while True:
            with SessionLocal() as db:
                queued = db.execute(
                    select(Job.id).where(Job.status == "queued").order_by(Job.created_at).limit(4)
                ).scalars().all()
            for job_id in queued:
                if job_id not in self._active:
                    task = asyncio.create_task(self._execute(job_id))
                    self._active[job_id] = task
                    task.add_done_callback(lambda _task, jid=job_id: self._active.pop(jid, None))
            await asyncio.sleep(self.poll_interval)

    async def _execute(self, job_id: int) -> None:
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            if job is None or job.status != "queued":
                return
            if job.cancel_requested:
                job.status = "cancelled"
                job.completed_at = now_utc()
                db.commit()
                return
            job.status = "running"
            job.started_at = now_utc()
            job.completed_at = None
            job.error_message = None
            job.progress_message = "任务已开始"
            payload = json.loads(job.payload_json or "{}")
            timeout_seconds = job.timeout_seconds
            task_type = job.task_type
            db.commit()

        try:
            handler = _handlers.get(task_type)
            if handler is None:
                raise ValueError(f"Unsupported task type: {task_type}")
            result = await asyncio.wait_for(handler(JobContext(job_id), payload), timeout=timeout_seconds)
        except JobCancelled:
            self._finish(job_id, "cancelled", error=None)
        except asyncio.TimeoutError:
            self._finish(job_id, "failed", error=f"任务超过 {timeout_seconds} 秒超时限制")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # worker boundary: persist failures instead of losing them
            self._finish(job_id, "failed", error=str(exc) or exc.__class__.__name__)
        else:
            self._finish(job_id, "succeeded", result=result or {})

    @staticmethod
    def _finish(job_id: int, status: str, *, result: dict[str, Any] | None = None, error: str | None = None) -> None:
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            if job is None:
                return
            if job.cancel_requested:
                status, result, error = "cancelled", None, None
            job.status = status
            job.progress = 100 if status == "succeeded" else job.progress
            job.progress_message = {"succeeded": "已完成", "failed": "执行失败", "cancelled": "已取消"}[status]
            job.result_json = json.dumps(result, ensure_ascii=False) if result is not None else None
            job.error_message = error
            job.completed_at = now_utc()
            organization_id = db.execute(
                select(OrganizationMember.organization_id)
                .where(OrganizationMember.user_id == job.owner_user_id)
                .order_by(OrganizationMember.id)
            ).scalars().first()
            payload = json.loads(job.payload_json or "{}")
            duration_ms = None
            if job.started_at is not None:
                duration_ms = (_as_utc(job.completed_at) - _as_utc(job.started_at)).total_seconds() * 1000
            event_name = {
                "cape_analysis": "cape.task",
                "file_parse": "file.process",
                "model_inference": "model.call",
                "report_generation": "model.call",
            }.get(job.task_type, "job.task")
            emit_event(
                db,
                event_name=event_name,
                user_id=job.owner_user_id,
                organization_id=organization_id,
                route="job.runner",
                model_id=str(payload.get("model")) if payload.get("model") else None,
                task_id=str(payload.get("taskId") or job.id),
                duration_ms=duration_ms,
                error_type=error.__class__.__name__ if error and not isinstance(error, str) else ("JobError" if error else None),
                status_code=200 if status == "succeeded" else 499 if status == "cancelled" else 500,
                metadata={"job_id": job.id, "task_type": job.task_type, "status": status},
            )
            notification_type = "cape_completed" if job.task_type == "cape_analysis" and status == "succeeded" else (
                "model_failed" if job.task_type in {"model_inference", "report_generation"} and status == "failed" else None
            )
            if notification_type and organization_id is not None:
                notify(db, NotificationEvent(
                    organization_id=organization_id, user_id=job.owner_user_id,
                    notification_type=notification_type,
                    title="CAPE 分析任务已完成" if notification_type == "cape_completed" else "模型任务执行失败",
                    body=error, resource_type="job", resource_id=str(job.id), resource_url="/jobs",
                    idempotency_key=f"job:{job.id}:{status}",
                ))
            db.commit()


job_runner = JobRunner()
