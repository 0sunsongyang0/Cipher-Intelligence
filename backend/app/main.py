from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import asyncio
from contextlib import suppress

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import init_db
from app.routes.auth import router as auth_router
from app.routes.account import router as account_router
from app.routes.cape import router as cape_router
from app.routes.chat import router as chat_router
from app.routes.cases import router as cases_router
from app.routes.conversations import router as conversations_router
from app.routes.frontend import (
    FRONTEND_ASSETS_DIR,
    router as frontend_router,
)
from app.routes.feedback import router as feedback_router
from app.routes.upload_zip import router as upload_zip_router
from app.routes.skills import router as skills_router
from app.routes.organizations import router as organizations_router
from app.routes.notifications import router as notifications_router
from app.routes.usage import router as usage_router
from app.routes.commerce import router as commerce_router
from app.observability import ObservabilityMiddleware
from app.routes.admin import router as admin_router
from app.routes.jobs import router as jobs_router
from app.routes.analysis_templates import router as analysis_templates_router
from app.routes.uploads import router as uploads_router
from app.jobs import job_runner
import app.job_handlers  # noqa: F401 - registers built-in durable task handlers


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    init_db()
    from app.database import SessionLocal
    from app.retention import run_retention_cleanup
    from app.upload_sessions import cleanup_expired_uploads
    with SessionLocal() as db:
        run_retention_cleanup(db)
    cleanup_expired_uploads()
    async def retention_loop() -> None:
        while True:
            await asyncio.sleep(max(60, settings.retention_cleanup_interval_seconds))
            with SessionLocal() as db:
                run_retention_cleanup(db)
            cleanup_expired_uploads()
    retention_task = asyncio.create_task(retention_loop())
    job_runner.start()
    try:
        yield
    finally:
        retention_task.cancel()
        with suppress(asyncio.CancelledError):
            await retention_task
        await job_runner.stop()


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.add_middleware(ObservabilityMiddleware)
    app.include_router(auth_router)
    app.include_router(account_router)
    app.include_router(cape_router)
    app.include_router(chat_router)
    app.include_router(feedback_router)
    app.include_router(cases_router)
    app.include_router(conversations_router)
    app.include_router(upload_zip_router)
    app.include_router(skills_router)
    app.include_router(organizations_router)
    app.include_router(notifications_router)
    app.include_router(usage_router)
    app.include_router(commerce_router)
    app.include_router(admin_router)
    app.include_router(jobs_router)
    app.include_router(analysis_templates_router)
    app.include_router(uploads_router)
    if FRONTEND_ASSETS_DIR.is_dir():
        app.mount("/assets", StaticFiles(directory=FRONTEND_ASSETS_DIR), name="frontend-assets")

    @app.get("/api/health")
    def health_check() -> dict[str, str]:
        return {"status": "ok", "service": "campus-llm-assistant"}

    app.include_router(frontend_router)
    return app


app = create_app()
