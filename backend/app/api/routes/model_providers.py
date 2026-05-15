"""Model Provider Config CRUD API endpoints."""
from __future__ import annotations

import uuid
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.model_provider import ModelProviderConfig
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/model-providers", tags=["model-providers"])

_VALID_PROVIDER_TYPES = {"llm", "embedding", "rerank"}


# ── Schemas ───────────────────────────────────────────────────────────────────

class ModelProviderCreate(BaseModel):
    provider_type: str  # llm | embedding | rerank
    provider_name: str  # bedrock | openai | cohere
    model_id: str
    api_key: Optional[str] = None
    region: Optional[str] = None
    extra_config: dict = {}
    is_default: bool = False


class ModelProviderUpdate(BaseModel):
    provider_name: Optional[str] = None
    model_id: Optional[str] = None
    api_key: Optional[str] = None
    region: Optional[str] = None
    extra_config: Optional[dict] = None
    is_default: Optional[bool] = None


class ModelProviderOut(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    provider_type: str
    provider_name: str
    model_id: str
    region: Optional[str]
    extra_config: dict
    is_default: bool
    created_at: datetime
    # NOTE: api_key is intentionally excluded for security

    model_config = {"from_attributes": True}


class SetDefaultsRequest(BaseModel):
    llm: Optional[uuid.UUID] = None
    embedding: Optional[uuid.UUID] = None
    rerank: Optional[uuid.UUID] = None


# ── Helpers ────────────────────────────────────────────────────────────────────

def _to_out(p: ModelProviderConfig) -> ModelProviderOut:
    return ModelProviderOut(
        id=p.id,
        workspace_id=p.workspace_id,
        provider_type=p.provider_type,
        provider_name=p.provider_name,
        model_id=p.model_id,
        region=p.region,
        extra_config=p.extra_config or {},
        is_default=p.is_default,
        created_at=p.created_at,
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("", response_model=list[ModelProviderOut])
async def list_model_providers(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all model provider configs for the current workspace."""
    result = await db.execute(
        select(ModelProviderConfig)
        .where(ModelProviderConfig.workspace_id == current_user.workspace_id)
        .order_by(ModelProviderConfig.created_at.asc())
    )
    return [_to_out(p) for p in result.scalars().all()]


@router.post("", status_code=status.HTTP_201_CREATED, response_model=ModelProviderOut)
async def create_model_provider(
    body: ModelProviderCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new model provider config."""
    if body.provider_type not in _VALID_PROVIDER_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"provider_type must be one of: {', '.join(sorted(_VALID_PROVIDER_TYPES))}",
        )

    # If setting as default, unset other defaults of same type first
    if body.is_default:
        existing_defaults = await db.execute(
            select(ModelProviderConfig).where(
                ModelProviderConfig.workspace_id == current_user.workspace_id,
                ModelProviderConfig.provider_type == body.provider_type,
                ModelProviderConfig.is_default == True,
            )
        )
        for p in existing_defaults.scalars().all():
            p.is_default = False

    provider = ModelProviderConfig(
        workspace_id=current_user.workspace_id,
        provider_type=body.provider_type,
        provider_name=body.provider_name,
        model_id=body.model_id,
        api_key=body.api_key,
        region=body.region,
        extra_config=body.extra_config or {},
        is_default=body.is_default,
    )
    db.add(provider)
    await db.commit()
    await db.refresh(provider)
    return _to_out(provider)


@router.get("/defaults")
async def get_defaults(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return workspace default providers per type."""
    result = await db.execute(
        select(ModelProviderConfig).where(
            ModelProviderConfig.workspace_id == current_user.workspace_id,
            ModelProviderConfig.is_default == True,
        )
    )
    defaults: dict[str, ModelProviderOut | None] = {"llm": None, "embedding": None, "rerank": None}
    for p in result.scalars().all():
        defaults[p.provider_type] = _to_out(p)
    return defaults


@router.put("/defaults")
async def set_defaults(
    body: SetDefaultsRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Set the default provider for each type."""
    updates: dict[str, uuid.UUID | None] = {
        "llm": body.llm,
        "embedding": body.embedding,
        "rerank": body.rerank,
    }

    for provider_type, provider_id in updates.items():
        if provider_id is None:
            continue

        # Unset current defaults for this type
        existing_defaults = await db.execute(
            select(ModelProviderConfig).where(
                ModelProviderConfig.workspace_id == current_user.workspace_id,
                ModelProviderConfig.provider_type == provider_type,
                ModelProviderConfig.is_default == True,
            )
        )
        for p in existing_defaults.scalars().all():
            p.is_default = False

        # Set the new default
        new_default = await db.execute(
            select(ModelProviderConfig).where(
                ModelProviderConfig.id == provider_id,
                ModelProviderConfig.workspace_id == current_user.workspace_id,
            )
        )
        p = new_default.scalar_one_or_none()
        if p:
            p.is_default = True

    await db.commit()
    return {"message": "Defaults updated"}


@router.put("/{provider_id}", response_model=ModelProviderOut)
async def update_model_provider(
    provider_id: uuid.UUID,
    body: ModelProviderUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a model provider config."""
    result = await db.execute(
        select(ModelProviderConfig).where(
            ModelProviderConfig.id == provider_id,
            ModelProviderConfig.workspace_id == current_user.workspace_id,
        )
    )
    provider = result.scalar_one_or_none()
    if provider is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider not found")

    if body.provider_name is not None:
        provider.provider_name = body.provider_name
    if body.model_id is not None:
        provider.model_id = body.model_id
    if body.api_key is not None:
        provider.api_key = body.api_key
    if body.region is not None:
        provider.region = body.region
    if body.extra_config is not None:
        provider.extra_config = body.extra_config
    if body.is_default is not None:
        if body.is_default:
            # Unset other defaults of same type
            existing_defaults = await db.execute(
                select(ModelProviderConfig).where(
                    ModelProviderConfig.workspace_id == current_user.workspace_id,
                    ModelProviderConfig.provider_type == provider.provider_type,
                    ModelProviderConfig.is_default == True,
                    ModelProviderConfig.id != provider_id,
                )
            )
            for p in existing_defaults.scalars().all():
                p.is_default = False
        provider.is_default = body.is_default

    await db.commit()
    await db.refresh(provider)
    return _to_out(provider)


@router.delete("/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_model_provider(
    provider_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a model provider config."""
    result = await db.execute(
        select(ModelProviderConfig).where(
            ModelProviderConfig.id == provider_id,
            ModelProviderConfig.workspace_id == current_user.workspace_id,
        )
    )
    provider = result.scalar_one_or_none()
    if provider is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider not found")

    await db.delete(provider)
    await db.commit()


@router.post("/{provider_id}/test")
async def test_model_provider(
    provider_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Test a model provider config by making a sample call."""
    result = await db.execute(
        select(ModelProviderConfig).where(
            ModelProviderConfig.id == provider_id,
            ModelProviderConfig.workspace_id == current_user.workspace_id,
        )
    )
    provider = result.scalar_one_or_none()
    if provider is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider not found")

    try:
        if provider.provider_type == "embedding":
            from app.services.embedding.factory import EmbeddingFactory
            emb = EmbeddingFactory.create(
                provider.provider_name,
                provider.model_id,
                api_key=provider.api_key,
                region=provider.region,
            )
            result_emb = await emb.embed_texts(["test"])
            return {
                "success": True,
                "provider_type": provider.provider_type,
                "model": provider.model_id,
                "dimensions": len(result_emb.embeddings[0]) if result_emb.embeddings else 0,
            }
        elif provider.provider_type == "llm":
            # Quick hello test for LLM providers
            if provider.provider_name == "bedrock":
                from app.services.llm.bedrock import BedrockProvider
                llm = BedrockProvider(model=provider.model_id)
                resp = await llm.complete([{"role": "user", "content": "Say hello in 3 words."}])
                return {"success": True, "provider_type": "llm", "response_preview": resp.content[:100]}
            return {"success": True, "provider_type": "llm", "message": "Test not implemented for this provider"}
        else:
            return {"success": True, "provider_type": provider.provider_type, "message": "Test not available"}
    except Exception as exc:
        logger.warning("Provider test failed", extra={"provider_id": str(provider_id), "error": str(exc)})
        return {"success": False, "error": str(exc)}
