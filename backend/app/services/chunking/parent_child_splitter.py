"""Parent-child text splitter: splits into parent paragraphs then child sub-chunks."""
from __future__ import annotations

from app.services.chunking.recursive_splitter import RecursiveCharacterSplitter

_PARENT_SEPARATOR = "\n\n"
_CHILD_CHUNK_SIZE = 300
_CHILD_CHUNK_OVERLAP = 50


class ParentChildSplitter:
    """
    Two-pass splitter.
    1. First splits on double newlines to create parent chunks.
    2. Then splits each parent into smaller child chunks using RecursiveCharacterSplitter.

    Returns all chunks (parents and children) so that:
    - Parent chunks have parent_chunk_index = None
    - Child chunks have parent_chunk_index = index of their parent
    """

    def __init__(
        self,
        parent_chunk_size: int = 2000,
        child_chunk_size: int = _CHILD_CHUNK_SIZE,
        child_chunk_overlap: int = _CHILD_CHUNK_OVERLAP,
    ):
        self.parent_chunk_size = parent_chunk_size
        self.child_splitter = RecursiveCharacterSplitter(
            chunk_size=child_chunk_size,
            chunk_overlap=child_chunk_overlap,
        )

    def split(self, text: str) -> list[dict]:
        """
        Split text into parent and child chunks.

        Returns:
            List of dicts with keys: text, char_start, char_end, page_number,
            chunk_index, parent_chunk_index (None for parents, int for children)
        """
        # Step 1: split into parent chunks on double newlines
        parent_splitter = RecursiveCharacterSplitter(
            chunk_size=self.parent_chunk_size,
            chunk_overlap=0,
            separators=["\n\n", "\n"],
        )
        parent_raw = parent_splitter.split(text)

        result: list[dict] = []
        global_chunk_index = 0
        parent_index_map: list[int] = []  # maps parent_raw index -> global chunk_index

        # Step 2: add parent chunks
        for parent_raw_idx, parent in enumerate(parent_raw):
            parent_global_idx = global_chunk_index
            parent_index_map.append(parent_global_idx)
            result.append({
                "text": parent["text"],
                "char_start": parent["char_start"],
                "char_end": parent["char_end"],
                "page_number": parent["page_number"],
                "chunk_index": global_chunk_index,
                "parent_chunk_index": None,  # parents have no parent
            })
            global_chunk_index += 1

        # Step 3: add child chunks for each parent
        for parent_raw_idx, parent in enumerate(parent_raw):
            parent_global_idx = parent_index_map[parent_raw_idx]
            children = self.child_splitter.split(parent["text"])

            for child in children:
                # Adjust char positions relative to the full document
                abs_char_start = parent["char_start"] + child["char_start"]
                abs_char_end = parent["char_start"] + child["char_end"]

                result.append({
                    "text": child["text"],
                    "char_start": abs_char_start,
                    "char_end": abs_char_end,
                    "page_number": child["page_number"],
                    "chunk_index": global_chunk_index,
                    "parent_chunk_index": parent_global_idx,
                })
                global_chunk_index += 1

        return result
