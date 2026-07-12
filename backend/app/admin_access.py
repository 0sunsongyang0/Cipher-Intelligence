from fastapi import HTTPException, Request, status

LOCAL_ADMIN_ERROR = "Admin is available only from this machine."
_LOOPBACK_CLIENT_HOSTS = {"127.0.0.1", "::1"}


def assert_local_admin_request(request: Request) -> None:
    client_host = getattr(request.client, "host", None)
    if client_host in _LOOPBACK_CLIENT_HOSTS:
        return

    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=LOCAL_ADMIN_ERROR)
