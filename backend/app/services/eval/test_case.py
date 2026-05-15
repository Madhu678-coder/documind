"""Build DeepEval LLMTestCase from a stored chat message (Requirement 13.3)."""
from __future__ import annotations

import logging
import uuid
from typing import Any

logger = logging.getLogger(__name__)


def _extract_node_text(tree_json: dict, node_id: str) -> str | None:
    """
    Recursively search a document tree for a node by ID and return its text.
    Handles both plain node IDs and prefixed '{doc_id}::{node_id}' formats.
    """
    # Strip doc_id prefix if present (e.g. "abc123::n1" → "n1")
    bare_id = node_id.split("::")[-1] if "::" in node_id else node_id

    def _search(nodes: list[dict]) -> str | None:
        for node in nodes:
            nid = node.get("node_id", "")
            bare_nid = nid.split("::")[-1] if "::" in nid else nid
            if nid == node_id or bare_nid == bare_id:
                return node.get("text", "")
            found = _search(node.get("children", []))
            if found is not None:
                return found
        return None

    return _search(tree_json.get("nodes", []))


async def build_test_case(message_id: str | uuid.UUID, db_session: Any) -> Any:
    """
    Build a DeepEval LLMTestCase from a stored chat message.

    Fetches the assistant message and its preceding user message from the DB,
    then collects raw section text for all visited node IDs as retrieval_context.

    Args:
        message_id: UUID of the assistant chat_message record.
        db_session: An active AsyncSession.

    Returns:
        deepeval.test_case.LLMTestCase instance.

    Raises:
        ValueError: If the message is not found or is not an assistant message.
    """
    from sqlalchemy import select
    from app.models.chat_message import ChatMessage
    from app.models.document_tree import DocumentTree
    from app.models.document import Document

    msg_uuid = uuid.UUID(str(message_id))

    # Load the assistant message
    result = await db_session.execute(
        select(ChatMessage).where(ChatMessage.id == msg_uuid)
    )
    assistant_msg: ChatMessage | None = result.scalar_one_or_none()
    if assistant_msg is None:
        raise ValueError(f"ChatMessage {message_id} not found")

    # Find the preceding user message in the same session
    user_result = await db_session.execute(
        select(ChatMessage)
        .where(
            ChatMessage.session_id == assistant_msg.session_id,
            ChatMessage.role == "user",
            ChatMessage.created_at < assistant_msg.created_at,
        )
        .order_by(ChatMessage.created_at.desc())
        .limit(1)
    )
    user_msg: ChatMessage | None = user_result.scalar_one_or_none()
    user_query = user_msg.content if user_msg else ""

    # Collect retrieval_context from visited node IDs
    node_ids: list[str] = assistant_msg.node_ids_visited or []
    retrieval_context: list[str] = []

    if node_ids:
        # Load all document trees for documents referenced by these node IDs
        # Node IDs may be prefixed as "{doc_id}::{node_id}"
        doc_ids_from_nodes: set[str] = set()
        for nid in node_ids:
            if "::" in nid:
                doc_ids_from_nodes.add(nid.split("::")[0])

        if doc_ids_from_nodes:
            doc_uuids = [uuid.UUID(d) for d in doc_ids_from_nodes if _is_valid_uuid(d)]
            trees_result = await db_session.execute(
                select(DocumentTree).where(DocumentTree.document_id.in_(doc_uuids))
            )
            trees = trees_result.scalars().all()
        else:
            # No prefix — load all trees for the session's KB
            trees_result = await db_session.execute(
                select(DocumentTree)
                .join(Document, Document.id == DocumentTree.document_id)
                .where(Document.status == "ready")
            )
            trees = trees_result.scalars().all()

        tree_map: dict[str, dict] = {str(t.document_id): t.tree_json for t in trees}

        unresolved_ids: list[str] = []
        for nid in node_ids:
            text: str | None = None
            if "::" in nid:
                doc_id_str, _ = nid.split("::", 1)
                tree = tree_map.get(doc_id_str)
                if tree:
                    text = _extract_node_text(tree, nid)
            else:
                # Try all trees (PageIndex path)
                for tree in tree_map.values():
                    text = _extract_node_text(tree, nid)
                    if text:
                        break

            if text:
                retrieval_context.append(text)
            else:
                unresolved_ids.append(nid)

        # Vector RAG path: node_ids are DocumentChunk UUIDs — look them up directly
        if unresolved_ids:
            chunk_uuids = [uuid.UUID(nid) for nid in unresolved_ids if _is_valid_uuid(nid)]
            if chunk_uuids:
                from app.models.document_chunk import DocumentChunk
                chunks_result = await db_session.execute(
                    select(DocumentChunk).where(DocumentChunk.id.in_(chunk_uuids))
                )
                for chunk in chunks_result.scalars().all():
                    if chunk.text:
                        retrieval_context.append(chunk.text)

    try:
        import sys
        if sys.version_info >= (3, 10):
            from deepeval.test_case import LLMTestCase

            return LLMTestCase(
                input=user_query,
                actual_output=assistant_msg.content,
                retrieval_context=retrieval_context if retrieval_context else [""],
            )
        else:
            # Python < 3.10 - return dict instead
            return {
                "input": user_query,
                "actual_output": assistant_msg.content,
                "retrieval_context": retrieval_context if retrieval_context else [""],
            }
    except ImportError:
        # Return a plain dict when deepeval is not installed
        return {
            "input": user_query,
            "actual_output": assistant_msg.content,
            "retrieval_context": retrieval_context if retrieval_context else [""],
        }


def _is_valid_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except ValueError:
        return False
