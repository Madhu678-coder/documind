"""Chat session and message API endpoints with PageIndex pipeline."""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import decode_token, get_current_user
from app.models.audit_log import AuditLog
from app.models.chat_message import ChatMessage
from app.models.chat_session import ChatSession
from app.models.document import Document, DocumentStatus
from app.models.document_tree import DocumentTree
from app.models.knowledge_base import KnowledgeBase
from app.models.user import User
from app.schemas.chat import ChatMessageCreate, ChatMessageOut, ChatSessionCreate, ChatSessionOut
from app.services.llm.factory import get_llm_provider
from app.services.pageindex.answer_generator import generate_answer, stream_answer
from app.services.pageindex.trace_logger import build_trace
from app.services.pageindex.tree_navigator import navigate
from app.workers.eval_tasks import evaluate_response_async

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])

# Simple in-memory rate limiter: {user_id: [timestamps]}
_rate_limit_store: dict[str, list[float]] = {}
_RATE_WINDOW_SECONDS = 60


def _check_rate_limit(user_id: str) -> None:
    """Raise HTTP 429 if user exceeds rate limit."""
    now = time.time()
    window_start = now - _RATE_WINDOW_SECONDS
    timestamps = _rate_limit_store.get(user_id, [])
    # Prune old timestamps
    timestamps = [t for t in timestamps if t > window_start]
    if len(timestamps) >= settings.rate_limit_per_minute:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Please slow down.",
        )
    timestamps.append(now)
    _rate_limit_store[user_id] = timestamps


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


async def _get_session_or_403(
    session_id: uuid.UUID, workspace_id: uuid.UUID, db: AsyncSession
) -> ChatSession:
    result = await db.execute(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.workspace_id == workspace_id,
        )
    )
    session = result.scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Session not found")
    return session


async def _load_kb_trees(kb_id: uuid.UUID, db: AsyncSession) -> list[tuple[str, str, dict, list]]:
    """Load all ready document trees for a KB.

    Returns (doc_id, filename, tree_json, source_pages) tuples.
    source_pages is the per-page content list for PageIndex page-range retrieval.
    """
    result = await db.execute(
        select(Document, DocumentTree)
        .join(DocumentTree, DocumentTree.document_id == Document.id)
        .where(
            Document.kb_id == kb_id,
            Document.status == DocumentStatus.ready,
        )
    )
    rows = result.all()
    return [
        (str(doc.id), doc.filename, tree.tree_json, tree.source_pages or [])
        for doc, tree in rows
    ]


async def _add_audit_log(
    db: AsyncSession,
    user_id: uuid.UUID,
    action: str,
    resource_type: str,
    resource_id: uuid.UUID,
    metadata: dict | None = None,
) -> None:
    log = AuditLog(
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        log_metadata=metadata or {},
    )
    db.add(log)


# ── POST /chat/sessions ───────────────────────────────────────────────────────

@router.post("/sessions", status_code=status.HTTP_201_CREATED, response_model=ChatSessionOut)
async def create_session(
    body: ChatSessionCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new chat session linked to a KnowledgeBase.
    Auto-deletes any existing empty sessions for this user first.
    """
    await _get_kb_or_403(body.kb_id, current_user.workspace_id, db)

    # Delete any empty sessions for this user (no messages) before creating a new one
    empty_sessions_result = await db.execute(
        select(ChatSession).where(
            ChatSession.workspace_id == current_user.workspace_id,
            ChatSession.user_id == current_user.id,
        )
    )
    for s in empty_sessions_result.scalars().all():
        msg_count_result = await db.execute(
            select(ChatMessage).where(ChatMessage.session_id == s.id).limit(1)
        )
        if msg_count_result.scalar_one_or_none() is None:
            await db.delete(s)
    await db.flush()

    session = ChatSession(
        workspace_id=current_user.workspace_id,
        kb_id=body.kb_id,
        user_id=current_user.id,
        title="New conversation",
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)

    logger.info("Chat session created", extra={"session_id": str(session.id)})
    return session


# ── GET /chat/sessions ────────────────────────────────────────────────────────

@router.get("/sessions", response_model=list[ChatSessionOut])
async def list_sessions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List chat sessions that have at least one message, newest first."""
    result = await db.execute(
        select(ChatSession)
        .where(
            ChatSession.workspace_id == current_user.workspace_id,
            ChatSession.user_id == current_user.id,
        )
        .order_by(ChatSession.created_at.desc())
    )
    sessions = result.scalars().all()

    # Filter to only sessions with messages
    sessions_with_messages = []
    for s in sessions:
        msg_result = await db.execute(
            select(ChatMessage).where(ChatMessage.session_id == s.id).limit(1)
        )
        if msg_result.scalar_one_or_none() is not None:
            sessions_with_messages.append(s)
    return sessions_with_messages


# ── POST /chat/sessions/{id}/messages ─────────────────────────────────────────

@router.post("/sessions/{session_id}/messages")
async def send_message(
    session_id: uuid.UUID,
    body: ChatMessageCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Send a user message and receive a streamed SSE response.
    Runs the full PageIndex pipeline: tree_navigator → answer_generator → trace_logger.
    """
    _check_rate_limit(str(current_user.id))

    session = await _get_session_or_403(session_id, current_user.workspace_id, db)

    # Store user message
    user_msg = ChatMessage(
        session_id=session_id,
        role="user",
        content=body.content,
    )
    db.add(user_msg)
    await db.flush()

    # Auto-title the session from the first user message (truncated to 60 chars)
    if session.title == "New conversation":
        title = body.content.strip().replace('\n', ' ')
        session.title = title[:60] + ('…' if len(title) > 60 else '')
        db.add(session)

    await db.commit()
    await db.refresh(user_msg)

    # Audit log for chat query
    await _add_audit_log(db, current_user.id, "chat.query", "chat_session", session_id)
    await db.commit()

    # Load message history for multi-turn context
    history_result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.asc())
    )
    history = [
        {"role": m.role, "content": m.content}
        for m in history_result.scalars().all()
        if m.id != user_msg.id
    ]

    # Load KB to check rag_mode
    kb_result = await db.execute(select(KnowledgeBase).where(KnowledgeBase.id == session.kb_id))
    kb = kb_result.scalar_one()
    rag_mode = (kb.settings or {}).get("rag_mode", "pageindex")

    llm = await get_llm_provider(current_user.workspace_id, db)

    if rag_mode == "vector":
        # Vector RAG path
        from app.services.embedding.factory import EmbeddingFactory
        from app.services.retrieval.factory import RetrieverFactory
        from app.services.pageindex.chunk_answer_generator import generate_answer_from_chunks

        kb_settings = kb.settings or {}
        emb = EmbeddingFactory.create(
            kb_settings.get("embedding_provider", "bedrock"),
            kb_settings.get("embedding_model", "amazon.titan-embed-text-v2:0"),
        )
        retriever = RetrieverFactory.create(kb_settings, emb)
        chunks = await retriever.retrieve(body.content, session.kb_id, current_user.workspace_id, db)
        answer = await generate_answer_from_chunks(body.content, chunks, history, llm)

        reasoning_trace_data = {
            "mode": "vector",
            "chunks_retrieved": len(chunks),
            "retrieval_mode": kb_settings.get("retrieval_mode", "vector"),
        }
        node_ids_visited = [c.node_id for c in answer.citations]

        # Store assistant message
        assistant_msg = ChatMessage(
            session_id=session_id,
            role="assistant",
            content=answer.content,
            citations=[c.to_dict() for c in answer.citations],
            reasoning_trace=reasoning_trace_data,
            node_ids_visited=node_ids_visited,
        )
    elif rag_mode == "wiki":
        # Wiki RAG path — query the LLM-maintained wiki pages
        from sqlalchemy import select as sa_select
        from app.models.wiki_page import WikiPage
        from app.services.wiki.wiki_navigator import navigate_wiki
        from app.services.wiki.wiki_answer_generator import generate_answer_from_wiki

        wiki_result = await db.execute(
            sa_select(WikiPage)
            .where(WikiPage.kb_id == session.kb_id)
            .order_by(WikiPage.title)
        )
        wiki_pages = wiki_result.scalars().all()
        # Filter out structural pages from navigation
        nav_pages = [p for p in wiki_pages if p.page_type not in ("index", "log")]
        nav_result = await navigate_wiki(body.content, nav_pages, llm, history=history)
        selected_pages = [p for p in nav_pages if str(p.id) in nav_result.selected_page_ids]
        answer = await generate_answer_from_wiki(body.content, selected_pages, history, llm, all_pages=nav_pages)

        reasoning_trace_data = {
            "mode": "wiki",
            "pages_retrieved": len(selected_pages),
            "rationale": nav_result.rationale,
            "confidence": nav_result.confidence,
        }
        node_ids_visited = nav_result.selected_page_ids

        # ── Q&A Compounding (Karpathy pattern) ───────────────────────────────
        # File the answered question as a qa/ wiki page so future queries benefit.
        # Only file non-trivial answers with sufficient confidence.
        qa_compounding = (kb.settings or {}).get("qa_compounding", True)
        if qa_compounding and nav_result.confidence >= 0.6 and len(body.content.split()) >= 4:
            try:
                from app.services.wiki.wiki_builder import (
                    file_qa_answer, add_frontmatter_to_page, _INDEX_TITLE, _LOG_TITLE,
                    build_index_content, build_log_entry, prepend_log_entry,
                )
                selected_titles = [p.title for p in selected_pages]
                qa_page_data = await file_qa_answer(llm, body.content, answer.content, selected_titles)
                qa_title_key = qa_page_data["title"].lower()
                existing_qa = next(
                    (p for p in wiki_pages if p.title.lower() == qa_title_key), None
                )
                if not existing_qa:
                    content_with_fm = add_frontmatter_to_page(
                        qa_page_data["content"], qa_page_data["title"],
                        "qa", [str(p.id) for p in selected_pages],
                    )
                    new_qa = WikiPage(
                        kb_id=session.kb_id,
                        workspace_id=current_user.workspace_id,
                        title=qa_page_data["title"],
                        summary=qa_page_data.get("summary"),
                        content=content_with_fm,
                        page_type="qa",
                        source_doc_ids=[str(p.id) for p in selected_pages],
                        related_titles=selected_titles,
                        llm_model_used=llm.model if hasattr(llm, "model") else None,
                    )
                    db.add(new_qa)
                    # Update index after adding qa page
                    all_updated = [p for p in wiki_pages if p.page_type not in ("index", "log")] + [new_qa]
                    index_pg = next((p for p in wiki_pages if p.title == _INDEX_TITLE), None)
                    log_pg = next((p for p in wiki_pages if p.title == _LOG_TITLE), None)
                    if index_pg:
                        index_pg.content = build_index_content(all_updated)
                    if log_pg:
                        entry = build_log_entry(f"query | filed Q&A", {
                            "question": body.content[:80],
                            "confidence": nav_result.confidence,
                        })
                        log_pg.content = prepend_log_entry(log_pg.content, entry)
                    logger.info("Q&A page filed", extra={"title": qa_page_data["title"][:60]})
            except Exception as _qa_exc:
                logger.warning("Q&A compounding failed (non-fatal)", extra={"error": str(_qa_exc)})

        assistant_msg = ChatMessage(
            session_id=session_id,
            role="assistant",
            content=answer.content,
            citations=[c.to_dict() for c in answer.citations],
            reasoning_trace=reasoning_trace_data,
            node_ids_visited=node_ids_visited,
        )
    elif rag_mode == "graph":
        # GraphRAG path — entity extraction + graph traversal
        from app.services.embedding.factory import EmbeddingFactory
        from app.services.graph.graph_navigator import navigate_graph
        from app.services.graph.graph_answer_generator import generate_answer_from_graph

        kb_settings = kb.settings or {}
        embedding_provider = EmbeddingFactory.create(
            kb_settings.get("embedding_provider", "bedrock"),
            kb_settings.get("embedding_model", "amazon.titan-embed-text-v2:0"),
        )

        graph_context = await navigate_graph(
            query=body.content,
            kb_id=session.kb_id,
            llm=llm,
            embedding_provider=embedding_provider,
            db=db,
        )

        answer = await generate_answer_from_graph(body.content, graph_context, history, llm)

        reasoning_trace_data = {
            "mode": "graph",
            "entities_found": len(graph_context.nodes),
            "relationships_found": len(graph_context.edges),
            "query_entities": graph_context.query_entities,
        }
        node_ids_visited = graph_context.start_node_ids

        assistant_msg = ChatMessage(
            session_id=session_id,
            role="assistant",
            content=answer.content,
            citations=[c.to_dict() for c in answer.citations],
            reasoning_trace=reasoning_trace_data,
            node_ids_visited=node_ids_visited,
        )
    elif rag_mode == "openkb":
        # OpenKB path — compiled wiki with summary / concept / entity pages
        from sqlalchemy import select as sa_select
        from app.models.openkb_page import OpenKBPage
        from app.services.openkb.navigator import navigate_openkb
        from app.services.openkb.answer_generator import generate_answer_from_openkb

        all_pages_res = await db.execute(
            sa_select(OpenKBPage)
            .where(OpenKBPage.kb_id == session.kb_id)
            .order_by(OpenKBPage.page_category, OpenKBPage.title)
        )
        all_openkb_pages = all_pages_res.scalars().all()
        nav_result = await navigate_openkb(body.content, all_openkb_pages, llm, history=history)
        answer = await generate_answer_from_openkb(body.content, nav_result, history, llm)

        reasoning_trace_data = {
            "mode": "openkb",
            "pages_retrieved": len(nav_result.selected_pages),
            "page_ranges_retrieved": len(nav_result.page_range_content),
            "rationale": nav_result.rationale,
            "confidence": nav_result.confidence,
        }
        node_ids_visited = nav_result.selected_page_ids

        assistant_msg = ChatMessage(
            session_id=session_id,
            role="assistant",
            content=answer.content,
            citations=[c.to_dict() for c in answer.citations],
            reasoning_trace=reasoning_trace_data,
            node_ids_visited=node_ids_visited,
        )
    else:
        # PageIndex path — hierarchical tree navigation + page-range content retrieval
        trees = await _load_kb_trees(session.kb_id, db)

        nav_trees = [(doc_id, tree) for doc_id, _, tree, _ in trees]
        nav_result = await navigate(body.content, nav_trees, llm, history=history)

        # ── NEW: Retrieve actual page content for selected nodes ──────────────
        # Instead of using the truncated text embedded in tree nodes at index time,
        # we now fetch the full page content from source_pages stored in DocumentTree.
        # This is the core PageIndex retrieval step.
        from app.services.pageindex.content_retriever import retrieve_nodes as _retrieve_nodes
        enriched_trees: list[tuple[str, str, dict, list]] = []
        for doc_id, doc_name, tree, source_pages in trees:
            if source_pages and nav_result.selected_node_ids:
                # Fetch full page content for selected nodes
                retrieved = _retrieve_nodes(tree, nav_result.selected_node_ids, source_pages)
                # Inject retrieved content back into tree nodes for answer generator
                node_map: dict[str, dict] = {}
                def _idx(nodes: list) -> None:
                    for n in nodes:
                        node_map[n["node_id"]] = n
                        _idx(n.get("children", []))
                _idx(tree.get("nodes", []))
                for r in retrieved:
                    raw_id = r["node_id"].split("::")[-1] if "::" in r["node_id"] else r["node_id"]
                    if raw_id in node_map and r["content"]:
                        node_map[raw_id]["text"] = r["content"]  # replace truncated text
            enriched_trees.append((doc_id, doc_name, tree))

        trace = build_trace(
            query=body.content,
            selected_node_ids=nav_result.selected_node_ids,
            rationale=nav_result.rationale,
            confidence=nav_result.confidence,
            trees=nav_trees,
        )

        answer = await generate_answer(
            query=body.content,
            node_ids=nav_result.selected_node_ids,
            trees=enriched_trees,
            history=history,
            llm=llm,
        )

        assistant_msg = ChatMessage(
            session_id=session_id,
            role="assistant",
            content=answer.content,
            citations=[c.to_dict() for c in answer.citations],
            reasoning_trace=trace.to_dict(),
            node_ids_visited=trace.node_ids,
        )
    db.add(assistant_msg)
    await db.flush()  # get assistant_msg.id before audit log

    # Audit log for citation access
    if answer.citations:
        await _add_audit_log(
            db, current_user.id, "citation.access", "chat_message", assistant_msg.id,
            {"citation_count": len(answer.citations)},
        )

    await db.commit()
    await db.refresh(assistant_msg)

    # Trigger async evaluation (non-blocking)
    evaluate_response_async.apply_async(
        args=[str(assistant_msg.id), str(current_user.workspace_id)],
        kwargs={"triggered_by": "online"},
    )

    logger.info(
        "Chat message processed",
        extra={"session_id": str(session_id), "nodes_visited": len(assistant_msg.node_ids_visited or [])},
    )

    return ChatMessageOut.model_validate(assistant_msg)


# ── DELETE /chat/sessions/{id} ────────────────────────────────────────────────

@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a chat session and all its messages."""
    session = await _get_session_or_403(session_id, current_user.workspace_id, db)
    await db.delete(session)
    await db.commit()


# ── GET /chat/sessions/{id}/messages ──────────────────────────────────────────

@router.get("/sessions/{session_id}/messages", response_model=list[ChatMessageOut])
async def get_messages(
    session_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return full message history for a session in chronological order."""
    await _get_session_or_403(session_id, current_user.workspace_id, db)

    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.asc())
    )
    return result.scalars().all()


# ── WS /ws/chat/{session_id} ──────────────────────────────────────────────────

async def _get_ws_user(token: str, db: AsyncSession) -> User | None:
    """Authenticate a WebSocket connection via JWT query param."""
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            return None
        user_id = payload.get("sub")
        if not user_id:
            return None
        result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
        return result.scalar_one_or_none()
    except Exception:
        return None


async def _ws_stream_answer(
    websocket: WebSocket,
    session: ChatSession,
    query: str,
    history: list[dict],
    trees: list[tuple[str, str, dict, list]],  # (doc_id, filename, tree_dict, source_pages)
    db: AsyncSession,
    user: User,
    kb: KnowledgeBase | None = None,
) -> tuple[str, list, dict, list[str]]:
    """Run RAG pipeline and stream tokens over WebSocket. Returns (content, citations, trace_dict, node_ids)."""
    llm = await get_llm_provider(user.workspace_id, db)

    # Check rag_mode
    rag_mode = (kb.settings or {}).get("rag_mode", "pageindex") if kb else "pageindex"

    if rag_mode == "vector":
        from app.services.embedding.factory import EmbeddingFactory
        from app.services.retrieval.factory import RetrieverFactory
        from app.services.pageindex.chunk_answer_generator import generate_answer_from_chunks

        kb_settings = (kb.settings or {}) if kb else {}
        emb = EmbeddingFactory.create(
            kb_settings.get("embedding_provider", "bedrock"),
            kb_settings.get("embedding_model", "amazon.titan-embed-text-v2:0"),
        )
        retriever = RetrieverFactory.create(kb_settings, emb)
        chunks = await retriever.retrieve(query, session.kb_id, user.workspace_id, db)
        answer = await generate_answer_from_chunks(query, chunks, history, llm)

        trace_dict = {
            "mode": "vector",
            "chunks_retrieved": len(chunks),
            "retrieval_mode": kb_settings.get("retrieval_mode", "vector"),
        }
        node_ids = [c.node_id for c in answer.citations]

        await websocket.send_json({"type": "trace", "data": trace_dict})

        chunk_size = 5
        for i in range(0, len(answer.content), chunk_size):
            tok = answer.content[i:i + chunk_size]
            await websocket.send_json({"type": "token", "data": tok})

        await websocket.send_json({
            "type": "done",
            "citations": [c.to_dict() for c in answer.citations],
        })

        return answer.content, answer.citations, trace_dict, node_ids

    elif rag_mode == "wiki":
        from sqlalchemy import select as sa_select
        from app.models.wiki_page import WikiPage
        from app.services.wiki.wiki_navigator import navigate_wiki
        from app.services.wiki.wiki_answer_generator import generate_answer_from_wiki

        wiki_result = await db.execute(
            sa_select(WikiPage)
            .where(WikiPage.kb_id == session.kb_id)
            .order_by(WikiPage.title)
        )
        wiki_pages = wiki_result.scalars().all()
        nav_result = await navigate_wiki(query, wiki_pages, llm, history=history)
        selected_pages = [p for p in wiki_pages if str(p.id) in nav_result.selected_page_ids]
        answer = await generate_answer_from_wiki(query, selected_pages, history, llm, all_pages=wiki_pages)

        trace_dict = {
            "mode": "wiki",
            "pages_retrieved": len(selected_pages),
            "rationale": nav_result.rationale,
            "confidence": nav_result.confidence,
        }
        node_ids = nav_result.selected_page_ids

        await websocket.send_json({"type": "trace", "data": trace_dict})

        chunk_size = 5
        for i in range(0, len(answer.content), chunk_size):
            tok = answer.content[i:i + chunk_size]
            await websocket.send_json({"type": "token", "data": tok})

        await websocket.send_json({
            "type": "done",
            "citations": [c.to_dict() for c in answer.citations],
        })

        return answer.content, answer.citations, trace_dict, node_ids

    elif rag_mode == "graph":
        # GraphRAG path — entity extraction + graph traversal
        from app.services.embedding.factory import EmbeddingFactory
        from app.services.graph.graph_navigator import navigate_graph
        from app.services.graph.graph_answer_generator import generate_answer_from_graph

        kb_settings = (kb.settings or {}) if kb else {}
        embedding_provider = EmbeddingFactory.create(
            kb_settings.get("embedding_provider", "bedrock"),
            kb_settings.get("embedding_model", "amazon.titan-embed-text-v2:0"),
        )

        graph_context = await navigate_graph(
            query=query,
            kb_id=session.kb_id,
            llm=llm,
            embedding_provider=embedding_provider,
            db=db,
        )

        answer = await generate_answer_from_graph(query, graph_context, history, llm)

        trace_dict = {
            "mode": "graph",
            "entities_found": len(graph_context.nodes),
            "relationships_found": len(graph_context.edges),
            "query_entities": graph_context.query_entities,
        }
        node_ids = graph_context.start_node_ids

        await websocket.send_json({"type": "trace", "data": trace_dict})

        chunk_size = 5
        for i in range(0, len(answer.content), chunk_size):
            tok = answer.content[i:i + chunk_size]
            await websocket.send_json({"type": "token", "data": tok})

        await websocket.send_json({
            "type": "done",
            "citations": [c.to_dict() for c in answer.citations],
        })

        return answer.content, [c for c in answer.citations], trace_dict, node_ids

    elif rag_mode == "openkb":
        # OpenKB path — compiled wiki with summary / concept / entity pages
        from sqlalchemy import select as sa_select
        from app.models.openkb_page import OpenKBPage
        from app.services.openkb.navigator import navigate_openkb
        from app.services.openkb.answer_generator import generate_answer_from_openkb

        all_pages_res = await db.execute(
            sa_select(OpenKBPage)
            .where(OpenKBPage.kb_id == session.kb_id)
            .order_by(OpenKBPage.page_category, OpenKBPage.title)
        )
        all_openkb_pages = all_pages_res.scalars().all()
        nav_result = await navigate_openkb(query, all_openkb_pages, llm, history=history)
        answer = await generate_answer_from_openkb(query, nav_result, history, llm)

        trace_dict = {
            "mode": "openkb",
            "pages_retrieved": len(nav_result.selected_pages),
            "page_ranges_retrieved": len(nav_result.page_range_content),
            "rationale": nav_result.rationale,
            "confidence": nav_result.confidence,
        }
        node_ids = nav_result.selected_page_ids

        await websocket.send_json({"type": "trace", "data": trace_dict})
        chunk_size = 5
        for i in range(0, len(answer.content), chunk_size):
            await websocket.send_json({"type": "token", "data": answer.content[i:i + chunk_size]})
        await websocket.send_json({"type": "done", "citations": [c.to_dict() for c in answer.citations]})
        return answer.content, answer.citations, trace_dict, node_ids

    else:
        # PageIndex path with real page-range retrieval
        nav_trees = [(doc_id, tree) for doc_id, _, tree, _ in trees]
        nav_result = await navigate(query, nav_trees, llm, history=history)

        trace = build_trace(
            query=query,
            selected_node_ids=nav_result.selected_node_ids,
            rationale=nav_result.rationale,
            confidence=nav_result.confidence,
            trees=nav_trees,
        )

        # Retrieve actual page content for selected nodes
        from app.services.pageindex.content_retriever import retrieve_nodes as _retrieve_nodes
        enriched_trees = []
        for doc_id, doc_name, tree, source_pages in trees:
            if source_pages and nav_result.selected_node_ids:
                node_map: dict[str, dict] = {}
                def _idx(nodes: list) -> None:
                    for n in nodes:
                        node_map[n["node_id"]] = n
                        _idx(n.get("children", []))
                _idx(tree.get("nodes", []))
                for r in _retrieve_nodes(tree, nav_result.selected_node_ids, source_pages):
                    raw_id = r["node_id"].split("::")[-1] if "::" in r["node_id"] else r["node_id"]
                    if raw_id in node_map and r["content"]:
                        node_map[raw_id]["text"] = r["content"]
            enriched_trees.append((doc_id, doc_name, tree))

        await websocket.send_json({"type": "trace", "data": trace.to_dict()})

        full_content = ""
        async for chunk in stream_answer(query, nav_result.selected_node_ids, enriched_trees, history, llm):
            full_content += chunk

        from app.services.pageindex.answer_generator import _parse_answer_and_citations
        answer_text, citations = _parse_answer_and_citations(full_content)

        chunk_size = 5
        for i in range(0, len(answer_text), chunk_size):
            await websocket.send_json({"type": "token", "data": answer_text[i:i + chunk_size]})

        await websocket.send_json({
            "type": "done",
            "citations": [c.to_dict() for c in citations],
        })

        return answer_text, citations, trace.to_dict(), trace.node_ids


# WebSocket router is registered on the app directly (not under /api/v1 prefix)
ws_router = APIRouter(tags=["chat-ws"])


@ws_router.websocket("/ws/chat/{session_id}")
async def websocket_chat(
    websocket: WebSocket,
    session_id: uuid.UUID,
    token: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """WebSocket endpoint for streaming chat tokens and events. JWT via query param."""
    await websocket.accept()

    user = await _get_ws_user(token, db)
    if user is None:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    session_result = await db.execute(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.workspace_id == user.workspace_id,
        )
    )
    session = session_result.scalar_one_or_none()
    if session is None:
        await websocket.close(code=4003, reason="Session not found")
        return

    try:
        while True:
            data = await websocket.receive_json()
            query = data.get("content", "").strip()
            if not query:
                continue

            _check_rate_limit(str(user.id))

            # Store user message
            user_msg = ChatMessage(session_id=session_id, role="user", content=query)
            db.add(user_msg)
            await db.commit()

            # Load history and trees
            history_result = await db.execute(
                select(ChatMessage)
                .where(ChatMessage.session_id == session_id)
                .order_by(ChatMessage.created_at.asc())
            )
            history = [
                {"role": m.role, "content": m.content}
                for m in history_result.scalars().all()
                if m.id != user_msg.id
            ]
            trees = await _load_kb_trees(session.kb_id, db)

            # Load KB for rag_mode check
            kb_res = await db.execute(select(KnowledgeBase).where(KnowledgeBase.id == session.kb_id))
            ws_kb = kb_res.scalar_one_or_none()

            answer_text, citations, trace_dict, node_ids = await _ws_stream_answer(
                websocket, session, query, history, trees, db, user, kb=ws_kb
            )

            # Store assistant message
            assistant_msg = ChatMessage(
                session_id=session_id,
                role="assistant",
                content=answer_text,
                citations=[c.to_dict() for c in citations],
                reasoning_trace=trace_dict,
                node_ids_visited=node_ids,
            )
            db.add(assistant_msg)
            await _add_audit_log(db, user.id, "chat.query", "chat_session", session_id)
            await db.commit()
            await db.refresh(assistant_msg)

            # Trigger async evaluation (non-blocking)
            evaluate_response_async.apply_async(
                args=[str(assistant_msg.id), str(user.workspace_id)],
                kwargs={"triggered_by": "online"},
            )

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected", extra={"session_id": str(session_id)})
    except HTTPException as exc:
        await websocket.send_json({"type": "error", "detail": exc.detail})
        await websocket.close(code=4029, reason="Rate limit exceeded")
    except Exception as exc:
        logger.exception("WebSocket error", extra={"session_id": str(session_id)})
        await websocket.close(code=1011, reason="Internal error")
