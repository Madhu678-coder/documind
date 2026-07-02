"""OpenKB RAG mode — REST API endpoints.

All routes live under /knowledge-bases/{kb_id}/openkb/

  GET  /pages                  — list all compiled pages (filterable by category)
  GET  /pages/{page_id}        — full page detail
  GET  /index                  — the living catalog page (__index__)
  GET  /visualization          — D3-compatible wikilink graph
  GET  /lint                   — wiki health checks
  GET  /export                 — export all pages as a single Markdown file
  POST /skills                 — generate a SKILL.md from wiki content
  POST /decks                  — generate an HTML slide deck from wiki content
"""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.knowledge_base import KnowledgeBase
from app.models.openkb_page import OpenKBPage
from app.models.user import User

router = APIRouter(prefix="/knowledge-bases", tags=["openkb"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class OpenKBPageOut(BaseModel):
    """List view — omits full content for performance."""
    id: str
    kb_id: str
    title: str
    page_category: str
    page_type: str
    summary: str | None
    source_doc_count: int
    source_doc_ids: list[str]
    related_titles: list[str]
    updated_at: str

    model_config = {"from_attributes": True}


class OpenKBPageDetailOut(BaseModel):
    """Full detail view — includes Markdown content."""
    id: str
    kb_id: str
    workspace_id: str
    title: str
    page_category: str
    page_type: str
    summary: str | None
    content: str
    source_doc_ids: list[str]
    related_titles: list[str]
    llm_model_used: str | None
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


class VisualizationOut(BaseModel):
    """D3 / vis.js compatible wikilink graph."""
    nodes: list[dict]
    edges: list[dict]


class SkillRequest(BaseModel):
    skill_name: str
    intent: str


class SkillOut(BaseModel):
    skill_name: str
    intent: str
    content: str
    page_count_used: int


class DeckRequest(BaseModel):
    deck_name: str
    intent: str


# ---------------------------------------------------------------------------
# Auth / KB guard
# ---------------------------------------------------------------------------


async def _get_kb(kb_id: uuid.UUID, workspace_id: uuid.UUID, db: AsyncSession) -> KnowledgeBase:
    res = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.id == kb_id,
            KnowledgeBase.workspace_id == workspace_id,
        )
    )
    kb = res.scalar_one_or_none()
    if kb is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="KnowledgeBase not found")
    return kb


async def _load_pages(kb_id: uuid.UUID, db: AsyncSession) -> list[OpenKBPage]:
    res = await db.execute(
        select(OpenKBPage)
        .where(OpenKBPage.kb_id == kb_id)
        .order_by(OpenKBPage.page_category, OpenKBPage.title)
    )
    return res.scalars().all()


def _page_to_out(p: OpenKBPage) -> OpenKBPageOut:
    return OpenKBPageOut(
        id=str(p.id),
        kb_id=str(p.kb_id),
        title=p.title,
        page_category=p.page_category,
        page_type=p.page_type,
        summary=p.summary,
        source_doc_count=len(p.source_doc_ids) if p.source_doc_ids else 0,
        source_doc_ids=list(p.source_doc_ids or []),
        related_titles=list(p.related_titles or []),
        updated_at=p.updated_at.isoformat() if p.updated_at else "",
    )


def _page_to_detail(p: OpenKBPage) -> OpenKBPageDetailOut:
    return OpenKBPageDetailOut(
        id=str(p.id),
        kb_id=str(p.kb_id),
        workspace_id=str(p.workspace_id),
        title=p.title,
        page_category=p.page_category,
        page_type=p.page_type,
        summary=p.summary,
        content=p.content,
        source_doc_ids=list(p.source_doc_ids or []),
        related_titles=list(p.related_titles or []),
        llm_model_used=p.llm_model_used,
        created_at=p.created_at.isoformat() if p.created_at else "",
        updated_at=p.updated_at.isoformat() if p.updated_at else "",
    )


# ---------------------------------------------------------------------------
# GET /pages
# ---------------------------------------------------------------------------


@router.get("/{kb_id}/openkb/pages", response_model=list[OpenKBPageOut])
async def list_openkb_pages(
    kb_id: uuid.UUID,
    category: str | None = Query(None, description="Filter by page_category: summary|concept|entity|exploration|index"),
    doc_id: uuid.UUID | None = Query(None, description="Filter by source document UUID"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all compiled OpenKB pages for a knowledge base.

    Optionally filter by ``category`` (summary, concept, entity, exploration, index)
    or by the source document UUID that contributed to each page.
    """
    await _get_kb(kb_id, current_user.workspace_id, db)

    query = (
        select(OpenKBPage)
        .where(OpenKBPage.kb_id == kb_id)
        .order_by(OpenKBPage.page_category, OpenKBPage.title)
    )
    if category:
        query = query.where(OpenKBPage.page_category == category)

    res = await db.execute(query)
    pages = res.scalars().all()

    if doc_id:
        doc_id_str = str(doc_id)
        pages = [p for p in pages if doc_id_str in (p.source_doc_ids or [])]

    return [_page_to_out(p) for p in pages]


# ---------------------------------------------------------------------------
# GET /pages/{page_id}
# ---------------------------------------------------------------------------


@router.get("/{kb_id}/openkb/pages/{page_id}", response_model=OpenKBPageDetailOut)
async def get_openkb_page(
    kb_id: uuid.UUID,
    page_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve the full content of a single OpenKB page."""
    await _get_kb(kb_id, current_user.workspace_id, db)

    res = await db.execute(
        select(OpenKBPage).where(
            OpenKBPage.id == page_id,
            OpenKBPage.kb_id == kb_id,
        )
    )
    page = res.scalar_one_or_none()
    if page is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Page not found")

    return _page_to_detail(page)


# ---------------------------------------------------------------------------
# GET /index  — living catalog
# ---------------------------------------------------------------------------


@router.get("/{kb_id}/openkb/index")
async def get_openkb_index(
    kb_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the living index page — a catalog of all compiled pages.

    If the index page hasn't been built yet (no documents ingested), returns an
    empty catalog.
    """
    await _get_kb(kb_id, current_user.workspace_id, db)

    res = await db.execute(
        select(OpenKBPage).where(
            OpenKBPage.kb_id == kb_id,
            OpenKBPage.title == "__index__",
        )
    )
    index_page = res.scalar_one_or_none()

    if index_page is None:
        # Build an on-the-fly index from whatever pages exist
        all_pages = await _load_pages(kb_id, db)
        from app.services.openkb.compiler import build_index_content
        content = build_index_content([p for p in all_pages if p.page_category != "index"])
        return {
            "title": "__index__",
            "page_category": "index",
            "content": content,
            "last_updated": None,
        }

    return {
        "title": index_page.title,
        "page_category": index_page.page_category,
        "content": index_page.content,
        "last_updated": index_page.updated_at.isoformat() if index_page.updated_at else None,
    }


# ---------------------------------------------------------------------------
# GET /visualization  — wikilink graph
# ---------------------------------------------------------------------------


@router.get("/{kb_id}/openkb/visualization", response_model=VisualizationOut)
async def get_openkb_visualization(
    kb_id: uuid.UUID,
    category: str | None = Query(None, description="Filter nodes by page_category"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a D3 / vis.js compatible wikilink graph for the compiled wiki.

    Nodes represent pages; edges represent [[wikilinks]] found in page content
    and entries in the related_titles field.  Node size scales with the number
    of source documents that contributed to the page.
    """
    await _get_kb(kb_id, current_user.workspace_id, db)

    all_pages = await _load_pages(kb_id, db)

    # Filter out the internal index page from the visual graph
    content_pages = [p for p in all_pages if p.page_category != "index"]
    if category:
        content_pages = [p for p in content_pages if p.page_category == category]

    title_to_id = {p.title.lower(): str(p.id) for p in content_pages}

    # ── Colour by category ────────────────────────────────────────────────────
    category_colours = {
        "summary": "#6366f1",     # indigo
        "concept": "#22c55e",     # green
        "entity": "#f59e0b",      # amber
        "exploration": "#ec4899", # pink
    }
    entity_type_colours = {
        "person": "#f97316",
        "organization": "#14b8a6",
        "place": "#84cc16",
        "product": "#a855f7",
        "work": "#06b6d4",
        "event": "#ef4444",
        "other": "#94a3b8",
    }

    nodes = []
    for p in content_pages:
        if p.page_category == "entity":
            colour = entity_type_colours.get(p.page_type, "#94a3b8")
        else:
            colour = category_colours.get(p.page_category, "#64748b")

        src_count = len(p.source_doc_ids) if p.source_doc_ids else 0
        nodes.append(
            {
                "id": str(p.id),
                "label": p.title,
                "category": p.page_category,
                "page_type": p.page_type,
                "description": p.summary or "",
                "color": colour,
                "size": min(10 + src_count * 6, 40),
                "source_doc_count": src_count,
            }
        )

    # ── Edges from wikilinks + related_titles ─────────────────────────────────
    import re

    edges: list[dict] = []
    seen_edges: set[tuple[str, str]] = set()
    valid_ids = {str(p.id) for p in content_pages}

    def _add_edge(source_id: str, target_id: str, label: str = "links_to") -> None:
        if source_id == target_id:
            return
        key = (min(source_id, target_id), max(source_id, target_id))
        if key not in seen_edges and source_id in valid_ids and target_id in valid_ids:
            seen_edges.add(key)
            edges.append(
                {
                    "id": f"{source_id}_{target_id}",
                    "source": source_id,
                    "target": target_id,
                    "label": label,
                }
            )

    for p in content_pages:
        src_id = str(p.id)

        # Wikilinks in content
        for link_title in re.findall(r"\[\[([^\]]+)\]\]", p.content or ""):
            tgt_id = title_to_id.get(link_title.lower())
            if tgt_id:
                _add_edge(src_id, tgt_id, "wikilink")

        # related_titles field
        for rel_title in (p.related_titles or []):
            tgt_id = title_to_id.get(rel_title.lower())
            if tgt_id:
                _add_edge(src_id, tgt_id, "related")

    return VisualizationOut(nodes=nodes, edges=edges)


# ---------------------------------------------------------------------------
# GET /lint  — wiki health checks
# ---------------------------------------------------------------------------


@router.get("/{kb_id}/openkb/lint")
async def lint_openkb(
    kb_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Run health checks on the compiled OpenKB wiki.

    Returns a structured report with errors, warnings, and informational issues
    (ghost wikilinks, orphaned pages, empty content, missing summaries, duplicate titles).
    """
    await _get_kb(kb_id, current_user.workspace_id, db)

    all_pages = await _load_pages(kb_id, db)
    if not all_pages:
        return {"passed": True, "pages_checked": 0, "error_count": 0, "warning_count": 0, "issues": []}

    from app.services.openkb.lint import lint_wiki
    report = lint_wiki(all_pages)
    return report.to_dict()


# ---------------------------------------------------------------------------
# GET /export  — Obsidian-compatible Markdown export
# ---------------------------------------------------------------------------


@router.get("/{kb_id}/openkb/images/{doc_name}/{filename}")
async def serve_openkb_image(
    kb_id: uuid.UUID,
    doc_name: str,
    filename: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Serve an image extracted from an OpenKB-compiled document.

    Images are stored in S3 under key: openkb/{kb_id}/{doc_name}/{filename}
    and referenced in wiki page content as API paths so they render in the
    frontend without broken links.
    """
    from fastapi.responses import Response as FastResponse
    import boto3
    from app.core.config import settings as _settings

    await _get_kb(kb_id, current_user.workspace_id, db)

    s3_key = f"openkb/{kb_id}/{doc_name}/{filename}"

    try:
        session_kwargs: dict = {}
        if _settings.aws_endpoint_url:
            session_kwargs = {"aws_access_key_id": "test", "aws_secret_access_key": "test"}
        elif _settings.aws_profile:
            session_kwargs = {"profile_name": _settings.aws_profile}
        boto_session = boto3.Session(**session_kwargs)
        client_kwargs: dict = {"region_name": _settings.aws_region}
        if _settings.aws_endpoint_url:
            client_kwargs["endpoint_url"] = _settings.aws_endpoint_url
        s3 = boto_session.client("s3", **client_kwargs)
        obj = s3.get_object(Bucket=_settings.s3_bucket, Key=s3_key)
        image_bytes = obj["Body"].read()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Image not found: {doc_name}/{filename}",
        ) from exc

    # Determine MIME type from extension
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "png"
    mime_map = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                "gif": "image/gif", "webp": "image/webp"}
    media_type = mime_map.get(ext, "image/png")

    return FastResponse(content=image_bytes, media_type=media_type)


@router.get("/{kb_id}/openkb/export")
async def export_openkb_markdown(
    kb_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Export all OpenKB pages as a single Markdown document.

    The export preserves [[wikilinks]] for Obsidian / Notion compatibility and
    includes an INDEX section at the top.
    """
    await _get_kb(kb_id, current_user.workspace_id, db)

    kb_res = await db.execute(
        select(KnowledgeBase).where(KnowledgeBase.id == kb_id)
    )
    kb = kb_res.scalar_one()
    all_pages = await _load_pages(kb_id, db)
    content_pages = [p for p in all_pages if p.page_category != "index"]

    if not content_pages:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No OpenKB pages found for this knowledge base.",
        )

    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    lines: list[str] = [
        f"# {kb.name} — OpenKB Wiki Export",
        "",
        f"*Exported: {now}*",
        f"*Pages: {len(content_pages)}*",
        "",
        "## INDEX",
        "",
    ]

    for category, heading in [
        ("summary", "### Documents"),
        ("concept", "### Concepts"),
        ("entity", "### Entities"),
        ("exploration", "### Explorations"),
    ]:
        cat_pages = [p for p in content_pages if p.page_category == category]
        if cat_pages:
            lines.append(heading)
            for p in sorted(cat_pages, key=lambda x: x.title):
                brief = f" — {p.summary}" if p.summary else ""
                lines.append(f"- [[{p.title}]]{brief}")
            lines.append("")

    lines += ["---", ""]

    for p in content_pages:
        lines.append(f"## {p.title}")
        lines.append("")
        lines.append(
            f"*Category: {p.page_category} | Type: {p.page_type} | "
            f"Sources: {len(p.source_doc_ids or [])} document(s)*"
        )
        if p.related_titles:
            related = ", ".join(f"[[{t}]]" for t in p.related_titles)
            lines.append(f"*Related: {related}*")
        lines.append("")
        lines.append(p.content or "")
        lines.append("")
        lines.append("---")
        lines.append("")

    filename = kb.name.replace(" ", "_") + "_openkb_wiki.md"
    return PlainTextResponse(
        content="\n".join(lines),
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# POST /skills  — SKILL.md generator
# ---------------------------------------------------------------------------


@router.post("/{kb_id}/openkb/skills", response_model=SkillOut)
async def generate_openkb_skill(
    kb_id: uuid.UUID,
    body: SkillRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Distil a portable agent SKILL.md from the compiled wiki.

    The generated skill can be loaded by Claude Code, Codex, or Gemini CLI
    so the agent reasons like a domain expert on this knowledge base's content.

    Body:
      - ``skill_name``: short slug for the skill (e.g. ``"hr-policy-expert"``)
      - ``intent``: one-sentence description of what the skill enables
    """
    await _get_kb(kb_id, current_user.workspace_id, db)

    all_pages = await _load_pages(kb_id, db)
    if not all_pages:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No OpenKB pages found. Upload and compile documents first.",
        )

    from app.services.llm.factory import get_llm_provider
    from app.services.openkb.skill_factory import generate_skill

    llm = await get_llm_provider(current_user.workspace_id, db)
    skill = await generate_skill(
        provider=llm,
        pages=all_pages,
        skill_name=body.skill_name,
        intent=body.intent,
    )
    return SkillOut(
        skill_name=skill.skill_name,
        intent=skill.intent,
        content=skill.content,
        page_count_used=skill.page_count_used,
    )


# ---------------------------------------------------------------------------
# POST /decks  — HTML slide deck generator
# ---------------------------------------------------------------------------


@router.post("/{kb_id}/openkb/decks")
async def generate_openkb_deck(
    kb_id: uuid.UUID,
    body: DeckRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate a self-contained interactive HTML slide deck from wiki content.

    The deck includes a table-of-contents sidebar, keyboard navigation
    (← →), and a progress bar.  The HTML file has no external dependencies.

    Body:
      - ``deck_name``: display title for the deck
      - ``intent``: what the deck should communicate (guides LLM structure)

    Returns the HTML file as a download (``text/html``).
    """
    await _get_kb(kb_id, current_user.workspace_id, db)

    all_pages = await _load_pages(kb_id, db)
    if not all_pages:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No OpenKB pages found. Upload and compile documents first.",
        )

    from app.services.llm.factory import get_llm_provider
    from app.services.openkb.deck_generator import generate_deck

    llm = await get_llm_provider(current_user.workspace_id, db)
    deck = await generate_deck(
        provider=llm,
        pages=all_pages,
        deck_name=body.deck_name,
        intent=body.intent,
    )

    safe_name = body.deck_name.replace(" ", "_").replace("/", "_")
    return HTMLResponse(
        content=deck.html_content,
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name}.html"',
            "X-Slide-Count": str(deck.slide_count),
        },
    )
