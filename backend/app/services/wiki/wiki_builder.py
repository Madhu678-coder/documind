"""Wiki builder — extracts wiki pages from documents and merges new info into existing pages.

Features:
  1. extract_pages(): Document text → list of new wiki page dicts
  2. merge_page_content(): Existing page content + new passages → updated content
  3. check_merge_compatibility(): Semantic check if two pages are truly the same topic
  4. inject_wikilinks(): Embed [[Page Title]] links inside page content
  5. update_related_pages(): Propagate new info to pages that reference the updated page
"""
from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.llm.provider import LLMProvider

logger = logging.getLogger(__name__)

_WIKI_MAX_PAGES = 100     # Hard cap per KB to control LLM costs
_EXTRACT_MAX_CHARS = 100_000  # Full context window (Claude supports 200K tokens)

# ── Prompts ───────────────────────────────────────────────────────────────────

_EXTRACT_SYSTEM_PROMPT = """\
You are a knowledge base curator. Analyze the provided document and extract wiki-style pages \
for the most important entities, concepts, processes, and topics it covers.

For each page return exactly these fields:
- title: Clear, concise canonical title. This is the unique merge key — use consistent naming.
  IMPORTANT: If a topic is specific to the document's domain or scope, prefix the title with \
that context to avoid wrong merges. For example:
  - "Domestic Travel - Mode of Travel" (not just "Mode of Travel")
  - "International Travel - Mode of Travel" (different document, different rules)
  - "Leave Policy - Eligibility" (not just "Eligibility")
  Only use generic titles (without prefix) for truly universal concepts that would be the same \
across all documents (e.g. "City Classification", "Employee Categories").
- page_type: one of "entity", "concept", "process", "event", "general"
- summary: 1–2 sentence description (used as a search index)
- content: 3–6 paragraph markdown explanation with ## subheadings where helpful. \
When referencing other topics you are extracting, use [[Topic Title]] wikilink syntax inline. \
Use ONLY the simple format [[Title]] — do NOT use piped links like [[Title|display text]] or nested brackets.
- related_titles: list of other page titles defined in this same response that this topic \
links to (use the exact title strings you defined)

Return ONLY valid JSON in this format:
{"pages": [{"title": "...", "page_type": "...", "summary": "...", "content": "...", "related_titles": [...]}]}

Extract between 3 and 15 pages. Prefer quality over quantity.\
"""

_MERGE_SYSTEM_PROMPT = """\
You are updating a wiki page with new information from a document.

Rules:
- Preserve all accurate existing information
- Integrate new facts, examples, and context naturally into the markdown structure
- If new information contradicts existing content, add a blockquote note:
  > ⚠️ **Conflict**: [brief description of the contradiction]
- Keep the page well-organized with ## markdown subheadings
- Use [[Topic Title]] wikilink syntax when referencing other known topics
- Return ONLY the updated markdown content — no explanation, no JSON wrapper\
"""

_MERGE_CHECK_SYSTEM_PROMPT = """\
You are a knowledge base curator deciding whether two wiki pages should be merged.

Given two page summaries, determine if they cover the SAME topic (should merge) or \
DIFFERENT topics that happen to have similar titles (should stay separate).

Return ONLY valid JSON:
{"should_merge": true/false, "reason": "brief explanation"}\
"""

_CROSS_UPDATE_SYSTEM_PROMPT = """\
You are updating a wiki page with relevant new context from a related page that was just modified.

The related page was updated with new information. If any of that new information is relevant \
to THIS page, integrate it briefly (1-2 sentences max). If nothing is relevant, return the \
existing content unchanged.

Rules:
- Only add information that is directly relevant to this page's topic
- Keep additions brief — this is a cross-reference update, not a full rewrite
- Use [[Topic Title]] wikilink syntax for cross-references
- Return ONLY the updated markdown content — no explanation, no JSON wrapper\
"""


# ── Core Functions ────────────────────────────────────────────────────────────


async def extract_pages(provider: "LLMProvider", text: str, filename: str) -> list[dict]:
    """
    Send document text to the LLM and extract structured wiki page dicts.

    Returns a list of dicts with keys: title, page_type, summary, content, related_titles.
    Returns [] on any failure — callers should handle an empty list gracefully.
    """
    truncated = text[:_EXTRACT_MAX_CHARS]
    messages = [
        {
            "role": "user",
            "content": f"Document: {filename}\n\n{truncated}",
        }
    ]
    try:
        response = await provider.complete(messages, system_prompt=_EXTRACT_SYSTEM_PROMPT, max_tokens=8192)
        logger.info("Wiki extraction LLM response received", extra={"doc_filename": filename, "response_len": len(response.content)})
        pages = _parse_pages_json(response.content)
        if not pages:
            logger.warning("Wiki extraction returned no valid pages", extra={"doc_filename": filename, "raw_response": response.content[:500]})
            return []
        # Inject wikilinks into content based on related_titles
        all_titles = [p["title"] for p in pages]
        for page in pages:
            page["content"] = inject_wikilinks(page["content"], all_titles, page["title"])
        return pages
    except Exception as exc:
        logger.warning("Wiki page extraction failed", extra={"doc_filename": filename, "error": str(exc), "error_type": type(exc).__name__})
        return []


async def merge_page_content(
    provider: "LLMProvider",
    existing_content: str,
    new_passages: str,
) -> str:
    """
    Ask the LLM to merge new document passages into an existing wiki page.

    Returns the updated markdown content string.
    Falls back to existing_content unchanged if the LLM call fails.
    """
    messages = [
        {
            "role": "user",
            "content": f"EXISTING PAGE:\n{existing_content}\n\nNEW INFORMATION:\n{new_passages}",
        }
    ]
    try:
        response = await provider.complete(messages, system_prompt=_MERGE_SYSTEM_PROMPT)
        merged = response.content.strip()
        # Strip any accidental markdown fences the LLM may add
        if merged.startswith("```"):
            lines = merged.split("\n")
            merged = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
        return merged or existing_content
    except Exception as exc:
        logger.warning("Wiki page merge failed", extra={"error": str(exc)})
        return existing_content


# ── Semantic Merge Check ──────────────────────────────────────────────────────

_BATCH_MERGE_CHECK_PROMPT = """\
You are a knowledge base curator deciding which page pairs should be merged.

For each numbered pair below, determine if they cover the SAME topic (should merge) or \
DIFFERENT topics that happen to have similar titles (should stay separate).

Return ONLY valid JSON — an array of objects, one per pair:
[{"pair": 1, "should_merge": true, "reason": "..."}, {"pair": 2, "should_merge": false, "reason": "..."}]
"""


async def batch_check_merge_compatibility(
    provider: "LLMProvider",
    pairs: list[dict],
) -> list[bool]:
    """
    Check multiple page pairs for merge compatibility in a single LLM call.

    Args:
        provider: LLM provider
        pairs: List of dicts with keys: existing_title, existing_summary, new_title, new_summary

    Returns:
        List of booleans (True = should merge) in same order as input pairs.
    """
    if not pairs:
        return []

    # Build batch prompt
    pair_texts = []
    for i, pair in enumerate(pairs):
        pair_texts.append(
            f"[Pair {i+1}]\n"
            f"  Page A — Title: \"{pair['existing_title']}\"\n"
            f"  Summary: {pair['existing_summary']}\n"
            f"  Page B — Title: \"{pair['new_title']}\"\n"
            f"  Summary: {pair['new_summary']}"
        )

    messages = [
        {
            "role": "user",
            "content": "\n\n".join(pair_texts),
        }
    ]

    try:
        response = await provider.complete(messages, system_prompt=_BATCH_MERGE_CHECK_PROMPT)
        raw = response.content.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
            if raw.startswith("json"):
                raw = raw[4:]

        results = json.loads(raw)
        if isinstance(results, list) and len(results) == len(pairs):
            return [bool(r.get("should_merge", True)) for r in results]

        # Fallback: if response doesn't match expected format
        logger.warning("Batch merge check returned unexpected format, defaulting to merge")
        return [True] * len(pairs)

    except Exception as exc:
        logger.warning("Batch merge check failed, defaulting to merge", extra={"error": str(exc)})
        return [True] * len(pairs)


async def check_merge_compatibility(
    provider: "LLMProvider",
    existing_summary: str,
    existing_title: str,
    new_summary: str,
    new_title: str,
) -> bool:
    """
    Ask the LLM whether two pages with similar titles are truly the same topic.

    Returns True if they should be merged, False if they should stay separate.
    Defaults to True (merge) on any failure to maintain backward compatibility.
    """
    messages = [
        {
            "role": "user",
            "content": (
                f"Page A — Title: \"{existing_title}\"\n"
                f"Summary: {existing_summary}\n\n"
                f"Page B — Title: \"{new_title}\"\n"
                f"Summary: {new_summary}\n\n"
                f"Are these the same topic that should be merged into one page?"
            ),
        }
    ]
    try:
        response = await provider.complete(messages, system_prompt=_MERGE_CHECK_SYSTEM_PROMPT)
        raw = response.content.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
            if raw.startswith("json"):
                raw = raw[4:]
        data = json.loads(raw)
        should_merge = data.get("should_merge", True)
        reason = data.get("reason", "")
        logger.info(
            "Merge compatibility check",
            extra={
                "existing_title": existing_title,
                "new_title": new_title,
                "should_merge": should_merge,
                "reason": reason,
            },
        )
        return bool(should_merge)
    except Exception as exc:
        logger.warning("Merge compatibility check failed, defaulting to merge", extra={"error": str(exc)})
        return True


# ── Cross-Page Updates ────────────────────────────────────────────────────────


async def update_related_page(
    provider: "LLMProvider",
    related_page_content: str,
    related_page_title: str,
    updated_page_title: str,
    updated_page_summary: str,
    new_info_snippet: str,
) -> str:
    """
    Update a related page with relevant context from a page that was just modified.

    Returns the updated content, or the original content if nothing was relevant.
    """
    messages = [
        {
            "role": "user",
            "content": (
                f"THIS PAGE: \"{related_page_title}\"\n"
                f"Current content:\n{related_page_content}\n\n"
                f"---\n\n"
                f"RELATED PAGE UPDATED: \"{updated_page_title}\"\n"
                f"Summary: {updated_page_summary}\n"
                f"New information added:\n{new_info_snippet[:2000]}"
            ),
        }
    ]
    try:
        response = await provider.complete(messages, system_prompt=_CROSS_UPDATE_SYSTEM_PROMPT)
        updated = response.content.strip()
        if updated.startswith("```"):
            lines = updated.split("\n")
            updated = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
        return updated or related_page_content
    except Exception as exc:
        logger.warning(
            "Cross-page update failed",
            extra={"related_title": related_page_title, "error": str(exc)},
        )
        return related_page_content


# ── Wikilinks ─────────────────────────────────────────────────────────────────


def inject_wikilinks(content: str, all_titles: list[str], current_title: str) -> str:
    """
    Scan content for mentions of other wiki page titles and wrap them in [[]] wikilink syntax.

    Also cleans up malformed wikilinks from LLM output (nested brackets, piped links).
    Skips the current page's own title to avoid self-links.
    Only links the first occurrence of each title to avoid over-linking.
    """
    # First, clean up malformed wikilinks from LLM
    content = _clean_malformed_wikilinks(content)

    # Sort titles by length (longest first) to avoid partial matches
    titles_to_link = sorted(
        [t for t in all_titles if t.lower() != current_title.lower()],
        key=len,
        reverse=True,
    )

    linked: set[str] = set()
    # Find existing wikilinks to avoid double-linking
    existing_links = set(re.findall(r'\[\[([^\]]+)\]\]', content))

    for title in titles_to_link:
        if title in existing_links:
            continue
        if title.lower() in linked:
            continue

        # Case-insensitive search for the title in content (not inside existing [[]])
        pattern = re.compile(re.escape(title), re.IGNORECASE)
        match = pattern.search(content)
        if match:
            # Only replace the first occurrence
            original_text = match.group(0)
            content = content[:match.start()] + f"[[{original_text}]]" + content[match.end():]
            linked.add(title.lower())

    return content


def _clean_malformed_wikilinks(content: str) -> str:
    """
    Fix common LLM wikilink mistakes:
    - [[[[Title]]|display text]] → [[Title]]
    - [[[Title]]] → [[Title]]
    - [[Title|display]] → [[Title]]
    """
    # Fix nested brackets: [[[[Title]]|text]] or [[[[Title]]]] → [[Title]]
    content = re.sub(r'\[\[\[\[([^\]]+)\]\]\|[^\]]*\]\]', r'[[\1]]', content)
    content = re.sub(r'\[\[\[\[([^\]]+)\]\]\]\]', r'[[\1]]', content)

    # Fix piped links: [[Title|display text]] → [[Title]]
    content = re.sub(r'\[\[([^\]|]+)\|[^\]]*\]\]', r'[[\1]]', content)

    # Fix triple brackets: [[[Title]]] → [[Title]]
    content = re.sub(r'\[\[\[([^\]]+)\]\]\]', r'[[\1]]', content)

    return content


# ── JSON Parsing ──────────────────────────────────────────────────────────────


def _parse_pages_json(raw: str) -> list[dict]:
    """Parse LLM response containing JSON wiki pages. Returns [] on any error."""
    try:
        content = raw.strip()
        # Strip markdown code fences if present
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
            if content.startswith("json"):
                content = content[4:]

        data = json.loads(content)
        pages = data.get("pages", [])
        if not isinstance(pages, list):
            logger.warning("Wiki extraction: 'pages' is not a list")
            return []

        validated = []
        for p in pages:
            if not isinstance(p, dict):
                continue
            title = str(p.get("title", "")).strip()
            content_text = str(p.get("content", "")).strip()
            if not title or not content_text:
                continue
            validated.append({
                "title": title,
                "page_type": str(p.get("page_type", "general")).strip(),
                "summary": str(p.get("summary", "")).strip(),
                "content": content_text,
                "related_titles": [str(t) for t in p.get("related_titles", []) if t],
            })
        return validated

    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        logger.warning("Wiki page JSON parse failed", extra={"error": str(exc)})
        return []
