from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import init_db
from app.routes.admin import router as admin_router
from app.routes.admin_frontend import FRONTEND_ASSETS_DIR, router as admin_frontend_router
from app.routes.auth import admin_router as admin_auth_router
from app.routes.audit import router as audit_router
from app.routes.commerce import admin_router as commerce_admin_router
from app.routes.analysis_templates import router as analysis_templates_router
from app.observability import ObservabilityMiddleware


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    init_db()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title=f"{settings.app_name} Admin",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.add_middleware(ObservabilityMiddleware)
    app.include_router(admin_auth_router)
    app.include_router(admin_router)
    app.include_router(audit_router)
    app.include_router(commerce_admin_router)
    app.include_router(analysis_templates_router)
    if FRONTEND_ASSETS_DIR.is_dir():
        app.mount("/assets", StaticFiles(directory=FRONTEND_ASSETS_DIR), name="admin-frontend-assets")

    @app.get("/api/health")
    def health_check() -> dict[str, str]:
        return {"status": "ok", "service": "cipher-admin-console"}

    app.include_router(admin_frontend_router)
    return app


app = create_app()
