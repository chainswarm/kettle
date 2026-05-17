from fastapi import APIRouter, Depends, HTTPException, Query, Request

from subnet.api.auth.dependencies import limiter
from subnet.api.auth.ratelimit import get_dynamic_limit
from subnet.api.config import settings
from subnet.api.dependencies import get_db
from subnet.api.models import (
    ErrorResponse,
    KeyListResponse,
    KeyValueResponse,
    NestedKeyListResponse,
    NestedKeyResponse,
)
from subnet.utils.db.database import RocksDB

router = APIRouter(prefix="/keys", tags=["keys"])


@router.get(
    "",
    response_model=KeyListResponse,
    responses={500: {"model": ErrorResponse}},
    summary="List all keys",
    description="Get a paginated list of all keys in the database",
)
@limiter.limit(get_dynamic_limit)
async def list_keys(
    request: Request,
    offset: int = Query(0, ge=0, description="Pagination offset"),
    limit: int = Query(
        settings.default_page_size,
        ge=1,
        le=settings.max_page_size,
        description="Maximum number of keys to return",
    ),
    db: RocksDB = Depends(get_db),
) -> KeyListResponse:
    """
    List all keys in the database with pagination.

    Args:
        request: The FastAPI request object
        offset: Pagination offset (default: 0)
        limit: Maximum number of keys to return (default: 100, max: 1000)
        db: Database dependency

    Returns:
        KeyListResponse with paginated keys

    """
    try:
        # Get all keys
        all_keys = [k for k in db.store.keys() if isinstance(k, str)]

        # Apply pagination
        paginated_keys = all_keys[offset : offset + limit]

        return KeyListResponse(
            keys=paginated_keys,
            total=len(all_keys),
            offset=offset,
            limit=limit,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list keys: {str(e)}")


@router.get(
    "/{key}",
    response_model=KeyValueResponse,
    responses={404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    summary="Get value by key",
    description="Get the value for a specific key",
)
@limiter.limit(get_dynamic_limit)
async def get_key(
    request: Request,
    key: str,
    db: RocksDB = Depends(get_db),
) -> KeyValueResponse:
    """
    Get the value for a specific key.

    Args:
        request: The FastAPI request object
        key: The key to retrieve
        db: Database dependency

    Returns:
        KeyValueResponse with the key and value

    Raises:
        HTTPException: 404 if key not found, 500 on other errors

    """
    try:
        value = db.get(key)

        if value is None:
            raise HTTPException(
                status_code=404,
                detail=f"Key '{key}' not found",
            )

        return KeyValueResponse(
            key=key,
            value=value,
            exists=True,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get key: {str(e)}")


@router.get(
    "/nested/{k1}",
    response_model=NestedKeyListResponse,
    responses={500: {"model": ErrorResponse}},
    summary="Get all nested keys under k1",
    description="Get all k2 keys and values under a given k1 key",
)
@limiter.limit(get_dynamic_limit)
async def get_nested_keys(
    request: Request,
    k1: str,
    recursive: bool = Query(False, description="Include all nested levels recursively"),
    db: RocksDB = Depends(get_db),
) -> NestedKeyListResponse:
    """
    Get all nested keys under k1.

    Args:
        request: The FastAPI request object
        k1: The first level key
        recursive: If True, include all nested levels; if False, only direct children
        db: Database dependency

    Returns:
        NestedKeyListResponse with all nested keys and values

    """
    try:
        if recursive:
            children = db.get_all_under_key_recursive(k1)
        else:
            children = db.get_all_under_key(k1)

        return NestedKeyListResponse(
            k1=k1,
            children=children,
            total=len(children),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get nested keys: {str(e)}")


@router.get(
    "/nested/{k1}/{k2}",
    response_model=NestedKeyResponse,
    responses={404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    summary="Get nested key value",
    description="Get the value for a specific nested key (k1:k2)",
)
@limiter.limit(get_dynamic_limit)
async def get_nested_key(
    request: Request,
    k1: str,
    k2: str,
    db: RocksDB = Depends(get_db),
) -> NestedKeyResponse:
    """
    Get the value for a nested key.

    Args:
        request: The FastAPI request object
        k1: The first level key
        k2: The second level key
        db: Database dependency

    Returns:
        NestedKeyResponse with the nested key and value

    Raises:
        HTTPException: 404 if key not found, 500 on other errors

    """
    try:
        value = db.get_nested(k1, k2)

        if value is None:
            raise HTTPException(
                status_code=404,
                detail=f"Nested key '{k1}:{k2}' not found",
            )

        return NestedKeyResponse(
            k1=k1,
            k2=k2,
            value=value,
            exists=True,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get nested key: {str(e)}")
