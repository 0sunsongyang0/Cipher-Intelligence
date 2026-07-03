from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.database import init_db
from app.routes import conversations_router


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    init_db()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.include_router(conversations_router)


@app.get("/api/health")
def health_check() -> dict[str, str]:
    return {"status": "ok", "service": "campus-llm-assistant"}
