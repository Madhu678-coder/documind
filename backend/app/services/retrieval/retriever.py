"""RetrievalResult dataclass shared by all retriever implementations."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RetrievalResult:
    chunk_id: str
    document_id: str
    doc_filename: str
    text: str
    score: float
    page_number: int
    chunk_index: int
