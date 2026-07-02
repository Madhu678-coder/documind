from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator
from typing import Optional, Union

# .env lives at the repo root, one level above the backend/ directory
_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        case_sensitive=False,
        env_ignore_empty=True,
        extra="ignore",
    )

    # Database
    database_url: str
    # Redis
    redis_url: str
    celery_broker_url: str
    celery_result_backend: str
    # Security
    secret_key: str
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    # AWS
    aws_profile: Optional[str] = None  # local dev only — leave unset to use env var credentials
    aws_region: str = "us-east-1"
    aws_bedrock_region: str = "us-east-1"  # Bedrock region (can differ from S3)
    aws_endpoint_url: Optional[str] = None  # set to http://localstack:4566 in dev

    @field_validator("aws_profile", mode="before")
    @classmethod
    def empty_str_to_none(cls, v):
        """Convert empty string to None so boto3 doesn't try to use a blank profile."""
        if isinstance(v, str) and not v.strip():
            return None
        return v
    # S3
    s3_bucket: str
    # Neo4j
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "documind123"
    # CORS — accepts comma-separated string or JSON list
    cors_origins: Union[list[str], str] = ["http://localhost:3000", "http://localhost:5173"]
    # Rate limiting
    rate_limit_per_minute: int = 60
    # Logging
    log_level: str = "INFO"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v):
        if isinstance(v, str):
            v = v.strip().strip("[]")
            return [o.strip().strip('"').strip("'") for o in v.split(",") if o.strip()]
        return v


settings = Settings()
