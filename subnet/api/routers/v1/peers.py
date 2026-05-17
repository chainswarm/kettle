from fastapi import APIRouter, Depends, HTTPException, Query, Request

from subnet.api.auth.dependencies import limiter
from subnet.api.auth.ratelimit import get_dynamic_limit
from subnet.api.config import settings
from subnet.api.dependencies import get_db
from subnet.api.models import ErrorResponse, PeerListResponse, PeerResponse
from subnet.utils.db.database import RocksDB

router = APIRouter(prefix="/peers", tags=["peers"])


@router.get(
    "",
    response_model=PeerListResponse,
    responses={500: {"model": ErrorResponse}},
    summary="List all peers",
    description="Get all peer IDs and their data from the 'peers' named map",
)
@limiter.limit(get_dynamic_limit)
async def list_peers(
    request: Request,
    offset: int = Query(0, ge=0, description="Pagination offset"),
    limit: int = Query(
        settings.default_page_size,
        ge=1,
        le=settings.max_page_size,
        description="Maximum number of peers to return",
    ),
    db: RocksDB = Depends(get_db),
) -> PeerListResponse:
    """
    List all peers stored in the 'peers' named map.

    Args:
        request: The FastAPI request object
        offset: Pagination offset (default: 0)
        limit: Maximum number of peers to return (default: 100, max: 1000)
        db: Database dependency

    Returns:
        PeerListResponse with peer data and pagination info

    """
    try:
        # Get all peers from the 'peers' named map
        all_peers = db.nmap_get_all("peers")

        # Apply pagination
        peer_items = list(all_peers.items())
        paginated_peers = dict(peer_items[offset : offset + limit])

        return PeerListResponse(
            peers=paginated_peers,
            total=len(all_peers),
            offset=offset,
            limit=limit,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list peers: {str(e)}")


@router.get(
    "/{peer_id}",
    response_model=PeerResponse,
    responses={404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    summary="Get peer by ID",
    description="Get data for a specific peer ID from the 'peers' named map",
)
@limiter.limit(get_dynamic_limit)
async def get_peer(
    request: Request,
    peer_id: str,
    db: RocksDB = Depends(get_db),
) -> PeerResponse:
    """
    Get data for a specific peer.

    Args:
        request: The FastAPI request object
        peer_id: The peer ID to retrieve
        db: Database dependency

    Returns:
        PeerResponse with peer data

    Raises:
        HTTPException: 404 if peer not found, 500 on other errors

    """
    try:
        # Get peer data from the 'peers' named map
        peer_data = db.nmap_get("peers", peer_id)

        if peer_data is None:
            raise HTTPException(
                status_code=404,
                detail=f"Peer '{peer_id}' not found",
            )

        return PeerResponse(
            peer_id=peer_id,
            data=peer_data,
            exists=True,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get peer: {str(e)}")
