"""FastAPI dependencies for API key authentication and rate limiting."""

from typing import Optional

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader
from slowapi import Limiter
from slowapi.util import get_remote_address

from subnet.api.auth.manager import AuthManager
from subnet.api.config import settings

# Header name for the API key
API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)

# Global auth manager
_auth_manager: Optional[AuthManager] = None

# Global limiter
# Using an in-memory storage for sliding window counts
limiter = Limiter(key_func=get_remote_address, default_limits=[])


def get_auth_manager() -> AuthManager:
    """Get or initialize the global AuthManager."""
    global _auth_manager
    if _auth_manager is None:
        _auth_manager = AuthManager()
    return _auth_manager


async def get_api_key(
    request: Request,
    api_key: Optional[str] = Security(API_KEY_HEADER),
    auth_manager: AuthManager = Depends(get_auth_manager),
) -> str:
    """
    Dependency that validates the API key provided in the header.

    Returns the raw API key if valid and active.
    """
    if not settings.enable_auth:
        return "unauthenticated"

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="API Key missing. Use 'X-API-Key' header.",
        )

    metadata = auth_manager.get_metadata(api_key)
    if not metadata or not metadata.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or revoked API Key.",
        )

    # Store metadata in request state for the rate limiter to use
    request.state.api_key_metadata = metadata
    return api_key


def get_rate_limit_key(request: Request) -> str:
    """
    Identify the user for rate limiting.
    Uses the hash of the API key if authenticated, otherwise remote address.
    """
    if hasattr(request.state, "api_key_metadata"):
        # We use a combined key of the owner so it's consistent
        return f"api_key:{request.state.api_key_metadata.owner}"
    return get_remote_address(request)


# Update limiter key_func to use our custom key retriever
limiter.key_func = get_rate_limit_key
