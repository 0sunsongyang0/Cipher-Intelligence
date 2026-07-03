from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.database import init_db
from app.routes.auth import router as auth_router
from app.routes.chat import router as chat_router
from app.routes.conversations import router as conversations_router


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    init_db()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(conversations_router)


@app.get("/api/health")
def health_check() -> dict[str, str]:
    return {"status": "ok", "service": "campus-llm-assistant"}