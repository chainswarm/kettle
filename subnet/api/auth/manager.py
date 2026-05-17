"""API key authentication manager."""

from datetime import datetime, timezone
import hashlib
import secrets
from typing import Optional

from rocksdict import Rdict

from subnet.api.config import settings
from subnet.api.models import APIKeyMetadata


class AuthManager:
    """
    Manager for API key authentication using a dedicated RocksDB.
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or settings.auth_db_path
        # We don't use the wrapper class because we need read-write access
        # for management and potentially rate limit state if persistent.
        self.store = Rdict(f"{self.db_path}_store")

    def _hash_key(self, api_key: str) -> str:
        """Hash the API key for safe storage."""
        return hashlib.sha256(api_key.encode()).hexdigest()

    def create_key(self, owner: str, qpm_limit: Optional[int] = None) -> str:
        """
        Generate and store a new API key.
        Returns the raw key (only shown once).
        """
        raw_key = f"st_{secrets.token_urlsafe(32)}"
        key_hash = self._hash_key(raw_key)

        metadata = APIKeyMetadata(
            owner=owner,
            qpm_limit=qpm_limit or settings.default_qpm,
            is_active=True,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

        self.store[key_hash] = metadata.model_dump()
        return raw_key

    def revoke_key(self, api_key_hash: str) -> bool:
        """Deactivate an API key by its hash."""
        if api_key_hash not in self.store:
            return False

        data = self.store[api_key_hash]
        metadata = APIKeyMetadata(**data)
        metadata.is_active = False
        self.store[api_key_hash] = metadata.model_dump()
        return True

    def get_metadata(self, api_key: str) -> Optional[APIKeyMetadata]:
        """Retrieve metadata for a raw API key."""
        key_hash = self._hash_key(api_key)
        data = self.store.get(key_hash)
        if data:
            return APIKeyMetadata(**data)
        return None

    def get_metadata_by_hash(self, api_key_hash: str) -> Optional[APIKeyMetadata]:
        """Retrieve metadata by key hash."""
        data = self.store.get(api_key_hash)
        if data:
            return APIKeyMetadata(**data)
        return None

    def list_keys(self) -> dict[str, APIKeyMetadata]:
        """List all keys and their metadata."""
        results = {}
        for h, v in self.store.items():
            if isinstance(h, str):
                results[h] = APIKeyMetadata(**v)
        return results

    def close(self):
        """Close the database."""
        self.store.close()
