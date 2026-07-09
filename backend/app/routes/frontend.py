from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse, RedirectResponse
from starlette.routing import Match
from sqlalchemy.orm import Session

from app.admin_access import assert_local_admin_request
from app.auth import COOKIE_NAME, get_session_record
from app.database import get_db

router = APIRouter(tags=["frontend"], include_in_schema=False)

FRONTEND_DIST_DIR = Path(__file__).resolve().parents[3] / "frontend" / "dist"
FRONTEND_INDEX_PATH = FRONTEND_DIST_DIR / "index.html"
FRONTEND_ASSETS_DIR = FRONTEND_DIST_DIR / "assets"
SPA_SHELL_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}


def serve_spa_shell() -> FileResponse:
    if not FRONTEND_INDEX_PATH.is_file():
        raise HTTPException(status_code=503, detail="Frontend build is not available.")

    return FileResponse(FRONTEND_INDEX_PATH, headers=SPA_SHELL_HEADERS)


def api_not_found() -> None:
    raise HTTPException(status_code=404, detail="Not Found")


def preserve_api_status_for_request(request: Request) -> None:
    allowed_methods: set[str] = set()

    for route in request.app.router.routes:
        route_path = getattr(route, "path", "")
        if not route_path.startswith("/api") or route_path in {"/api", "/api/{api_path:path}"}:
            continue

        match, _ = route.matches(request.scope)
        if match == Match.PARTIAL:
            allowed_methods.update(route.methods or set())

    if allowed_methods:
        allow_header = ", ".join(sorted(method for method in allowed_methods if method != "HEAD"))
        raise HTTPException(
            status_code=405,
            detail="Method Not Allowed",
            headers={"Allow": allow_header} if allow_header else None,
        )

    api_not_found()


@router.get("/", response_model=None)
def serve_root() -> Response:
    return serve_spa_shell()


@router.get("/chat", response_model=None)
def serve_authenticated_chat_entry(
    request: Request, db: Session = Depends(get_db)
) -> Response:
    session = get_session_record(db, request.cookies.get(COOKIE_NAME))
    if session is None or session.user_id is None:
        return RedirectResponse(url="/", status_code=307)

    return serve_spa_shell()


@router.get("/admin", response_model=None)
def serve_admin_entry(request: Request, db: Session = Depends(get_db)) -> Response:
    session = get_session_record(db, request.cookies.get(COOKIE_NAME))
    if session is None:
        return RedirectResponse(url="/", status_code=307)

    assert_local_admin_request(request)
    return serve_spa_shell()


@router.get("/admin/{admin_path:path}", response_model=None)
def serve_admin_nested_path(
    admin_path: str, request: Request, db: Session = Depends(get_db)
) -> Response:
    del admin_path
    session = get_session_record(db, request.cookies.get(COOKIE_NAME))
    if session is None:
        return RedirectResponse(url="/", status_code=307)

    assert_local_admin_request(request)
    return serve_spa_shell()


@router.api_route("/api", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
def preserve_exact_api_path(request: Request) -> None:
    preserve_api_status_for_request(request)

@router.api_route(
    "/api/{api_path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
)
def preserve_api_paths(api_path: str, request: Request) -> None:
    del api_path
    preserve_api_status_for_request(request)


@router.get("/{frontend_path:path}", response_model=None)
def serve_guarded_frontend_path(
    frontend_path: str, request: Request, db: Session = Depends(get_db)
) -> Response:
    session = get_session_record(db, request.cookies.get(COOKIE_NAME))
    if session is None or session.user_id is None:
        return RedirectResponse(url="/", status_code=307)

    return serve_spa_shell()
