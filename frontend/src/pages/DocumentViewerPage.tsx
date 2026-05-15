import { ArrowLeft, BookOpen, ChevronDown, ChevronUp, Database, FileText, Layers, Search } from 'lucide-react';
import { WikiPageExplorer } from '../components/wiki/WikiPageExplorer';
import { NeovisGraph } from '../components/graph/NeovisGraph';
import { useEffect, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { fetchDocumentInsights, type PageIndexInsights, type VectorInsights } from '../api/insights';
import { getDocument, getKnowledgeBases } from '../api/documents';
import { DocumentSummary } from '../components/insights/DocumentSummary';
import { TreeExplorer } from '../components/insights/TreeExplorer';
import { PDFViewer } from '../components/viewer/PDFViewer';
import type { Document, KnowledgeBase } from '../types';

// ── Chunk list for Vector RAG ─────────────────────────────────────────────────

interface ChunkRowProps {
  index: number;
  text: string;
  pageNumber: number;
  hasEmbedding: boolean;
  highlight?: string;
}

function ChunkRow({ index, text, pageNumber, hasEmbedding, highlight }: ChunkRowProps) {
  const [expanded, setExpanded] = useState(false);
  const isHighlighted = highlight && text.toLowerCase().includes(highlight.toLowerCase().slice(0, 40));

  return (
    <div className={`border rounded-lg overflow-hidden transition-colors ${isHighlighted ? 'border-amber-300 bg-amber-50' : 'border-slate-200 bg-white'}`}>
      <button
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-slate-50 transition-colors"
      >
        <span className="shrink-0 w-6 h-6 rounded-full bg-slate-100 text-slate-500 text-xs font-mono flex items-center justify-center">
          {index}
        </span>
        <span className="flex-1 text-xs text-slate-700 line-clamp-2">{text}</span>
        <div className="flex items-center gap-2 shrink-0">
          <span className="text-xs text-slate-400">p.{pageNumber}</span>
          <span className={`w-2 h-2 rounded-full shrink-0 ${hasEmbedding ? 'bg-emerald-400' : 'bg-slate-300'}`} title={hasEmbedding ? 'Embedded' : 'Not embedded'} />
          {expanded ? <ChevronUp className="h-3.5 w-3.5 text-slate-400" /> : <ChevronDown className="h-3.5 w-3.5 text-slate-400" />}
        </div>
      </button>
      {expanded && (
        <div className="px-4 pb-4 pt-0 text-xs text-slate-600 leading-relaxed border-t border-slate-100 bg-slate-50 whitespace-pre-wrap">
          {text}
        </div>
      )}
    </div>
  );
}

function VectorStructurePanel({ docId, highlightText }: { docId: string; highlightText?: string }) {
  const [insights, setInsights] = useState<VectorInsights | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');

  useEffect(() => {
    setLoading(true);
    fetchDocumentInsights(docId)
      .then((data) => {
        if (data.rag_mode === 'vector') setInsights(data as VectorInsights);
        setLoading(false);
      })
      .catch((err) => {
        setError(err?.response?.data?.detail ?? err?.message ?? 'Failed to load chunks.');
        setLoading(false);
      });
  }, [docId]);

  if (loading) {
    return (
      <div className="flex flex-col gap-3 p-4 animate-pulse">
        {[...Array(5)].map((_, i) => (
          <div key={i} className="h-16 rounded-lg bg-slate-100" />
        ))}
      </div>
    );
  }

  if (error) {
    return <div className="p-4 text-sm text-red-600">{error}</div>;
  }

  if (!insights) return null;

  const term = search.toLowerCase();
  const filtered = insights.chunks.filter(
    (c) => !term || c.text.toLowerCase().includes(term)
  );

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Stats */}
      <div className="grid grid-cols-3 gap-3 p-4 border-b border-slate-200 bg-slate-50 shrink-0">
        <div className="text-center">
          <p className="text-lg font-semibold text-slate-900">{insights.chunk_count}</p>
          <p className="text-xs text-slate-500">Total Chunks</p>
        </div>
        <div className="text-center">
          <p className="text-lg font-semibold text-emerald-600">{insights.embedded_count}</p>
          <p className="text-xs text-slate-500">Embedded</p>
        </div>
        <div className="text-center">
          <p className="text-lg font-semibold text-slate-900">{insights.page_count}</p>
          <p className="text-xs text-slate-500">Pages</p>
        </div>
      </div>

      {/* Search */}
      <div className="p-3 border-b border-slate-200 shrink-0">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-slate-400" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search chunks…"
            className="w-full rounded-lg border border-slate-200 pl-9 pr-3 py-2 text-xs focus:outline-none focus:ring-2 focus:ring-[var(--dm-primary)] bg-white"
          />
        </div>
      </div>

      {/* Chunk list */}
      <div className="flex-1 overflow-y-auto p-3 space-y-2">
        {filtered.length === 0 ? (
          <p className="text-xs text-slate-500 text-center py-8">No chunks match your search.</p>
        ) : (
          filtered.map((chunk) => (
            <ChunkRow
              key={chunk.id}
              index={chunk.chunk_index}
              text={chunk.text}
              pageNumber={chunk.page_number}
              hasEmbedding={chunk.has_embedding}
              highlight={highlightText}
            />
          ))
        )}
      </div>
    </div>
  );
}

function VectorInsightsPanel({ docId }: { docId: string }) {
  const [insights, setInsights] = useState<VectorInsights | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchDocumentInsights(docId)
      .then((data) => {
        if (data.rag_mode === 'vector') setInsights(data as VectorInsights);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, [docId]);

  if (loading) {
    return <div className="p-6 animate-pulse space-y-4">{[...Array(3)].map((_, i) => <div key={i} className="h-12 bg-slate-100 rounded-lg" />)}</div>;
  }

  if (!insights) return <div className="p-6 text-sm text-slate-500">No insights available.</div>;

  const embeddingPct = insights.chunk_count > 0 ? Math.round((insights.embedded_count / insights.chunk_count) * 100) : 0;

  return (
    <div className="p-5 space-y-5">
      <div className="rounded-xl border border-slate-200 bg-white overflow-hidden shadow-sm">
        <div className="px-5 py-4 border-b border-slate-200 bg-slate-50">
          <h3 className="text-sm font-semibold text-slate-900">Vector Index Statistics</h3>
        </div>
        <div className="p-5 space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="rounded-lg bg-slate-50 p-3 text-center">
              <p className="text-2xl font-bold text-slate-900">{insights.chunk_count}</p>
              <p className="text-xs text-slate-500 mt-0.5">Total Chunks</p>
            </div>
            <div className="rounded-lg bg-emerald-50 p-3 text-center">
              <p className="text-2xl font-bold text-emerald-600">{insights.embedded_count}</p>
              <p className="text-xs text-slate-500 mt-0.5">Embedded</p>
            </div>
            <div className="rounded-lg bg-blue-50 p-3 text-center">
              <p className="text-2xl font-bold text-blue-600">{insights.page_count}</p>
              <p className="text-xs text-slate-500 mt-0.5">Pages Indexed</p>
            </div>
            <div className="rounded-lg bg-amber-50 p-3 text-center">
              <p className="text-2xl font-bold text-amber-600">{embeddingPct}%</p>
              <p className="text-xs text-slate-500 mt-0.5">Coverage</p>
            </div>
          </div>
          {/* Embedding coverage bar */}
          <div className="space-y-1.5">
            <div className="flex justify-between text-xs text-slate-600">
              <span>Embedding Coverage</span>
              <span className="font-medium">{insights.embedded_count} / {insights.chunk_count}</span>
            </div>
            <div className="h-2 w-full rounded-full bg-slate-100 overflow-hidden">
              <div
                className="h-full rounded-full bg-emerald-500 transition-all duration-500"
                style={{ width: `${embeddingPct}%` }}
                role="progressbar"
                aria-valuenow={embeddingPct}
                aria-valuemin={0}
                aria-valuemax={100}
              />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Graph Insights Panel ──────────────────────────────────────────────────────

function GraphInsightsPanel({ kbId }: { kbId: string }) {
  const [stats, setStats] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!kbId) return;
    import('../api/client').then(({ apiClient }) => {
      apiClient.get(`/knowledge-bases/${kbId}/graph/stats`)
        .then(({ data }) => { setStats(data); setLoading(false); })
        .catch(() => setLoading(false));
    });
  }, [kbId]);

  if (loading) {
    return <div className="animate-pulse space-y-3">{[1,2,3].map(i => <div key={i} className="h-16 rounded-lg bg-slate-100" />)}</div>;
  }

  if (!stats || stats.total_nodes === 0) {
    return (
      <div className="rounded-xl border border-orange-200 bg-orange-50 p-4">
        <p className="text-sm font-medium text-orange-800">No graph data yet</p>
        <p className="text-xs text-orange-700 mt-1">Upload documents to extract entities and relationships.</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Stats cards */}
      <div className="grid grid-cols-2 gap-3">
        <div className="rounded-xl border border-slate-200 bg-white p-3 text-center">
          <p className="text-2xl font-bold text-orange-600">{stats.total_nodes}</p>
          <p className="text-xs text-slate-500">Entities</p>
        </div>
        <div className="rounded-xl border border-slate-200 bg-white p-3 text-center">
          <p className="text-2xl font-bold text-blue-600">{stats.total_edges}</p>
          <p className="text-xs text-slate-500">Relationships</p>
        </div>
      </div>

      {/* Entity types */}
      {stats.entity_types && Object.keys(stats.entity_types).length > 0 && (
        <div className="rounded-xl border border-slate-200 bg-white p-4">
          <p className="text-xs font-semibold text-slate-700 mb-3">Entity Types</p>
          <div className="space-y-2">
            {Object.entries(stats.entity_types).sort((a: any, b: any) => b[1] - a[1]).map(([type, count]: any) => (
              <div key={type} className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: TYPE_COLORS_MAP[type] || '#aaa' }} />
                  <span className="text-xs text-slate-600 capitalize">{type}</span>
                </div>
                <span className="text-xs font-medium text-slate-800">{count}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Top entities */}
      {stats.top_entities && stats.top_entities.length > 0 && (
        <div className="rounded-xl border border-slate-200 bg-white p-4">
          <p className="text-xs font-semibold text-slate-700 mb-3">Top Entities</p>
          <div className="space-y-2">
            {stats.top_entities.map((entity: any, i: number) => (
              <div key={i} className="flex items-center justify-between">
                <div className="flex items-center gap-2 min-w-0">
                  <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: TYPE_COLORS_MAP[entity.type] || '#aaa' }} />
                  <span className="text-xs text-slate-700 truncate">{entity.name}</span>
                </div>
                <span className="text-[10px] text-slate-400 shrink-0 ml-2">{entity.mentions} mentions</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

const TYPE_COLORS_MAP: Record<string, string> = {
  organization: '#4e79a7', person: '#f28e2b', role: '#e15759',
  policy: '#76b7b2', process: '#59a14f', category: '#edc948',
  location: '#9c755f', amount: '#ff9da7', department: '#b07aa1',
  document: '#bab0ac', concept: '#4e79a7', rule: '#e15759',
};

// ── PageIndex Structure Panel ─────────────────────────────────────────────────

function PageIndexStructurePanel({ docId, docTitle }: { docId: string; docTitle?: string }) {
  const [insights, setInsights] = useState<PageIndexInsights | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchDocumentInsights(docId)
      .then((data) => {
        if (data.rag_mode === 'pageindex') setInsights(data as PageIndexInsights);
        setLoading(false);
      })
      .catch((err) => {
        setError(err?.response?.data?.detail ?? err?.message ?? 'Failed to load tree.');
        setLoading(false);
      });
  }, [docId]);

  if (loading) {
    return (
      <div className="p-4 space-y-3 animate-pulse">
        {[...Array(6)].map((_, i) => <div key={i} className="h-10 bg-slate-100 rounded-lg" />)}
      </div>
    );
  }

  if (error) return <div className="p-4 text-sm text-red-600">{error}</div>;

  if (!insights?.tree_json) {
    return <div className="p-6 text-sm text-slate-500">No document tree available. The document may still be processing.</div>;
  }

  // Normalise the two shapes the backend may store:
  // 1. { doc_id, title, nodes: [] }  — current format (LLM prompt returns this)
  // 2. { node_id, title, children: [] } — legacy single-root-node format
  const raw = insights.tree_json as Record<string, unknown>;
  let treeJson: Parameters<typeof TreeExplorer>[0]['treeJson'];

  if (Array.isArray(raw.nodes)) {
    treeJson = raw as unknown as Parameters<typeof TreeExplorer>[0]['treeJson'];
  } else if (Array.isArray(raw.children)) {
    treeJson = {
      doc_id: docId,
      title: (raw.title as string) ?? docTitle ?? 'Document',
      nodes: (raw.children as Parameters<typeof TreeExplorer>[0]['treeJson']['nodes']),
    };
  } else {
    return <div className="p-6 text-sm text-slate-500">Document tree has an unexpected format and cannot be displayed.</div>;
  }

  return (
    <div className="h-full overflow-hidden">
      <TreeExplorer treeJson={treeJson} docTitle={docTitle} />
    </div>
  );
}

// ── Main DocumentViewerPage ───────────────────────────────────────────────────

type Tab = 'structure' | 'insights' | 'wiki';

export function DocumentViewerPage() {
  const { docId } = useParams<{ docId: string }>();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();

  const initialPage = parseInt(searchParams.get('page') ?? '1', 10) || 1;
  const highlightText = searchParams.get('highlight') ?? undefined;
  const fromPath = searchParams.get('from') ?? undefined;

  const [doc, setDoc] = useState<Document | null>(null);
  const [kb, setKb] = useState<KnowledgeBase | null>(null);
  const [loading, setLoading] = useState(true);
  const [currentPage, setCurrentPage] = useState(initialPage);
  const [activeTab, setActiveTab] = useState<Tab>('structure');

  useEffect(() => {
    if (!docId) return;
    setLoading(true);
    Promise.all([getDocument(docId), getKnowledgeBases()])
      .then(([docData, kbs]) => {
        setDoc(docData);
        const matchedKb = kbs.find((k) => k.id === docData.kb_id) ?? null;
        setKb(matchedKb);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, [docId]);

  const handleBack = () => {
    if (fromPath) {
      navigate(fromPath);
    } else {
      navigate(-1);
    }
  };

  const ragMode = kb?.settings?.rag_mode ?? kb?.rag_mode ?? 'pageindex';

  // Set default tab based on rag mode once KB is loaded
  useEffect(() => {
    if (ragMode === 'wiki') setActiveTab('wiki');
    else if (ragMode === 'graph') setActiveTab('structure');
    else setActiveTab('structure');
  }, [ragMode]);
  const isPDF = doc?.file_type?.toLowerCase() === 'pdf';
  const pdfUrl = docId ? `/api/v1/documents/${docId}/file` : null;

  const TABS: { id: Tab; label: string; Icon: React.ElementType }[] =
    ragMode === 'wiki'
      ? [
          { id: 'wiki', label: 'Wiki Pages', Icon: BookOpen },
          { id: 'insights', label: 'Insights', Icon: FileText },
        ]
      : [
          { id: 'structure', label: ragMode === 'vector' ? 'Chunks' : ragMode === 'graph' ? 'Graph' : 'Tree', Icon: ragMode === 'vector' ? Database : Layers },
          { id: 'insights', label: 'Insights', Icon: FileText },
        ];

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="animate-pulse text-sm text-slate-400">Loading document…</div>
      </div>
    );
  }

  if (!doc) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-4">
        <p className="text-sm text-slate-500">Document not found.</p>
        <button onClick={handleBack} className="text-sm text-[var(--dm-primary)] hover:underline">Go back</button>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-4 px-5 py-3 border-b border-slate-200 bg-white shadow-sm shrink-0">
        <button
          onClick={handleBack}
          className="flex items-center gap-1.5 text-sm text-slate-600 hover:text-slate-900 transition-colors rounded-lg px-2 py-1.5 hover:bg-slate-100"
          aria-label="Go back"
        >
          <ArrowLeft className="h-4 w-4" />
          Back
        </button>

        <div className="h-5 w-px bg-slate-200" />

        {/* File icon */}
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-blue-50 shrink-0">
          <BookOpen className="h-4 w-4 text-[var(--dm-primary)]" />
        </div>

        {/* Filename */}
        <div className="flex-1 min-w-0">
          <p className="font-semibold text-slate-900 text-sm truncate">{doc.filename}</p>
          {kb && <p className="text-xs text-slate-500 truncate">{kb.name}</p>}
        </div>

        {/* Badges */}
        <div className="flex items-center gap-2 shrink-0">
          <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${
            ragMode === 'vector'
              ? 'bg-emerald-100 text-emerald-700 border border-emerald-200'
              : ragMode === 'wiki'
              ? 'bg-violet-100 text-violet-700 border border-violet-200'
              : ragMode === 'graph'
              ? 'bg-orange-100 text-orange-700 border border-orange-200'
              : 'bg-blue-100 text-blue-700 border border-blue-200'
          }`}>
            <span className={`w-1.5 h-1.5 rounded-full ${ragMode === 'vector' ? 'bg-emerald-500' : ragMode === 'wiki' ? 'bg-violet-500' : ragMode === 'graph' ? 'bg-orange-500' : 'bg-blue-500'}`} />
            {ragMode === 'vector' ? 'Vector RAG' : ragMode === 'wiki' ? 'Wiki' : ragMode === 'graph' ? 'Graph RAG' : 'PageIndex'}
          </span>
          <span className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium border ${
            doc.status === 'ready'
              ? 'bg-green-50 text-green-700 border-green-200'
              : doc.status === 'processing'
              ? 'bg-amber-50 text-amber-700 border-amber-200'
              : doc.status === 'failed'
              ? 'bg-red-50 text-red-700 border-red-200'
              : 'bg-slate-50 text-slate-700 border-slate-200'
          }`}>
            {doc.status}
          </span>
        </div>
      </div>

      {/* Body */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left: PDF Viewer (60%) */}
        <div className="flex-[3] min-w-0 overflow-hidden border-r border-slate-200">
          {isPDF ? (
            <PDFViewer
              url={pdfUrl}
              currentPage={currentPage}
              highlight={highlightText}
              onPageChange={setCurrentPage}
            />
          ) : (
            <div className="flex h-full flex-col items-center justify-center gap-4 text-slate-400">
              <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-slate-100">
                <FileText size={32} strokeWidth={1.5} className="text-slate-300" />
              </div>
              <p className="text-sm text-slate-500">Preview not available for .{doc.file_type} files</p>
            </div>
          )}
        </div>

        {/* Right: Tabs (40%) */}
        <div className="flex-[2] min-w-0 flex flex-col overflow-hidden bg-slate-50">
          {/* Tab bar */}
          <div className="flex items-center gap-0 border-b border-slate-200 bg-white shrink-0 px-1 pt-1">
            {TABS.map(({ id, label, Icon }) => (
              <button
                key={id}
                onClick={() => setActiveTab(id)}
                className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium rounded-t-lg border-b-2 transition-colors ${
                  activeTab === id
                    ? 'border-[var(--dm-primary)] text-[var(--dm-primary)] bg-blue-50/50'
                    : 'border-transparent text-slate-500 hover:text-slate-800 hover:bg-slate-50'
                }`}
              >
                <Icon className="h-4 w-4" />
                {label}
              </button>
            ))}
          </div>

          {/* Tab content */}
          <div className="flex-1 overflow-hidden">
            {activeTab === 'structure' && ragMode !== 'wiki' && (
              ragMode === 'vector' ? (
                <VectorStructurePanel docId={doc.id} highlightText={highlightText} />
              ) : ragMode === 'graph' ? (
                <div className="h-full flex flex-col">
                  <div className="px-3 py-2 border-b border-slate-200 flex items-center justify-between shrink-0">
                    <span className="text-xs text-slate-500">Knowledge Graph</span>
                    <a
                      href="http://localhost:7474"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-xs text-orange-600 hover:text-orange-800 hover:underline"
                    >
                      Open Neo4j Browser ↗
                    </a>
                  </div>
                  <div className="flex-1">
                    <NeovisGraph kbId={kb?.id || ''} docId={doc.id} />
                  </div>
                </div>
              ) : (
                <PageIndexStructurePanel docId={doc.id} docTitle={doc.filename} />
              )
            )}
            {activeTab === 'wiki' && ragMode === 'wiki' && kb && (
              <div className="h-full overflow-y-auto p-4">
                <WikiPageExplorer kbId={kb.id} filterDocId={doc.id} />
              </div>
            )}
            {activeTab === 'insights' && (
              <div className="h-full overflow-y-auto">
                {ragMode === 'vector' ? (
                  <VectorInsightsPanel docId={doc.id} />
                ) : ragMode === 'wiki' ? (
                  <div className="p-6 text-sm text-slate-500">
                    <div className="rounded-xl border border-violet-200 bg-violet-50 p-4">
                      <p className="text-sm font-medium text-violet-800 mb-1">Wiki Mode</p>
                      <p className="text-xs text-violet-700">Document insights are built into the Wiki Pages tab. Each extracted page contains structured knowledge from this document.</p>
                    </div>
                  </div>
                ) : ragMode === 'graph' ? (
                  <div className="p-4">
                    <DocumentSummary docId={doc.id} />
                  </div>
                ) : (
                  <div className="p-4">
                    <DocumentSummary docId={doc.id} />
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
