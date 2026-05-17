"""API configuration and settings management."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    API configuration settings.

    All settings can be overridden via environment variables with the API_ prefix.
    Example: API_DB_PATH=/path/to/db API_PORT=9000
    """

    # Database configuration
    db_path: str = "/tmp/bootstrap"
    db_read_only: bool = True

    # Auth and Rate Limiting
    auth_db_path: str = "/tmp/auth_db"
    enable_auth: bool = True
    default_qpm: int = 60  # Default queries per minute per key

    # API server configuration
    host: str = "127.0.0.1"
    port: int = 8000
    reload: bool = False

    # API metadata
    title: str = "RocksDB API"
    description: str = "Production-ready API for querying RocksDB database"
    version: str = "1.0.0"
    api_prefix: str = "/api"

    # CORS configuration
    cors_origins: list[str] = ["*"]
    cors_credentials: bool = True
    cors_methods: list[str] = ["GET", "HEAD", "OPTIONS"]
    cors_headers: list[str] = ["*"]

    # Pagination defaults
    default_page_size: int = 100
    max_page_size: int = 1000

    model_config = SettingsConfigDict(
        env_prefix="API_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # Ignore extra fields from .env file
    )


# Global settings instance
settings = Settings()
