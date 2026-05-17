"""Pydantic models for API request/response validation."""

from typing import Any

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Health check response model."""

    status: str = Field(..., description="Health status of the API")
    db_path: str = Field(..., description="Path to the RocksDB database")
    db_accessible: bool = Field(..., description="Whether the database is accessible")
    timestamp: str = Field(..., description="Current server timestamp")


class MetricsResponse(BaseModel):
    """Metrics response model."""

    total_keys: int = Field(..., description="Total number of keys in the database")
    db_size_bytes: int = Field(..., description="Database size in bytes")
    uptime_seconds: float = Field(..., description="API uptime in seconds")


class KeyValueResponse(BaseModel):
    """Response model for key-value queries."""

    key: str = Field(..., description="The key")
    value: Any = Field(..., description="The value associated with the key")
    exists: bool = Field(True, description="Whether the key exists")


class KeyListResponse(BaseModel):
    """Response model for listing keys."""

    keys: list[str] = Field(..., description="List of keys")
    total: int = Field(..., description="Total number of keys")
    offset: int = Field(..., description="Offset used for pagination")
    limit: int = Field(..., description="Limit used for pagination")


class NestedKeyResponse(BaseModel):
    """Response model for nested key queries."""

    k1: str = Field(..., description="First level key")
    k2: str | None = Field(None, description="Second level key (if applicable)")
    value: Any = Field(..., description="The value")
    exists: bool = Field(True, description="Whether the key exists")


class NestedKeyListResponse(BaseModel):
    """Response model for listing nested keys."""

    k1: str = Field(..., description="First level key")
    children: dict[str, Any] = Field(..., description="Dictionary of k2: value pairs")
    total: int = Field(..., description="Total number of children")


class NMapResponse(BaseModel):
    """Response model for named map queries."""

    nmap: str = Field(..., description="Named map name")
    key: str = Field(..., description="Key within the named map")
    value: Any = Field(..., description="The value")
    exists: bool = Field(True, description="Whether the entry exists")


class NMapListResponse(BaseModel):
    """Response model for listing named map entries."""

    nmap: str = Field(..., description="Named map name")
    entries: dict[str, Any] = Field(..., description="Dictionary of key: value pairs")
    total: int = Field(..., description="Total number of entries")


class NMapNamesResponse(BaseModel):
    """Response model for listing named map names."""

    nmaps: list[str] = Field(..., description="List of named map names")
    total: int = Field(..., description="Total number of named maps")


class PeerResponse(BaseModel):
    """Response model for peer queries."""

    peer_id: str = Field(..., description="Peer ID")
    data: Any = Field(..., description="Peer data")
    exists: bool = Field(True, description="Whether the peer exists")


class PeerListResponse(BaseModel):
    """Response model for listing peers."""

    peers: dict[str, Any] = Field(..., description="Dictionary of peer_id: data pairs")
    total: int = Field(..., description="Total number of peers")
    offset: int = Field(..., description="Offset used for pagination")
    limit: int = Field(..., description="Limit used for pagination")


class APIKeyMetadata(BaseModel):
    """Metadata model for stored API keys."""

    owner: str = Field(..., description="Owner of the API key")
    qpm_limit: int = Field(60, description="Rate limit (queries per minute)")
    is_active: bool = Field(True, description="Whether the key is active")
    created_at: str = Field(..., description="Creation timestamp")


class SecurityEventResponse(BaseModel):
    """Response model for a list of security events."""

    events: list[dict[str, Any]] = Field(..., description="List of security event records")
    total: int = Field(..., description="Number of events returned")


class SecurityEventCountsResponse(BaseModel):
    """Response model for security event counts."""

    counts: dict[str, int] = Field(..., description="Event counts by category")
    total: int = Field(..., description="Total number of events")


class ErrorResponse(BaseModel):
    """Error response model."""

    error: str = Field(..., description="Error message")
    detail: str | None = Field(None, description="Detailed error information")
