"""Session authentication and CSRF protection for the editor panel."""

import secrets

from fastapi import HTTPException, Request


def ensure_csrf_token(request: Request) -> str:
    token = request.session.get("csrf_token")
    if token is None:
        token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = token
    return token


def require_admin(request: Request) -> None:
    if request.session.get("is_admin") is not True:
        raise HTTPException(
            status_code=303,
            headers={"Location": "/login"},
        )


def verify_csrf(request: Request, submitted_token: str) -> None:
    expected_token = request.session.get("csrf_token")
    if (
        not expected_token
        or not submitted_token
        or not secrets.compare_digest(expected_token, submitted_token)
    ):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")


def verify_password(submitted: str, configured: str) -> bool:
    return secrets.compare_digest(submitted.encode(), configured.encode())

