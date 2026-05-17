"""Named map (nmap) endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Request

from subnet.api.auth.dependencies import limiter
from subnet.api.auth.ratelimit import get_dynamic_limit
from subnet.api.dependencies import get_db
from subnet.api.models import ErrorResponse, NMapListResponse, NMapNamesResponse, NMapResponse
from subnet.utils.db.database import RocksDB

router = APIRouter(prefix="/nmaps", tags=["nmaps"])


@router.get(
    "",
    response_model=NMapNamesResponse,
    responses={500: {"model": ErrorResponse}},
    summary="List all named maps",
    description="Get a list of all named map names in the database",
)
@limiter.limit(get_dynamic_limit)
async def list_nmaps(
    request: Request,
    db: RocksDB = Depends(get_db),
) -> NMapNamesResponse:
    """
    List all named map names.

    This scans the database for all keys with the 'nmap:' prefix and extracts
    unique named map names.

    Args:
        request: The FastAPI request object
        db: Database dependency

    Returns:
        NMapNamesResponse with list of named map names

    """
    try:
        # Get all keys and extract unique nmap names
        nmap_names = set()
        prefix = f"nmap{db.SEPARATOR}"

        for key in db.store.keys():
            if isinstance(key, str) and key.startswith(prefix):
                # Extract nmap name (between first and second separator)
                remaining = key[len(prefix) :]
                if db.SEPARATOR in remaining:
                    nmap_name = remaining.split(db.SEPARATOR)[0]
                    nmap_names.add(nmap_name)

        nmap_list = sorted(list(nmap_names))

        return NMapNamesResponse(
            nmaps=nmap_list,
            total=len(nmap_list),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list named maps: {str(e)}")


@router.get(
    "/{nmap_name}",
    response_model=NMapListResponse,
    responses={500: {"model": ErrorResponse}},
    summary="Get all entries in a named map",
    description="Get all key-value pairs in a specific named map",
)
@limiter.limit(get_dynamic_limit)
async def get_nmap_entries(
    request: Request,
    nmap_name: str,
    db: RocksDB = Depends(get_db),
) -> NMapListResponse:
    """
    Get all entries in a named map.

    Args:
        request: The FastAPI request object
        nmap_name: The name of the named map
        db: Database dependency

    Returns:
        NMapListResponse with all entries in the named map

    """
    try:
        entries = db.nmap_get_all(nmap_name)

        return NMapListResponse(
            nmap=nmap_name,
            entries=entries,
            total=len(entries),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get named map entries: {str(e)}")


@router.get(
    "/{nmap_name}/{key:path}",
    response_model=NMapResponse,
    responses={404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    summary="Get specific entry in a named map",
    description="Get a specific key-value pair from a named map (supports composite keys with ':')",
)
@limiter.limit(get_dynamic_limit)
async def get_nmap_entry(
    request: Request,
    nmap_name: str,
    key: str,
    db: RocksDB = Depends(get_db),
) -> NMapResponse:
    """
    Get a specific entry from a named map.

    Supports composite keys (e.g., 'subnet_1:node_5').

    Args:
        request: The FastAPI request object
        nmap_name: The name of the named map
        key: The key within the named map (can include ':' for composite keys)
        db: Database dependency

    Returns:
        NMapResponse with the entry data

    Raises:
        HTTPException: 404 if entry not found, 500 on other errors

    """
    try:
        value = db.nmap_get(nmap_name, key)

        if value is None:
            raise HTTPException(
                status_code=404,
                detail=f"Entry '{key}' not found in named map '{nmap_name}'",
            )

        return NMapResponse(
            nmap=nmap_name,
            key=key,
            value=value,
            exists=True,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get named map entry: {str(e)}")
