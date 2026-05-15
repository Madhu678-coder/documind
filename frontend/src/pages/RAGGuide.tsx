import { BookOpen, Brain, ChevronDown, ChevronUp, FileSearch, GitMerge, Layers, Search, Sparkles, Zap } from 'lucide-react';
import { useState } from 'react';

// ── Collapsible section ───────────────────────────────────────────────────────
function Section({ title, children, defaultOpen = false }: { title: string; children: React.ReactNode; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="rounded-xl border border-slate-200 bg-white shadow-sm overflow-hidden">
      <button
        onClick={() => setOpen(v => !v)}
        className="w-full flex items-center justify-between px-5 py-4 text-left hover:bg-slate-50 transition-colors"
      >
        <span className="text-sm font-semibold text-slate-800">{title}</span>
        {open ? <ChevronUp className="h-4 w-4 text-slate-400" /> : <ChevronDown className="h-4 w-4 text-slate-400" />}
      </button>
      {open && <div className="px-5 pb-5 text-sm text-slate-600 space-y-3">{children}</div>}
    </div>
  );
}

// ── Pro/Con badge ─────────────────────────────────────────────────────────────
function Pro({ children }: { children: React.ReactNode }) {
  return (
    <li className="flex items-start gap-2">
      <span className="mt-0.5 flex-shrink-0 h-4 w-4 rounded-full bg-green-100 text-green-700 flex items-center justify-center text-xs font-bold">+</span>
      <span>{children}</span>
    </li>
  );
}
function Con({ children }: { children: React.ReactNode }) {
  return (
    <li className="flex items-start gap-2">
      <span className="mt-0.5 flex-shrink-0 h-4 w-4 rounded-full bg-red-100 text-red-600 flex items-center justify-center text-xs font-bold">−</span>
      <span>{children}</span>
    </li>
  );
}

// ── Example card ──────────────────────────────────────────────────────────────
function Example({ title, query, why }: { title: string; query: string; why: string }) {
  return (
    <div className="rounded-lg border border-slate-100 bg-slate-50 p-3">
      <p className="font-medium text-slate-700 mb-1">{title}</p>
      <p className="text-xs text-slate-500 italic mb-1.5">"{query}"</p>
      <p className="text-xs text-slate-600">{why}</p>
    </div>
  );
}

// ── Comparison table ──────────────────────────────────────────────────────────
const COMPARISON_ROWS = [
  {
    aspect: 'Ingest cost',
    pageindex: { text: 'Medium', sub: '1 LLM call/doc', level: 1 },
    vector:    { text: 'Low',    sub: 'embeddings only', level: 0 },
    wiki:      { text: 'High',   sub: 'LLM per page, per doc', level: 2 },
  },
  {
    aspect: 'Query cost',
    pageindex: { text: 'Medium', sub: '2 LLM calls', level: 1 },
    vector:    { text: 'Low',    sub: 'embedding + retrieval', level: 0 },
    wiki:      { text: 'Medium', sub: '2 LLM calls', level: 1 },
  },
  {
    aspect: 'Cross-doc synthesis',
    pageindex: { text: 'Limited',   sub: 'tree per doc', level: 0 },
    vector:    { text: 'Moderate',  sub: 'chunks mixed', level: 1 },
    wiki:      { text: 'Excellent', sub: 'pages merged', level: 2 },
  },
  {
    aspect: 'Best for',
    pageindex: { text: 'Long, structured docs',     sub: '', level: -1 },
    vector:    { text: 'Large, growing collections', sub: '', level: -1 },
    wiki:      { text: 'Evolving topic libraries',   sub: '', level: -1 },
  },
  {
    aspect: 'Answer style',
    pageindex: { text: 'Deep, section-level',   sub: '', level: -1 },
    vector:    { text: 'Snippet-level, broad',  sub: '', level: -1 },
    wiki:      { text: 'Encyclopedic, curated', sub: '', level: -1 },
  },
  {
    aspect: 'Knowledge accumulation',
    pageindex: { text: 'No',  sub: 'per-doc', level: 0 },
    vector:    { text: 'No',  sub: 'per-doc', level: 0 },
    wiki:      { text: 'Yes', sub: 'pages merge', level: 2 },
  },
  {
    aspect: 'Setup complexity',
    pageindex: { text: 'Low',    sub: '', level: 0 },
    vector:    { text: 'Medium', sub: 'embedding model', level: 1 },
    wiki:      { text: 'Low',    sub: '', level: 0 },
  },
];

const LEVEL_STYLES: Record<number, string> = {
  0: 'bg-green-50 text-green-700 border border-green-200',
  1: 'bg-amber-50 text-amber-700 border border-amber-200',
  2: 'bg-red-50 text-red-600 border border-red-200',
};

function GlanceCell({ text, sub, level }: { text: string; sub: string; level: number }) {
  if (level === -1) {
    return (
      <div className="text-xs text-slate-600 leading-snug">
        {text}
        {sub && <span className="block text-slate-400 text-[11px]">{sub}</span>}
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-0.5">
      <span className={`inline-flex w-fit items-center rounded-md px-2 py-0.5 text-xs font-semibold ${LEVEL_STYLES[level]}`}>
        {text}
      </span>
      {sub && <span className="text-[11px] text-slate-400 leading-tight">{sub}</span>}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────
export function RAGGuide() {
  return (
    <div className="max-w-4xl mx-auto px-6 py-8 space-y-8">
      {/* Header */}
      <div>
        <div className="flex items-center gap-3 mb-2">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-100">
            <Brain className="h-5 w-5 text-blue-600" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-slate-900">RAG Mode Guide</h1>
            <p className="text-sm text-slate-500">How to choose the right retrieval strategy for your knowledge base</p>
          </div>
        </div>
        <p className="mt-3 text-sm text-slate-600 leading-relaxed">
          DocuMind offers three fundamentally different ways to index and query your documents. Each trades off
          speed, cost, and answer quality differently. This guide explains how each mode works, when to use it,
          and what real-world scenarios it's best suited for.
        </p>
      </div>

      {/* Quick comparison */}
      <div className="rounded-xl border border-slate-200 bg-white shadow-sm overflow-hidden">
        <div className="px-5 py-4 border-b border-slate-100 flex items-center gap-2">
          <Layers className="h-4 w-4 text-slate-400" />
          <h2 className="text-sm font-semibold text-slate-800">At a Glance</h2>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr>
                <th className="w-[180px] px-5 py-4" />
                {/* PageIndex */}
                <th className="px-4 py-4 text-left">
                  <div className="flex items-center gap-2">
                    <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-blue-100">
                      <FileSearch className="h-3.5 w-3.5 text-blue-600" />
                    </div>
                    <div>
                      <p className="text-xs font-bold text-blue-700 uppercase tracking-wide">PageIndex</p>
                      <p className="text-[11px] text-slate-400 font-normal">Vectorless</p>
                    </div>
                  </div>
                </th>
                {/* Vector RAG */}
                <th className="px-4 py-4 text-left">
                  <div className="flex items-center gap-2">
                    <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-emerald-100">
                      <Search className="h-3.5 w-3.5 text-emerald-600" />
                    </div>
                    <div>
                      <p className="text-xs font-bold text-emerald-700 uppercase tracking-wide">Vector RAG</p>
                      <p className="text-[11px] text-slate-400 font-normal">Semantic Search</p>
                    </div>
                  </div>
                </th>
                {/* Wiki */}
                <th className="px-4 py-4 text-left">
                  <div className="flex items-center gap-2">
                    <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-violet-100">
                      <BookOpen className="h-3.5 w-3.5 text-violet-600" />
                    </div>
                    <div>
                      <p className="text-xs font-bold text-violet-700 uppercase tracking-wide">Wiki</p>
                      <p className="text-[11px] text-slate-400 font-normal">Living KB</p>
                    </div>
                  </div>
                </th>
              </tr>
              {/* Colored underline bars */}
              <tr>
                <td className="px-5 pb-1" />
                <td className="px-4 pb-1"><div className="h-0.5 rounded-full bg-blue-400" /></td>
                <td className="px-4 pb-1"><div className="h-0.5 rounded-full bg-emerald-400" /></td>
                <td className="px-4 pb-1"><div className="h-0.5 rounded-full bg-violet-400" /></td>
              </tr>
            </thead>
            <tbody>
              {COMPARISON_ROWS.map((row, i) => (
                <tr key={row.aspect} className={i % 2 === 0 ? 'bg-slate-50/60' : 'bg-white'}>
                  <td className="px-5 py-3 text-xs font-semibold text-slate-500 whitespace-nowrap">
                    {row.aspect}
                  </td>
                  <td className="px-4 py-3">
                    <GlanceCell {...row.pageindex} />
                  </td>
                  <td className="px-4 py-3">
                    <GlanceCell {...row.vector} />
                  </td>
                  <td className="px-4 py-3">
                    <GlanceCell {...row.wiki} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Legend */}
        <div className="px-5 py-3 border-t border-slate-100 flex items-center gap-4 bg-slate-50/50">
          <span className="text-[11px] text-slate-400 font-medium">Legend:</span>
          <span className="inline-flex items-center gap-1 text-[11px] text-green-700"><span className="h-2 w-2 rounded-sm bg-green-200 border border-green-300 inline-block" /> Low / Good</span>
          <span className="inline-flex items-center gap-1 text-[11px] text-amber-700"><span className="h-2 w-2 rounded-sm bg-amber-200 border border-amber-300 inline-block" /> Medium</span>
          <span className="inline-flex items-center gap-1 text-[11px] text-red-600"><span className="h-2 w-2 rounded-sm bg-red-200 border border-red-300 inline-block" /> High / Limited</span>
        </div>
      </div>

      {/* ── PageIndex ─────────────────────────────────────────────────────── */}
      <div className="space-y-3">
        <div className="flex items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-blue-100">
            <FileSearch className="h-4 w-4 text-blue-600" />
          </div>
          <h2 className="text-lg font-bold text-slate-900">PageIndex</h2>
          <span className="rounded-full bg-blue-100 px-2.5 py-0.5 text-xs font-medium text-blue-700">Vectorless</span>
        </div>

        <Section title="How it works" defaultOpen>
          <p>
            When you upload a document, an LLM reads the full text and constructs a <strong>hierarchical tree</strong>:
            chapters at the top, sections and subsections below. Each node stores its title, page range, and
            the actual text from that section.
          </p>
          <p>
            At query time, DocuMind presents the tree table-of-contents (up to 50 nodes) to the LLM alongside
            your question. The LLM selects the most relevant nodes — like a skilled researcher flipping to the
            right chapters — then reads only those sections to generate a cited answer. No vectors, no similarity
            search.
          </p>
          <div className="rounded-lg bg-blue-50 border border-blue-100 p-3 text-xs text-blue-800">
            <strong>Analogy:</strong> A librarian who has read the table of contents of every book and can go
            directly to the right chapter for your question.
          </div>
        </Section>

        <Section title="Pros & Cons">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <p className="text-xs font-semibold text-green-700 mb-2 uppercase tracking-wide">Strengths</p>
              <ul className="space-y-1.5">
                <Pro>No embedding model needed — pure LLM reasoning</Pro>
                <Pro>Preserves document structure (chapters, sections)</Pro>
                <Pro>Deep, contextual answers that respect the document's narrative flow</Pro>
                <Pro>Great for long-form documents (contracts, manuals, reports)</Pro>
                <Pro>Low setup complexity</Pro>
              </ul>
            </div>
            <div>
              <p className="text-xs font-semibold text-red-600 mb-2 uppercase tracking-wide">Limitations</p>
              <ul className="space-y-1.5">
                <Con>Tree is per-document — can't naturally synthesize across many docs</Con>
                <Con>Ingest requires a full LLM call per document</Con>
                <Con>Doesn't scale well past ~50 nodes per tree (navigator prompt gets large)</Con>
                <Con>Doesn't accumulate cross-document knowledge</Con>
              </ul>
            </div>
          </div>
        </Section>

        <Section title="When to use PageIndex">
          <p>PageIndex excels when your documents are <strong>long, structured, and self-contained</strong> — each document has a clear internal hierarchy that should be respected.</p>
          <div className="grid grid-cols-1 gap-2 mt-2">
            <Example
              title="Legal contracts & agreements"
              query="What are the termination clauses and notice periods in this MSA?"
              why="The contract's section structure (Article 12: Termination) maps perfectly to PageIndex nodes. The LLM navigates directly to the right section rather than hoping a similarity search finds the right chunk."
            />
            <Example
              title="Technical manuals & API docs"
              query="How do I configure rate limiting for the OAuth2 endpoint?"
              why="Manuals have clear chapter/section hierarchies. PageIndex finds 'Chapter 4 > Authentication > Rate Limiting' precisely, unlike a vector search that might surface unrelated auth snippets."
            />
            <Example
              title="Research papers"
              query="What methodology did the authors use and what were the control variables?"
              why="Academic papers follow a rigid structure (Abstract → Methods → Results → Discussion). PageIndex respects that structure and retrieves the Methodology section directly."
            />
          </div>
        </Section>
      </div>

      {/* ── Vector RAG ────────────────────────────────────────────────────── */}
      <div className="space-y-3">
        <div className="flex items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-100">
            <Search className="h-4 w-4 text-emerald-600" />
          </div>
          <h2 className="text-lg font-bold text-slate-900">Vector RAG</h2>
          <span className="rounded-full bg-emerald-100 px-2.5 py-0.5 text-xs font-medium text-emerald-700">Semantic Search</span>
        </div>

        <Section title="How it works" defaultOpen>
          <p>
            At ingest, each document is split into overlapping chunks (typically 512–1024 tokens with ~20%
            overlap). An embedding model converts each chunk into a high-dimensional vector. These vectors are
            stored in the database alongside the raw text.
          </p>
          <p>
            At query time, your question is also embedded into a vector. DocuMind finds the <em>k</em> chunks
            whose vectors are closest to the query vector (cosine similarity, BM25 fulltext, or a hybrid of
            both). The top-k chunks are assembled into a context window and the LLM generates an answer.
          </p>
          <div className="rounded-lg bg-emerald-50 border border-emerald-100 p-3 text-xs text-emerald-800">
            <strong>Analogy:</strong> A fast keyword + semantic search engine across all your documents —
            like Google Search, but over your private files.
          </div>
        </Section>

        <Section title="Pros & Cons">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <p className="text-xs font-semibold text-green-700 mb-2 uppercase tracking-wide">Strengths</p>
              <ul className="space-y-1.5">
                <Pro>Fast query time — vector lookup is sub-second</Pro>
                <Pro>Scales to hundreds or thousands of documents</Pro>
                <Pro>Handles semantic synonyms well ("car" finds "automobile")</Pro>
                <Pro>Works for unstructured content without clear section hierarchy</Pro>
                <Pro>Hybrid mode (vector + BM25) further improves precision</Pro>
              </ul>
            </div>
            <div>
              <p className="text-xs font-semibold text-red-600 mb-2 uppercase tracking-wide">Limitations</p>
              <ul className="space-y-1.5">
                <Con>Requires an embedding model (Bedrock or OpenAI)</Con>
                <Con>Chunks lose surrounding context — answers can feel snippety</Con>
                <Con>Poor at synthesis questions that span many documents</Con>
                <Con>Chunk boundaries can split critical information</Con>
                <Con>Score thresholds need tuning for optimal precision/recall</Con>
              </ul>
            </div>
          </div>
        </Section>

        <Section title="When to use Vector RAG">
          <p>Vector RAG is the right choice when you have <strong>many documents, unstructured text, or need fast search</strong> over a large corpus.</p>
          <div className="grid grid-cols-1 gap-2 mt-2">
            <Example
              title="Customer support knowledge base"
              query="How do I reset my password if I don't have access to my email?"
              why="Support articles are short and unstructured. Vector search finds the specific password-reset article regardless of how it's titled or formatted. Scales as the KB grows from 100 to 10,000 articles."
            />
            <Example
              title="Large document collection (mixed types)"
              query="What do our policies say about parental leave?"
              why="When your KB contains HR policies, benefits guides, employee handbooks, and FAQs as separate PDFs, vector search can pull relevant passages from multiple documents simultaneously."
            />
            <Example
              title="News archive / document repository"
              query="Find articles that mention supply chain disruptions in Southeast Asia"
              why="For repositories with hundreds of news articles or reports, semantic vector search finds relevant content even when the exact phrase isn't used — 'logistics bottlenecks in Vietnam' will surface too."
            />
          </div>
        </Section>
      </div>

      {/* ── Wiki ──────────────────────────────────────────────────────────── */}
      <div className="space-y-3">
        <div className="flex items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-violet-100">
            <BookOpen className="h-4 w-4 text-violet-600" />
          </div>
          <h2 className="text-lg font-bold text-slate-900">Wiki</h2>
          <span className="rounded-full bg-violet-100 px-2.5 py-0.5 text-xs font-medium text-violet-700">Living Knowledge Base</span>
        </div>

        <Section title="How it works" defaultOpen>
          <p>
            Inspired by Andrej Karpathy's LLM Wiki concept — instead of querying raw documents, an LLM{' '}
            <strong>builds and maintains a structured wiki</strong> as documents are ingested.
          </p>
          <p>
            On each upload, DocuMind extracts 3–15 wiki pages (entities, concepts, processes, events) from the
            document text. If a page with the same title already exists from a previous document, the LLM{' '}
            <strong>merges</strong> the new information into the existing page — preserving prior content,
            integrating new facts, and flagging any contradictions with a ⚠️ conflict marker.
          </p>
          <p>
            At query time, a lightweight navigator LLM reads the table of contents (all page summaries) and
            selects the 1–8 most relevant wiki pages. A second LLM call reads the full page content and
            generates an answer. Knowledge is cumulative: the more documents you add on a topic, the richer
            and more accurate that topic's wiki page becomes.
          </p>
          <div className="rounded-lg bg-violet-50 border border-violet-100 p-3 text-xs text-violet-800">
            <strong>Analogy:</strong> A team of subject-matter experts who read each new document, update
            their shared notebook, and answer your questions from the notebook — not from the original documents.
          </div>
        </Section>

        <Section title="Pros & Cons">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <p className="text-xs font-semibold text-green-700 mb-2 uppercase tracking-wide">Strengths</p>
              <ul className="space-y-1.5">
                <Pro>Knowledge compounds — second document on a topic makes the first answer better</Pro>
                <Pro>Excellent cross-document synthesis (contradictions surfaced explicitly)</Pro>
                <Pro>Encyclopedic answers with clear structure and markdown formatting</Pro>
                <Pro>No embedding model needed</Pro>
                <Pro>Wiki pages are human-readable and auditable in the Wiki Pages tab</Pro>
              </ul>
            </div>
            <div>
              <p className="text-xs font-semibold text-red-600 mb-2 uppercase tracking-wide">Limitations</p>
              <ul className="space-y-1.5">
                <Con>Highest ingest cost — LLM extraction + merge per document</Con>
                <Con>Capped at 100 pages per KB (designed for curated libraries, not massive corpora)</Con>
                <Con>LLM may mis-merge or miss nuances in complex domain content</Con>
                <Con>Not ideal for exact verbatim retrieval from source documents</Con>
              </ul>
            </div>
          </div>
        </Section>

        <Section title="When to use Wiki">
          <p>Wiki mode is ideal when your documents <strong>cover overlapping topics that build on each other</strong>, and you want answers that synthesize knowledge across all of them.</p>
          <div className="grid grid-cols-1 gap-2 mt-2">
            <Example
              title="Competitive intelligence library"
              query="What are the key differentiators of Competitor X's product vs ours?"
              why="You add analyst reports, press releases, and feature comparison sheets over time. Wiki merges all mentions of Competitor X into a single, up-to-date page. Each new document makes the answer richer — Vector RAG would surface only the most recently uploaded chunks."
            />
            <Example
              title="Internal product/domain knowledge base"
              query="How does our pricing model work and what are the edge cases?"
              why="You have pricing docs, sales decks, Slack exports, and support tickets. Wiki synthesizes 'Pricing Model' into one authoritative page combining rules from all sources. Contradictions (old pricing vs new) are explicitly flagged."
            />
            <Example
              title="Research literature collection"
              query="What are the current leading approaches to transformer efficiency?"
              why="You add 20 ML papers over 3 months. Each paper's content is merged into pages like 'Sparse Attention', 'Knowledge Distillation', 'Quantization'. Asking a synthesis question gets an encyclopedic answer — far better than vector search retrieving 8 random paragraph chunks."
            />
          </div>
        </Section>
      </div>

      {/* ── Decision guide ────────────────────────────────────────────────── */}
      <div className="rounded-xl border border-slate-200 bg-white shadow-sm overflow-hidden">
        <div className="px-5 py-4 border-b border-slate-100">
          <h2 className="text-sm font-semibold text-slate-800 flex items-center gap-2">
            <GitMerge className="h-4 w-4 text-slate-400" />
            Decision Guide: Which mode should I pick?
          </h2>
        </div>
        <div className="px-5 py-4 space-y-3 text-sm text-slate-600">
          <div className="grid grid-cols-1 gap-3">
            <div className="rounded-lg border border-blue-100 bg-blue-50 p-3">
              <p className="font-semibold text-blue-800 mb-1">Use PageIndex if…</p>
              <ul className="space-y-0.5 text-xs text-blue-700 list-disc ml-4">
                <li>Documents are long, dense, and structured (reports, contracts, manuals)</li>
                <li>You need deep, section-level answers that respect the document structure</li>
                <li>You don't have or want an embedding model configured</li>
                <li>Your KB has fewer than ~20–30 documents</li>
              </ul>
            </div>
            <div className="rounded-lg border border-emerald-100 bg-emerald-50 p-3">
              <p className="font-semibold text-emerald-800 mb-1">Use Vector RAG if…</p>
              <ul className="space-y-0.5 text-xs text-emerald-700 list-disc ml-4">
                <li>You have many documents (50+) or plan to add many more</li>
                <li>Documents are diverse, unstructured, or short (articles, FAQs, emails)</li>
                <li>Speed matters — you need sub-second query response</li>
                <li>You want semantic search (synonyms, paraphrasing) across a large corpus</li>
              </ul>
            </div>
            <div className="rounded-lg border border-violet-100 bg-violet-50 p-3">
              <p className="font-semibold text-violet-800 mb-1">Use Wiki if…</p>
              <ul className="space-y-0.5 text-xs text-violet-700 list-disc ml-4">
                <li>Documents cover overlapping topics and knowledge should compound over time</li>
                <li>You want synthesis answers across multiple documents, not just retrieved passages</li>
                <li>The KB is a curated library (&lt;100 topics) that grows incrementally</li>
                <li>You want human-readable, auditable knowledge pages as a side effect</li>
              </ul>
            </div>
          </div>
        </div>
      </div>

      {/* ── Mode cannot be changed ─────────────────────────────────────────── */}
      <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 flex items-start gap-3">
        <Zap className="h-4 w-4 text-amber-600 flex-shrink-0 mt-0.5" />
        <div className="text-xs text-amber-800">
          <p className="font-semibold mb-0.5">RAG mode is set at knowledge base creation time</p>
          <p>You can't switch modes on an existing KB — the index format is different for each mode. Create a new KB and re-upload documents if you want to try a different approach. Vector RAG additionally requires an embedding model provider configured in Settings.</p>
        </div>
      </div>

      {/* ── Footer ────────────────────────────────────────────────────────── */}
      <div className="flex items-center gap-2 text-xs text-slate-400 pt-2">
        <Sparkles className="h-3.5 w-3.5" />
        <span>All three modes use the same LLM provider configured in Settings. Configure model providers in <strong className="text-slate-500">Settings → Model Providers</strong>.</span>
      </div>
    </div>
  );
}
