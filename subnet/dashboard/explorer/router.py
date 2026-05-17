"""Explorer API router with endpoints for security events, epochs, nodes, audit, and search."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request

from subnet.dashboard.explorer.indexer import EventIndexer
from subnet.dashboard.explorer.models import EventType, Severity


def _get_indexer(request: Request) -> EventIndexer:
    """Get an EventIndexer backed by the app's RocksDB instance."""
    db = getattr(request.app.state, "db", None)
    if db is None:
        raise HTTPException(status_code=503, detail="Database not available")
    return EventIndexer(db)


def create_explorer_router() -> APIRouter:
    """Create the explorer API router."""
    router = APIRouter(prefix="/api/explorer", tags=["explorer"])

    @router.get("/events")
    async def query_events(
        request: Request,
        epoch_min: Optional[int] = Query(default=None, description="Minimum epoch (inclusive)"),
        epoch_max: Optional[int] = Query(default=None, description="Maximum epoch (inclusive)"),
        peer_id: Optional[str] = Query(default=None, description="Filter by peer ID"),
        event_type: Optional[EventType] = Query(default=None, description="Filter by event type"),
        severity: Optional[Severity] = Query(default=None, description="Filter by severity"),
        limit: int = Query(default=100, ge=1, le=500, description="Max results"),
        offset: int = Query(default=0, ge=0, description="Offset for pagination"),
    ):
        """Query security events with filters (EXP-01).

        Supports filtering by epoch range, peer_id, event_type, and severity.
        Results are sorted by epoch descending.
        """
        indexer = _get_indexer(request)
        items, total = indexer.query_events(
            epoch_min=epoch_min,
            epoch_max=epoch_max,
            peer_id=peer_id,
            event_type=event_type,
            severity=severity,
            limit=limit,
            offset=offset,
        )
        return {
            "items": [item.model_dump() for item in items],
            "total": total,
            "offset": offset,
            "limit": limit,
        }

    @router.get("/epochs")
    async def epoch_history(
        request: Request,
        epoch_min: Optional[int] = Query(default=None, description="Minimum epoch"),
        epoch_max: Optional[int] = Query(default=None, description="Maximum epoch"),
    ):
        """Epoch history with per-epoch summaries (EXP-02).

        Returns node count, event counts by type, scores, and tamper detection
        for each epoch in the range.
        """
        indexer = _get_indexer(request)
        summaries = indexer.epoch_summaries(epoch_min=epoch_min, epoch_max=epoch_max)
        return {"epochs": [s.model_dump() for s in summaries]}

    @router.get("/epochs/{epoch}")
    async def epoch_detail(
        request: Request,
        epoch: int,
    ):
        """Single epoch detail (EXP-02).

        Returns detailed summary for a specific epoch including node count,
        event breakdown, scores, and tamper status.
        """
        indexer = _get_indexer(request)
        summary = indexer.epoch_detail(epoch)
        if summary is None:
            raise HTTPException(status_code=404, detail=f"No events found for epoch {epoch}")
        return summary.model_dump()

    @router.get("/nodes/{peer_id}/history")
    async def node_history(
        request: Request,
        peer_id: str,
        limit: int = Query(default=100, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
    ):
        """All events for a specific node (EXP-03).

        Returns the full event history for a peer_id, sorted by epoch descending.
        """
        indexer = _get_indexer(request)
        items, total = indexer.node_history(peer_id, limit=limit, offset=offset)
        if total == 0:
            raise HTTPException(status_code=404, detail=f"No events found for node {peer_id}")
        return {
            "peer_id": peer_id,
            "items": [item.model_dump() for item in items],
            "total": total,
            "offset": offset,
            "limit": limit,
        }

    @router.get("/audit")
    async def audit_log(
        request: Request,
        epoch_min: Optional[int] = Query(default=None),
        epoch_max: Optional[int] = Query(default=None),
        peer_id: Optional[str] = Query(default=None),
        limit: int = Query(default=100, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
    ):
        """Overwatch audit log with slash history and tamper evidence (EXP-04).

        Returns audit entries from overwatch work record verification,
        including pass/fail/tampered results and evidence data.
        """
        indexer = _get_indexer(request)
        items, total = indexer.audit_log(
            epoch_min=epoch_min,
            epoch_max=epoch_max,
            peer_id=peer_id,
            limit=limit,
            offset=offset,
        )
        return {
            "items": [item.model_dump() for item in items],
            "total": total,
            "offset": offset,
            "limit": limit,
        }

    @router.get("/search")
    async def search(
        request: Request,
        q: str = Query(description="Search query (peer_id, epoch, event_type, hardware_id)"),
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ):
        """Search across events by peer_id, epoch, event_type, or hardware_id (EXP-05).

        Matches peer_id and hardware_id by substring, epoch by exact match,
        and event_type by substring. Results sorted by relevance and recency.
        """
        indexer = _get_indexer(request)
        results, total = indexer.search(query=q, limit=limit, offset=offset)
        return {
            "items": [
                {"match_type": r["match_type"], "event": r["event"].model_dump()}
                for r in results
            ],
            "total": total,
            "offset": offset,
            "limit": limit,
        }

    return router
