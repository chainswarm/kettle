"""FastAPI dependencies for database access."""

from contextlib import asynccontextmanager
import os
from typing import AsyncGenerator

from rocksdict import AccessType, Rdict

from subnet.api.config import settings
from subnet.utils.db.database import RocksDB


class DatabaseManager:
    """
    Singleton database manager for read-only RocksDB access.

    This manager ensures only one database connection is created and shared
    across all API requests.
    """

    _instance: RocksDB | None = None
    _raw_store: Rdict | None = None

    @classmethod
    def initialize(cls) -> None:
        """Initialize the database connection in read-only mode."""
        if cls._instance is not None:
            return

        db_path = settings.db_path
        if not os.path.exists(f"{db_path}_store"):
            raise FileNotFoundError(f"Database not found at {db_path}_store")

        # Open RocksDB in read-only mode for safe concurrent access
        cls._raw_store = Rdict(
            f"{db_path}_store",
            access_type=AccessType.read_only(),
        )

        # Create a RocksDB wrapper instance
        # We'll manually set the store to our read-only instance
        cls._instance = RocksDB.__new__(RocksDB)
        cls._instance.base_path = db_path
        cls._instance.db_path = f"{db_path}_store"
        cls._instance.store = cls._raw_store
        cls._instance.SEPARATOR = ":"

    @classmethod
    def get_db(cls) -> RocksDB:
        """Get the database instance."""
        if cls._instance is None:
            raise RuntimeError("Database not initialized. Call initialize() first.")
        return cls._instance

    @classmethod
    def close(cls) -> None:
        """Close the database connection."""
        if cls._raw_store is not None:
            cls._raw_store.close()
            cls._raw_store = None
            cls._instance = None


@asynccontextmanager
async def lifespan_manager(app) -> AsyncGenerator[None, None]:
    """
    Lifespan context manager for FastAPI application.

    Handles database initialization on startup and cleanup on shutdown.
    """
    # Startup: Initialize database
    DatabaseManager.initialize()
    yield
    # Shutdown: Close database
    DatabaseManager.close()


def get_db() -> RocksDB:
    """
    FastAPI dependency for getting the database instance.

    Usage:
        @app.get("/endpoint")
        async def endpoint(db: RocksDB = Depends(get_db)):
            return db.get("key")
    """
    return DatabaseManager.get_db()
