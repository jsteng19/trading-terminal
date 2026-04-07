"""Security middleware and helpers."""

from fastapi import Header, HTTPException, Query
from backend.config import SESSION_TOKEN


def require_token(authorization: str = Header(None)):
    """Dependency that validates the session token on mutating endpoints."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or parts[1] != SESSION_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid session token")


def require_ws_token(token: str = Query(None)):
    """Validate session token for WebSocket connections (via query param)."""
    if token != SESSION_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid session token")
