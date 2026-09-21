"""Application settings, sourced exclusively from environment variables.

No secret ever has a real default here — anything security-sensitive
defaults to an obviously-fake value so a misconfigured deployment fails
loudly (auth errors, refused S3 calls) instead of silently trusting a
committed secret.
"""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: Literal["local", "test", "ci", "production"] = "local"

    # --- Database ---
    database_url: str = "postgresql+psycopg://compliance:compliance@localhost:5432/compliance"

    # --- Auth / JWT ---
    jwt_secret_key: str = "CHANGE-ME-INSECURE-DEV-SECRET"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60

    # --- Object storage (S3 / LocalStack) ---
    s3_bucket_name: str = "compliance-reports"
    s3_region: str = "us-east-1"
    s3_endpoint_url: str | None = None  # set to LocalStack URL for local/demo use
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None

    # --- Local export fallback (always written, S3 upload is best-effort) ---
    reports_local_dir: str = "./report_exports"

    # --- Ingestion limits ---
    max_upload_size_bytes: int = 25 * 1024 * 1024  # 25 MB
    max_transactions_per_batch: int = 200_000

    # --- Logging ---
    log_level: str = "INFO"

    @property
    def is_test(self) -> bool:
        return self.environment in ("test", "ci")


@lru_cache
def get_settings() -> Settings:
    return Settings()
