from fastapi import FastAPI

from app.config import settings
from app.routes import conversations_router


app = FastAPI(title=settings.app_name)
app.include_router(conversations_router)


@app.get("/api/health")
def health_check() -> dict[str, str]:
    return {"status": "ok", "service": "campus-llm-assistant"}
