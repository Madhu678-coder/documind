"""PageIndex page extractor — extracts per-page content from any document format.

This is the foundation of the PageIndex algorithm. Unlike raw text extraction,
we preserve page boundaries so we can:
  - Build a tree with accurate page numbers
  - Retrieve specific page ranges at query time

Output schema per page:
  {
    "page": int,          # 1-indexed page number
    "content": str,       # full text content of the page
    "images": [           # extracted images (PDFs only)
      {"path": str}
    ],
    "word_count": int,    # quick density signal for structure analysis
    "headings": [str],    # detected headings on this page (heuristic)
  }
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Minimum words per page to be considered non-empty
_MIN_WORDS = 5
# Minimum image dimension to save (skip tiny bullets/icons)
_MIN_IMAGE_DIM = 32


# ---------------------------------------------------------------------------
# Heading heuristics
# ---------------------------------------------------------------------------

def _detect_headings(text: str) -> list[str]:
    """Heuristically detect headings in page text.

    Headings tend to be:
    - Short lines (< 80 chars)
    - All-caps or Title Case
    - Numbered (1. / 1.1 / Chapter 1)
    - Followed by a blank line
    """
    headings: list[str] = []
    lines = text.split("\n")
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or len(stripped) > 120:
            continue
        # Numbered heading: "1.", "1.1", "Chapter 1", "Section 2.3"
        if re.match(r"^(Chapter|Section|Part|Appendix|\d+\.[\d\.]*)\s+\S", stripped, re.IGNORECASE):
            headings.append(stripped)
            continue
        # Short ALL-CAPS line (at least 3 words)
        words = stripped.split()
        if len(words) >= 2 and stripped == stripped.upper() and stripped.isalpha() or \
                (len(stripped) < 80 and stripped.istitle() and len(words) >= 2):
            # Check it's not just a normal sentence
            if len(stripped) < 80 and not stripped.endswith((",", ";", ":")):
                headings.append(stripped)
    return headings[:5]  # cap at 5 per page


# ---------------------------------------------------------------------------
# PDF extraction
# ---------------------------------------------------------------------------

def _extract_pdf_pages(
    file_path: str,
    doc_name: str,
    images_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Extract per-page content from a PDF using pymupdf dict-mode.

    Mirrors and extends OpenKB's convert_pdf_to_pages() with:
    - Heading detection per page
    - Word count per page
    - Richer text reconstruction (preserves paragraph spacing)
    """
    import pymupdf  # type: ignore[import]

    if images_dir:
        images_dir.mkdir(parents=True, exist_ok=True)

    pages: list[dict[str, Any]] = []
    img_counter = 0

    with pymupdf.open(file_path) as doc:
        for page_idx in range(len(doc)):
            page = doc[page_idx]
            page_num = page_idx + 1
            text_blocks: list[str] = []
            page_images: list[dict] = []

            for block in page.get_text("dict")["blocks"]:
                if block["type"] == 0:  # text block
                    block_lines: list[str] = []
                    for line in block["lines"]:
                        line_text = "".join(span["text"] for span in line["spans"])
                        if line_text.strip():
                            block_lines.append(line_text)
                    if block_lines:
                        text_blocks.append("\n".join(block_lines))

                elif block["type"] == 1 and images_dir:  # image block
                    # bbox is (x0, y0, x1, y1) — derive width/height from it
                    bbox = block.get("bbox", (0, 0, 0, 0))
                    w = bbox[2] - bbox[0]
                    h = bbox[3] - bbox[1]
                    if w < _MIN_IMAGE_DIM or h < _MIN_IMAGE_DIM:
                        continue
                    image_bytes = block.get("image")
                    if not image_bytes:
                        continue
                    try:
                        pix = pymupdf.Pixmap(image_bytes)
                        if pix.n > 4:
                            pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
                        img_counter += 1
                        filename = f"p{page_num}_img{img_counter}.png"
                        (images_dir / filename).write_bytes(pix.tobytes("png"))
                        img_path = f"sources/images/{doc_name}/{filename}"
                        text_blocks.append(f"![image]({img_path})")
                        page_images.append({"path": img_path})
                    except Exception:
                        pass

            content = "\n\n".join(text_blocks).strip()

            # Fallback to simple get_text() if dict-mode gave almost nothing
            if len(content) < 20:
                content = page.get_text().strip()

            words = len(content.split()) if content else 0
            headings = _detect_headings(content) if content else []

            pages.append({
                "page": page_num,
                "content": content,
                "images": page_images,
                "word_count": words,
                "headings": headings,
            })

    logger.info(
        "PDF page extraction complete",
        extra={"pages": len(pages), "doc": doc_name},
    )
    return pages


# ---------------------------------------------------------------------------
# Markdown / plain-text extraction
# ---------------------------------------------------------------------------

def _extract_text_pages(file_path: str, chars_per_page: int = 3000) -> list[dict[str, Any]]:
    """Split a text/markdown file into virtual pages.

    Since text files have no native page concept, we split by logical units:
    1. Markdown headings (## / #) create natural page breaks
    2. If no headings found, split by character count with paragraph alignment
    """
    text = Path(file_path).read_text(encoding="utf-8", errors="replace")
    lines = text.split("\n")

    # Try heading-based splitting first (for markdown)
    segments: list[str] = []
    current: list[str] = []
    for line in lines:
        if re.match(r"^#{1,3}\s+\S", line) and current:
            # New heading — flush current segment
            segment = "\n".join(current).strip()
            if segment:
                segments.append(segment)
            current = [line]
        else:
            current.append(line)
    if current:
        segment = "\n".join(current).strip()
        if segment:
            segments.append(segment)

    # If heading-based split gave only 1 segment, fall back to character split
    if len(segments) <= 1:
        segments = []
        start = 0
        while start < len(text):
            end = start + chars_per_page
            # Align to paragraph boundary
            if end < len(text):
                newline_pos = text.rfind("\n\n", start, end + 500)
                if newline_pos > start:
                    end = newline_pos
            segments.append(text[start:end].strip())
            start = end

    pages = []
    for i, seg in enumerate(segments, 1):
        if not seg:
            continue
        words = len(seg.split())
        headings = _detect_headings(seg)
        pages.append({
            "page": i,
            "content": seg,
            "images": [],
            "word_count": words,
            "headings": headings,
        })

    logger.info("Text page extraction complete", extra={"pages": len(pages)})
    return pages


# ---------------------------------------------------------------------------
# DOCX / PPTX / HTML / XLSX extraction
# ---------------------------------------------------------------------------

def _extract_markitdown_pages(file_path: str, chars_per_page: int = 3000) -> list[dict[str, Any]]:
    """Convert non-PDF formats to markdown via markitdown, then split into pages."""
    try:
        from markitdown import MarkItDown  # type: ignore[import]
        mid = MarkItDown()
        result = mid.convert(file_path)
        markdown = result.text_content or ""
    except ImportError:
        # Fallback: raw text read
        try:
            markdown = Path(file_path).read_text(encoding="utf-8", errors="replace")
        except Exception:
            markdown = ""

    if not markdown.strip():
        return [{"page": 1, "content": "", "images": [], "word_count": 0, "headings": []}]

    # Write to a temp .md file and reuse the text extractor
    import tempfile
    import os
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as tmp:
        tmp.write(markdown)
        tmp_path = tmp.name
    try:
        pages = _extract_text_pages(tmp_path, chars_per_page=chars_per_page)
    finally:
        os.unlink(tmp_path)
    return pages


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_pages(
    file_path: str,
    file_type: str,
    doc_name: str | None = None,
    images_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Extract per-page content from any supported document format.

    Args:
        file_path: Absolute path to the document.
        file_type: Extension without dot — "pdf", "docx", "txt", "md", etc.
        doc_name: Used for image path construction in PDFs.
        images_dir: Directory to save extracted images (PDFs only).

    Returns:
        List of page dicts — see module docstring for schema.
        Always returns at least 1 page (even for empty docs).
    """
    ft = (file_type or "").lower().strip(".")
    name = doc_name or Path(file_path).stem

    try:
        if ft == "pdf":
            pages = _extract_pdf_pages(file_path, name, images_dir)
        elif ft in ("txt", "md", "markdown"):
            pages = _extract_text_pages(file_path)
        else:
            # DOCX, PPTX, HTML, XLSX, CSV — use markitdown
            pages = _extract_markitdown_pages(file_path)
    except Exception as exc:
        logger.error(
            "Page extraction failed, returning empty result",
            extra={"file": file_path, "error": str(exc)},
        )
        pages = []

    # Filter out truly empty pages but preserve empty PDFs gracefully
    non_empty = [p for p in pages if p.get("word_count", 0) >= _MIN_WORDS or p.get("content", "").strip()]
    if not non_empty:
        non_empty = [{"page": 1, "content": "", "images": [], "word_count": 0, "headings": []}]

    return non_empty


def get_page_content(pages: list[dict], page_spec: str) -> str:
    """Retrieve and format content for a page range spec like '3-5,7,10-12'.

    Args:
        pages: List of page dicts from extract_pages().
        page_spec: Comma-separated page numbers and ranges.

    Returns:
        Formatted string with page markers and content.
    """
    # Parse page spec
    requested: set[int] = set()
    for part in page_spec.split(","):
        part = part.strip()
        if "-" in part:
            segs = part.split("-")
            try:
                requested.update(range(int(segs[0]), int(segs[1]) + 1))
            except (ValueError, IndexError):
                pass
        else:
            try:
                requested.add(int(part))
            except ValueError:
                pass

    page_map = {p["page"]: p for p in pages}
    parts: list[str] = []
    for num in sorted(requested):
        if num in page_map:
            p = page_map[num]
            parts.append(f"[Page {num}]\n{p['content']}")

    return "\n\n".join(parts) if parts else ""
