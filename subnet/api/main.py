"""FastAPI application for RocksDB API."""

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
import uvicorn

from subnet.api.auth.dependencies import get_api_key, limiter
from subnet.api.auth.ratelimit import request_var
from subnet.api.config import settings
from subnet.api.dependencies import lifespan_manager
from subnet.api.routers.v1 import router as v1_router


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        token = request_var.set(request)
        try:
            response = await call_next(request)
        finally:
            request_var.reset(token)
        return response


# Create FastAPI application
app = FastAPI(
    title=settings.title,
    description=settings.description,
    version=settings.version,
    lifespan=lifespan_manager,
    docs_url=f"{settings.api_prefix}/docs",
    redoc_url=f"{settings.api_prefix}/redoc",
    openapi_url=f"{settings.api_prefix}/openapi.json",
    dependencies=[Depends(get_api_key)],  # Apply authentication globally
)

# Add middlewares
app.add_middleware(RequestContextMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=settings.cors_credentials,
    allow_methods=settings.cors_methods,
    allow_headers=settings.cors_headers,
)

# Add slowapi limiter to app state and error handler
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Include API routers
app.include_router(v1_router, prefix=settings.api_prefix)


@app.get("/", include_in_schema=False)
async def root():
    """Redirect root to API documentation."""
    return RedirectResponse(url=f"{settings.api_prefix}/docs")


@app.get("/api", include_in_schema=False)
async def api_root():
    """Redirect /api to API documentation."""
    return RedirectResponse(url=f"{settings.api_prefix}/docs")


@app.get("/metrics", include_in_schema=False)
async def root_metrics():
    """Redirect root /metrics to health metrics."""
    return RedirectResponse(url=f"{settings.api_prefix}/v1.0/health/metrics")


def cli() -> None:
    """
    CLI entry point for running the API server.

    python -m subnet.api.main run_api

    Usage:
        run_api
        API_DB_PATH=/path/to/db run_api
        API_PORT=9000 run_api
    """
    # Print startup information
    print(f"Starting {settings.title} v{settings.version}")
    print(f"Database path: {settings.db_path}")
    print(f"Server: http://{settings.host}:{settings.port}")
    print(f"API docs: http://{settings.host}:{settings.port}{settings.api_prefix}/docs")
    print(f"Read-only mode: {settings.db_read_only}")
    print()

    # Run the server
    uvicorn.run(
        "subnet.api.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.reload,
        log_level="info",
    )


if __name__ == "__main__":
    cli()
