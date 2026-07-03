
"""PageIndex structure analyzer — detects section hierarchy using the Vectify algorithm.

The real PageIndex algorithm has three paths:

  Path 1 — PDF has TOC with page numbers:
    Use PDF bookmarks/outline directly → accurate tree with no LLM needed for structure

  Path 2 — PDF has TOC but no page numbers:
    Use TOC for section titles/hierarchy, then run token-chunk analysis to find
    which physical page each section starts on

  Path 3 — No TOC (or non-PDF):
    Group pages into ~20,000-token chunks.
    For each chunk: send content + running TOC (accumulated so far) to LLM.
    LLM returns local section structure with positions relative to the chunk.
    Apply physical page offset to convert chunk-local positions to real page numbers:
        global_page = chunk_start_physical_page + local_position - 1

The physical page index from pymupdf is the source of truth for page numbers.
The LLM only identifies WHERE in the content section boundaries fall;
pymupdf tells us WHAT actual page number that maps to.
"""
from __future__ import annotations

import json
import logging
import random
from collections import Counter
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.llm.provider import LLMProvider

logger = logging.getLogger(__name__)

# ~20,000 tokens per chunk (mirrors Vectify PageIndex default)
_MAX_TOKENS_PER_CHUNK = 20_000
# Overlap: 1 page carried into the next chunk (mirrors Vectify overlap_page=1)
_CHUNK_OVERLAP_PAGES = 1

# ---------------------------------------------------------------------------
# Exact Vectify PageIndex prompts
# (source: github.com/VectifyAI/PageIndex — pageindex/page_index.py)
# ---------------------------------------------------------------------------

# Path 3 — first chunk: generate initial tree structure
_GENERATE_TOC_INIT = """\
You are an expert in extracting hierarchical tree structure, your task is to generate the tree structure of the document.

The structure variable is the numeric system which represents the index of the hierarchy section in the table of contents. For example, the first section has structure index 1, the first subsection has structure index 1.1, the second subsection has structure index 1.2, etc.

For the title, you need to extract the original title from the text, only fix the space inconsistency.

The provided text contains tags like <physical_index_X> and <physical_index_X> to indicate the start and end of page X.

For the physical_index, you need to extract the physical index of the start of the section from the text. Keep the <physical_index_X> format.

The response should be in the following format.
    [
        {
            "structure": <structure index, "x.x.x"> (string),
            "title": <title of the section, keep the original title>,
            "physical_index": "<physical_index_X> (keep the format)"
        },
    ],

Directly return the final JSON structure. Do not output anything else."""

# Path 3 — subsequent chunks: continue from previously built tree
_GENERATE_TOC_CONTINUE = """\
You are an expert in extracting hierarchical tree structure.
You are given a tree structure of the previous part and the text of the current part.
Your task is to continue the tree structure from the previous part to include the current part.

The structure variable is the numeric system which represents the index of the hierarchy section in the table of contents. For example, the first section has structure index 1, the first subsection has structure index 1.1, the second subsection has structure index 1.2, etc.

For the title, you need to extract the original title from the text, only fix the space inconsistency.

The provided text contains tags like <physical_index_X> and <physical_index_X> to indicate the start and end of page X.

For the physical_index, you need to extract the physical index of the start of the section from the text. Keep the <physical_index_X> format.

The response should be in the following format.
    [
        {
            "structure": <structure index, "x.x.x"> (string),
            "title": <title of the section, keep the original title>,
            "physical_index": "<physical_index_X> (keep the format)"
        },
        ...
    ]

Directly return the additional part of the final JSON structure. Do not output anything else."""

# Verification — check if a section title appears on its claimed page
_CHECK_TITLE_APPEARANCE = """\
Your job is to check if the given section appears or starts in the given page_text.

Note: do fuzzy matching, ignore any space inconsistency in the page_text.

Reply format:
{
    "thinking": <why do you think the section appears or starts in the page_text>,
    "answer": "yes or no" (yes if the section appears or starts in the page_text, no otherwise)
}
Directly return the final JSON structure. Do not output anything else."""

# Fix incorrect TOC entry — find the real physical index in a page range
_FIX_TOC_ITEM = """\
You are given a section title and several pages of a document, your job is to find the physical index of the start page of the section in the partial document.

The provided pages contains tags like <physical_index_X> and <physical_index_X> to indicate the physical location of the page X.

Reply in a JSON format:
{
    "thinking": <explain which page, started and closed by <physical_index_X>, contains the start of this section>,
    "physical_index": "<physical_index_X>" (keep the format)
}
Directly return the final JSON structure. Do not output anything else."""

# Path 2 — TOC no page numbers: match TOC entries to physical pages
_ADD_PAGE_NUMBER_TO_TOC = """\
You are given an JSON structure of a document and a partial part of the document. Your task is to check if the title that is described in the structure is started in the partial given document.

The provided text contains tags like <physical_index_X> and <physical_index_X> to indicate the physical location of the page X.

If the full target section starts in the partial given document, insert the given JSON structure with the "start": "yes", and "start_index": "<physical_index_X>".

If the full target section does not start in the partial given document, insert "start": "no", "start_index": None.

The response should be in the following format.
    [
        {
            "structure": <structure index, "x.x.x" or None> (string),
            "title": <title of the section>,
            "start": "<yes or no>",
            "physical_index": "<physical_index_X> (keep the format)" or None
        },
        ...
    ]
The given structure contains the result of the previous part, you need to fill the result of the current part, do not change the previous result.
Directly return the final JSON structure. Do not output anything else."""

# ---------------------------------------------------------------------------
# Path 1 helpers — PDF TOC with page numbers
# ---------------------------------------------------------------------------

def extract_pdf_toc(file_path: str) -> list[dict]:
    """Extract TOC from PDF bookmarks/outline via pymupdf.

    Returns list of {level, title, page} dicts (1-indexed pages).
    Returns [] if no TOC or not a PDF.
    """
    try:
        import pymupdf  # type: ignore[import]
        with pymupdf.open(file_path) as doc:
            raw = doc.get_toc()  # [(level, title, page), ...]
            if not raw:
                return []
            return [
                {"level": item[0], "title": str(item[1]).strip(), "page": int(item[2])}
                for item in raw
                if item[1] and item[1].strip()
            ]
    except Exception as exc:
        logger.debug("PDF TOC extraction failed: %s", exc)
        return []


def toc_has_valid_pages(toc: list[dict], total_pages: int) -> bool:
    """Return True when >= 80% of TOC entries have valid page numbers."""
    if not toc:
        return False
    valid = sum(1 for e in toc if 1 <= e.get("page", 0) <= total_pages)
    return valid >= len(toc) * 0.8


# ---------------------------------------------------------------------------
# Page-offset detection — random sampling + LLM verification (Vectify step)
# ---------------------------------------------------------------------------

_OFFSET_VERIFY_SYSTEM = """\
You are verifying whether a PDF's table-of-contents page numbers match the actual document pages.

You will be given:
  - A list of TOC entries (title → reported page number)
  - The content of one or more sampled pages from the document

For the sampled page shown, identify which TOC section that content belongs to,
then report the TOC's claimed page for that section.

Return JSON:
{
  "toc_title":    "<exact title from the TOC list>",
  "toc_page":     <int — the page number the TOC claims for this section>,
  "actual_page":  <int — the page number shown in the sampled content header>
}

If you cannot confidently match the content to any TOC section, return:
{"toc_title": null, "toc_page": null, "actual_page": null}

Return ONLY valid JSON, no explanation."""


async def _detect_page_number_offset(
    toc: list[dict],
    pages: list[dict],
    llm: "LLMProvider",
    n_samples: int = 6,
) -> int:
    """Detect the page-number offset between TOC bookmarks and pymupdf physical pages.

    Some PDFs have a systematic discrepancy: e.g. roman-numeral front matter
    (i–xvi) is counted by pymupdf but the TOC treats page 1 as the first body
    page.  If the TOC says "Chapter 1 → page 1" but pymupdf's page 1 is the
    preface, the offset is +16.

    Algorithm (mirrors Vectify PageIndex):
      1. Randomly sample n_samples page indices across the full page range.
      2. For each sampled page, show the LLM the page content + full TOC list.
      3. LLM identifies which TOC section this page belongs to and what the
         TOC claims as that section's page.
      4. offset = actual_pymupdf_page − toc_claimed_page  (per sample)
      5. Return the mode (most-common offset) across all samples.

    Returns 0 if detection fails or offset is unanimous at 0.
    """
    if not toc or not pages:
        return 0

    total_pages = pages[-1]["page"]
    page_map = {p["page"]: p for p in pages}

    # Build a short TOC summary to include in each LLM call
    toc_summary = "\n".join(
        f"  - {e['title']} → page {e['page']}" for e in toc[:40]
    )

    # Randomly sample page indices spread across the document
    # Avoid the very first and last few pages (often cover/appendix with no TOC match)
    lo = max(1, int(total_pages * 0.05))
    hi = min(total_pages, int(total_pages * 0.95))
    population = list(range(lo, hi + 1))
    sample_pages = random.sample(population, min(n_samples, len(population)))

    offsets: list[int] = []

    for pn in sample_pages:
        page = page_map.get(pn)
        if not page:
            continue
        content_snippet = page.get("content", "")[:600].strip()
        if not content_snippet:
            continue

        prompt = (
            f"Table of Contents:\n{toc_summary}\n\n"
            f"Sampled page content (this is pymupdf page {pn}):\n"
            f"--- Page {pn} ---\n{content_snippet}"
        )

        try:
            resp = await llm.complete(
                [{"role": "user", "content": prompt}],
                system_prompt=_OFFSET_VERIFY_SYSTEM,
                max_tokens=128,
            )
            raw = resp.content.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1].removeprefix("json").strip()
            data = json.loads(raw)
            toc_pg = data.get("toc_page")
            actual_pg = data.get("actual_page")
            if toc_pg is not None and actual_pg is not None:
                offsets.append(int(actual_pg) - int(toc_pg))
        except Exception as exc:
            logger.debug("Page offset sample %d failed: %s", pn, exc)

    if not offsets:
        return 0

    detected = Counter(offsets).most_common(1)[0][0]
    if detected != 0:
        logger.info(
            "PageIndex: detected TOC page offset %+d (from %d samples)",
            detected, len(offsets),
        )
    return detected


async def _verify_section_boundaries(
    sections_flat: list[dict],
    pages: list[dict],
    llm: "LLMProvider",
    n_samples: int = 4,
) -> list[dict]:
    """Spot-check n_samples section boundaries: verify the content at
    page_start actually matches the section title.

    If the LLM says the content doesn't match, it looks ±2 pages for a
    better fit and adjusts page_start.  Used as a final correction pass
    after TOC-based tree building.

    Only checks sections where we have page content — skips any that fall
    outside the extracted page range.
    """
    if not sections_flat or not pages:
        return sections_flat

    page_map = {p["page"]: p for p in pages}
    total_pages = pages[-1]["page"]

    # Sample min(n_samples, len(sections_flat)) sections randomly
    sample_indices = random.sample(
        range(len(sections_flat)), min(n_samples, len(sections_flat))
    )

    for idx in sample_indices:
        section = sections_flat[idx]
        claimed = section.get("page_start", 1)
        title = section.get("title", "")

        # Gather content from claimed page ± 2 using Vectify <physical_index_X> format
        search_range = range(max(1, claimed - 2), min(total_pages, claimed + 2) + 1)
        snippets = []
        for pn in search_range:
            p = page_map.get(pn)
            if p:
                snippets.append(
                    f"<physical_index_{pn}>\n{p.get('content', '')[:400]}\n<physical_index_{pn}>"
                )

        if not snippets:
            continue

        # Step 1 — check_title_appearance (Vectify exact prompt)
        check_prompt = (
            f"The given section title is {title}.\n"
            f"The given page_text is:\n" + "\n\n".join(snippets)
        )

        try:
            resp = await llm.complete(
                [{"role": "user", "content": check_prompt}],
                system_prompt=_CHECK_TITLE_APPEARANCE,
                max_tokens=256,
            )
            raw = resp.content.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1].removeprefix("json").strip()
            data = json.loads(raw)
            answer = data.get("answer", "yes")

            if answer.lower() == "no":
                # Step 2 — fix with single_toc_item_index_fixer (Vectify exact prompt)
                fix_prompt = (
                    f"Section Title:\n{title}\n\n"
                    f"Document pages:\n" + "\n\n".join(snippets)
                )
                fix_resp = await llm.complete(
                    [{"role": "user", "content": fix_prompt}],
                    system_prompt=_FIX_TOC_ITEM,
                    max_tokens=128,
                )
                fix_raw = fix_resp.content.strip()
                if fix_raw.startswith("```"):
                    fix_raw = fix_raw.split("```")[1].removeprefix("json").strip()
                fix_data = json.loads(fix_raw)
                correct = _parse_physical_index(fix_data.get("physical_index"))
                if correct is not None and correct != claimed and 1 <= correct <= total_pages:
                    logger.info(
                        "PageIndex: boundary correction '%s': %d → %d",
                        title, claimed, correct,
                    )
                    sections_flat[idx]["page_start"] = correct
        except Exception as exc:
            logger.debug("Boundary verify failed for '%s': %s", title, exc)

    return sections_flat


def _toc_to_sections(toc: list[dict], total_pages: int) -> list[dict]:
    """Convert flat TOC list to nested section dicts with page ranges.

    Page end = start of next sibling/parent section - 1, or total_pages.
    """
    if not toc:
        return []

    # Build flat list with end pages
    entries: list[dict] = []
    for i, item in enumerate(toc):
        ps = item["page"]
        # page_end = next entry's page - 1 (same or shallower level), or total
        pe = total_pages
        for j in range(i + 1, len(toc)):
            if toc[j]["level"] <= item["level"]:
                pe = toc[j]["page"] - 1
                break
        pe = max(ps, min(pe, total_pages))
        entries.append({
            "node_id": f"n{i+1}",
            "title":   item["title"],
            "level":   item["level"],
            "page_start": ps,
            "page_end":   pe,
            "depth":   item["level"],
            "children": [],
            "text":    "",
            "summary": "",
            "images":  [],
        })

    # Nest by level
    return _nest_sections(entries)


def _nest_sections(flat: list[dict]) -> list[dict]:
    """Convert a flat list of sections (with level) to a nested tree."""
    if not flat:
        return []

    root: list[dict] = []
    stack: list[dict] = []  # (node,)

    for node in flat:
        level = node["level"]
        # Pop stack until parent level
        while stack and stack[-1]["level"] >= level:
            stack.pop()
        if stack:
            stack[-1]["children"].append(node)
        else:
            root.append(node)
        stack.append(node)

    return root

# ---------------------------------------------------------------------------
# Token-chunk grouping (Path 2 & 3)
# ---------------------------------------------------------------------------

def _count_tokens(text: str, model: str = "gpt-4") -> int:
    """Count real tokens using litellm (mirrors Vectify's token counting)."""
    try:
        import litellm
        return litellm.token_counter(model=model, text=text)
    except Exception:
        # Fallback: estimate at 4 chars/token if litellm unavailable
        return max(1, len(text) // 4)


def _group_pages_into_chunks(
    pages: list[dict],
    max_tokens: int = _MAX_TOKENS_PER_CHUNK,
    overlap_pages: int = _CHUNK_OVERLAP_PAGES,
    model: str = "gpt-4",
) -> list[list[dict]]:
    """Group pages into ~20k-token chunks using real token counts (Vectify pattern).

    Mirrors Vectify's page_list_to_group_text():
    1. Count actual tokens per page via litellm.token_counter()
    2. Calculate average_tokens_per_part to balance chunk sizes evenly
    3. Overlap by overlap_pages pages so sections near boundaries aren't missed
    """
    if not pages:
        return []

    # Count real tokens for each page
    token_lengths = [_count_tokens(p.get("content", ""), model) for p in pages]
    total_tokens = sum(token_lengths)

    if total_tokens <= max_tokens:
        return [pages]  # everything fits in one chunk

    # Vectify's balanced chunk sizing formula:
    # average = ceil((total/num_parts + max_tokens) / 2)
    # This prevents the last chunk being tiny by averaging the ideal and max sizes
    import math
    expected_parts = math.ceil(total_tokens / max_tokens)
    average_tokens_per_part = math.ceil(((total_tokens / expected_parts) + max_tokens) / 2)

    chunks: list[list[dict]] = []
    current: list[dict] = []
    current_tokens = 0

    for i, (page, page_tokens) in enumerate(zip(pages, token_lengths)):
        if current_tokens + page_tokens > average_tokens_per_part and current:
            chunks.append(current)
            # Overlap: carry back overlap_pages pages into next chunk
            overlap_start = max(i - overlap_pages, 0)
            current = pages[overlap_start:i]
            current_tokens = sum(token_lengths[overlap_start:i])

        current.append(page)
        current_tokens += page_tokens

    if current:
        chunks.append(current)

    return chunks


def _format_chunk_for_llm(chunk_pages: list[dict], max_content_chars: int = 60_000) -> str:
    """Format a chunk of pages using Vectify's <physical_index_X> tag format.

    Each page is wrapped with opening and closing <physical_index_X> tags so
    the LLM can reference and return exact physical page numbers.
    This matches the exact format used by the Vectify PageIndex implementation.
    """
    parts: list[str] = []
    total = 0
    for p in chunk_pages:
        pn = p["page"]
        content = p.get("content", "").strip()
        # Vectify format: <physical_index_X> ... <physical_index_X>
        block = f"<physical_index_{pn}>\n{content}\n<physical_index_{pn}>\n"
        if total + len(block) > max_content_chars:
            remaining = max_content_chars - total
            if remaining > 200:
                parts.append(block[:remaining] + "\n…")
            break
        parts.append(block)
        total += len(block)
    return "\n".join(parts)

# ---------------------------------------------------------------------------
# Helpers — parse <physical_index_X> format (Vectify standard)
# ---------------------------------------------------------------------------

import re as _re

def _parse_physical_index(value: str | int | None) -> int | None:
    """Convert '<physical_index_5>' or 5 or '5' to int 5. Returns None on failure."""
    if value is None:
        return None
    if isinstance(value, int):
        return value
    s = str(value).strip()
    # Match <physical_index_5> or physical_index_5
    m = _re.search(r"physical_index_(\d+)", s)
    if m:
        return int(m.group(1))
    try:
        return int(s)
    except (ValueError, TypeError):
        return None


def _parse_vectify_response(content: str) -> list[dict]:
    """Parse LLM JSON list response (Vectify format).

    Expected items: {"structure": "1.2", "title": "...", "physical_index": "<physical_index_X>"}
    Returns list of dicts with 'title', 'structure', 'physical_index' (int).
    """
    raw = content.strip()
    if raw.startswith("```"):
        first_nl = raw.find("\n")
        raw = raw[first_nl + 1:] if first_nl != -1 else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.removeprefix("json").strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        try:
            from json_repair import repair_json  # type: ignore[import]
            data = json.loads(repair_json(raw))
        except Exception:
            return []

    if not isinstance(data, list):
        return []

    result = []
    for item in data:
        if not isinstance(item, dict) or not item.get("title"):
            continue
        pi = _parse_physical_index(item.get("physical_index"))
        if pi is None:
            continue
        result.append({
            "title":          str(item["title"]).strip(),
            "structure":      str(item.get("structure") or ""),
            "physical_index": pi,
        })
    return result


def _structure_to_level(structure: str) -> int:
    """Convert Vectify structure string '1.2.3' → depth int (1-indexed)."""
    if not structure:
        return 1
    return min(3, len(structure.split(".")))


# ---------------------------------------------------------------------------
# Path 3 — No TOC: token-chunked LLM analysis (Vectify generate_toc_init/continue)
# ---------------------------------------------------------------------------

async def _analyze_no_toc(
    pages: list[dict],
    filename: str,
    llm: "LLMProvider",
) -> tuple[list[dict], str]:
    """Path 3: full token-chunk analysis using Vectify's exact prompts.

    Chunk 1  → _GENERATE_TOC_INIT   (no prior context)
    Chunk 2+ → _GENERATE_TOC_CONTINUE (passes accumulated tree as context)

    Each page is wrapped as <physical_index_X>…<physical_index_X> so the LLM
    returns exact physical page numbers back in the same tag format.
    """
    chunks = _group_pages_into_chunks(pages)
    accumulated: list[dict] = []   # flat list of {title, structure, physical_index}

    logger.info("PageIndex Path 3: %d chunks for '%s'", len(chunks), filename)

    for chunk_idx, chunk_pages in enumerate(chunks):
        if not chunk_pages:
            continue

        chunk_text = _format_chunk_for_llm(chunk_pages)
            # First chunk — generate initial tree
            prompt = f"Given text:\n{chunk_text}"
            system = _GENERATE_TOC_INIT
        else:
            # Subsequent chunks — continue from accumulated tree
            prior_json = json.dumps(accumulated, indent=2)
            prompt = (
                f"Given text:\n{chunk_text}\n\n"
                f"Previous tree structure:\n{prior_json}"
            )
            system = _GENERATE_TOC_CONTINUE

        try:
            resp = await llm.complete(
                [{"role": "user", "content": prompt}],
                system_prompt=system,
                max_tokens=4096,
            )
            new_items = _parse_vectify_response(resp.content)
        except Exception as exc:
            logger.warning("PageIndex chunk %d failed: %s", chunk_idx + 1, exc)
            new_items = []

        accumulated.extend(new_items)
        logger.debug(
            "PageIndex chunk %d/%d: %d new sections",
            chunk_idx + 1, len(chunks), len(new_items),
        )

    if not accumulated:
        return [{
            "node_id":    "n1",
            "title":      filename,
            "level":      1,
            "page_start": pages[0]["page"],
            "page_end":   pages[-1]["page"],
            "depth":      1,
            "text":       "",
            "summary":    "",
            "images":     [],
            "children":   [],
        }], filename

    # Convert accumulated flat list → our tree node format
    last_page = pages[-1]["page"]
    flat_sections: list[dict] = []
    for i, item in enumerate(accumulated):
        level = _structure_to_level(item["structure"])
        ps = item["physical_index"]
        pe = last_page
        for j in range(i + 1, len(accumulated)):
            nxt_level = _structure_to_level(accumulated[j]["structure"])
            if nxt_level <= level:
                pe = accumulated[j]["physical_index"] - 1
                break
        pe = max(ps, min(pe, last_page))
        flat_sections.append({
            "node_id":    f"n{i+1}",
            "title":      item["title"],
            "level":      level,
            "page_start": ps,
            "page_end":   pe,
            "depth":      level,
            "text":       "",
            "summary":    "",
            "images":     [],
            "children":   [],
        })

    return _nest_sections(flat_sections), filename


# ---------------------------------------------------------------------------
# Path 2 — TOC exists but missing page numbers (Vectify add_page_number_to_toc)
# ---------------------------------------------------------------------------

async def _analyze_toc_no_pages(
    toc: list[dict],
    pages: list[dict],
    filename: str,
    llm: "LLMProvider",
) -> tuple[list[dict], str]:
    """Path 2: TOC has structure but no page numbers.

    Uses Vectify's _ADD_PAGE_NUMBER_TO_TOC prompt: passes the entire TOC JSON
    + one chunk of pages; LLM fills in physical_index for each matched entry.
    Accumulates results across chunks.
    """
    # Build TOC as Vectify-style JSON (structure, title, no physical_index yet)
    toc_json: list[dict] = [
        {"structure": str(i + 1), "title": e["title"], "physical_index": None}
        for i, e in enumerate(toc)
    ]

    chunks = _group_pages_into_chunks(pages)

    for chunk_pages in chunks:
        # Stop early if every entry is matched
        if all(e.get("physical_index") is not None for e in toc_json):
            break

        chunk_text = _format_chunk_for_llm(chunk_pages)
        prompt = (
            f"Current Partial Document:\n{chunk_text}\n\n"
            f"Given Structure:\n{json.dumps(toc_json, indent=2)}"
        )

        try:
            resp = await llm.complete(
                [{"role": "user", "content": prompt}],
                system_prompt=_ADD_PAGE_NUMBER_TO_TOC,
                max_tokens=4096,
            )
            raw = resp.content.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1].removeprefix("json").strip()
                if raw.endswith("```"):
                    raw = raw[:-3]
            updated = json.loads(raw)
            if isinstance(updated, list):
                toc_json = updated
        except Exception as exc:
            logger.debug("TOC page matching chunk failed: %s", exc)

    # Resolve physical_index values and fallback for unmatched entries
    last_page = pages[-1]["page"] if pages else 1
    resolved: list[dict] = []
    for entry in toc_json:
        pi = _parse_physical_index(entry.get("physical_index"))
        if pi is None:
            pi = resolved[-1]["page"] if resolved else pages[0]["page"]
        # Derive level from original TOC
        orig = next((t for t in toc if t["title"] == entry.get("title")), None)
        level = orig["level"] if orig else 1
        resolved.append({"level": level, "title": entry.get("title", ""), "page": pi})

    sections = _toc_to_sections(resolved, last_page)
    return sections, filename


# ---------------------------------------------------------------------------
# Post-processing — populate section text from actual page content
# ---------------------------------------------------------------------------

def _populate_section_text(section: dict, page_map: dict[int, dict]) -> dict:
    """Fill section.text with concatenated content from its page range."""
    ps = section.get("page_start", 1)
    pe = section.get("page_end", ps)
    children = section.get("children", [])

    if children:
        section["text"] = (page_map.get(ps, {}).get("content", "") or "")[:500]
        section["children"] = [_populate_section_text(c, page_map) for c in children]
    else:
        texts: list[str] = []
        images: list[dict] = []
        for pn in range(ps, pe + 1):
            p = page_map.get(pn)
            if p:
                if p.get("content"):
                    texts.append(p["content"])
                images.extend(p.get("images", []))
        section["text"]   = "\n\n".join(texts).strip()
        section["images"] = images

    return section


# ---------------------------------------------------------------------------
# Missing Vectify helpers
# ---------------------------------------------------------------------------

def _add_preface_if_needed(flat_items: list[dict], first_page: int) -> list[dict]:
    """Mirror of Vectify add_preface_if_needed.

    If the first detected section doesn't start at page 1 (or first_page),
    insert a synthetic 'Preface' section covering the unclaimed front matter.
    """
    if not flat_items:
        return flat_items
    first_pi = flat_items[0].get("physical_index") or flat_items[0].get("page_start", 1)
    if first_pi is not None and first_pi > first_page:
        preface = {
            "node_id":    "n0",
            "title":      "Preface",
            "structure":  "0",
            "level":      1,
            "page_start": first_page,
            "page_end":   first_pi - 1,
            "depth":      1,
            "text":       "",
            "summary":    "",
            "images":     [],
            "children":   [],
        }
        flat_items.insert(0, preface)
    return flat_items


def _validate_page_indices(flat_items: list[dict], total_pages: int, start_index: int = 1) -> list[dict]:
    """Mirror of Vectify validate_and_truncate_physical_indices.

    Removes entries whose page_start exceeds the document length — these can
    happen when the LLM hallucinates or the TOC references non-existent pages.
    """
    max_allowed = total_pages + start_index - 1
    valid = []
    for item in flat_items:
        pi = item.get("page_start") or item.get("physical_index")
        if pi is not None and pi > max_allowed:
            logger.info(
                "PageIndex: removing '%s' — page %d exceeds document length %d",
                item.get("title", "?"), pi, max_allowed,
            )
            continue
        valid.append(item)
    return valid


async def _run_verify_and_fix(
    flat_items: list[dict],
    pages: list[dict],
    llm: "LLMProvider",
    n_samples: int = 5,
) -> tuple[float, list[dict]]:
    """Run concurrent title-appearance checks on a random sample.

    Mirrors Vectify verify_toc: checks N random entries, returns (accuracy, bad_items).
    bad_items contains entries where the title was NOT found on its claimed page.
    """
    if not flat_items or not pages:
        return 1.0, []

    page_map = {p["page"]: p for p in pages}
    total_pages = pages[-1]["page"]

    # Early exit if the last valid physical index < half of document
    # (indicates a completely wrong TOC — same check as Vectify)
    last_pi = max(
        (item.get("page_start", 0) for item in flat_items if item.get("page_start")),
        default=0,
    )
    if last_pi < total_pages / 2:
        logger.warning("PageIndex verify: last section page %d < half of %d — skipping verify", last_pi, total_pages)
        return 0.0, []

    n = min(n_samples, len(flat_items))
    sample_indices = random.sample(range(len(flat_items)), n)

    import asyncio as _asyncio

    async def _check_one(idx: int) -> tuple[int, bool]:
        item = flat_items[idx]
        claimed = item.get("page_start", 1)
        title = item.get("title", "")
        page = page_map.get(claimed)
        if not page:
            return idx, True  # can't check → assume ok
        page_text = f"<physical_index_{claimed}>\n{page.get('content', '')[:800]}\n<physical_index_{claimed}>"
        prompt = (
            f"The given section title is {title}.\n"
            f"The given page_text is:\n{page_text}"
        )
        try:
            resp = await llm.complete(
                [{"role": "user", "content": prompt}],
                system_prompt=_CHECK_TITLE_APPEARANCE,
                max_tokens=256,
            )
            raw = resp.content.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1].removeprefix("json").strip()
            data = json.loads(raw)
            answer = data.get("answer", "yes")
            return idx, answer.lower() == "yes"
        except Exception as exc:
            logger.debug("verify_toc check failed for '%s': %s", title, exc)
            return idx, True

    results = await _asyncio.gather(*[_check_one(i) for i in sample_indices])

    correct = sum(1 for _, ok in results if ok)
    bad_indices = [i for i, ok in results if not ok]
    accuracy = correct / len(results) if results else 1.0

    logger.info("PageIndex verify: accuracy=%.0f%% (%d/%d checked)", accuracy * 100, correct, len(results))
    return accuracy, [flat_items[i] for i in bad_indices]


async def _fix_bad_entries(
    flat_items: list[dict],
    bad_items: list[dict],
    pages: list[dict],
    llm: "LLMProvider",
    max_retries: int = 3,
) -> list[dict]:
    """Mirror of Vectify fix_incorrect_toc_with_retries.

    For each bad entry: search ±3 pages for the real page using _FIX_TOC_ITEM,
    then re-verify. Retries up to max_retries times.
    """
    page_map = {p["page"]: p for p in pages}
    total_pages = pages[-1]["page"]

    # Build a set of titles to fix for fast lookup
    bad_titles = {item.get("title", "") for item in bad_items}

    for attempt in range(max_retries):
        still_bad: list[dict] = []
        for item in flat_items:
            if item.get("title") not in bad_titles:
                continue
            claimed = item.get("page_start", 1)
            title = item.get("title", "")
            search_range = range(max(1, claimed - 3), min(total_pages, claimed + 3) + 1)
            snippets = [
                f"<physical_index_{pn}>\n{page_map[pn].get('content','')[:500]}\n<physical_index_{pn}>"
                for pn in search_range if pn in page_map
            ]
            if not snippets:
                continue
            try:
                resp = await llm.complete(
                    [{"role": "user", "content": f"Section Title:\n{title}\n\nDocument pages:\n" + "\n\n".join(snippets)}],
                    system_prompt=_FIX_TOC_ITEM,
                    max_tokens=128,
                )
                raw = resp.content.strip()
                if raw.startswith("```"):
                    raw = raw.split("```")[1].removeprefix("json").strip()
                fix_data = json.loads(raw)
                correct = _parse_physical_index(fix_data.get("physical_index"))
                if correct and 1 <= correct <= total_pages:
                    item["page_start"] = correct
                    # Verify the fix
                    fixed_page = page_map.get(correct)
                    if fixed_page:
                        page_text = f"<physical_index_{correct}>\n{fixed_page.get('content','')[:800]}\n<physical_index_{correct}>"
                        check_resp = await llm.complete(
                            [{"role": "user", "content": f"The given section title is {title}.\nThe given page_text is:\n{page_text}"}],
                            system_prompt=_CHECK_TITLE_APPEARANCE,
                            max_tokens=256,
                        )
                        raw2 = check_resp.content.strip()
                        if raw2.startswith("```"):
                            raw2 = raw2.split("```")[1].removeprefix("json").strip()
                        data2 = json.loads(raw2)
                        if data2.get("answer", "no").lower() != "yes":
                            still_bad.append(item)
            except Exception as exc:
                logger.debug("fix_bad_entries failed for '%s': %s", title, exc)
                still_bad.append(item)

        if not still_bad:
            break
        bad_titles = {item.get("title", "") for item in still_bad}
        logger.info("PageIndex fix: %d still bad after attempt %d", len(still_bad), attempt + 1)

    return flat_items


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def analyze_structure(
    pages: list[dict],
    filename: str,
    llm: "LLMProvider",
    file_path: str | None = None,
    file_type: str | None = None,
) -> tuple[list[dict], str]:
    """Analyze document structure — full Vectify PageIndex logic.

    Routing (mirrors Vectify meta_processor + tree_parser):

      Path 1 — PDF TOC with valid page numbers
        → Detect page offset via sampling, apply offset, build tree.
        → verify_toc: if accuracy > 60% fix bad entries and return.
        → If accuracy <= 60% fall through to Path 2.

      Path 2 — PDF TOC without page numbers
        → LLM matches TOC entries to physical pages chunk by chunk.
        → verify_toc: if accuracy <= 60% fall through to Path 3.

      Path 3 — No TOC
        → Token-chunk LLM: generate_toc_init → generate_toc_continue.

    After any path:
      - validate_and_truncate_physical_indices (remove out-of-bounds)
      - add_preface_if_needed (cover unclaimed front matter)
      - populate section text from source_pages
    """
    if not pages:
        return [], filename

    page_map = {p["page"]: p for p in pages}
    last_page = pages[-1]["page"]
    first_page = pages[0]["page"]

    # ── Try TOC extraction (PDF only) ────────────────────────────────────────
    toc: list[dict] = []
    ft = (file_type or "").lower().strip(".")
    if file_path and ft == "pdf":
        toc = extract_pdf_toc(file_path)
        logger.info("PageIndex: PDF TOC has %d entries for '%s'", len(toc), filename)

    sections: list[dict] = []
    doc_title: str = filename
    path_used = None

    # ── Path 1: TOC with page numbers ────────────────────────────────────────
    if toc and toc_has_valid_pages(toc, last_page):
        logger.info("PageIndex Path 1: PDF TOC with pages for '%s'", filename)
        path_used = 1

        # Detect and apply page-number offset (roman-numeral front matter etc.)
        offset = await _detect_page_number_offset(toc, pages, llm)
        if offset != 0:
            toc = [{**e, "page": max(1, min(e["page"] + offset, last_page))} for e in toc]

        # Build flat list for verify
        flat_items = [
            {"title": e["title"], "level": e["level"], "page_start": e["page"],
             "node_id": f"n{i+1}", "page_end": last_page, "depth": e["level"],
             "text": "", "summary": "", "images": [], "children": []}
            for i, e in enumerate(toc)
        ]
        flat_items = _validate_page_indices(flat_items, last_page)

        accuracy, bad_items = await _run_verify_and_fix(flat_items, pages, llm)

        if accuracy > 0.6:
            if bad_items:
                flat_items = await _fix_bad_entries(flat_items, bad_items, pages, llm)
            # Compute page_end for each flat entry before nesting
            flat_items = _toc_to_sections(
                [{"title": x["title"], "level": x["level"], "page": x["page_start"]} for x in flat_items],
                last_page,
            )
            # flat_items is now nested — assign to sections
            sections = flat_items
        else:
            logger.warning("PageIndex Path 1 accuracy %.0f%% — falling back to Path 2/3", accuracy * 100)
            path_used = None  # will be re-evaluated below

    # ── Path 2: TOC without page numbers ─────────────────────────────────────
    if path_used is None and toc:
        logger.info("PageIndex Path 2: TOC no pages for '%s'", filename)
        path_used = 2
        sections, doc_title = await _analyze_toc_no_pages(toc, pages, filename, llm)

        # Flatten and verify
        flat_for_v2: list[dict] = []
        def _fl(nlist: list) -> None:
            for n in nlist:
                flat_for_v2.append(n)
                _fl(n.get("children", []))
        _fl(sections)

        accuracy2, bad2 = await _run_verify_and_fix(flat_for_v2, pages, llm)
        if accuracy2 > 0.6:
            if bad2:
                flat_for_v2 = await _fix_bad_entries(flat_for_v2, bad2, pages, llm)
        else:
            logger.warning("PageIndex Path 2 accuracy %.0f%% — falling back to Path 3", accuracy2 * 100)
            path_used = None

    # ── Path 3: No TOC — full token-chunk analysis ────────────────────────────
    if path_used is None:
        logger.info("PageIndex Path 3: no TOC, token-chunk analysis for '%s'", filename)
        sections, doc_title = await _analyze_no_toc(pages, filename, llm)

    if not sections:
        return [], doc_title

    # ── Post-processing (all paths) ───────────────────────────────────────────
    # 1. Flatten to apply preface + validation
    all_flat: list[dict] = []
    def _flatten_all(nlist: list) -> None:
        for n in nlist:
            all_flat.append(n)
            _flatten_all(n.get("children", []))
    _flatten_all(sections)

    # 2. validate_and_truncate_physical_indices
    all_flat = _validate_page_indices(all_flat, last_page, start_index=first_page)

    # 3. add_preface_if_needed — insert front-matter section if first section > page 1
    all_flat = _add_preface_if_needed(all_flat, first_page)

    # 4. Re-nest with corrected boundaries
    for n in all_flat:
        n["children"] = []
    sections = _nest_sections(all_flat)

    # 5. Populate section text from actual page content
    sections = [_populate_section_text(s, page_map) for s in sections]

    logger.info(
        "PageIndex done: %d top-level sections via Path %s, title=%r",
        len(sections), path_used or 3, doc_title,
    )
    return sections, doc_title
