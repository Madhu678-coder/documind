import {
  BookOpen,
  Brain,
  CheckCircle2,
  ChevronRight,
  FileSearch,
  GitMerge,
  Globe2,
  MessageSquare,
  Search,
  ShieldCheck,
  Sparkles,
  Star,
  TrendingUp,
  Upload,
  Users,
  Zap,
} from 'lucide-react';
import { useNavigate } from 'react-router-dom';

// ── Tiny helpers ──────────────────────────────────────────────────────────────
function Badge({ children }: { children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-blue-200 bg-blue-50 px-3 py-1 text-xs font-medium text-blue-700">
      <span className="h-1.5 w-1.5 rounded-full bg-blue-500 animate-pulse" />
      {children}
    </span>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-[#155EEF]/8 px-3 py-1 text-xs font-semibold uppercase tracking-widest text-[#155EEF]">
      {children}
    </span>
  );
}

function Stat({ value, label }: { value: string; label: string }) {
  return (
    <div className="text-center">
      <p className="text-3xl font-bold text-[#155EEF]">{value}</p>
      <p className="mt-0.5 text-xs text-slate-500">{label}</p>
    </div>
  );
}

// ── RAG mode card ──────────────────────────────────────────────────────────────
interface RagModeCardProps {
  icon: React.ReactNode;
  color: string;
  badge: string;
  badgeBg: string;
  badgeText: string;
  title: string;
  subtitle: string;
  description: string;
  bullets: string[];
  bestFor: string;
}

function RagModeCard({ icon, color, badge, badgeBg, badgeText, title, subtitle, description, bullets, bestFor }: RagModeCardProps) {
  return (
    <div className={`group relative flex flex-col rounded-2xl border border-slate-200 bg-white p-7 shadow-sm transition-all duration-300 hover:shadow-lg hover:-translate-y-1 overflow-hidden`}>
      <div className={`absolute inset-x-0 top-0 h-1 ${color}`} />
      <div className="flex items-start justify-between mb-5">
        <div className={`flex h-12 w-12 items-center justify-center rounded-xl ${badgeBg}`}>
          {icon}
        </div>
        <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${badgeBg} ${badgeText}`}>{badge}</span>
      </div>
      <h3 className="text-lg font-bold text-slate-900">{title}</h3>
      <p className="text-xs font-medium text-slate-400 mt-0.5 mb-3">{subtitle}</p>
      <p className="text-sm text-slate-600 leading-relaxed mb-4">{description}</p>
      <ul className="space-y-1.5 mb-5">
        {bullets.map((b, i) => (
          <li key={i} className="flex items-start gap-2 text-xs text-slate-600">
            <CheckCircle2 className="h-3.5 w-3.5 text-slate-400 flex-shrink-0 mt-0.5" />
            {b}
          </li>
        ))}
      </ul>
      <div className="mt-auto pt-4 border-t border-slate-100">
        <p className="text-xs text-slate-400 font-medium">Best for</p>
        <p className="text-xs text-slate-600 mt-0.5">{bestFor}</p>
      </div>
    </div>
  );
}

// ── Feature card ──────────────────────────────────────────────────────────────
function FeatureCard({ icon, title, description }: { icon: React.ReactNode; title: string; description: string }) {
  return (
    <div className="group flex flex-col gap-3 rounded-xl border border-slate-200 bg-white p-6 shadow-sm transition-all duration-200 hover:shadow-md hover:border-[#155EEF]/30">
      <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-[#155EEF]/8 text-[#155EEF] group-hover:bg-[#155EEF]/15 transition-colors">
        {icon}
      </div>
      <h4 className="font-semibold text-slate-900 text-sm">{title}</h4>
      <p className="text-xs text-slate-500 leading-relaxed">{description}</p>
    </div>
  );
}

// ── How it works step ──────────────────────────────────────────────────────────
function Step({ num, title, description }: { num: string; title: string; description: string }) {
  return (
    <div className="flex gap-4">
      <div className="flex-shrink-0 flex h-9 w-9 items-center justify-center rounded-full bg-[#155EEF] text-white text-sm font-bold shadow-md shadow-[#155EEF]/30">
        {num}
      </div>
      <div>
        <h4 className="font-semibold text-slate-900 text-sm">{title}</h4>
        <p className="text-xs text-slate-500 mt-1 leading-relaxed">{description}</p>
      </div>
    </div>
  );
}

// ── Testimonial ───────────────────────────────────────────────────────────────
function Testimonial({ quote, name, role, stars = 5 }: { quote: string; name: string; role: string; stars?: number }) {
  return (
    <div className="flex flex-col gap-4 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="flex gap-0.5">
        {Array.from({ length: stars }).map((_, i) => (
          <Star key={i} className="h-3.5 w-3.5 fill-amber-400 text-amber-400" />
        ))}
      </div>
      <p className="text-sm text-slate-600 leading-relaxed italic">"{quote}"</p>
      <div>
        <p className="text-sm font-semibold text-slate-900">{name}</p>
        <p className="text-xs text-slate-400">{role}</p>
      </div>
    </div>
  );
}

// ── Provider logo pill ────────────────────────────────────────────────────────
function ProviderPill({ name }: { name: string }) {
  return (
    <span className="rounded-full border border-slate-200 bg-white px-4 py-2 text-xs font-medium text-slate-600 shadow-sm">
      {name}
    </span>
  );
}

// ── Main landing page ──────────────────────────────────────────────────────────
export function Landing() {
  const navigate = useNavigate();

  return (
    <div className="min-h-screen bg-white font-body">

      {/* ── Nav ──────────────────────────────────────────────────────────── */}
      <header className="sticky top-0 z-50 border-b border-slate-100 bg-white/90 backdrop-blur-md">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-3.5">
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#155EEF]">
              <Brain className="h-4.5 w-4.5 text-white" style={{ height: '18px', width: '18px' }} />
            </div>
            <span className="text-lg font-bold text-slate-900">DocuMind</span>
          </div>
          <nav className="hidden md:flex items-center gap-6 text-sm text-slate-600">
            <a href="#modes" className="hover:text-[#155EEF] transition-colors">RAG Modes</a>
            <a href="#features" className="hover:text-[#155EEF] transition-colors">Features</a>
            <a href="#how-it-works" className="hover:text-[#155EEF] transition-colors">How it works</a>
            <a href="#providers" className="hover:text-[#155EEF] transition-colors">Integrations</a>
          </nav>
          <div className="flex items-center gap-3">
            <button
              onClick={() => navigate('/login')}
              className="rounded-lg px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-50 transition-colors"
            >
              Sign in
            </button>
            <button
              onClick={() => navigate('/login')}
              className="rounded-lg bg-[#155EEF] px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-[#0E4FC3] transition-colors"
            >
              Get started
            </button>
          </div>
        </div>
      </header>

      {/* ── Hero ─────────────────────────────────────────────────────────── */}
      <section className="relative overflow-hidden bg-gradient-to-br from-blue-50 via-indigo-50/40 to-white pt-20 pb-24">
        {/* Background decoration */}
        <div className="pointer-events-none absolute inset-0 overflow-hidden">
          <div className="absolute -top-40 right-0 h-[600px] w-[600px] rounded-full bg-[#155EEF]/5 blur-3xl" />
          <div className="absolute bottom-0 left-0 h-[400px] w-[400px] rounded-full bg-indigo-100/60 blur-3xl" />
        </div>

        <div className="relative mx-auto max-w-7xl px-6">
          <div className="flex flex-col items-center text-center lg:flex-row lg:text-left lg:gap-16">
            {/* Left */}
            <div className="flex-1 max-w-2xl">
              <Badge>Now with Wiki RAG — Living Knowledge Base</Badge>
              <h1 className="mt-6 text-5xl font-bold leading-tight text-slate-900 xl:text-6xl">
                AI-Powered<br />
                <span className="text-[#155EEF]">Document Intelligence</span><br />
                for Your Team
              </h1>
              <p className="mt-6 text-lg text-slate-600 leading-relaxed max-w-xl">
                DocuMind transforms your documents into an intelligent knowledge base. Ask questions,
                get cited answers, and let AI build a living wiki that compounds knowledge with every
                document you add.
              </p>

              <div className="mt-8 flex flex-wrap gap-3 justify-center lg:justify-start">
                <button
                  onClick={() => navigate('/login')}
                  className="flex items-center gap-2 rounded-xl bg-[#155EEF] px-6 py-3 text-sm font-semibold text-white shadow-lg shadow-[#155EEF]/25 hover:bg-[#0E4FC3] hover:shadow-xl hover:shadow-[#155EEF]/30 transition-all"
                >
                  Start for free
                  <ChevronRight className="h-4 w-4" />
                </button>
                <button
                  onClick={() => navigate('/guide')}
                  className="flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-6 py-3 text-sm font-semibold text-slate-700 shadow-sm hover:shadow-md transition-all"
                >
                  <BookOpen className="h-4 w-4" />
                  Explore RAG Guide
                </button>
              </div>

              {/* Stats row */}
              <div className="mt-10 flex flex-wrap items-center gap-8 justify-center lg:justify-start">
                <Stat value="3" label="RAG Modes" />
                <div className="h-8 w-px bg-slate-200 hidden sm:block" />
                <Stat value="6+" label="LLM Providers" />
                <div className="h-8 w-px bg-slate-200 hidden sm:block" />
                <Stat value="100%" label="Source-cited answers" />
              </div>
            </div>

            {/* Right — UI preview card */}
            <div className="mt-16 lg:mt-0 flex-1 max-w-xl w-full">
              <div className="relative rounded-2xl border border-slate-200 bg-white shadow-2xl overflow-hidden">
                {/* Fake browser bar */}
                <div className="flex items-center gap-1.5 border-b border-slate-100 bg-slate-50 px-4 py-3">
                  <span className="h-3 w-3 rounded-full bg-red-400" />
                  <span className="h-3 w-3 rounded-full bg-amber-400" />
                  <span className="h-3 w-3 rounded-full bg-green-400" />
                  <span className="ml-3 flex-1 rounded-md bg-slate-200 h-5 text-xs flex items-center px-3 text-slate-400">app.documind.ai/chat</span>
                </div>
                {/* Chat preview */}
                <div className="p-5 space-y-4 bg-[#F9FAFB]">
                  {/* User message */}
                  <div className="flex justify-end">
                    <div className="max-w-xs rounded-xl rounded-tr-sm bg-[#155EEF] px-4 py-2.5 text-sm text-white shadow-sm">
                      What are the leave encashment rules in our policy?
                    </div>
                  </div>
                  {/* Assistant message */}
                  <div className="flex gap-3">
                    <div className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-[#155EEF]/10">
                      <Brain className="h-4 w-4 text-[#155EEF]" />
                    </div>
                    <div className="max-w-sm rounded-xl rounded-tl-sm bg-white border border-slate-200 px-4 py-3 text-xs text-slate-700 shadow-sm leading-relaxed">
                      According to the Leave Policy, employees can encash up to <strong>15 earned leaves</strong> per year that remain unused. Encashment is calculated on basic salary.
                      <span className="inline-flex items-center ml-1 text-[10px] rounded-full bg-blue-100 text-blue-700 px-1.5 py-0.5 font-medium cursor-pointer">§1</span>
                      <div className="mt-3 rounded-lg bg-blue-50 border border-blue-100 p-2.5">
                        <p className="text-[10px] font-semibold text-blue-700 mb-1">Source — Leave_Policy.pdf · Page 4</p>
                        <p className="text-[10px] text-slate-500 line-clamp-2">"Employees are entitled to encash earned leaves not exceeding 15 days per calendar year..."</p>
                      </div>
                    </div>
                  </div>
                  {/* Typing indicator */}
                  <div className="flex gap-3 items-end">
                    <div className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-[#155EEF]/10">
                      <Brain className="h-4 w-4 text-[#155EEF]" />
                    </div>
                    <div className="flex items-center gap-1 rounded-xl rounded-tl-sm bg-white border border-slate-200 px-4 py-3 shadow-sm">
                      <span className="h-1.5 w-1.5 rounded-full bg-slate-400 animate-bounce" style={{ animationDelay: '0ms' }} />
                      <span className="h-1.5 w-1.5 rounded-full bg-slate-400 animate-bounce" style={{ animationDelay: '150ms' }} />
                      <span className="h-1.5 w-1.5 rounded-full bg-slate-400 animate-bounce" style={{ animationDelay: '300ms' }} />
                    </div>
                  </div>
                </div>
              </div>
              {/* Float badges */}
              <div className="absolute top-1/4 -right-4 hidden xl:flex items-center gap-2 rounded-full border border-emerald-200 bg-white px-3 py-1.5 shadow-lg text-xs text-emerald-700 font-medium">
                <ShieldCheck className="h-3.5 w-3.5" /> Quality evaluated
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ── Providers strip ───────────────────────────────────────────────── */}
      <section id="providers" className="border-y border-slate-100 bg-slate-50 py-6">
        <div className="mx-auto max-w-7xl px-6">
          <p className="text-center text-xs font-medium uppercase tracking-widest text-slate-400 mb-5">Works with the LLM providers you already use</p>
          <div className="flex flex-wrap justify-center gap-3">
            {['Amazon Bedrock', 'OpenAI', 'Anthropic', 'Google Gemini', 'DeepSeek', 'xAI Grok'].map(p => (
              <ProviderPill key={p} name={p} />
            ))}
          </div>
        </div>
      </section>

      {/* ── RAG Modes ────────────────────────────────────────────────────── */}
      <section id="modes" className="py-24 bg-gradient-to-b from-white to-slate-50">
        <div className="mx-auto max-w-7xl px-6">
          <div className="text-center mb-14">
            <SectionLabel>Three ways to unlock your docs</SectionLabel>
            <h2 className="mt-4 text-4xl font-bold text-slate-900">Choose the RAG mode that fits your data</h2>
            <p className="mt-4 text-slate-500 max-w-2xl mx-auto">
              Every knowledge base is different. DocuMind gives you three battle-tested retrieval strategies — pick the right one at creation time.
            </p>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            <RagModeCard
              icon={<FileSearch className="h-6 w-6 text-blue-600" />}
              color="bg-gradient-to-r from-blue-500 to-blue-600"
              badge="Vectorless"
              badgeBg="bg-blue-50"
              badgeText="text-blue-700"
              title="PageIndex"
              subtitle="Hierarchical Tree Navigation"
              description="An LLM reads your document and builds a table-of-contents tree. At query time, it navigates directly to the right chapter — no embeddings required."
              bullets={[
                'Preserves document structure and narrative',
                'Deep, section-level cited answers',
                'No embedding model needed',
              ]}
              bestFor="Long structured docs: contracts, manuals, research papers"
            />
            <RagModeCard
              icon={<Search className="h-6 w-6 text-emerald-600" />}
              color="bg-gradient-to-r from-emerald-500 to-teal-500"
              badge="Semantic Search"
              badgeBg="bg-emerald-50"
              badgeText="text-emerald-700"
              title="Vector RAG"
              subtitle="Embedding-based Retrieval"
              description="Documents are split into chunks and encoded as vectors. Queries find the most semantically similar passages across your entire corpus in milliseconds."
              bullets={[
                'Scales to thousands of documents',
                'Handles synonyms and paraphrasing',
                'Hybrid BM25 + vector retrieval',
              ]}
              bestFor="Large mixed collections: FAQs, articles, email archives"
            />
            <RagModeCard
              icon={<BookOpen className="h-6 w-6 text-violet-600" />}
              color="bg-gradient-to-r from-violet-500 to-purple-600"
              badge="Living Knowledge Base"
              badgeBg="bg-violet-50"
              badgeText="text-violet-700"
              title="Wiki"
              subtitle="Incremental LLM-built Wiki"
              description="Inspired by Karpathy's LLM Wiki pattern — AI builds and merges a persistent wiki as documents are ingested. Knowledge compounds with every upload."
              bullets={[
                'Cross-document synthesis at query time',
                'Conflicts surfaced and flagged automatically',
                'Human-readable auditable wiki pages',
              ]}
              bestFor="Evolving libraries: competitive intel, domain knowledge, research"
            />
          </div>
          <p className="text-center mt-8 text-xs text-slate-400">
            Not sure which to pick?{' '}
            <button onClick={() => {}} className="text-[#155EEF] underline underline-offset-2 hover:text-[#0E4FC3]">
              Read the RAG Guide →
            </button>
          </p>
        </div>
      </section>

      {/* ── Features grid ────────────────────────────────────────────────── */}
      <section id="features" className="py-24 bg-gradient-to-b from-slate-50 via-white to-white">
        <div className="mx-auto max-w-7xl px-6">
          <div className="text-center mb-14">
            <SectionLabel>Everything you need</SectionLabel>
            <h2 className="mt-4 text-4xl font-bold text-slate-900">Built for teams who take knowledge seriously</h2>
            <p className="mt-4 text-slate-500 max-w-xl mx-auto">
              From ingestion to answer quality — every layer is covered.
            </p>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
            <FeatureCard
              icon={<MessageSquare className="h-5 w-5" />}
              title="Chat with Citations"
              description="Every answer links directly to the source page and passage. Click to open the document exactly where the answer was found."
            />
            <FeatureCard
              icon={<TrendingUp className="h-5 w-5" />}
              title="Real-time Quality Evaluation"
              description="DeepEval scores faithfulness, relevancy, hallucination, and precision after every response. Low-quality answers get an automatic disclaimer."
            />
            <FeatureCard
              icon={<Users className="h-5 w-5" />}
              title="Multi-tenant Workspaces"
              description="Each workspace is fully isolated. Manage teams, control access with role-based permissions (viewer, editor, admin)."
            />
            <FeatureCard
              icon={<Upload className="h-5 w-5" />}
              title="Async Document Upload"
              description="Upload PDFs, Word docs, and text files. Ingestion runs in the background — browse and chat while files are being processed."
            />
            <FeatureCard
              icon={<GitMerge className="h-5 w-5" />}
              title="Cross-document Synthesis"
              description="Wiki mode merges knowledge from every document that covers the same topic, and explicitly flags contradictions between sources."
            />
            <FeatureCard
              icon={<Globe2 className="h-5 w-5" />}
              title="Bring Your Own LLM"
              description="Configure any of 6 providers — Bedrock, OpenAI, Anthropic, Gemini, DeepSeek, or Grok — as your default LLM and embedding model."
            />
            <FeatureCard
              icon={<Zap className="h-5 w-5" />}
              title="Streaming Responses"
              description="Answers stream word-by-word over WebSocket so you see results immediately, even for complex multi-source questions."
            />
            <FeatureCard
              icon={<ShieldCheck className="h-5 w-5" />}
              title="Hallucination Guard"
              description="Automated hallucination scoring on every response. Answers that fail the faithfulness threshold get flagged before users see them."
            />
            <FeatureCard
              icon={<Sparkles className="h-5 w-5" />}
              title="Smart Session Naming"
              description="Chat sessions are automatically named from the first message. Blank sessions are cleaned up. Your history stays organized."
            />
          </div>
        </div>
      </section>

      {/* ── How it works ─────────────────────────────────────────────────── */}
      <section id="how-it-works" className="py-24 bg-gradient-to-b from-white to-blue-50/40">
        <div className="mx-auto max-w-7xl px-6">
          <div className="flex flex-col lg:flex-row gap-16 items-start">
            <div className="flex-1">
              <SectionLabel>How it works</SectionLabel>
              <h2 className="mt-4 text-4xl font-bold text-slate-900">From upload to insight in minutes</h2>
              <p className="mt-4 text-slate-500 leading-relaxed">
                DocuMind handles the heavy lifting. You upload your documents and start asking questions — the AI takes care of indexing, retrieval, and answer quality.
              </p>
              <div className="mt-10 space-y-7">
                <Step
                  num="1"
                  title="Create a Knowledge Base"
                  description="Choose a name, pick your RAG mode (PageIndex, Vector, or Wiki), and select your LLM provider. Done in under a minute."
                />
                <Step
                  num="2"
                  title="Upload your documents"
                  description="Drag-and-drop PDFs, Word docs, or plain text. DocuMind ingests them asynchronously — no waiting around."
                />
                <Step
                  num="3"
                  title="Ask questions in Chat"
                  description="Open a chat session and ask anything. The AI retrieves the right content, generates a cited answer, and streams it back in real time."
                />
                <Step
                  num="4"
                  title="Trust the answer quality"
                  description="Every response is automatically evaluated for faithfulness and hallucination. Quality scores are visible in Analytics."
                />
              </div>
            </div>
            <div className="flex-1 max-w-md w-full mx-auto">
              {/* Ingestion progress mockup */}
              <div className="rounded-2xl border border-slate-200 bg-white shadow-xl overflow-hidden">
                <div className="border-b border-slate-100 bg-slate-50 px-5 py-4 flex items-center justify-between">
                  <span className="font-semibold text-sm text-slate-700">Knowledge Base — HR Policies</span>
                  <span className="rounded-full bg-violet-100 px-2 py-0.5 text-xs font-medium text-violet-700">Wiki</span>
                </div>
                <div className="p-5 space-y-3">
                  {[
                    { name: 'Leave_Policy.pdf', pages: 8, status: 'ready' },
                    { name: 'Code_Of_Conduct.pdf', pages: 12, status: 'ready' },
                    { name: 'Appraisal_Policy.pdf', pages: 6, status: 'ready' },
                    { name: 'GMC_Manual.pdf', pages: 24, status: 'processing' },
                  ].map((doc) => (
                    <div key={doc.name} className="flex items-center justify-between text-xs">
                      <div className="flex items-center gap-2.5 min-w-0">
                        <div className={`h-2 w-2 rounded-full flex-shrink-0 ${doc.status === 'ready' ? 'bg-emerald-500' : 'bg-amber-400 animate-pulse'}`} />
                        <span className="text-slate-700 truncate">{doc.name}</span>
                      </div>
                      <span className="text-slate-400 ml-3 flex-shrink-0">
                        {doc.status === 'ready' ? `${doc.pages} wiki pages` : 'processing...'}
                      </span>
                    </div>
                  ))}
                  <div className="mt-4 rounded-lg bg-violet-50 border border-violet-100 p-3">
                    <p className="text-xs font-semibold text-violet-700 mb-1">Wiki pages extracted</p>
                    <div className="flex flex-wrap gap-1.5">
                      {['Leave Encashment', 'Performance Review', 'Code of Ethics', 'Medical Benefits', '+14 more'].map(t => (
                        <span key={t} className="rounded-md bg-white border border-violet-200 px-2 py-0.5 text-xs text-violet-600">{t}</span>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ── Testimonials ─────────────────────────────────────────────────── */}
      <section className="py-24 bg-gradient-to-b from-blue-50/40 to-white">
        <div className="mx-auto max-w-7xl px-6">
          <div className="text-center mb-14">
            <SectionLabel>What teams say</SectionLabel>
            <h2 className="mt-4 text-4xl font-bold text-slate-900">Used by teams who can't afford bad answers</h2>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            <Testimonial
              quote="We switched to Wiki mode for our policy library. Now every new HR document automatically enriches the existing knowledge pages — no manual curation needed."
              name="Priya S."
              role="HR Lead, Fintech startup"
            />
            <Testimonial
              quote="The citation badges are a game-changer. Our legal team trusts the answers because they can instantly verify the exact contract clause being referenced."
              name="Arjun M."
              role="Legal Operations, SaaS company"
            />
            <Testimonial
              quote="PageIndex gives us deep structural answers from our 200-page technical manuals. No other tool we tried preserved the chapter-section hierarchy like this."
              name="Dilnoza K."
              role="Technical Lead, Engineering firm"
            />
          </div>
        </div>
      </section>

      {/* ── CTA ──────────────────────────────────────────────────────────── */}
      <section className="py-24 bg-gradient-to-br from-[#155EEF]/8 via-blue-50/50 to-indigo-50">
        <div className="mx-auto max-w-3xl px-6 text-center">
          <div className="rounded-2xl border border-[#155EEF]/15 bg-white/80 backdrop-blur-sm p-12 shadow-xl">
            <div className="flex justify-center mb-5">
              <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-[#155EEF] shadow-lg shadow-[#155EEF]/30">
                <Brain className="h-7 w-7 text-white" />
              </div>
            </div>
            <h2 className="text-3xl font-bold text-slate-900">Start building your knowledge base today</h2>
            <p className="mt-4 text-slate-500 leading-relaxed">
              Upload your first document, ask your first question, and see cited answers in under 5 minutes.
            </p>
            <div className="mt-8 flex flex-wrap gap-3 justify-center">
              <button
                onClick={() => navigate('/login')}
                className="flex items-center gap-2 rounded-xl bg-[#155EEF] px-8 py-3.5 text-sm font-semibold text-white shadow-lg shadow-[#155EEF]/25 hover:bg-[#0E4FC3] hover:shadow-xl transition-all"
              >
                Get started free
                <ChevronRight className="h-4 w-4" />
              </button>
              <button
                onClick={() => navigate('/guide')}
                className="flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-8 py-3.5 text-sm font-semibold text-slate-700 shadow-sm hover:shadow-md transition-all"
              >
                Read the guide
              </button>
            </div>
            <p className="mt-6 text-xs text-slate-400">No credit card required · All 3 RAG modes available · 6 LLM providers supported</p>
          </div>
        </div>
      </section>

      {/* ── Footer ───────────────────────────────────────────────────────── */}
      <footer className="border-t border-slate-200 bg-white py-12">
        <div className="mx-auto max-w-7xl px-6">
          <div className="flex flex-col md:flex-row items-start justify-between gap-10">
            <div>
              <div className="flex items-center gap-2.5 mb-3">
                <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-[#155EEF]">
                  <Brain className="h-4 w-4 text-white" />
                </div>
                <span className="font-bold text-slate-900">DocuMind</span>
              </div>
              <p className="text-xs text-slate-500 max-w-xs leading-relaxed">
                AI-powered document intelligence with PageIndex, Vector RAG, and Wiki modes — built for teams that need trusted, cited answers.
              </p>
              <p className="mt-4 text-xs text-slate-400">Powered by Minfy Technologies</p>
            </div>
            <div className="flex flex-wrap gap-10 text-sm">
              <div>
                <p className="font-semibold text-slate-900 mb-3 text-xs uppercase tracking-wide">Product</p>
                <div className="space-y-2">
                  {['Knowledge Bases', 'Chat', 'Analytics', 'RAG Guide', 'Settings'].map(l => (
                    <p key={l}><a href="#" className="text-slate-500 hover:text-[#155EEF] transition-colors text-xs">{l}</a></p>
                  ))}
                </div>
              </div>
              <div>
                <p className="font-semibold text-slate-900 mb-3 text-xs uppercase tracking-wide">RAG Modes</p>
                <div className="space-y-2">
                  {['PageIndex', 'Vector RAG', 'Wiki', 'Comparison guide'].map(l => (
                    <p key={l}><a href="#" className="text-slate-500 hover:text-[#155EEF] transition-colors text-xs">{l}</a></p>
                  ))}
                </div>
              </div>
              <div>
                <p className="font-semibold text-slate-900 mb-3 text-xs uppercase tracking-wide">Integrations</p>
                <div className="space-y-2">
                  {['Amazon Bedrock', 'OpenAI', 'Anthropic', 'Google Gemini', 'DeepSeek', 'xAI Grok'].map(l => (
                    <p key={l}><a href="#" className="text-slate-500 hover:text-[#155EEF] transition-colors text-xs">{l}</a></p>
                  ))}
                </div>
              </div>
            </div>
          </div>
          <div className="mt-10 border-t border-slate-100 pt-6 flex flex-col sm:flex-row items-center justify-between gap-4">
            <p className="text-xs text-slate-400">© 2026 DocuMind · Minfy Technologies · All rights reserved</p>
            <div className="flex gap-5 text-xs text-slate-400">
              <a href="#" className="hover:text-[#155EEF] transition-colors">Privacy</a>
              <a href="#" className="hover:text-[#155EEF] transition-colors">Terms</a>
              <a href="#" className="hover:text-[#155EEF] transition-colors">Security</a>
            </div>
          </div>
        </div>
      </footer>
    </div>
  );
}
