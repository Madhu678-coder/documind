"""Chunker factory: creates the appropriate splitter based on strategy."""
from __future__ import annotations

from typing import Callable


class ChunkerFactory:
    """Factory for creating text chunker callables."""

    @staticmethod
    def create(
        strategy: str,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
    ) -> Callable[[str], list[dict]]:
        """
        Create a chunker callable.

        Args:
            strategy: 'recursive' or 'parent_child'
            chunk_size: Target size of each chunk in characters
            chunk_overlap: Number of overlapping characters between consecutive chunks

        Returns:
            A callable that accepts a text string and returns a list of chunk dicts
        """
        if strategy == "recursive":
            from app.services.chunking.recursive_splitter import RecursiveCharacterSplitter
            splitter = RecursiveCharacterSplitter(
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
            )
            return splitter.split

        elif strategy == "parent_child":
            from app.services.chunking.parent_child_splitter import ParentChildSplitter
            splitter = ParentChildSplitter(
                parent_chunk_size=chunk_size * 2,  # parents are larger
                child_chunk_size=chunk_size // 3,  # children are smaller
                child_chunk_overlap=chunk_overlap // 4,
            )
            return splitter.split

        else:
            raise ValueError(f"Unknown chunking strategy: {strategy!r}. Must be 'recursive' or 'parent_child'.")
