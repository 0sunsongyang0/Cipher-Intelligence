from fastapi import FastAPI


app = FastAPI(title="Campus LLM Assistant API")


@app.get("/api/health")
def health_check() -> dict[str, str]:
    return {"status": "ok", "service": "campus-llm-assistant"}
