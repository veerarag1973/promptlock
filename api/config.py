"""API configuration — read from environment variables."""

from __future__ import annotations

import os


class Settings:
    database_url: str = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://promptlock:promptlock_dev@localhost:5432/promptlock",
    )
    redis_url: str = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

    # Object storage (S3 / MinIO)
    s3_endpoint_url: str = os.environ.get("S3_ENDPOINT_URL", "http://localhost:9000")
    s3_access_key: str = os.environ.get("S3_ACCESS_KEY", "minioadmin")
    s3_secret_key: str = os.environ.get("S3_SECRET_KEY", "minioadmin_dev")
    s3_bucket: str = os.environ.get("S3_BUCKET", "promptlock-objects")

    # JWT
    jwt_secret: str = os.environ.get("JWT_SECRET", "CHANGE_ME")
    jwt_algorithm: str = os.environ.get("JWT_ALGORITHM", "HS256")
    jwt_expire_minutes: int = int(os.environ.get("JWT_EXPIRE_MINUTES", "60"))

    # Runtime
    environment: str = os.environ.get("ENVIRONMENT", "development")
    log_level: str = os.environ.get("LOG_LEVEL", "info")
    api_version: str = os.environ.get("PROMPTLOCK_API_VERSION", "0.4.0")

    # Audit signing key (HMAC — rotate per org in production)
    audit_signing_key: str = os.environ.get("AUDIT_SIGNING_KEY", "audit-dev-secret")


settings = Settings()
