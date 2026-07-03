"""Thin async client for the existing DocuMind API.

This benchmark suite does not reimplement any RAG logic — it drives the real
app exactly the way the DocuMind frontend would: log in, create a KB per mode,
upload the same documents, wait for async ingestion, open a chat session, ask
the fixed question set, and poll the async DeepEval result for each answer.
"""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

_MIME_BY_EXT = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "txt": "text/plain",
    "md": "text/markdown",
}


class DocuMindAPIError(RuntimeError):
    pass


class DocuMindClient:
    def __init__(self, base_url: str, email: str, password: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._email = email
        self._password = password
        self._client = httpx.AsyncClient(base_url=self._base_url, timeout=60.0)
        self._access_token: Optional[str] = None

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "DocuMindClient":
        await self.login()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    # ── auth ──────────────────────────────────────────────────────────────

    async def login(self) -> None:
        resp = await self._client.post(
            "/auth/login",
            data={"username": self._email, "password": self._password},
        )
        if resp.status_code != 200:
            raise DocuMindAPIError(
                f"DocuMind login failed ({resp.status_code}): {resp.text[:300]}"
            )
        self._access_token = resp.json()["access_token"]

    def _headers(self) -> dict[str, str]:
        if not self._access_token:
            raise DocuMindAPIError("Not authenticated — call login() first")
        return {"Authorization": f"Bearer {self._access_token}"}

    # ── knowledge bases ───────────────────────────────────────────────────

    async def create_kb(self, name: str, settings: dict[str, Any]) -> dict[str, Any]:
        resp = await self._client.post(
            "/api/v1/knowledge-bases",
            json={"name": name, "settings": settings},
            headers=self._headers(),
        )
        if resp.status_code not in (200, 201):
            raise DocuMindAPIError(
                f"create_kb failed ({resp.status_code}): {resp.text[:300]}"
            )
        return resp.json()

    async def get_kb(self, kb_id: str) -> dict[str, Any]:
        resp = await self._client.get(f"/api/v1/knowledge-bases/{kb_id}", headers=self._headers())
        resp.raise_for_status()
        return resp.json()

    async def delete_kb(self, kb_id: str) -> None:
        resp = await self._client.delete(f"/api/v1/knowledge-bases/{kb_id}", headers=self._headers())
        if resp.status_code not in (204, 404):
            logger.warning("delete_kb non-204 response: %s %s", resp.status_code, resp.text[:200])

    # ── documents ─────────────────────────────────────────────────────────

    async def upload_document(self, kb_id: str, file_path: Path) -> dict[str, Any]:
        ext = file_path.suffix.lstrip(".").lower()
        mime = _MIME_BY_EXT.get(ext, "application/octet-stream")
        with file_path.open("rb") as fh:
            files = {"file": (file_path.name, fh, mime)}
            data = {"kb_id": kb_id}
            resp = await self._client.post(
                "/api/v1/documents/upload",
                data=data,
                files=files,
                headers=self._headers(),
            )
        if resp.status_code != 202:
            raise DocuMindAPIError(
                f"upload_document failed for {file_path.name} ({resp.status_code}): {resp.text[:300]}"
            )
        return resp.json()

    async def get_document(self, doc_id: str) -> dict[str, Any]:
        resp = await self._client.get(f"/api/v1/documents/{doc_id}", headers=self._headers())
        resp.raise_for_status()
        return resp.json()

    async def wait_for_documents_ready(
        self,
        doc_ids: list[str],
        timeout_seconds: int,
        poll_interval_seconds: float,
    ) -> tuple[int, int, float, int]:
        """Poll until every document is 'ready' or 'failed'. Returns
        (ready_count, failed_count, avg_seconds_per_doc, total_size_bytes_ready)."""
        start = time.monotonic()
        per_doc_started = {doc_id: start for doc_id in doc_ids}
        finished: dict[str, tuple[str, float, int]] = {}  # doc_id -> (status, elapsed_seconds, size_bytes)

        while len(finished) < len(doc_ids):
            if time.monotonic() - start > timeout_seconds:
                for doc_id in doc_ids:
                    if doc_id not in finished:
                        finished[doc_id] = ("timeout", timeout_seconds, 0)
                break

            for doc_id in doc_ids:
                if doc_id in finished:
                    continue
                doc = await self.get_document(doc_id)
                status = doc.get("status")
                if status in ("ready", "failed"):
                    finished[doc_id] = (
                        status,
                        time.monotonic() - per_doc_started[doc_id],
                        int(doc.get("size_bytes") or 0),
                    )

            if len(finished) < len(doc_ids):
                await asyncio.sleep(poll_interval_seconds)

        ready = [s for s, _, _ in finished.values() if s == "ready"]
        failed_or_timeout = [s for s, _, _ in finished.values() if s != "ready"]
        elapsed = [t for s, t, _ in finished.values() if s == "ready"]
        total_bytes = sum(b for s, _, b in finished.values() if s == "ready")
        avg_seconds = sum(elapsed) / len(elapsed) if elapsed else 0.0
        return len(ready), len(failed_or_timeout), avg_seconds, total_bytes

    # ── chat ──────────────────────────────────────────────────────────────

    async def create_session(self, kb_id: str, title: str) -> dict[str, Any]:
        resp = await self._client.post(
            "/api/v1/chat/sessions",
            json={"kb_id": kb_id, "title": title},
            headers=self._headers(),
        )
        if resp.status_code != 201:
            raise DocuMindAPIError(
                f"create_session failed ({resp.status_code}): {resp.text[:300]}"
            )
        return resp.json()

    async def send_message(self, session_id: str, content: str) -> tuple[dict[str, Any], float]:
        start = time.monotonic()
        resp = await self._client.post(
            f"/api/v1/chat/sessions/{session_id}/messages",
            json={"content": content},
            headers=self._headers(),
        )
        latency_ms = (time.monotonic() - start) * 1000
        if resp.status_code != 200:
            raise DocuMindAPIError(
                f"send_message failed ({resp.status_code}): {resp.text[:300]}"
            )
        return resp.json(), latency_ms

    # ── eval ──────────────────────────────────────────────────────────────

    async def poll_eval_result(
        self, message_id: str, timeout_seconds: int, poll_interval_seconds: float
    ) -> Optional[dict[str, Any]]:
        """DeepEval scoring runs async on the eval_queue after send_message returns.
        Poll GET /eval/results/{message_id} (admin-only) until it appears or times out."""
        start = time.monotonic()
        while time.monotonic() - start < timeout_seconds:
            resp = await self._client.get(
                f"/api/v1/eval/results/{message_id}", headers=self._headers()
            )
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code != 404:
                logger.warning(
                    "poll_eval_result unexpected status %s: %s", resp.status_code, resp.text[:200]
                )
            await asyncio.sleep(poll_interval_seconds)
        return None
