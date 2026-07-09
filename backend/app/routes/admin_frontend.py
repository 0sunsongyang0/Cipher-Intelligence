from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from starlette.routing import Match

from app.auth import require_admin_user_session
from app.database import get_db

router = APIRouter(tags=["admin-frontend"], include_in_schema=False)

FRONTEND_DIST_DIR = Path(__file__).resolve().parents[3] / "frontend" / "dist"
ADMIN_FRONTEND_INDEX_PATH = FRONTEND_DIST_DIR / "admin.html"
FRONTEND_ASSETS_DIR = FRONTEND_DIST_DIR / "assets"
SPA_SHELL_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}


def serve_admin_shell() -> FileResponse:
    if not ADMIN_FRONTEND_INDEX_PATH.is_file():
        raise HTTPException(status_code=503, detail="Admin frontend build is not available.")

    return FileResponse(ADMIN_FRONTEND_INDEX_PATH, headers=SPA_SHELL_HEADERS)


def preserve_api_status_for_request(request: Request) -> None:
    allowed_methods: set[str] = set()

    for route in request.app.router.routes:
        route_path = getattr(route, "path", "")
        if not route_path.startswith("/api") or route_path == "/api/{api_path:path}":
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

    raise HTTPException(status_code=404, detail="Not Found")


@router.get("/", response_model=None)
def serve_root(request: Request, db: Session = Depends(get_db)) -> Response:
    require_admin_user_session(request, db)
    return serve_admin_shell()


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
def serve_frontend_path(
    frontend_path: str,
    request: Request,
    db: Session = Depends(get_db),
) -> Response:
    del frontend_path
    require_admin_user_session(request, db)
    return serve_admin_shell()
