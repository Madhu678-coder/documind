"""OpenKB Skill Factory — distils a portable agent SKILL.md from wiki content.

Mirrors `openkb skill new <name> "<intent>"` from the OpenKB CLI.

The LLM reads the wiki's concept and entity pages and writes a structured
SKILL.md that any AI agent (Claude Code, Codex, Gemini CLI) can load to
reason like a domain expert on the KB's topic.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.services.llm.provider import LLMProvider

logger = logging.getLogger(__name__)

_MAX_WIKI_CHARS = 60_000     # Total wiki context chars sent to the LLM
_MAX_PAGES_IN_CONTEXT = 30   # Cap to avoid oversized prompts

_SKILL_SYSTEM = """\
You are a technical writer distilling a knowledge base into a portable agent
skill.  An agent skill is a SKILL.md file that an AI coding/chat agent can
read to instantly gain domain expertise on a topic.

A SKILL.md must contain:
1. A YAML front-matter block with:
   - name: the skill name (slug, no spaces)
   - description: one sentence explaining what the skill enables
   - version: "1.0.0"
   - triggers: list of phrases that should activate this skill (e.g. queries
     the user would type that mean they need this knowledge)
2. A Markdown body with:
   ## Overview          — 2–3 paragraph summary of the domain
   ## Core Concepts     — bullet list of the most important concepts with brief definitions
   ## Key Entities      — bullet list of important entities (people, orgs, products, etc.)
   ## Decision Rules    — if/then rules and policies extracted from the wiki
   ## Worked Examples   — 2–3 example questions with concise answers grounded in the wiki
   ## Limitations       — what this skill does NOT cover; caveats and edge cases

Keep the skill dense and factual.  The target audience is an AI agent that
needs to answer user questions using this skill as its primary knowledge source.
"""

_SKILL_USER = """\
Skill name   : {skill_name}
User intent  : {intent}

Wiki content (concept and entity pages):
{wiki_context}

Write a SKILL.md file for this skill.  The skill should make an AI agent able
to answer questions about the topics in this wiki accurately and concisely.

Return ONLY the raw Markdown content of SKILL.md — including the YAML
front-matter block.  No additional explanation.
"""


@dataclass
class SkillResult:
    skill_name: str
    intent: str
    content: str          # Full SKILL.md content (YAML front-matter + Markdown body)
    page_count_used: int


async def generate_skill(
    provider: "LLMProvider",
    pages: list[Any],          # list[OpenKBPage]
    skill_name: str,
    intent: str,
) -> SkillResult:
    """Generate a SKILL.md from the wiki's concept and entity pages.

    Args:
        provider   : LLM provider.
        pages      : All OpenKBPage rows for the KB.
        skill_name : Short name for the skill (e.g. "hr-policy-expert").
        intent     : One-sentence description of what the skill should do.

    Returns:
        SkillResult with the SKILL.md content ready to save or return.
    """
    # Prioritise concept pages, then entity pages, then summaries
    priority_order = {"concept": 0, "entity": 1, "summary": 2, "exploration": 3}
    content_pages = sorted(
        [p for p in pages if p.page_category not in ("index",)],
        key=lambda p: priority_order.get(p.page_category, 9),
    )[:_MAX_PAGES_IN_CONTEXT]

    # Build wiki context string
    parts: list[str] = []
    total_chars = 0
    pages_used = 0
    for p in content_pages:
        entry = f"### [{p.page_category.upper()}] {p.title}\n{p.content or ''}\n"
        if total_chars + len(entry) > _MAX_WIKI_CHARS:
            break
        parts.append(entry)
        total_chars += len(entry)
        pages_used += 1

    wiki_context = "\n---\n".join(parts) if parts else "(wiki is empty)"

    # Sanitise skill name: lowercase, hyphens only
    safe_name = skill_name.lower().replace(" ", "-").replace("_", "-")

    user_msg = _SKILL_USER.format(
        skill_name=safe_name,
        intent=intent,
        wiki_context=wiki_context,
    )

    try:
        resp = await provider.complete(
            [{"role": "user", "content": user_msg}],
            system_prompt=_SKILL_SYSTEM,
            max_tokens=8192,
        )
        skill_content = resp.content.strip()

        # Strip accidental code fences
        if skill_content.startswith("```"):
            lines = skill_content.split("\n")
            skill_content = "\n".join(
                lines[1:-1] if lines[-1].startswith("```") else lines[1:]
            )
            skill_content = skill_content.removeprefix("markdown").strip()

        logger.info(
            "OpenKB skill generated",
            extra={"skill_name": safe_name, "pages_used": pages_used},
        )
        return SkillResult(
            skill_name=safe_name,
            intent=intent,
            content=skill_content,
            page_count_used=pages_used,
        )

    except Exception as exc:
        logger.error(
            "OpenKB skill generation failed",
            extra={"skill_name": safe_name, "error": str(exc)},
        )
        raise RuntimeError(f"Skill generation failed: {exc}") from exc
