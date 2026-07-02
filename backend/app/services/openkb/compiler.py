"""OpenKB compiler — exact port of OpenKB's _compile_concepts pipeline with DB storage.

Ported from openkb/OpenKB/openkb/agent/compiler.py.
All prompts, entity types, filtering logic, ghost-link cleaning, and
concurrency patterns are identical to the original.

Differences from the original:
 - Uses documind's async LLMProvider instead of litellm directly.
 - Stores pages in PostgreSQL (returns CompileResult) instead of writing
   markdown files to disk.
 - Reads existing page context from OpenKBPage list instead of filesystem.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.llm.provider import LLMProvider

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants — identical to OpenKB
# ---------------------------------------------------------------------------

ENTITY_TYPES: tuple[str, ...] = (
    "person", "organization", "place", "product", "work", "event", "other",
)
_ENTITY_TYPES_SET = frozenset(ENTITY_TYPES)
DEFAULT_ENTITY_TYPES = list(ENTITY_TYPES)

_MAX_CONCURRENCY = 5
_JSON_RESPONSE_FORMAT = {"type": "json_object"}   # passed as extra kwarg hint

# ---------------------------------------------------------------------------
# Prompt templates — copied verbatim from OpenKB compiler.py
# ---------------------------------------------------------------------------

AGENTS_MD = """\
# Wiki Schema

## Directory Structure
- sources/ — Document content. Short docs as .md, long docs as .json (per-page).
- summaries/ — One per source document.
- concepts/ — Cross-document topic synthesis.
- entities/ — Specific named things: people, organizations, places, products, events.
- explorations/ — Saved query results and analyses.

## Page Types
- Summary Page (summaries/): Key content of a single source document.
- Concept Page (concepts/): Cross-document topic synthesis with [[wikilinks]].
- Entity Page (entities/): A specific named thing with a type: frontmatter field.

## Format
- Use [[wikilink]] to link other wiki pages (e.g., [[concepts/attention]])
- Standard Markdown heading hierarchy
- Keep each page focused on a single topic

## Frontmatter (managed by code — do NOT emit it in generated content)
- type: Summary | Concept | capitalized entity subtype
- description: single-sentence one-liner
"""

_SYSTEM_TEMPLATE = """\
You are OpenKB's wiki compilation agent for a personal knowledge base.

{schema_md}

Write all content in {language} language.
Use [[wikilinks]] to connect related pages (e.g. [[concepts/attention]]).
"""

_SUMMARY_USER = """\
New document: {doc_name}

Full text:
{content}

Write a summary page for this document in Markdown.

Return a JSON object with two keys:
- "description": A single sentence (under 100 chars) describing the document's main contribution
- "content": The full summary in Markdown. Include key concepts, findings, ideas, \
and [[wikilinks]] to concepts that could become cross-document concept pages

Return ONLY valid JSON, no fences.
"""

_CONCEPTS_PLAN_USER = """\
Based on the summary above, decide how to update the wiki's CONCEPT pages and
ENTITY pages.

A CONCEPT is an abstract, recurring idea/pattern/mechanism (e.g. "agentic
systems"). An ENTITY is a specific named thing — a person, organization,
place, product, named work, or event (e.g. "Anthropic"). Each name goes in
exactly ONE group. A topic may have both (entity "NVIDIA" and concept
"ai-infrastructure-demand"); they cross-link, they do not merge.

Existing concept pages:
{concept_briefs}

Existing entity pages (with source counts = how many docs already cite them):
{entity_briefs}

Return a JSON object with two top-level keys, "concepts" and "entities".

"concepts" is an object with:
1. "create" — new concepts. Array of {{"name": "concept-slug", "title": "Title"}}
2. "update" — existing concepts with significant new info. Same shape.
3. "related" — existing concept slugs to cross-link only. Array of strings.

"entities" is an object with the same three keys, but create/update objects
add a "type" field, one of: __ENTITY_TYPES__. Example:
   {{"name": "anthropic", "title": "Anthropic", "type": "organization"}}

Rules:
- For the first few documents, create 2-3 foundational concepts at most.
- Create an ENTITY page only when the entity is (a) central to this document
  or (b) likely to recur across sources. Do NOT page proper nouns mentioned
  only in passing. Roughly 5-15 entities per document is typical; fewer for
  sparse documents.
- Prefer "update" over "create" for any concept or entity already listed above.
- Do NOT create a concept/entity that overlaps an existing one — use "update".
- Do NOT create concepts that are just the document topic itself.
- "related" is lightweight cross-linking only, no content rewrite.

Return ONLY valid JSON, no fences, no explanation.
"""

_KNOWN_TARGETS_USER = """\
The wiki currently contains these pages, and they are the COMPLETE list of \
valid [[wikilink]] targets you may use in the responses that follow:

{known_targets}

Rules for [[wikilinks]] in all subsequent responses:
- For [[concepts/X]]: X must appear in the whitelist above.
- For [[summaries/Y]]: Y must appear in the whitelist above.
- For [[entities/Z]]: Z must appear in the whitelist above.
- Do NOT invent new wikilink targets. If you want to mention a concept \
or entity that is not in the whitelist, write it as plain text without brackets.
"""

_CONCEPT_PAGE_USER = """\
Write the concept page for: {title}

This concept relates to the document "{doc_name}" summarized above.
{update_instruction}

Return a JSON object with two keys:
- "description": A single sentence (under 100 chars) defining this concept
- "content": The full concept page in Markdown. Include clear explanation, \
key details from the source document, and [[wikilinks]] to related concepts \
and [[summaries/{doc_name}]] — subject to the wikilink rules from the \
whitelist message above.

Return ONLY valid JSON, no fences.
"""

_CONCEPT_UPDATE_USER = """\
Update the concept page for: {title}

Current content of this page:
{existing_content}

New information from document "{doc_name}" (summarized above) should be \
integrated into this page. Rewrite the full page incorporating the new \
information naturally — do not just append. Preserve the existing structure \
and intent of the page.

For [[wikilinks]] in the rewrite, follow the whitelist rules from the \
message above: keep links whose target is in the whitelist, convert any \
existing links whose target is NOT in the whitelist to plain text, and do \
not invent new wikilink targets.

Return a JSON object with two keys:
- "description": A single sentence (under 100 chars) defining this concept (may differ from before)
- "content": The rewritten full concept page in Markdown

Return ONLY valid JSON, no fences.
"""

_ENTITY_PAGE_USER = """\
Write the entity page for: {title} (type: {type})

This entity relates to the document "{doc_name}" summarized above.

Return a JSON object with three keys:
- "description": A single sentence (under 100 chars) identifying this entity
- "type": one of __ENTITY_TYPES__
- "content": The full entity page in Markdown — what this entity is, the key
  facts about it from this document, and [[wikilinks]] to related concepts,
  other [[entities/...]], and [[summaries/{doc_name}]] — subject to the
  whitelist rules from the message above.

Return ONLY valid JSON, no fences.
"""

_ENTITY_UPDATE_USER = """\
Update the entity page for: {title} (type: {type})

Current content of this page:
{existing_content}

Integrate the new facts about this entity from document "{doc_name}"
(summarized above). Rewrite the full page — do not just append. Preserve the
existing structure and intent. Follow the whitelist rules from the message
above for all [[wikilinks]].

Return a JSON object with three keys:
- "description": A single sentence (under 100 chars) identifying this entity
- "type": one of __ENTITY_TYPES__
- "content": The rewritten full entity page in Markdown

Return ONLY valid JSON, no fences.
"""

_SUMMARY_REWRITE_USER = """\
Task: Rewrite the summary you wrote above into a final version that is \
consistent with the concept pages now in the wiki (per the whitelist message \
above).

STRICT rules:
- Preserve every factual claim, finding, and detail from your draft. Do \
NOT add or remove technical content, examples, or claims.
- For [[wikilinks]], follow the whitelist message above: keep valid links, \
replace targets not in the whitelist with plain text, do not invent new \
wikilink targets.
- You MAY upgrade plain-text mentions to [[wikilinks]] when the concept \
appears in the whitelist — this is encouraged.
- Keep the headings, paragraph structure, and approximately the same length \
as the draft.

Return ONLY the rewritten Markdown content (no JSON, no fences, no frontmatter).
"""

_LONG_DOC_SUMMARY_USER = """\
This is a PageIndex summary for long document "{doc_name}" (doc_id: {doc_id}):

{content}

Based on this structured summary, write a concise overview that captures \
the key themes and findings. This will be used to generate concept pages.

Return ONLY the Markdown content (no frontmatter, no code fences).
"""

# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class PageData:
    """A wiki page to create or update in the DB."""
    title: str
    page_category: str       # "summary" | "concept" | "entity"
    page_type: str            # entity subtype OR mirrors page_category
    description: str          # stored as .summary in DB
    content: str
    doc_type: str = "short"   # "short" | "pageindex"
    is_update: bool = False
    existing_id: str | None = None  # UUID of row to update


@dataclass
class CompileResult:
    """Full compilation result for one document — no DB writes in this layer."""
    summary: PageData | None = None
    concept_pages: list[PageData] = field(default_factory=list)
    entity_pages: list[PageData] = field(default_factory=list)
    # Existing pages that only need a "See also: [[summaries/doc]]" link appended
    # (the "related" items that are cross-linked but not rewritten)
    related_page_updates: list[PageData] = field(default_factory=list)
    doc_brief: str = ""
    doc_type: str = "short"

    @property
    def all_pages(self) -> list[PageData]:
        out: list[PageData] = []
        if self.summary:
            out.append(self.summary)
        out.extend(self.concept_pages)
        out.extend(self.entity_pages)
        out.extend(self.related_page_updates)
        return out

# ---------------------------------------------------------------------------
# JSON parsing — ported from OpenKB _parse_json
# ---------------------------------------------------------------------------


def _parse_json(text: str) -> dict | list:
    """Parse JSON from LLM response; tolerates fences and malformed JSON."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        first_nl = cleaned.find("\n")
        cleaned = cleaned[first_nl + 1:] if first_nl != -1 else cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.removeprefix("json").strip()
    try:
        result = json.loads(cleaned)
    except json.JSONDecodeError:
        try:
            from json_repair import repair_json  # type: ignore[import]
            result = json.loads(repair_json(cleaned))
        except Exception:
            raise
    if not isinstance(result, (dict, list)):
        raise ValueError(f"Expected JSON object or array, got {type(result).__name__}")
    return result


# ---------------------------------------------------------------------------
# Name sanitization — identical to OpenKB
# ---------------------------------------------------------------------------

_SAFE_NAME_RE = re.compile(r"[^\w\-]")


def _sanitize_concept_name(name: str) -> str:
    name = unicodedata.normalize("NFKC", name)
    sanitized = _SAFE_NAME_RE.sub("-", name).strip("-")
    return sanitized or "unnamed-concept"


# ---------------------------------------------------------------------------
# Plan filtering — identical to OpenKB
# ---------------------------------------------------------------------------


def _filter_concept_items(items: object, label: str) -> list[dict]:
    if not isinstance(items, list):
        return []
    return [
        c for c in items
        if isinstance(c, dict) and isinstance(c.get("name"), str) and c["name"].strip()
    ]


def _filter_related_slugs(items: object) -> list[str]:
    if not isinstance(items, list):
        return []
    return [s for s in items if isinstance(s, str) and s.strip()]


def _filter_entity_items(items: object, valid_types: frozenset | None = None) -> list[dict]:
    if valid_types is None:
        valid_types = _ENTITY_TYPES_SET
    out: list[dict] = []
    if not isinstance(items, list):
        return out
    for it in items:
        if not isinstance(it, dict):
            continue
        name = it.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        title = it.get("title") if isinstance(it.get("title"), str) else name
        etype = it.get("type")
        if not isinstance(etype, str) or etype not in valid_types:
            etype = "other"
        out.append({"name": name, "title": title, "type": etype})
    return out


def _parse_entities_plan(parsed: object, valid_types: frozenset | None = None) -> dict:
    empty: dict = {"create": [], "update": [], "related": []}
    if not isinstance(parsed, dict):
        return empty
    group = parsed.get("entities")
    if not isinstance(group, dict):
        return empty
    return {
        "create": _filter_entity_items(group.get("create", []), valid_types),
        "update": _filter_entity_items(group.get("update", []), valid_types),
        "related": _filter_related_slugs(group.get("related", [])),
    }

# ---------------------------------------------------------------------------
# Ghost wikilink cleaning — ported from OpenKB lint.py
# ---------------------------------------------------------------------------

_WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")


def _normalize_target(target: str) -> str:
    s = unicodedata.normalize("NFKC", target).lower().replace("_", "-")
    parts = [re.sub(r"-+", "-", p).strip("-") for p in s.split("/")]
    return "/".join(parts)


def strip_ghost_wikilinks(content: str, known_targets: set[str]) -> tuple[str, list[str]]:
    """Remove [[wikilinks]] whose targets do not exist in known_targets.

    Returns (cleaned_content, list_of_ghost_targets).
    """
    norm_index = {_normalize_target(t): t for t in known_targets}
    ghosts: list[str] = []

    def _repl(m: re.Match) -> str:
        raw = m.group(1)
        if "|" in raw:
            target, alias = raw.split("|", 1)
            target, alias = target.strip(), alias.strip()
        else:
            target, alias = raw.strip(), None

        if target in known_targets:
            return m.group(0)

        canonical = norm_index.get(_normalize_target(target))
        if canonical is not None:
            return f"[[{canonical}|{alias}]]" if alias else f"[[{canonical}]]"

        ghosts.append(target)
        return alias or target.rsplit("/", 1)[-1].replace("-", " ").replace("_", " ")

    return _WIKILINK_RE.sub(_repl, content), ghosts


# ---------------------------------------------------------------------------
# DB context readers — mirrors OpenKB's _read_concept_briefs / _read_entity_briefs
# ---------------------------------------------------------------------------


def _read_concept_briefs_db(existing_pages: list) -> str:
    concepts = sorted(
        [p for p in existing_pages if p.page_category == "concept"],
        key=lambda p: p.title,
    )
    if not concepts:
        return "(none yet)"
    lines = []
    for p in concepts:
        brief = (p.summary or "").replace("\n", " ")[:150]
        lines.append(f"- {p.title}: {brief}" if brief else f"- {p.title}")
    return "\n".join(lines)


def _read_entity_briefs_db(existing_pages: list) -> str:
    entities = sorted(
        [p for p in existing_pages if p.page_category == "entity"],
        key=lambda p: p.title,
    )
    if not entities:
        return "(none yet)"
    lines = []
    for p in entities:
        etype = p.page_type if p.page_type in ENTITY_TYPES else "other"
        n = len(p.source_doc_ids) if p.source_doc_ids else 0
        brief = (p.summary or "").replace("\n", " ")[:150]
        suffix = f" — {brief}" if brief else ""
        lines.append(f"- {p.title} ({etype}, {n} sources){suffix}")
    return "\n".join(lines)


def list_existing_wiki_targets_db(existing_pages: list) -> set[str]:
    """Mirrors OpenKB's list_existing_wiki_targets but reads from DB pages."""
    targets: set[str] = set()
    for p in existing_pages:
        cat = p.page_category
        if cat == "concept":
            targets.add(f"concepts/{p.title}")
        elif cat == "summary":
            targets.add(f"summaries/{p.title}")
        elif cat == "entity":
            targets.add(f"entities/{p.title}")
    if any(p.page_category == "index" for p in existing_pages):
        targets.add("index")
    return targets


def _format_known_targets(targets: set[str]) -> str:
    if not targets:
        return "(none yet — do not use any [[wikilinks]] in your output)"
    return "\n".join(f"- {t}" for t in sorted(targets))

# ---------------------------------------------------------------------------
# Index content builder — mirrors OpenKB's _update_index
# ---------------------------------------------------------------------------


def build_index_content(existing_pages: list, new_pages: list[PageData] | None = None) -> str:
    """Build the full index.md content from all existing + new pages."""
    all_pages = list(existing_pages) + list(new_pages or [])

    summaries = sorted(
        [p for p in all_pages if getattr(p, "page_category", "") == "summary"],
        key=lambda p: p.title,
    )
    concepts = sorted(
        [p for p in all_pages if getattr(p, "page_category", "") == "concept"],
        key=lambda p: p.title,
    )
    entities = sorted(
        [p for p in all_pages if getattr(p, "page_category", "") == "entity"],
        key=lambda p: p.title,
    )

    lines = ["# Knowledge Base Index", "", "## Documents", ""]
    for p in summaries:
        brief = (p.summary if isinstance(p, PageData) else getattr(p, "summary", None)) or ""
        doc_t = (p.doc_type if isinstance(p, PageData) else getattr(p, "doc_type", "short")) or "short"
        entry = f"- [[summaries/{p.title}]] ({doc_t})"
        if brief:
            entry += f" — {brief}"
        lines.append(entry)

    lines += ["", "## Concepts", ""]
    for p in concepts:
        brief = (p.summary if isinstance(p, PageData) else getattr(p, "summary", None)) or ""
        entry = f"- [[concepts/{p.title}]]"
        if brief:
            entry += f" — {brief}"
        lines.append(entry)

    lines += ["", "## Entities", ""]
    for p in entities:
        etype = (p.page_type if isinstance(p, PageData) else getattr(p, "page_type", "other")) or "other"
        brief = (p.summary if isinstance(p, PageData) else getattr(p, "summary", None)) or ""
        entry = f"- [[entities/{p.title}]] ({etype})"
        if brief:
            entry += f" — {brief}"
        lines.append(entry)

    lines += ["", "## Explorations", ""]
    return "\n".join(lines)

# ---------------------------------------------------------------------------
# Backlinks — mirrors OpenKB's _backlink_summary / _backlink_concepts /
#             _backlink_entities / _add_related_link
# ---------------------------------------------------------------------------


def _ensure_section(content: str, heading: str, new_entry: str) -> str:
    """Append or add-to a ## section in Markdown content.

    If the section exists, appends new_entry as a bullet inside it.
    If absent, creates the section at the end.
    """
    if heading in content:
        # Find the section and append inside it, before the next ## heading
        idx = content.index(heading)
        after = content[idx + len(heading):]
        next_heading = after.find("\n## ")
        insert_at = idx + len(heading) + (next_heading if next_heading != -1 else len(after))
        return content[:insert_at].rstrip() + f"\n- {new_entry}\n" + content[insert_at:]
    return content.rstrip() + f"\n\n{heading}\n- {new_entry}\n"


def _apply_backlinks(
    summary_page: PageData,
    concept_pages: list[PageData],
    entity_pages: list[PageData],
    related_concept_slugs: list[str],
    related_entity_slugs: list[str],
    existing_pages: list,
    doc_name: str,
) -> tuple[PageData, list[PageData], list[PageData], list[PageData]]:
    """Add bidirectional cross-reference links — mirrors OpenKB's backlink helpers.

    OpenKB equivalents:
      _backlink_summary          → ## Related Concepts section on summary page
      _backlink_summary_entities → ## Entities section on summary page
      _backlink_concepts         → ## Related Documents section on each concept page
      _backlink_entities         → ## Related Documents section on each entity page
      _add_related_link          → "See also: [[summaries/doc]]" on related-only pages

    Returns (summary, concept_pages, entity_pages, related_page_updates).
    """
    summary_link = f"[[summaries/{doc_name}]]"
    concept_slugs = [p.title for p in concept_pages]
    entity_slugs  = [p.title for p in entity_pages]

    # ── 1. Summary page: ## Related Concepts + ## Entities ───────────────────
    all_concept_backlinks = concept_slugs + [s for s in related_concept_slugs if s not in concept_slugs]
    all_entity_backlinks  = entity_slugs  + [s for s in related_entity_slugs  if s not in entity_slugs]

    for slug in all_concept_backlinks:
        link = f"[[concepts/{slug}]]"
        if link not in summary_page.content:
            summary_page.content = _ensure_section(summary_page.content, "## Related Concepts", link)

    for slug in all_entity_backlinks:
        link = f"[[entities/{slug}]]"
        if link not in summary_page.content:
            summary_page.content = _ensure_section(summary_page.content, "## Entities", link)

    # ── 2. Each concept page: ## Related Documents ────────────────────────────
    for p in concept_pages:
        if summary_link not in p.content:
            p.content = _ensure_section(p.content, "## Related Documents", summary_link)

    # ── 3. Each entity page: ## Related Documents ─────────────────────────────
    for p in entity_pages:
        if summary_link not in p.content:
            p.content = _ensure_section(p.content, "## Related Documents", summary_link)

    # ── 4. Related-only items: append "See also: [[summaries/doc]]" ───────────
    #       These are existing pages that get a lightweight cross-link — no LLM
    #       rewrite.  Mirrors OpenKB's _add_related_link().
    related_updates: list[PageData] = []
    see_also = f"\n\nSee also: {summary_link}"

    def _make_related_update(existing, cat: str) -> None:
        if existing and summary_link not in (existing.content or ""):
            related_updates.append(PageData(
                title=existing.title,
                page_category=cat,
                page_type=existing.page_type,
                description=existing.summary or "",
                content=(existing.content or "") + see_also,
                doc_type=getattr(existing, "doc_type", "short") or "short",
                is_update=True,
                existing_id=str(existing.id),
            ))

    for slug in related_concept_slugs:
        ex = next((p for p in existing_pages if p.page_category == "concept" and p.title == slug), None)
        _make_related_update(ex, "concept")

    for slug in related_entity_slugs:
        ex = next((p for p in existing_pages if p.page_category == "entity" and p.title == slug), None)
        _make_related_update(ex, "entity")

    return summary_page, concept_pages, entity_pages, related_updates


# ---------------------------------------------------------------------------
# AGENTS.md schema seed — mirrors OpenKB's schema.AGENTS_MD
# ---------------------------------------------------------------------------

FULL_AGENTS_MD = """\
# Wiki Schema

## Directory Structure
- sources/ — Document content. Short docs as .md, long docs as .json (per-page). Do not modify directly.
- sources/images/ — Extracted images from documents, referenced by sources.
- summaries/ — One per source document. Summary of key content.
- concepts/ — Cross-document topic synthesis. Created when a theme spans multiple documents.
- entities/ — Specific named things: people, organizations, places, products, named works, events.
             One page per entity, accumulated across documents.
- explorations/ — Saved query results, analyses, and comparisons worth keeping.

## Special Files
- index.md — Content catalog: every page with link, one-line summary, organized by category.

## Page Types
- **Summary Page** (summaries/): Key content of a single source document.
  - doc_type: short     → full source text embedded in the summary.
  - doc_type: pageindex → source is a long PDF indexed by PageIndex; retrieve by page range.
- **Concept Page** (concepts/): Cross-document topic synthesis with [[wikilinks]].
- **Entity Page** (entities/): A specific named thing (person, organization, place, product,
  named work, event, or other). Each page has a type: frontmatter field.
- **Exploration Page** (explorations/): Saved query results — analyses, comparisons, syntheses.
- **Index Page** (index.md): One-liner summary of every page in the wiki. Auto-maintained.

## Index Page Format
index.md lists all documents, concepts, entities with:
- Documents: name, one-liner description, type (short|pageindex)
- Concepts: name, one-liner description
- Entities: name, entity-type, one-liner description

## Format
- Use [[wikilink]] to link other wiki pages (e.g., [[concepts/attention]])
- Standard Markdown heading hierarchy
- Keep each page focused on a single topic

## Frontmatter (managed by code — do NOT emit in generated content)
- type: Summary | Concept | capitalized entity subtype (e.g. Organization)
- description: single-sentence one-liner
- doc_type: short | pageindex (summary pages only)
- sources: list of source doc slugs that contributed to this page
"""


async def _compile_concepts_db(
    provider: "LLMProvider",
    system_str: str,
    doc_content_prompt: str,   # full _SUMMARY_USER formatted string (includes doc text)
    summary: str,               # v1 summary text (from step 1)
    doc_name: str,
    doc_id: str,
    existing_pages: list,       # all OpenKBPage rows currently in this KB
    doc_type: str = "short",
    rewrite_summary: bool = False,
    entity_types: list[str] | None = None,
) -> tuple[PageData, list[PageData], list[PageData], str, list[PageData]]:
    """Shared Steps 2-4: plan → concurrent generate/update → index.

    Returns (summary_page_data, concept_pages, entity_pages, doc_brief, related_page_updates).
    Mirrors OpenKB's _compile_concepts() with DB storage.
    """
    if entity_types is None:
        entity_types = DEFAULT_ENTITY_TYPES
    types_str = ", ".join(entity_types)
    valid_types = frozenset(entity_types)

    source_file = f"summaries/{doc_name}"

    # --- Step 2: Get concepts plan ---
    concept_briefs = _read_concept_briefs_db(existing_pages)
    entity_briefs = _read_entity_briefs_db(existing_pages)

    plan_messages = [
        {"role": "user", "content": doc_content_prompt},
        {"role": "assistant", "content": summary},
        {"role": "user", "content": _CONCEPTS_PLAN_USER.format(
            concept_briefs=concept_briefs,
            entity_briefs=entity_briefs,
        ).replace("__ENTITY_TYPES__", types_str)},
    ]

    plan_raw = ""
    doc_brief = ""
    try:
        plan_resp = await provider.complete(plan_messages, system_prompt=system_str, max_tokens=4096)
        plan_raw = plan_resp.content.strip()
        parsed = _parse_json(plan_raw)
    except Exception as exc:
        logger.warning("OpenKB: concepts plan failed for %s: %s", doc_name, exc)
        parsed = {}

    if not isinstance(parsed, (dict, list)):
        parsed = {}

    if isinstance(parsed, list):
        plan = {"create": _filter_concept_items(parsed, "list"), "update": [], "related": []}
        entities_plan: dict = {"create": [], "update": [], "related": []}
    else:
        concepts_group = (
            parsed.get("concepts")
            if isinstance(parsed.get("concepts"), dict)
            else parsed
        )
        if not isinstance(concepts_group, dict):
            concepts_group = {}
        plan = {
            "create": _filter_concept_items(concepts_group.get("create", []), "create"),
            "update": _filter_concept_items(concepts_group.get("update", []), "update"),
            "related": _filter_related_slugs(concepts_group.get("related", [])),
        }
        entities_plan = _parse_entities_plan(parsed, valid_types)

    create_items = plan["create"]
    update_items = plan["update"]
    related_items = plan["related"]
    entity_create = entities_plan["create"]
    entity_update = entities_plan["update"]

    # Filter related items to only existing pages
    existing_concept_slugs = {
        _sanitize_concept_name(p.title)
        for p in existing_pages if p.page_category == "concept"
    }
    existing_entity_slugs = {
        _sanitize_concept_name(p.title)
        for p in existing_pages if p.page_category == "entity"
    }
    related_items = [s for s in related_items if _sanitize_concept_name(s) in existing_concept_slugs]
    entity_related = [s for s in entities_plan["related"] if _sanitize_concept_name(s) in existing_entity_slugs]

    if not (create_items or update_items or related_items
            or entity_create or entity_update or entity_related):
        # Empty plan — write summary stripped of ghost links and return
        known = list_existing_wiki_targets_db(existing_pages)
        known.add(f"summaries/{doc_name}")
        cleaned, _ = strip_ghost_wikilinks(summary, known)
        sum_page = PageData(
            title=doc_name, page_category="summary", page_type="summary",
            description="", content=cleaned, doc_type=doc_type,
            is_update=any(p.page_category == "summary" and p.title == doc_name for p in existing_pages),
        )
        return sum_page, [], [], "", []

    # Build known-targets whitelist (existing + this round's planned pages)
    planned_concept_slugs = {
        _sanitize_concept_name(c["name"]) for c in create_items + update_items
    } | {_sanitize_concept_name(s) for s in related_items}
    planned_entity_slugs = {
        _sanitize_concept_name(e["name"]) for e in entity_create + entity_update
    } | {_sanitize_concept_name(s) for s in entity_related}

    known_targets: set[str] = (
        list_existing_wiki_targets_db(existing_pages)
        | {f"concepts/{s}" for s in planned_concept_slugs}
        | {f"entities/{s}" for s in planned_entity_slugs}
        | {f"summaries/{doc_name}"}
    )
    known_targets_str = _format_known_targets(known_targets)

    # Base message context reused for every concurrent call
    base_messages = [
        {"role": "user", "content": doc_content_prompt},
        {"role": "assistant", "content": summary},
        {"role": "user", "content": _KNOWN_TARGETS_USER.format(known_targets=known_targets_str)},
    ]

    semaphore = asyncio.Semaphore(_MAX_CONCURRENCY)

    # --- Concept generators ---
    async def _gen_concept_create(concept: dict) -> tuple[str, str, str]:
        name, title = concept["name"], concept.get("title", concept["name"])
        prompt = _CONCEPT_PAGE_USER.format(title=title, doc_name=doc_name, update_instruction="")
        async with semaphore:
            resp = await provider.complete(
                base_messages + [{"role": "user", "content": prompt}],
                system_prompt=system_str, max_tokens=4096,
            )
        try:
            data = _parse_json(resp.content)
            return name, data.get("description", ""), data.get("content") or resp.content
        except Exception:
            return name, "", resp.content

    async def _gen_concept_update(concept: dict) -> tuple[str, str, str]:
        name, title = concept["name"], concept.get("title", concept["name"])
        slug = _sanitize_concept_name(name)
        existing = next((p for p in existing_pages if p.page_category == "concept" and p.title == slug), None)
        existing_content = (existing.content if existing else "(page not found — create from scratch)")
        prompt = _CONCEPT_UPDATE_USER.format(
            title=title, doc_name=doc_name, existing_content=existing_content[:8000],
        )
        async with semaphore:
            resp = await provider.complete(
                base_messages + [{"role": "user", "content": prompt}],
                system_prompt=system_str, max_tokens=4096,
            )
        try:
            data = _parse_json(resp.content)
            return name, data.get("description", ""), data.get("content") or resp.content
        except Exception:
            return name, "", resp.content

    async def _gen_entity_create(ent: dict) -> tuple[str, str, str, str]:
        name, title, etype = ent["name"], ent.get("title", ent["name"]), ent.get("type", "other")
        prompt = _ENTITY_PAGE_USER.format(
            title=title, type=etype, doc_name=doc_name,
        ).replace("__ENTITY_TYPES__", types_str)
        async with semaphore:
            resp = await provider.complete(
                base_messages + [{"role": "user", "content": prompt}],
                system_prompt=system_str, max_tokens=4096,
            )
        try:
            data = _parse_json(resp.content)
            etype_out = data.get("type") if data.get("type") in valid_types else etype
            return name, data.get("description", ""), data.get("content") or resp.content, etype_out
        except Exception:
            return name, "", resp.content, etype

    async def _gen_entity_update(ent: dict) -> tuple[str, str, str, str]:
        name, title, etype = ent["name"], ent.get("title", ent["name"]), ent.get("type", "other")
        slug = _sanitize_concept_name(name)
        existing = next((p for p in existing_pages if p.page_category == "entity" and p.title == slug), None)
        existing_content = (existing.content if existing else "(page not found — create from scratch)")
        prompt = _ENTITY_UPDATE_USER.format(
            title=title, type=etype, doc_name=doc_name, existing_content=existing_content[:8000],
        ).replace("__ENTITY_TYPES__", types_str)
        async with semaphore:
            resp = await provider.complete(
                base_messages + [{"role": "user", "content": prompt}],
                system_prompt=system_str, max_tokens=4096,
            )
        try:
            data = _parse_json(resp.content)
            etype_out = data.get("type") if data.get("type") in valid_types else etype
            return name, data.get("description", ""), data.get("content") or resp.content, etype_out
        except Exception:
            return name, "", resp.content, etype

    concept_coros = [_gen_concept_create(c) for c in create_items] + \
                    [_gen_concept_update(c) for c in update_items]
    entity_coros  = [_gen_entity_create(e) for e in entity_create] + \
                    [_gen_entity_update(e) for e in entity_update]

    concept_results_raw, entity_results_raw = await asyncio.gather(
        asyncio.gather(*concept_coros, return_exceptions=True),
        asyncio.gather(*entity_coros, return_exceptions=True),
    )

    # --- Collect and clean concept pages ---
    concept_pages: list[PageData] = []
    for i, r in enumerate(concept_results_raw):
        if isinstance(r, Exception):
            logger.warning("OpenKB: concept generation exception: %s", r)
            continue
        name, brief, body = r
        slug = _sanitize_concept_name(name)
        cleaned_body, ghosts = strip_ghost_wikilinks(body, known_targets)
        if ghosts:
            logger.debug("OpenKB: stripped %d ghost link(s) from concept %s", len(ghosts), name)
        is_upd = any(p.page_category == "concept" and p.title == slug for p in existing_pages)
        ex_id = next((str(p.id) for p in existing_pages if p.page_category == "concept" and p.title == slug), None)
        concept_pages.append(PageData(
            title=slug, page_category="concept", page_type="concept",
            description=brief, content=cleaned_body, doc_type=doc_type,
            is_update=is_upd, existing_id=ex_id,
        ))
        if not doc_brief and brief:
            pass  # doc_brief comes from summary description

    # --- Collect and clean entity pages ---
    entity_pages: list[PageData] = []
    for r in entity_results_raw:
        if isinstance(r, Exception):
            logger.warning("OpenKB: entity generation exception: %s", r)
            continue
        name, brief, body, etype = r
        slug = _sanitize_concept_name(name)
        cleaned_body, ghosts = strip_ghost_wikilinks(body, known_targets)
        is_upd = any(p.page_category == "entity" and p.title == slug for p in existing_pages)
        ex_id = next((str(p.id) for p in existing_pages if p.page_category == "entity" and p.title == slug), None)
        entity_pages.append(PageData(
            title=slug, page_category="entity", page_type=etype,
            description=brief, content=cleaned_body, doc_type=doc_type,
            is_update=is_upd, existing_id=ex_id,
        ))

    # --- Summary rewrite (short-doc path only) ---
    final_summary = summary
    if rewrite_summary:
        try:
            rewrite_resp = await provider.complete(
                base_messages + [{"role": "user", "content": _SUMMARY_REWRITE_USER}],
                system_prompt=system_str,
            )
            candidate = rewrite_resp.content.strip()
            cleaned_cand, _ = strip_ghost_wikilinks(candidate, known_targets)
            if cleaned_cand:
                final_summary = cleaned_cand
        except Exception as exc:
            logger.warning("OpenKB: summary rewrite failed for %s: %s", doc_name, exc)
            final_summary, _ = strip_ghost_wikilinks(summary, known_targets)

    is_sum_update = any(p.page_category == "summary" and p.title == doc_name for p in existing_pages)
    ex_sum_id = next(
        (str(p.id) for p in existing_pages if p.page_category == "summary" and p.title == doc_name), None
    )
    summary_page = PageData(
        title=doc_name, page_category="summary", page_type="summary",
        description=doc_brief, content=final_summary, doc_type=doc_type,
        is_update=is_sum_update, existing_id=ex_sum_id,
    )

    logger.info(
        "OpenKB: compile_concepts done for %s — %d concepts, %d entities",
        doc_name, len(concept_pages), len(entity_pages),
    )

    # ── Backlinks — mirrors OpenKB's _backlink_* and _add_related_link ────────
    summary_page, concept_pages, entity_pages, related_updates = _apply_backlinks(
        summary_page=summary_page,
        concept_pages=concept_pages,
        entity_pages=entity_pages,
        related_concept_slugs=[_sanitize_concept_name(s) for s in related_items],
        related_entity_slugs=[_sanitize_concept_name(s) for s in entity_related],
        existing_pages=existing_pages,
        doc_name=doc_name,
    )

    return summary_page, concept_pages, entity_pages, doc_brief, related_updates


# ---------------------------------------------------------------------------
# Public compile entry points
# ---------------------------------------------------------------------------


async def compile_short_doc_db(
    provider: "LLMProvider",
    doc_name: str,
    source_text: str,
    doc_id: str,
    existing_pages: list,
    language: str = "en",
) -> CompileResult:
    """Compile a short document (< pageindex_threshold pages).

    Mirrors OpenKB's compile_short_doc() but stores pages in DB.
    """
    system_str = _SYSTEM_TEMPLATE.format(schema_md=FULL_AGENTS_MD, language=language)
    doc_content_prompt = _SUMMARY_USER.format(doc_name=doc_name, content=source_text)

    # Step 1: Generate v1 summary
    try:
        sum_resp = await provider.complete(
            [{"role": "user", "content": doc_content_prompt}],
            system_prompt=system_str,
            max_tokens=4096,
        )
        sum_data = _parse_json(sum_resp.content)
        doc_brief = sum_data.get("description", "")
        summary = sum_data.get("content", sum_resp.content)
    except Exception as exc:
        logger.warning("OpenKB: short-doc summary failed for %s: %s", doc_name, exc)
        doc_brief = ""
        summary = source_text[:3000]

    # Steps 2-4: plan → concurrent generation → summary rewrite → index
    sum_page, concept_pages, entity_pages, _, related_updates = await _compile_concepts_db(
        provider=provider,
        system_str=system_str,
        doc_content_prompt=doc_content_prompt,
        summary=summary,
        doc_name=doc_name,
        doc_id=doc_id,
        existing_pages=existing_pages,
        doc_type="short",
        rewrite_summary=True,
    )
    sum_page.description = doc_brief

    return CompileResult(
        summary=sum_page,
        concept_pages=concept_pages,
        entity_pages=entity_pages,
        related_page_updates=related_updates,
        doc_brief=doc_brief,
        doc_type="short",
    )


async def compile_long_doc_db(
    provider: "LLMProvider",
    doc_name: str,
    summary_md: str,
    doc_id: str,
    existing_pages: list,
    doc_description: str = "",
    language: str = "en",
) -> CompileResult:
    """Compile a long document (>= pageindex_threshold pages, indexed by PageIndex).

    Mirrors OpenKB's compile_long_doc() but stores pages in DB.
    summary_md is the tree-structure Markdown produced by the PageIndex indexer.
    """
    system_str = _SYSTEM_TEMPLATE.format(schema_md=FULL_AGENTS_MD, language=language)
    doc_content_prompt = _LONG_DOC_SUMMARY_USER.format(
        doc_name=doc_name, doc_id=doc_id, content=summary_md,
    )

    # Step 1: Generate overview from PageIndex tree summary
    try:
        ov_resp = await provider.complete(
            [{"role": "user", "content": doc_content_prompt}],
            system_prompt=system_str,
        )
        overview = ov_resp.content.strip()
    except Exception as exc:
        logger.warning("OpenKB: long-doc overview failed for %s: %s", doc_name, exc)
        overview = summary_md[:3000]

    # Steps 2-4: plan → concurrent generation → index (no summary rewrite for long docs)
    sum_page, concept_pages, entity_pages, _, related_updates = await _compile_concepts_db(
        provider=provider,
        system_str=system_str,
        doc_content_prompt=doc_content_prompt,
        summary=overview,
        doc_name=doc_name,
        doc_id=doc_id,
        existing_pages=existing_pages,
        doc_type="pageindex",
        rewrite_summary=False,
    )
    # For long docs the summary page content is the tree structure (already written by indexer)
    sum_page.content = summary_md
    sum_page.description = doc_description or overview[:100]
    sum_page.doc_type = "pageindex"

    return CompileResult(
        summary=sum_page,
        concept_pages=concept_pages,
        entity_pages=entity_pages,
        related_page_updates=related_updates,
        doc_brief=doc_description,
        doc_type="pageindex",
    )
