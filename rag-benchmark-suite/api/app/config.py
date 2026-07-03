"""Settings for the RAG Benchmark Suite — a standalone service that drives the
existing DocuMind API through every rag_mode and records comparable metrics.

Nothing here talks to AWS/Bedrock directly: all LLM calls happen inside the
main DocuMind backend. This service is an orchestrator + results store.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="BENCHMARK_", extra="ignore")

    # This service's own Postgres (separate from DocuMind's DB)
    database_url: str = "postgresql+asyncpg://benchmark:benchmark@localhost:5441/rag_benchmark"

    # The existing DocuMind app this service drives via its public API
    documind_api_base_url: str = "http://localhost:8010"
    documind_admin_email: str = ""
    documind_admin_password: str = ""

    # Dataset access — folder path must be visible inside this container (mount it),
    # S3 access relies on the ambient AWS credential chain (profile/role), never
    # hardcoded keys, in line with Minfy's data-handling rules.
    dataset_root: str = "/data"

    # Confluence Cloud (REST API, basic auth with an API token — never a password)
    confluence_base_url: str = ""  # e.g. https://your-domain.atlassian.net
    confluence_email: str = ""
    confluence_api_token: str = ""

    # Google Drive — service account, suited to a headless backend job (no interactive
    # OAuth consent screen). Share the target folder with the service account's email.
    gdrive_service_account_json: str = ""  # path to the key file, mounted read-only

    # SharePoint / OneDrive via Microsoft Graph — app-only auth (client credentials).
    # Requires an Azure AD app registration with admin-consented Sites.Read.All.
    azure_tenant_id: str = ""
    azure_client_id: str = ""
    azure_client_secret: str = ""

    # Polling behaviour while waiting on the async DocuMind pipeline
    poll_interval_seconds: float = 3.0
    ingestion_timeout_seconds: int = 900
    eval_timeout_seconds: int = 180

    # Draft question generation reuses DocuMind's own chat pipeline against a
    # throwaway pageindex KB (see question_gen.py) instead of this suite having
    # its own LLM credentials. It's a synchronous, user-facing call from the
    # New Run page, so it gets a shorter ingestion timeout than a full run.
    question_gen_ingestion_timeout_seconds: int = 300
    question_gen_default_count: int = 8

    cors_origins: str = "http://localhost:5190"
    port: int = 8020


@lru_cache
def get_settings() -> Settings:
    return Settings()
