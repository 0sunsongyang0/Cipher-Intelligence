from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.auth import COOKIE_NAME, get_session_record
from app.database import get_db

router = APIRouter(tags=["frontend"], include_in_schema=False)

FRONTEND_DIST_DIR = Path(__file__).resolve().parents[3] / "frontend" / "dist"
FRONTEND_INDEX_PATH = FRONTEND_DIST_DIR / "index.html"
FRONTEND_ASSETS_DIR = FRONTEND_DIST_DIR / "assets"


def serve_spa_shell() -> FileResponse:
    return FileResponse(FRONTEND_INDEX_PATH)


@router.get("/", response_model=None)
def serve_root() -> Response:
    return serve_spa_shell()


@router.get("/chat", response_model=None)
def serve_authenticated_chat_entry(
    request: Request, db: Session = Depends(get_db)
) -> Response:
    session = get_session_record(db, request.cookies.get(COOKIE_NAME))
    if session is None:
        return RedirectResponse(url="/", status_code=307)

    return serve_spa_shell()


@router.get("/{frontend_path:path}", response_model=None)
def serve_guarded_frontend_path(
    frontend_path: str, request: Request, db: Session = Depends(get_db)
) -> Response:
    if frontend_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not Found")

    session = get_session_record(db, request.cookies.get(COOKIE_NAME))
    if session is None:
        return RedirectResponse(url="/", status_code=307)

    return serve_spa_shell()
