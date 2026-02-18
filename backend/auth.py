"""
Optional API key authentication for remote deployments.
"""

from __future__ import annotations

from fastapi import Header, HTTPException, status
import hmac
from typing import Optional

from .settings import BackendSettings


def _extract_bearer_token(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    prefix = "bearer "
    if authorization.lower().startswith(prefix):
        return authorization[len(prefix):].strip()
    return None


def create_api_key_dependency(settings: BackendSettings):
    async def require_api_key(authorization: Optional[str] = Header(default=None)) -> None:
        # Backward-compatible: no key configured => open mode.
        if not settings.api_key:
            return

        token = _extract_bearer_token(authorization)
        if not token or not hmac.compare_digest(token, settings.api_key):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unauthorized",
            )

    return require_api_key


def is_request_authorized(
    settings: BackendSettings,
    authorization: Optional[str],
    query_token: Optional[str] = None,
    method: str = "GET",
) -> bool:
    """
    Validate request token against configured API key.

    Rules:
    - If no API key configured: open mode (authorized).
    - Bearer token is accepted for any method.
    - Query token is accepted only for GET requests (media/SSE use-cases).
    """
    if not settings.api_key:
        return True

    bearer_token = _extract_bearer_token(authorization)
    if bearer_token and hmac.compare_digest(bearer_token, settings.api_key):
        return True

    if method.upper() == "GET" and query_token:
        return hmac.compare_digest(query_token, settings.api_key)

    return False
