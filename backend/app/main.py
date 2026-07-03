from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import init_db
from app.routes.auth import router as auth_router
from app.routes.frontend import FRONTEND_ASSETS_DIR, router as frontend_router


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    init_db()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.include_router(auth_router)
    if FRONTEND_ASSETS_DIR.is_dir():
        app.mount("/assets", StaticFiles(directory=FRONTEND_ASSETS_DIR), name="frontend-assets")

    @app.get("/api/health")
    def health_check() -> dict[str, str]:
        return {"status": "ok", "service": "campus-llm-assistant"}

    app.include_router(frontend_router)
    return app


app = create_app()
