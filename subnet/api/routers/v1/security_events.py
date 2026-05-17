"""Security event endpoints — query indexed rejections and failures."""

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from subnet.api.auth.dependencies import limiter
from subnet.api.auth.ratelimit import get_dynamic_limit
from subnet.api.dependencies import get_db
from subnet.api.models import ErrorResponse, SecurityEventCountsResponse, SecurityEventResponse
from subnet.security.events import SecurityEventIndexer
from subnet.utils.db.database import RocksDB

router = APIRouter(prefix="/security-events", tags=["security-events"])


def _get_indexer(db: RocksDB = Depends(get_db)) -> SecurityEventIndexer:
    """Create a SecurityEventIndexer from the shared DB dependency."""
    return SecurityEventIndexer(db=db)


@router.get(
    "",
    response_model=SecurityEventResponse,
    responses={500: {"model": ErrorResponse}},
    summary="List recent security events",
    description="Get the most recent security events (rejections, failures, slashes), ordered by time descending.",
)
@limiter.limit(get_dynamic_limit)
async def list_security_events(
    request: Request,
    limit: int = Query(default=100, ge=1, le=1000, description="Maximum events to return"),
    indexer: SecurityEventIndexer = Depends(_get_indexer),
) -> SecurityEventResponse:
    """List recent security events."""
    try:
        events = indexer.get_recent_events(limit=limit)
        return SecurityEventResponse(events=events, total=len(events))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list security events: {str(e)}")


@router.get(
    "/by-peer/{peer_id}",
    response_model=SecurityEventResponse,
    responses={500: {"model": ErrorResponse}},
    summary="Get security events for a specific peer",
    description="Get all security events associated with a specific peer ID.",
)
@limiter.limit(get_dynamic_limit)
async def get_events_by_peer(
    request: Request,
    peer_id: str,
    limit: int = Query(default=100, ge=1, le=1000, description="Maximum events to return"),
    indexer: SecurityEventIndexer = Depends(_get_indexer),
) -> SecurityEventResponse:
    """Get security events for a specific peer."""
    try:
        events = indexer.get_events_by_peer(peer_id, limit=limit)
        return SecurityEventResponse(events=events, total=len(events))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get peer events: {str(e)}")


@router.get(
    "/by-type/{event_type}",
    response_model=SecurityEventResponse,
    responses={500: {"model": ErrorResponse}},
    summary="Get security events by type",
    description="Get all security events of a specific type (e.g., tee_nonce_mismatch, overwatch_slash).",
)
@limiter.limit(get_dynamic_limit)
async def get_events_by_type(
    request: Request,
    event_type: str,
    limit: int = Query(default=100, ge=1, le=1000, description="Maximum events to return"),
    indexer: SecurityEventIndexer = Depends(_get_indexer),
) -> SecurityEventResponse:
    """Get security events by type."""
    try:
        events = indexer.get_events_by_type(event_type, limit=limit)
        return SecurityEventResponse(events=events, total=len(events))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get events by type: {str(e)}")


@router.get(
    "/counts",
    response_model=SecurityEventCountsResponse,
    responses={500: {"model": ErrorResponse}},
    summary="Get security event counts by type",
    description="Get a summary count of security events grouped by event type.",
)
@limiter.limit(get_dynamic_limit)
async def get_event_counts(
    request: Request,
    indexer: SecurityEventIndexer = Depends(_get_indexer),
) -> SecurityEventCountsResponse:
    """Get event counts by type."""
    try:
        counts = indexer.get_event_counts()
        total = sum(counts.values())
        return SecurityEventCountsResponse(counts=counts, total=total)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get event counts: {str(e)}")


@router.get(
    "/counts/severity",
    response_model=SecurityEventCountsResponse,
    responses={500: {"model": ErrorResponse}},
    summary="Get security event counts by severity",
    description="Get a summary count of security events grouped by severity level.",
)
@limiter.limit(get_dynamic_limit)
async def get_event_counts_by_severity(
    request: Request,
    indexer: SecurityEventIndexer = Depends(_get_indexer),
) -> SecurityEventCountsResponse:
    """Get event counts by severity."""
    try:
        counts = indexer.get_event_counts_by_severity()
        total = sum(counts.values())
        return SecurityEventCountsResponse(counts=counts, total=total)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get severity counts: {str(e)}")
