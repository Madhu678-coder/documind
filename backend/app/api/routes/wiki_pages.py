"""Wiki pages API — list and retrieve LLM-maintained wiki pages for a Knowledge Base."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.knowledge_base import KnowledgeBase
from app.models.user import User
from app.models.wiki_page import WikiPage

router = APIRouter(prefix="/knowledge-bases", tags=["wiki"])


# ── Pydantic output schemas ───────────────────────────────────────────────────

class WikiPageOut(BaseModel):
    """Summary view — used in list endpoint (omits full content for performance)."""
    id: str
    kb_id: str
    title: str
    summary: str | None
    page_type: str
    source_doc_count: int
    related_titles: list[str]
    updated_at: str

    model_config = {"from_attributes": True}


class WikiPageDetailOut(BaseModel):
    """Full view — includes complete markdown content."""
    id: str
    kb_id: str
    workspace_id: str
    title: str
    summary: str | None
    content: str
    page_type: str
    source_doc_ids: list[str]
    related_titles: list[str]
    llm_model_used: str | None
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _get_kb_or_403(kb_id: uuid.UUID, workspace_id: uuid.UUID, db: AsyncSession) -> KnowledgeBase:
    result = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.id == kb_id,
            KnowledgeBase.workspace_id == workspace_id,
        )
    )
    kb = result.scalar_one_or_none()
    if kb is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="KnowledgeBase not found in workspace")
    return kb


def _page_to_summary(page: WikiPage) -> WikiPageOut:
    return WikiPageOut(
        id=str(page.id),
        kb_id=str(page.kb_id),
        title=page.title,
        summary=page.summary,
        page_type=page.page_type,
        source_doc_count=len(page.source_doc_ids) if page.source_doc_ids else 0,
        related_titles=list(page.related_titles or []),
        updated_at=page.updated_at.isoformat() if page.updated_at else "",
    )


def _page_to_detail(page: WikiPage) -> WikiPageDetailOut:
    return WikiPageDetailOut(
        id=str(page.id),
        kb_id=str(page.kb_id),
        workspace_id=str(page.workspace_id),
        title=page.title,
        summary=page.summary,
        content=page.content,
        page_type=page.page_type,
        source_doc_ids=list(page.source_doc_ids or []),
        related_titles=list(page.related_titles or []),
        llm_model_used=page.llm_model_used,
        created_at=page.created_at.isoformat() if page.created_at else "",
        updated_at=page.updated_at.isoformat() if page.updated_at else "",
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/{kb_id}/wiki-pages", response_model=list[WikiPageOut])
async def list_wiki_pages(
    kb_id: uuid.UUID,
    doc_id: uuid.UUID | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List wiki pages for a KB. Optionally filter by source document ID."""
    await _get_kb_or_403(kb_id, current_user.workspace_id, db)

    result = await db.execute(
        select(WikiPage)
        .where(WikiPage.kb_id == kb_id)
        .order_by(WikiPage.page_type, WikiPage.title)
    )
    pages = result.scalars().all()

    # Filter by source document if doc_id provided
    if doc_id:
        doc_id_str = str(doc_id)
        pages = [p for p in pages if doc_id_str in (p.source_doc_ids or [])]

    return [_page_to_summary(p) for p in pages]


@router.get("/{kb_id}/wiki-pages/{page_id}", response_model=WikiPageDetailOut)
async def get_wiki_page(
    kb_id: uuid.UUID,
    page_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the full content of a single wiki page."""
    await _get_kb_or_403(kb_id, current_user.workspace_id, db)

    result = await db.execute(
        select(WikiPage).where(
            WikiPage.id == page_id,
            WikiPage.kb_id == kb_id,
        )
    )
    page = result.scalar_one_or_none()
    if page is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Wiki page not found")

    return _page_to_detail(page)


# ── Export as Markdown ────────────────────────────────────────────────────────

@router.get("/{kb_id}/wiki-pages/export/markdown")
async def export_wiki_as_markdown(
    kb_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Export all wiki pages for a KB as a single markdown document.
    Includes an INDEX section at the top and full page content below.
    Wikilinks [[Title]] are preserved for Obsidian/Notion compatibility.
    """
    from fastapi.responses import PlainTextResponse

    await _get_kb_or_403(kb_id, current_user.workspace_id, db)

    result = await db.execute(
        select(WikiPage)
        .where(WikiPage.kb_id == kb_id)
        .order_by(WikiPage.page_type, WikiPage.title)
    )
    pages = result.scalars().all()

    if not pages:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No wiki pages found for this KB")

    # Build the markdown export
    lines: list[str] = []

    # Header
    kb_result = await db.execute(select(KnowledgeBase).where(KnowledgeBase.id == kb_id))
    kb = kb_result.scalar_one()
    lines.append(f"# {kb.name} — Wiki Export")
    lines.append("")
    lines.append(f"*Exported: {__import__('datetime').datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}*")
    lines.append(f"*Pages: {len(pages)}*")
    lines.append("")

    # INDEX section
    lines.append("## INDEX")
    lines.append("")
    current_type = ""
    for page in pages:
        if page.page_type != current_type:
            current_type = page.page_type
            lines.append(f"### {current_type.capitalize()}")
        summary = f" — {page.summary}" if page.summary else ""
        lines.append(f"- [[{page.title}]]{summary}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Full page content
    for page in pages:
        lines.append(f"## {page.title}")
        lines.append("")
        lines.append(f"*Type: {page.page_type} | Sources: {len(page.source_doc_ids or [])} document(s)*")
        if page.related_titles:
            related = ", ".join(f"[[{t}]]" for t in page.related_titles)
            lines.append(f"*Related: {related}*")
        lines.append("")
        lines.append(page.content)
        lines.append("")
        lines.append("---")
        lines.append("")

    markdown_content = "\n".join(lines)

    return PlainTextResponse(
        content=markdown_content,
        media_type="text/markdown",
        headers={
            "Content-Disposition": f'attachment; filename="{kb.name.replace(" ", "_")}_wiki.md"',
        },
    )
