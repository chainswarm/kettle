from datetime import datetime, timezone
import os
import time

from fastapi import APIRouter, Depends, HTTPException, Request

from subnet.api.auth.dependencies import limiter
from subnet.api.auth.ratelimit import get_dynamic_limit
from subnet.api.dependencies import get_db
from subnet.api.models import ErrorResponse, HealthResponse, MetricsResponse
from subnet.utils.db.database import RocksDB

router = APIRouter(prefix="/health", tags=["health"])

# Track startup time for uptime calculation
_startup_time = time.time()


@router.get(
    "",
    response_model=HealthResponse,
    responses={500: {"model": ErrorResponse}},
    summary="Health check",
    description="Check if the API and database are accessible",
)
@limiter.limit(get_dynamic_limit)
async def health_check(request: Request, db: RocksDB = Depends(get_db)) -> HealthResponse:
    """
    Perform a health check on the API and database.

    Args:
        request: The FastAPI request object
        db: Database dependency checking if store is accessible

    Returns:
        HealthResponse with status, database path, and accessibility info

    """
    try:
        # Test database access by checking if store is accessible
        db_accessible = db.store is not None

        return HealthResponse(
            status="healthy" if db_accessible else "unhealthy",
            db_path=db.db_path,
            db_accessible=db_accessible,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Health check failed: {str(e)}")


@router.get(
    "/metrics",
    response_model=MetricsResponse,
    responses={500: {"model": ErrorResponse}},
    summary="API metrics",
    description="Get basic metrics about the database and API",
)
@limiter.limit(get_dynamic_limit)
async def get_metrics(request: Request, db: RocksDB = Depends(get_db)) -> MetricsResponse:
    """
    Get API and database metrics.

    Returns:
        MetricsResponse with key count, database size, and uptime

    """
    try:
        # Count total keys
        total_keys = len(list(db.store.keys()))

        # Get database size
        db_size = 0
        if os.path.exists(db.db_path):
            for dirpath, dirnames, filenames in os.walk(db.db_path):
                for filename in filenames:
                    filepath = os.path.join(dirpath, filename)
                    if os.path.isfile(filepath):
                        db_size += os.path.getsize(filepath)

        # Calculate uptime
        uptime = time.time() - _startup_time

        return MetricsResponse(
            total_keys=total_keys,
            db_size_bytes=db_size,
            uptime_seconds=uptime,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get metrics: {str(e)}")
