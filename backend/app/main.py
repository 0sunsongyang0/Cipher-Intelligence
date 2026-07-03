from fastapi import FastAPI

from app.config import settings


app = FastAPI(title=settings.app_name)


@app.get("/api/health")
def health_check() -> dict[str, str]:
    return {"status": "ok", "service": "campus-llm-assistant"}
