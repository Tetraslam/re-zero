"""API key authentication dependency."""

import logging
from dataclasses import dataclass

from fastapi import Header, HTTPException

from .convex_client import convex_query, convex_mutation

logger = logging.getLogger(__name__)


@dataclass
class AuthContext:
    """Result of successful authentication."""
    user_id: str  # Convex user _id


async def require_api_key(
    x_api_key: str = Header(..., alias="X-API-Key"),
) -> AuthContext:
    """FastAPI dependency: validates API key via Convex query."""
    if not x_api_key.startswith("re0_"):
        raise HTTPException(status_code=401, detail="Invalid API key format")

    result = await convex_query("apiKeys:validate", {"key": x_api_key})

    # Convex HTTP API wraps responses: {"value": ..., "status": "success"}
    value = result.get("value", result) if isinstance(result, dict) else result

    if not value or not value.get("valid"):
        raise HTTPException(status_code=401, detail="Invalid or revoked API key")

    # Fire-and-forget: update lastUsedAt
    try:
        await convex_mutation("apiKeys:touch", {"key": x_api_key})
    except Exception:
        pass

    return AuthContext(user_id=value["userId"])
