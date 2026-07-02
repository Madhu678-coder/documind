"""OpenKB Deck Generator — generates a single-file interactive HTML slide deck.

Mirrors `openkb deck new <name> "<intent>"` from the OpenKB CLI.

The LLM reads the wiki content and structures it into slides.  The result is a
self-contained HTML file (no external dependencies) with keyboard navigation,
a table-of-contents sidebar, and a clean professional design.
"""
from __future__ import annotations

import html
import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.services.llm.provider import LLMProvider

logger = logging.getLogger(__name__)

_MAX_WIKI_CHARS = 50_000
_MAX_PAGES_IN_CONTEXT = 25

_DECK_SYSTEM = """\
You are a presentation designer creating a slide deck from a knowledge base.
Your output must be a JSON object that represents a slide deck.

Each slide has:
  - "title": short slide title (5–8 words)
  - "type": one of "title_slide" | "content" | "two_column" | "quote" | "summary"
  - "content": Markdown body text for the slide

Slide structure rules:
- Slide 1 must be type "title_slide" with the deck title and a subtitle.
- Slide 2 must be an "Agenda" / Table of Contents slide.
- Last slide must be a "summary" or "key_takeaways" slide.
- Total slides: 8–15. Adjust within this range based on content depth — use fewer slides for concise topics, more for complex ones.
- For "two_column" slides, use "left" and "right" keys instead of "content".
- Keep each slide concise — bullets over paragraphs.
- Prefer "content" slides with 3–5 bullet points.

Return ONLY valid JSON:
{
  "title": "Deck Title",
  "subtitle": "Subtitle or author",
  "slides": [
    {"title": "...", "type": "title_slide", "content": "..."},
    ...
  ]
}
No code fences. No extra keys.
"""

_DECK_USER = """\
Deck name    : {deck_name}
User intent  : {intent}

Wiki content:
{wiki_context}

Create a professional slide deck based on the wiki content above.
The deck should help the audience understand the key topics and insights.
Return the JSON slide structure as specified.
"""

# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{deck_title}</title>
<style>
  :root {{
    --bg: #0f172a; --surface: #1e293b; --surface2: #334155;
    --accent: #6366f1; --accent2: #818cf8;
    --text: #f1f5f9; --muted: #94a3b8; --border: #475569;
    --slide-w: 960px; --slide-h: 540px;
  }}
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: var(--bg); color: var(--text); height: 100vh;
    display: flex; flex-direction: column; overflow: hidden;
  }}

  /* ── Top bar ── */
  .topbar {{
    background: var(--surface); border-bottom: 1px solid var(--border);
    padding: 0.5rem 1.2rem; display: flex; align-items: center;
    gap: 1rem; flex-shrink: 0; font-size: 0.85rem; color: var(--muted);
  }}
  .topbar .deck-title {{ color: var(--text); font-weight: 600; flex: 1; }}
  .slide-counter {{ font-variant-numeric: tabular-nums; }}

  /* ── Main layout ── */
  .main {{ display: flex; flex: 1; overflow: hidden; }}

  /* ── TOC sidebar ── */
  .toc {{
    width: 220px; background: var(--surface); border-right: 1px solid var(--border);
    overflow-y: auto; flex-shrink: 0; padding: 0.75rem 0;
  }}
  .toc-item {{
    padding: 0.45rem 1rem; font-size: 0.78rem; color: var(--muted);
    cursor: pointer; border-left: 3px solid transparent;
    transition: all 0.15s; white-space: nowrap; overflow: hidden;
    text-overflow: ellipsis;
  }}
  .toc-item:hover {{ background: var(--surface2); color: var(--text); }}
  .toc-item.active {{
    border-left-color: var(--accent); color: var(--accent2);
    background: rgba(99,102,241,0.1);
  }}
  .toc-num {{ color: var(--border); margin-right: 0.4rem; font-size: 0.72rem; }}

  /* ── Slide stage ── */
  .stage {{
    flex: 1; display: flex; flex-direction: column;
    align-items: center; justify-content: center;
    padding: 2rem; overflow: hidden;
  }}
  .slide {{
    width: var(--slide-w); max-width: 100%;
    aspect-ratio: 16/9; background: var(--surface);
    border-radius: 12px; border: 1px solid var(--border);
    box-shadow: 0 24px 64px rgba(0,0,0,0.5);
    display: none; flex-direction: column;
    padding: 3rem 3.5rem; position: relative; overflow: hidden;
  }}
  .slide.active {{ display: flex; }}
  .slide::before {{
    content: ''; position: absolute; inset: 0;
    background: linear-gradient(135deg, rgba(99,102,241,0.04) 0%, transparent 60%);
    pointer-events: none;
  }}

  /* ── Slide types ── */
  .slide.title-slide {{
    align-items: center; justify-content: center; text-align: center;
    background: linear-gradient(135deg, #1e293b 0%, #0f172a 60%);
  }}
  .slide.title-slide .slide-title {{
    font-size: clamp(1.8rem, 3.5vw, 2.8rem); font-weight: 700;
    color: var(--accent2); margin-bottom: 1rem; line-height: 1.2;
  }}
  .slide.title-slide .slide-subtitle {{
    font-size: 1.1rem; color: var(--muted); max-width: 600px;
  }}

  .slide-badge {{
    position: absolute; top: 1.2rem; right: 1.5rem;
    font-size: 0.68rem; text-transform: uppercase; letter-spacing: 0.08em;
    color: var(--accent); border: 1px solid var(--accent);
    padding: 0.15rem 0.5rem; border-radius: 4px; opacity: 0.7;
  }}

  /* ── Content slides ── */
  .slide-title {{
    font-size: clamp(1.1rem, 2vw, 1.55rem); font-weight: 700;
    margin-bottom: 1.5rem; color: var(--text);
    padding-bottom: 0.75rem; border-bottom: 2px solid var(--accent);
    display: inline-block;
  }}
  .slide-body {{ flex: 1; overflow: hidden; font-size: clamp(0.85rem, 1.4vw, 1.05rem); }}
  .slide-body ul {{
    list-style: none; display: flex; flex-direction: column; gap: 0.6rem;
  }}
  .slide-body li {{ display: flex; gap: 0.6rem; line-height: 1.45; }}
  .slide-body li::before {{
    content: '›'; color: var(--accent); font-size: 1.1em;
    flex-shrink: 0; margin-top: 0.05em;
  }}
  .slide-body p {{ line-height: 1.6; margin-bottom: 0.75rem; color: var(--text); }}
  .slide-body strong {{ color: var(--accent2); font-weight: 600; }}
  .slide-body code {{
    background: var(--surface2); padding: 0.1em 0.35em;
    border-radius: 4px; font-family: monospace; font-size: 0.9em;
  }}

  /* ── Two-column ── */
  .two-col {{ display: grid; grid-template-columns: 1fr 1fr; gap: 2rem; flex: 1; }}
  .col-label {{
    font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.1em;
    color: var(--accent); margin-bottom: 0.75rem; font-weight: 600;
  }}

  /* ── Quote slide ── */
  .slide.quote-slide .quote-text {{
    font-size: clamp(1.1rem, 2vw, 1.5rem); font-style: italic;
    color: var(--accent2); line-height: 1.5; text-align: center;
    padding: 0 2rem; flex: 1; display: flex; align-items: center;
    justify-content: center;
  }}
  .slide.quote-slide .slide-title {{ display: none; }}

  /* ── Navigation ── */
  .nav {{
    background: var(--surface); border-top: 1px solid var(--border);
    padding: 0.6rem 1.2rem; display: flex; align-items: center;
    justify-content: center; gap: 1.2rem; flex-shrink: 0;
  }}
  .nav button {{
    background: var(--surface2); border: 1px solid var(--border);
    color: var(--text); padding: 0.4rem 1.2rem; border-radius: 6px;
    cursor: pointer; font-size: 0.9rem; transition: all 0.15s;
  }}
  .nav button:hover:not(:disabled) {{
    background: var(--accent); border-color: var(--accent);
  }}
  .nav button:disabled {{ opacity: 0.35; cursor: not-allowed; }}
  .nav .kbd {{
    font-size: 0.72rem; color: var(--border);
  }}
  .progress {{
    position: absolute; bottom: 0; left: 0; height: 3px;
    background: var(--accent); transition: width 0.25s ease;
  }}
</style>
</head>
<body>

<div class="topbar">
  <span class="deck-title">{deck_title}</span>
  <span class="slide-counter" id="counter">1 / {total_slides}</span>
</div>

<div class="main">
  <div class="toc" id="toc"></div>
  <div class="stage">
    {slides_html}
    <div class="progress" id="progress"></div>
  </div>
</div>

<div class="nav">
  <button id="prev" onclick="navigate(-1)">&#8592; Prev</button>
  <span class="kbd">← → arrow keys or click TOC</span>
  <button id="next" onclick="navigate(1)">Next &#8594;</button>
</div>

<script>
const slides = document.querySelectorAll('.slide');
const tocEl = document.getElementById('toc');
const counter = document.getElementById('counter');
const progress = document.getElementById('progress');
const slideTitles = {slide_titles_json};
let current = 0;

function buildToc() {{
  slideTitles.forEach((title, i) => {{
    const d = document.createElement('div');
    d.className = 'toc-item' + (i === 0 ? ' active' : '');
    d.innerHTML = `<span class="toc-num">${{String(i+1).padStart(2,'0')}}</span>${{title}}`;
    d.onclick = () => goTo(i);
    tocEl.appendChild(d);
  }});
}}

function goTo(n) {{
  slides[current].classList.remove('active');
  tocEl.children[current].classList.remove('active');
  current = Math.max(0, Math.min(n, slides.length - 1));
  slides[current].classList.add('active');
  tocEl.children[current].classList.add('active');
  tocEl.children[current].scrollIntoView({{block:'nearest'}});
  counter.textContent = (current + 1) + ' / ' + slides.length;
  progress.style.width = ((current + 1) / slides.length * 100) + '%';
  document.getElementById('prev').disabled = current === 0;
  document.getElementById('next').disabled = current === slides.length - 1;
}}

function navigate(dir) {{ goTo(current + dir); }}

document.addEventListener('keydown', e => {{
  if (e.key === 'ArrowRight' || e.key === 'ArrowDown') navigate(1);
  if (e.key === 'ArrowLeft'  || e.key === 'ArrowUp')   navigate(-1);
}});

buildToc();
goTo(0);
</script>
</body>
</html>
"""


@dataclass
class DeckResult:
    deck_name: str
    intent: str
    html_content: str
    slide_count: int


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def generate_deck(
    provider: "LLMProvider",
    pages: list[Any],       # list[OpenKBPage]
    deck_name: str,
    intent: str,
) -> DeckResult:
    """Generate a self-contained HTML slide deck from wiki content.

    Args:
        provider  : LLM provider.
        pages     : All OpenKBPage rows for the KB.
        deck_name : Display name for the deck.
        intent    : What the deck should communicate.

    Returns:
        DeckResult with the complete HTML string.
    """
    # Build wiki context (concept pages first for better slide structure)
    priority = {"concept": 0, "entity": 1, "summary": 2}
    content_pages = sorted(
        [p for p in pages if p.page_category not in ("index",)],
        key=lambda p: priority.get(p.page_category, 9),
    )[:_MAX_PAGES_IN_CONTEXT]

    parts: list[str] = []
    total_chars = 0
    for p in content_pages:
        entry = f"### {p.title}\n{p.content or ''}\n"
        if total_chars + len(entry) > _MAX_WIKI_CHARS:
            break
        parts.append(entry)
        total_chars += len(entry)

    wiki_context = "\n---\n".join(parts) if parts else "(wiki is empty)"

    user_msg = _DECK_USER.format(
        deck_name=deck_name,
        intent=intent,
        wiki_context=wiki_context,
    )

    try:
        resp = await provider.complete(
            [{"role": "user", "content": user_msg}],
            system_prompt=_DECK_SYSTEM,
            max_tokens=8192,
        )
        deck_data = _parse_deck_json(resp.content)
    except Exception as exc:
        logger.error("OpenKB deck generation failed", extra={"error": str(exc)})
        raise RuntimeError(f"Deck generation failed: {exc}") from exc

    html_content = _render_deck(deck_data, deck_name)
    slide_count = len(deck_data.get("slides", []))

    logger.info(
        "OpenKB deck generated",
        extra={"deck_name": deck_name, "slides": slide_count},
    )
    return DeckResult(
        deck_name=deck_name,
        intent=intent,
        html_content=html_content,
        slide_count=slide_count,
    )


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------


def _parse_deck_json(raw: str) -> dict:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        first_nl = cleaned.find("\n")
        cleaned = cleaned[first_nl + 1:] if first_nl != -1 else cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.removeprefix("json").strip()
    try:
        data = json.loads(cleaned)
        if not isinstance(data, dict) or "slides" not in data:
            raise ValueError("Missing 'slides' key")
        return data
    except Exception as exc:
        logger.warning("Deck JSON parse failed", extra={"error": str(exc)})
        return {"title": "Presentation", "subtitle": "", "slides": []}


def _md_to_html(text: str) -> str:
    """Minimal Markdown → HTML conversion (bold, bullets, paragraphs)."""
    if not text:
        return ""
    lines = text.strip().split("\n")
    out: list[str] = []
    in_ul = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if in_ul:
                out.append("</ul>")
                in_ul = False
            continue
        # Bullet
        if stripped.startswith(("- ", "* ", "• ")):
            if not in_ul:
                out.append("<ul>")
                in_ul = True
            item = stripped[2:].strip()
            out.append(f"<li>{_inline_md(item)}</li>")
        else:
            if in_ul:
                out.append("</ul>")
                in_ul = False
            out.append(f"<p>{_inline_md(stripped)}</p>")
    if in_ul:
        out.append("</ul>")
    return "\n".join(out)


def _inline_md(text: str) -> str:
    """Process inline Markdown: **bold** and `code`."""
    import re
    text = html.escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)
    return text


def _render_slide(slide: dict, index: int) -> str:
    """Render a single slide dict to HTML."""
    stype = slide.get("type", "content")
    title = html.escape(slide.get("title", f"Slide {index + 1}"))
    content = slide.get("content", "")

    css_class = "slide"
    badge = ""
    body_html = ""

    if stype == "title_slide":
        css_class += " title-slide"
        subtitle = html.escape(slide.get("subtitle", content or ""))
        return (
            f'<div class="{css_class}">'
            f'<div class="slide-title">{title}</div>'
            f'<div class="slide-subtitle">{subtitle}</div>'
            f"</div>"
        )

    elif stype == "quote":
        css_class += " quote-slide"
        body_html = f'<div class="quote-text">{html.escape(content)}</div>'

    elif stype == "two_column":
        badge = f'<div class="slide-badge">two-column</div>'
        left = _md_to_html(slide.get("left", ""))
        right = _md_to_html(slide.get("right", ""))
        body_html = (
            f'<div class="two-col">'
            f'<div><div class="col-label">◀</div>{left}</div>'
            f'<div><div class="col-label">▶</div>{right}</div>'
            f"</div>"
        )

    else:
        body_html = f'<div class="slide-body">{_md_to_html(content)}</div>'

    return (
        f'<div class="{css_class}">'
        f"{badge}"
        f'<div class="slide-title">{title}</div>'
        f"{body_html}"
        f"</div>"
    )


def _render_deck(deck_data: dict, fallback_title: str) -> str:
    """Render the full deck dict to a self-contained HTML string."""
    deck_title = html.escape(deck_data.get("title", fallback_title))
    slides = deck_data.get("slides", [])
    if not slides:
        slides = [{"title": "No Content", "type": "content", "content": "No slides generated."}]

    slides_html = "\n".join(_render_slide(s, i) for i, s in enumerate(slides))
    slide_titles_json = json.dumps([s.get("title", f"Slide {i+1}") for i, s in enumerate(slides)])

    return _HTML_TEMPLATE.format(
        deck_title=deck_title,
        total_slides=len(slides),
        slides_html=slides_html,
        slide_titles_json=slide_titles_json,
    )
