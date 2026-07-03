"""Wiki builder — extracts wiki pages from documents and merges new info into existing pages.

Implements Karpathy's LLM Wiki pattern (April 2026):
  1. extract_pages(): Document text → list of wiki page dicts (concept/process/entity)
  2. extract_connections(): Cross-cutting insight pages linking 2+ concepts
  3. merge_page_content(): Merge new info into existing page
  4. inject_wikilinks(): Embed [[Page Title]] links in content
  5. update_related_pages(): Propagate new info to linked pages
  6. generate_frontmatter(): YAML frontmatter for each page
  7. build_index_content(): Master catalog of all pages
  8. build_log_entry(): Append-only build log entry
  9. file_qa_answer(): File a Q&A answer as a persistent qa/ page
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.services.llm.provider import LLMProvider

logger = logging.getLogger(__name__)

_WIKI_MAX_PAGES = 100
# 25,000 tokens per chunk — leaves room for system prompt + 8192 token response
_MAX_TOKENS_PER_CHUNK = 25_000
# Overlap: 200 tokens carried into next chunk so topics near boundaries aren't lost
_CHUNK_OVERLAP_TOKENS = 200


# ── Prompts ───────────────────────────────────────────────────────────────────

_EXTRACT_SYSTEM_PROMPT = """\
You are a knowledge base curator. Analyze the provided document and extract wiki-style pages \
for the most important entities, concepts, processes, and topics it covers.

For each page return exactly these fields:
- title: Clear, concise canonical title. This is the unique merge key — use consistent naming.
  IMPORTANT: If a topic is specific to the document's domain or scope, prefix the title with \
that context to avoid wrong merges. For example:
  - "Domestic Travel - Mode of Travel" (not just "Mode of Travel")
  Only use generic titles (without prefix) for truly universal concepts that would be the same \
across all documents (e.g. "City Classification", "Employee Categories").
- page_type: one of "concept" | "entity" | "process" | "event" | "general"
- summary: 1–2 sentence description (used as search index)
- content: 3–6 paragraph markdown explanation with ## subheadings where helpful. \
When referencing other extracted topics, use [[Topic Title]] wikilink syntax inline.
- related_titles: list of other page titles defined in this same response

Return ONLY valid JSON:
{"pages": [{"title": "...", "page_type": "...", "summary": "...", "content": "...", "related_titles": [...]}]}

Extract between 3 and 15 pages. Prefer quality over quantity.\
"""

_MERGE_SYSTEM_PROMPT = """\
You are updating a wiki page with new information from a document.

Rules:
- Preserve all accurate existing information
- Integrate new facts, examples, and context naturally into the markdown structure
- If new information contradicts existing content, add a blockquote:
  > ⚠️ **Conflict**: [brief description of the contradiction]
- Keep the page well-organized with ## markdown subheadings
- Use [[Topic Title]] wikilink syntax when referencing other known topics
- Return ONLY the updated markdown content — no explanation, no JSON wrapper\
"""

_MERGE_CHECK_SYSTEM_PROMPT = """\
You are deciding whether two wiki pages should be merged.
Return ONLY valid JSON: {"should_merge": true/false, "reason": "brief explanation"}\
"""

_CROSS_UPDATE_SYSTEM_PROMPT = """\
You are updating a wiki page with relevant new context from a related page that was just modified.
If any of that new information is relevant to THIS page, integrate it briefly (1-2 sentences max).
If nothing is relevant, return the existing content unchanged.
- Only add information directly relevant to this page's topic
- Use [[Topic Title]] wikilink syntax for cross-references
- Return ONLY the updated markdown content — no explanation, no JSON wrapper\
"""

_CONNECTIONS_SYSTEM_PROMPT = """\
You are analyzing wiki pages to identify non-obvious cross-cutting connections between concepts.

For each meaningful connection found, create a "connection" page.
Only create connections that are non-obvious, supported by the content, and useful for understanding.

Return ONLY valid JSON:
{"connections": [
  {
    "title": "Connection: ConceptA and ConceptB",
    "summary": "One sentence explaining how they relate",
    "content": "## The Connection\\n\\n[explanation]\\n\\n## Key Insight\\n\\n[non-obvious relationship]\\n\\n## Evidence\\n\\n[specifics from the content]",
    "related_titles": ["ConceptA", "ConceptB"]
  }
]}

Return at most 3 connections. If no meaningful connections exist, return {"connections": []}.\
"""

_QA_FILE_SYSTEM_PROMPT = """\
You are creating a Q&A wiki article from an answered question.

Format the Q&A as a structured wiki page with:
## Question
[the original question]

## Answer
[the synthesized answer, written as a standalone article]

## Sources Consulted
[list of wiki page titles that were referenced, as [[wikilinks]]]

## Follow-Up Questions
[2-3 natural follow-up questions someone might ask]

Return ONLY the markdown content — no JSON, no explanation.\
"""

_BATCH_MERGE_CHECK_PROMPT = """\
For each numbered pair below, determine if they cover the SAME topic (should merge) or \
DIFFERENT topics that happen to have similar titles.
Return ONLY valid JSON — an array:
[{"pair": 1, "should_merge": true, "reason": "..."}, ...]
"""


# ── YAML Frontmatter ──────────────────────────────────────────────────────────

def generate_frontmatter(
    title: str,
    page_type: str,
    source_doc_ids: list[str],
    aliases: list[str] | None = None,
    tags: list[str] | None = None,
    created: str | None = None,
    updated: str | None = None,
) -> str:
    """Generate YAML frontmatter block for a wiki page (Karpathy pattern)."""
    today = date.today().isoformat()
    aliases_str = ", ".join(f'"{a}"' for a in (aliases or []))
    tags_str = ", ".join(f'"{t}"' for t in (tags or []))
    sources_lines = "\n".join(f'  - "{d}"' for d in source_doc_ids)
    return (
        "---\n"
        f'title: "{title}"\n'
        f"aliases: [{aliases_str}]\n"
        f"tags: [{tags_str}]\n"
        f"page_type: {page_type}\n"
        f"sources:\n{sources_lines or '  []'}\n"
        f"created: {created or today}\n"
        f"updated: {updated or today}\n"
        "---"
    )


def strip_frontmatter(content: str) -> tuple[str, str]:
    """Split content into (frontmatter_block, body). Returns ('', content) if no frontmatter."""
    if not content.startswith("---"):
        return "", content
    end = content.find("\n---\n", 4)
    if end == -1:
        end = content.find("\n---", 4)
    if end == -1:
        return "", content
    fm_end = content.find("\n", end + 1)
    frontmatter = content[:fm_end + 1] if fm_end != -1 else content[:end + 4]
    rest = content[len(frontmatter):].strip()
    return frontmatter, rest


def add_frontmatter_to_page(
    content: str,
    title: str,
    page_type: str,
    source_doc_ids: list[str],
    created: str | None = None,
) -> str:
    """Add or replace YAML frontmatter at the top of page content."""
    _, body = strip_frontmatter(content)
    fm = generate_frontmatter(title, page_type, source_doc_ids, created=created)
    return fm + "\n\n" + body


def get_frontmatter_created_date(content: str) -> str | None:
    """Extract 'created' date from frontmatter, or None if not present."""
    fm, _ = strip_frontmatter(content)
    if not fm:
        return None
    match = re.search(r"^created:\s*(.+)$", fm, re.MULTILINE)
    return match.group(1).strip() if match else None


# ── Core Extraction ───────────────────────────────────────────────────────────

async def extract_pages(provider: "LLMProvider", text: str, filename: str) -> list[dict]:
    """Send document text to LLM and extract structured wiki page dicts.

    For large documents, splits into overlapping chunks and calls LLM per chunk.
    Deduplicates by title across chunks.
    """
    if not text or not text.strip():
        return []

    chunks = _split_into_chunks(text)
    all_pages: list[dict] = []
    seen_titles: dict[str, int] = {}

    for chunk_idx, chunk in enumerate(chunks):
        chunk_note = (
            f"\n\n[This is part {chunk_idx + 1} of {len(chunks)} of the full document. "
            "Extract topics visible in this part.]"
        ) if len(chunks) > 1 else ""

        messages = [{"role": "user", "content": f"Document: {filename}{chunk_note}\n\n{chunk}"}]
        try:
            response = await provider.complete(messages, system_prompt=_EXTRACT_SYSTEM_PROMPT, max_tokens=8192)
            logger.info("Wiki extraction response received",
                        extra={"doc": filename, "chunk": chunk_idx + 1, "len": len(response.content)})
            chunk_pages = _parse_pages_json(response.content)
            if not chunk_pages:
                logger.warning("Wiki extraction: no valid pages for chunk",
                               extra={"doc": filename, "chunk": chunk_idx + 1})
                continue
            for page in chunk_pages:
                title_key = page["title"].lower()
                if title_key in seen_titles:
                    existing = all_pages[seen_titles[title_key]]
                    existing["content"] += "\n\n" + page["content"]
                    existing["related_titles"] = list(
                        set(existing.get("related_titles", []) + page.get("related_titles", []))
                    )
                else:
                    seen_titles[title_key] = len(all_pages)
                    all_pages.append(page)
        except Exception as exc:
            logger.warning("Wiki extraction failed for chunk",
                           extra={"doc": filename, "chunk": chunk_idx + 1, "error": str(exc)})

    if not all_pages:
        return []

    all_titles = [p["title"] for p in all_pages]
    for page in all_pages:
        page["content"] = inject_wikilinks(page["content"], all_titles, page["title"])

    return all_pages


async def extract_connections(
    provider: "LLMProvider",
    pages: list[dict],
    max_connections: int = 3,
) -> list[dict]:
    """Analyze extracted pages and create cross-cutting connection pages (Karpathy pattern).

    Returns list of connection page dicts (page_type='connection').
    """
    if len(pages) < 2:
        return []

    # Build a compact summary of all pages for the LLM
    page_summaries = "\n".join(
        f"- **{p['title']}** ({p.get('page_type','concept')}): {p.get('summary','')}"
        for p in pages[:20]  # cap to avoid token overflow
    )

    messages = [{
        "role": "user",
        "content": (
            f"Here are the wiki pages just extracted:\n\n{page_summaries}\n\n"
            "Identify the most meaningful cross-cutting connections between these concepts."
        ),
    }]

    try:
        response = await provider.complete(messages, system_prompt=_CONNECTIONS_SYSTEM_PROMPT, max_tokens=4096)
        raw = response.content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1].removeprefix("json").strip()
        data = json.loads(raw)
        connections = data.get("connections", [])
        result = []
        all_titles = [p["title"] for p in pages]
        for c in connections[:max_connections]:
            if not c.get("title") or not c.get("content"):
                continue
            content = inject_wikilinks(c["content"], all_titles, c["title"])
            result.append({
                "title": c["title"],
                "page_type": "connection",
                "summary": c.get("summary", ""),
                "content": content,
                "related_titles": c.get("related_titles", []),
            })
        logger.info("Wiki connections extracted", extra={"count": len(result)})
        return result
    except Exception as exc:
        logger.warning("Wiki connections extraction failed", extra={"error": str(exc)})
        return []


# ── Index Page ────────────────────────────────────────────────────────────────

_INDEX_TITLE = "__wiki_index__"
_LOG_TITLE = "__wiki_log__"


def build_index_content(all_pages: list[Any]) -> str:
    """Build the master catalog index page (Karpathy's index.md).

    Lists every article with its type and summary. This is the PRIMARY
    retrieval mechanism at query time — the navigator reads this first.
    """
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    fm = generate_frontmatter(_INDEX_TITLE, "index", [], tags=["structural"])
    lines = [
        fm,
        "",
        "# Wiki Index",
        "",
        f"*Updated: {now} · {len([p for p in all_pages if p.page_type not in ('index', 'log')])} articles*",
        "",
        "| Article | Type | Summary |",
        "|---------|------|---------|",
    ]

    # Group by type
    for ptype in ("concept", "connection", "entity", "process", "event", "general", "qa"):
        typed = [p for p in all_pages if p.page_type == ptype]
        if not typed:
            continue
        for page in sorted(typed, key=lambda p: p.title):
            summary = (page.summary or "").replace("|", "—").replace("\n", " ")[:100]
            lines.append(f"| [[{page.title}]] | {ptype} | {summary} |")

    return "\n".join(lines)


# ── Log Page ──────────────────────────────────────────────────────────────────

def build_log_entry(operation: str, details: dict) -> str:
    """Build a single append-only log entry (Karpathy's log.md)."""
    ts = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [f"## [{ts}] {operation}"]
    for k, v in details.items():
        lines.append(f"- {k}: {v}")
    lines.append("")
    return "\n".join(lines)


def prepend_log_entry(existing_log_content: str, new_entry: str) -> str:
    """Prepend a new log entry to existing log content (newest entries at top)."""
    _, body = strip_frontmatter(existing_log_content)
    fm = generate_frontmatter(_LOG_TITLE, "log", [], tags=["structural"])
    header = "# Build Log\n\n*(newest entries first)*\n\n"
    return fm + "\n\n" + header + new_entry + "\n" + body.replace("# Build Log\n\n*(newest entries first)*\n\n", "")


# ── Q&A Compounding ───────────────────────────────────────────────────────────

async def file_qa_answer(
    provider: "LLMProvider",
    question: str,
    answer: str,
    selected_page_titles: list[str],
) -> dict:
    """Create a qa/ wiki page from an answered question (Karpathy Q&A compounding).

    Returns a page dict ready to be inserted into WikiPage table.
    """
    title = f"Q: {question[:80]}{'…' if len(question) > 80 else ''}"

    messages = [{
        "role": "user",
        "content": (
            f"Question: {question}\n\n"
            f"Answer: {answer}\n\n"
            f"Pages consulted: {', '.join(selected_page_titles)}"
        ),
    }]

    try:
        response = await provider.complete(messages, system_prompt=_QA_FILE_SYSTEM_PROMPT, max_tokens=2048)
        content = response.content.strip()
        if content.startswith("```"):
            content = content.split("```")[1].removeprefix("markdown").strip()
        content = inject_wikilinks(content, selected_page_titles, title)
    except Exception as exc:
        logger.warning("Q&A filing failed, using simple format", extra={"error": str(exc)})
        sources = "\n".join(f"- [[{t}]]" for t in selected_page_titles)
        content = (
            f"## Question\n{question}\n\n"
            f"## Answer\n{answer}\n\n"
            f"## Sources Consulted\n{sources}"
        )

    return {
        "title": title,
        "page_type": "qa",
        "summary": f"Q: {question[:120]}",
        "content": content,
        "related_titles": selected_page_titles,
    }


# ── Merge Functions ───────────────────────────────────────────────────────────

async def merge_page_content(provider: "LLMProvider", existing_content: str, new_passages: str) -> str:
    """Ask the LLM to merge new document passages into an existing wiki page."""
    _, existing_body = strip_frontmatter(existing_content)
    messages = [{"role": "user", "content": f"EXISTING PAGE:\n{existing_body}\n\nNEW INFORMATION:\n{new_passages}"}]
    try:
        response = await provider.complete(messages, system_prompt=_MERGE_SYSTEM_PROMPT)
        merged = response.content.strip()
        if merged.startswith("```"):
            lines = merged.split("\n")
            merged = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
        return merged or existing_body
    except Exception as exc:
        logger.warning("Wiki page merge failed", extra={"error": str(exc)})
        return existing_body


async def batch_check_merge_compatibility(provider: "LLMProvider", pairs: list[dict]) -> list[bool]:
    """Check multiple page pairs for merge compatibility in one LLM call."""
    if not pairs:
        return []
    pair_texts = [
        f"[Pair {i+1}]\n  Page A: \"{p['existing_title']}\" — {p['existing_summary']}\n"
        f"  Page B: \"{p['new_title']}\" — {p['new_summary']}"
        for i, p in enumerate(pairs)
    ]
    messages = [{"role": "user", "content": "\n\n".join(pair_texts)}]
    try:
        response = await provider.complete(messages, system_prompt=_BATCH_MERGE_CHECK_PROMPT)
        raw = response.content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1].removeprefix("json").strip()
        results = json.loads(raw)
        if isinstance(results, list) and len(results) == len(pairs):
            return [bool(r.get("should_merge", True)) for r in results]
        return [True] * len(pairs)
    except Exception as exc:
        logger.warning("Batch merge check failed", extra={"error": str(exc)})
        return [True] * len(pairs)


async def check_merge_compatibility(
    provider: "LLMProvider",
    existing_summary: str, existing_title: str,
    new_summary: str, new_title: str,
) -> bool:
    """Ask the LLM whether two pages are truly the same topic."""
    messages = [{
        "role": "user",
        "content": (
            f'Page A — "{existing_title}": {existing_summary}\n\n'
            f'Page B — "{new_title}": {new_summary}\n\n'
            "Are these the same topic that should be merged?"
        ),
    }]
    try:
        response = await provider.complete(messages, system_prompt=_MERGE_CHECK_SYSTEM_PROMPT)
        raw = response.content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1].removeprefix("json").strip()
        data = json.loads(raw)
        return bool(data.get("should_merge", True))
    except Exception as exc:
        logger.warning("Merge check failed, defaulting to merge", extra={"error": str(exc)})
        return True


async def update_related_page(
    provider: "LLMProvider",
    related_page_content: str, related_page_title: str,
    updated_page_title: str, updated_page_summary: str, new_info_snippet: str,
) -> str:
    """Update a related page with relevant context from a page that was just modified."""
    _, body = strip_frontmatter(related_page_content)
    messages = [{
        "role": "user",
        "content": (
            f'THIS PAGE: "{related_page_title}"\nCurrent content:\n{body}\n\n---\n\n'
            f'RELATED PAGE UPDATED: "{updated_page_title}"\n'
            f"Summary: {updated_page_summary}\n"
            f"New information added:\n{new_info_snippet[:2000]}"
        ),
    }]
    try:
        response = await provider.complete(messages, system_prompt=_CROSS_UPDATE_SYSTEM_PROMPT)
        updated = response.content.strip()
        if updated.startswith("```"):
            lines = updated.split("\n")
            updated = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
        return updated or body
    except Exception as exc:
        logger.warning("Cross-page update failed", extra={"related": related_page_title, "error": str(exc)})
        return body


# ── Wikilinks ─────────────────────────────────────────────────────────────────

def inject_wikilinks(content: str, all_titles: list[str], current_title: str) -> str:
    """Scan content for mentions of other wiki page titles and wrap in [[]] syntax."""
    content = _clean_malformed_wikilinks(content)
    titles_to_link = sorted(
        [t for t in all_titles if t.lower() != current_title.lower()],
        key=len, reverse=True,
    )
    linked: set[str] = set()
    existing_links = set(re.findall(r'\[\[([^\]]+)\]\]', content))
    for title in titles_to_link:
        if title in existing_links or title.lower() in linked:
            continue
        pattern = re.compile(re.escape(title), re.IGNORECASE)
        match = pattern.search(content)
        if match:
            original_text = match.group(0)
            content = content[:match.start()] + f"[[{original_text}]]" + content[match.end():]
            linked.add(title.lower())
    return content


def _clean_malformed_wikilinks(content: str) -> str:
    """Fix common LLM wikilink mistakes: nested brackets, piped links, triple brackets."""
    content = re.sub(r'\[\[\[\[([^\]]+)\]\]\|[^\]]*\]\]', r'[[\1]]', content)
    content = re.sub(r'\[\[\[\[([^\]]+)\]\]\]\]', r'[[\1]]', content)
    content = re.sub(r'\[\[([^\]|]+)\|[^\]]*\]\]', r'[[\1]]', content)
    content = re.sub(r'\[\[\[([^\]]+)\]\]\]', r'[[\1]]', content)
    return content


def _should_merge_by_context(existing_source_docs: list[str], new_doc_filename: str) -> bool:
    """Always merge when titles match — rely on context-aware extraction prompt."""
    return True


# ── Chunking ──────────────────────────────────────────────────────────────────

def _count_tokens(text: str, model: str = "gpt-4") -> int:
    """Count real tokens using litellm (same as Vectify PageIndex)."""
    try:
        import litellm
        return litellm.token_counter(model=model, text=text)
    except Exception:
        return max(1, len(text) // 4)  # fallback: estimate 4 chars/token


def _split_into_chunks(text: str, model: str = "gpt-4") -> list[str]:
    """Split text into token-balanced chunks using real token counts (Vectify pattern).

    Mirrors Vectify's page_list_to_group_text():
    1. Build virtual 'pages' by splitting text at paragraph boundaries
    2. Count real tokens per segment via litellm.token_counter()
    3. Calculate average_tokens_per_part to balance chunks evenly
    4. Overlap by _CHUNK_OVERLAP_TOKENS tokens to preserve context at boundaries
    """
    if not text.strip():
        return []

    # Split text into paragraph-level segments (natural split points)
    segments = [s.strip() for s in text.split("\n\n") if s.strip()]
    if not segments:
        return [text]

    # Count real tokens per segment
    token_lengths = [_count_tokens(seg, model) for seg in segments]
    total_tokens = sum(token_lengths)

    if total_tokens <= _MAX_TOKENS_PER_CHUNK:
        return [text]  # entire text fits in one chunk

    # Vectify balanced chunk sizing:
    # average = ceil((total/num_parts + max_tokens) / 2)
    import math
    expected_parts = math.ceil(total_tokens / _MAX_TOKENS_PER_CHUNK)
    average_tokens_per_part = math.ceil(
        ((total_tokens / expected_parts) + _MAX_TOKENS_PER_CHUNK) / 2
    )

    chunks: list[str] = []
    current_segs: list[str] = []
    current_tokens = 0
    overlap_text = ""   # text carried over from previous chunk
    overlap_tokens = 0

    for i, (seg, seg_tokens) in enumerate(zip(segments, token_lengths)):
        if current_tokens + seg_tokens > average_tokens_per_part and current_segs:
            # Flush current chunk (prepend overlap from previous chunk)
            chunk_text = (overlap_text + "\n\n" if overlap_text else "") + "\n\n".join(current_segs)
            chunks.append(chunk_text.strip())

            # Calculate overlap: keep enough trailing segments to cover _CHUNK_OVERLAP_TOKENS
            overlap_segs: list[str] = []
            overlap_so_far = 0
            for prev_seg, prev_tokens in zip(reversed(current_segs), reversed(token_lengths[max(0, i - len(current_segs)):i])):
                if overlap_so_far + prev_tokens > _CHUNK_OVERLAP_TOKENS:
                    break
                overlap_segs.insert(0, prev_seg)
                overlap_so_far += prev_tokens
            overlap_text = "\n\n".join(overlap_segs)
            overlap_tokens = overlap_so_far

            current_segs = []
            current_tokens = 0

        current_segs.append(seg)
        current_tokens += seg_tokens

    # Final chunk
    if current_segs:
        chunk_text = (overlap_text + "\n\n" if overlap_text else "") + "\n\n".join(current_segs)
        chunks.append(chunk_text.strip())

    return [c for c in chunks if c]


# ── JSON Parsing ──────────────────────────────────────────────────────────────

def _parse_pages_json(raw: str) -> list[dict]:
    """Parse LLM response containing JSON wiki pages. Returns [] on any error."""
    try:
        content = raw.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
            if content.startswith("json"):
                content = content[4:]
        data = json.loads(content)
        pages = data.get("pages", [])
        if not isinstance(pages, list):
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
