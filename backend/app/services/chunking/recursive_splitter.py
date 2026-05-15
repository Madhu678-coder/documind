"""Recursive character text splitter for document chunking."""
from __future__ import annotations


_DEFAULT_SEPARATORS = ["\n\n", "\n", ". ", " ", ""]


class RecursiveCharacterSplitter:
    """
    Recursively splits text using a hierarchy of separators.

    Splits on separators in order: double newline, newline, sentence, word, character.
    Maintains overlap between chunks for context continuity.
    """

    def __init__(
        self,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
        separators: list[str] | None = None,
    ):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.separators = separators if separators is not None else _DEFAULT_SEPARATORS

    def _split_text(self, text: str, separators: list[str]) -> list[str]:
        """Recursively split text using the given separators."""
        if not text:
            return []

        # Find the first separator that actually appears in the text
        separator = separators[-1]  # default: split by character
        new_separators: list[str] = []
        for i, sep in enumerate(separators):
            if sep == "":
                separator = sep
                break
            if sep in text:
                separator = sep
                new_separators = separators[i + 1:]
                break

        # Split on the chosen separator
        if separator:
            splits = text.split(separator)
        else:
            splits = list(text)

        good_splits: list[str] = []
        current: list[str] = []
        current_len = 0

        for s in splits:
            s_len = len(s)
            if current_len + s_len + (len(separator) if current else 0) <= self.chunk_size:
                if current:
                    current_len += len(separator)
                current.append(s)
                current_len += s_len
            else:
                if current:
                    merged = separator.join(current)
                    # Recursively split if still too large and more separators available
                    if len(merged) > self.chunk_size and new_separators:
                        good_splits.extend(self._split_text(merged, new_separators))
                    else:
                        good_splits.append(merged)
                    current = []
                    current_len = 0
                # Handle individual split that is itself too large
                if s_len > self.chunk_size and new_separators:
                    good_splits.extend(self._split_text(s, new_separators))
                else:
                    current = [s]
                    current_len = s_len

        if current:
            merged = separator.join(current)
            if len(merged) > self.chunk_size and new_separators:
                good_splits.extend(self._split_text(merged, new_separators))
            else:
                good_splits.append(merged)

        return [s for s in good_splits if s.strip()]

    def split(self, text: str) -> list[dict]:
        """
        Split text into chunks with metadata.

        Returns:
            List of dicts with keys: text, char_start, char_end, page_number, chunk_index
        """
        raw_chunks = self._split_text(text, self.separators)

        # Apply overlap: merge consecutive chunks with overlap
        final_chunks: list[str] = []
        if not raw_chunks:
            return []

        final_chunks.append(raw_chunks[0])
        for i in range(1, len(raw_chunks)):
            prev = final_chunks[-1]
            curr = raw_chunks[i]
            # Add overlap from end of previous chunk
            if self.chunk_overlap > 0 and len(prev) >= self.chunk_overlap:
                overlap_text = prev[-self.chunk_overlap:]
                combined = overlap_text + curr
                # Trim to chunk_size if needed
                if len(combined) > self.chunk_size:
                    combined = combined[-self.chunk_size:]
                final_chunks.append(combined)
            else:
                final_chunks.append(curr)

        # Build result with positional metadata
        result: list[dict] = []
        char_pos = 0
        total_chars = len(text)

        for idx, chunk_text in enumerate(final_chunks):
            # Find approximate position in original text
            start = text.find(chunk_text.strip()[:50], char_pos)
            if start == -1:
                start = char_pos
            end = start + len(chunk_text)
            char_pos = max(char_pos, start)

            # Estimate page number based on position (rough approximation: ~3000 chars/page)
            chars_per_page = 3000
            page_number = max(1, (start // chars_per_page) + 1)

            result.append({
                "text": chunk_text,
                "char_start": start,
                "char_end": min(end, total_chars),
                "page_number": page_number,
                "chunk_index": idx,
            })

        return result
