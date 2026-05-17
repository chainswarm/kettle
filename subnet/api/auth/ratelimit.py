"""Rate limit providers for slowapi."""

from contextvars import ContextVar
from typing import Optional

from fastapi import Request

from subnet.api.config import settings

# ContextVar to store the current request for access in the rate limiter
request_var: ContextVar[Optional[Request]] = ContextVar("request", default=None)


def get_dynamic_limit() -> str:
    """
    Retrieve the rate limit for the current authenticated user.

    Uses ContextVar to get the current request.
    """
    request = request_var.get()
    if request and hasattr(request.state, "api_key_metadata"):
        limit = request.state.api_key_metadata.qpm_limit
        return f"{limit}/minute"

    return f"{settings.default_qpm}/minute"
