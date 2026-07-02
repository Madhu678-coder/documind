import {
  BookOpen,
  Brain,
  ChevronLeft,
  Database,
  Edit2,
  Eye,
  FileText,
  Layers,
  Plus,
  Search,
  Share2,
  Trash2,
  X,
} from 'lucide-react';
import { WikiPageExplorer } from '../components/wiki/WikiPageExplorer';
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiClient } from '../api/client';
import { DropZone } from '../components/upload/DropZone';
import { ProgressTracker } from '../components/upload/ProgressTracker';
import { useDocuments } from '../hooks/useDocuments';
import type { Document, KBSettings, KnowledgeBase } from '../types/index';

// ── Helpers ──────────────────────────────────────────────────────────────────

function fmt_bytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function getKbRagMode(kb: KnowledgeBase): 'pageindex' | 'vector' | 'wiki' | 'graph' | 'openkb' {
  return kb.settings?.rag_mode || kb.rag_mode || 'pageindex';
}

// ── Badges ───────────────────────────────────────────────────────────────────

function RagModeBadge({ ragMode }: { ragMode?: string }) {
  const mode = ragMode || 'pageindex';
  if (mode === 'vector') {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 border border-emerald-200 px-2 py-0.5 text-xs font-medium text-emerald-700">
        <Database className="h-3 w-3" />
        Vector RAG
      </span>
    );
  }
  if (mode === 'wiki') {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-violet-50 border border-violet-200 px-2 py-0.5 text-xs font-medium text-violet-700">
        <BookOpen className="h-3 w-3" />
        Wiki
      </span>
    );
  }
  if (mode === 'graph') {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-orange-50 border border-orange-200 px-2 py-0.5 text-xs font-medium text-orange-700">
        <Share2 className="h-3 w-3" />
        Graph RAG
      </span>
    );
  }
  if (mode === 'openkb') {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-teal-50 border border-teal-200 px-2 py-0.5 text-xs font-medium text-teal-700">
        <BookOpen className="h-3 w-3" />
        OpenKB
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-blue-50 border border-blue-200 px-2 py-0.5 text-xs font-medium text-blue-700">
      <Brain className="h-3 w-3" />
      PageIndex
    </span>
  );
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, { cls: string; label: string }> = {
    ready:      { cls: 'bg-emerald-50 text-emerald-700 border-emerald-200', label: 'Ready' },
    processing: { cls: 'bg-amber-50 text-amber-700 border-amber-200', label: 'Processing' },
    uploading:  { cls: 'bg-blue-50 text-blue-700 border-blue-200', label: 'Uploading' },
    failed:     { cls: 'bg-red-50 text-red-700 border-red-200', label: 'Failed' },
  };
  const { cls, label } = map[status] ?? { cls: 'bg-slate-100 text-slate-600 border-slate-200', label: status };
  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${cls}`}>
      {label}
    </span>
  );
}

// ── Hit Testing Panel ─────────────────────────────────────────────────────────

interface RetrievalChunk {
  chunk_id: string;
  document_id: string;
  doc_filename: string;
  text: string;
  score: number;
  page_number: number;
  chunk_index: number;
}

function HitTestingPanel({ kb }: { kb: KnowledgeBase }) {
  const [query, setQuery] = useState('');
  const [searching, setSearching] = useState(false);
  const [results, setResults] = useState<RetrievalChunk[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleSearch = async () => {
    if (!query.trim()) return;
    setSearching(true); setError(null);
    try {
      const { data } = await apiClient.post<{ chunks: RetrievalChunk[] }>('/retrieval/test', {
        kb_id: kb.id, query: query.trim(),
      });
      setResults(data.chunks);
    } catch (err: unknown) {
      const e = err as { response?: { data?: { detail?: string } } };
      setError(e?.response?.data?.detail || 'Retrieval test failed');
    } finally {
      setSearching(false);
    }
  };

  return (
    <div className="rounded-xl border border-emerald-200 bg-emerald-50/50">
      <div className="flex items-center gap-2 px-5 py-4 border-b border-emerald-200">
        <Search className="h-4 w-4 text-emerald-600" />
        <h4 className="text-sm font-semibold text-emerald-800">Hit Testing</h4>
        <span className="text-xs text-emerald-600 ml-auto">Test retrieval with any query</span>
      </div>
      <div className="p-5 flex flex-col gap-4">
        <div className="flex gap-2">
          <input value={query} onChange={e => setQuery(e.target.value)} onKeyDown={e => e.key === 'Enter' && handleSearch()}
            placeholder="Enter a test query to see which chunks are retrieved…"
            className="flex-1 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-emerald-500 focus:ring-2 focus:ring-emerald-100 transition-all" />
          <button onClick={handleSearch} disabled={searching || !query.trim()}
            className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-50 transition-colors">
            {searching ? '…' : 'Retrieve'}
          </button>
        </div>

        {error && <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">{error}</p>}
        {results !== null && results.length === 0 && (
          <p className="text-sm text-slate-500 text-center py-4">No matching chunks found for this query.</p>
        )}
        {results && results.length > 0 && (
          <div className="flex flex-col gap-2.5">
            <p className="text-xs font-medium text-slate-500">{results.length} chunk{results.length !== 1 ? 's' : ''} retrieved</p>
            {results.map((chunk, i) => (
              <div key={chunk.chunk_id} className="rounded-lg border border-slate-200 bg-white p-3.5 shadow-sm">
                <div className="flex items-start justify-between gap-2 mb-2">
                  <div className="flex items-center gap-2 flex-1 min-w-0">
                    <span className="shrink-0 flex h-5 w-5 items-center justify-center rounded-full bg-slate-100 text-xs font-bold text-slate-600">{i + 1}</span>
                    <span className="text-xs font-medium text-slate-700 truncate">{chunk.doc_filename}</span>
                    <span className="text-xs text-slate-400 shrink-0">p.{chunk.page_number} · chunk {chunk.chunk_index + 1}</span>
                  </div>
                  <span className={`shrink-0 text-xs font-bold px-2 py-0.5 rounded-full ${chunk.score > 0.7 ? 'bg-emerald-100 text-emerald-700' : chunk.score > 0.4 ? 'bg-amber-100 text-amber-700' : 'bg-slate-100 text-slate-600'}`}>
                    {(chunk.score * 100).toFixed(0)}%
                  </span>
                </div>
                <p className="text-xs text-slate-600 leading-relaxed line-clamp-3">{chunk.text}</p>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Document Table ────────────────────────────────────────────────────────────

function DocumentTable({ docs, ragMode, onViewDoc, onDeleteDoc }: {
  docs: Document[];
  ragMode: 'pageindex' | 'vector' | 'wiki';
  onViewDoc: (doc: Document) => void;
  onDeleteDoc?: (doc: Document) => void;
}) {
  if (docs.length === 0) return null;

  return (
    <div className="overflow-x-auto rounded-xl border border-slate-200 shadow-sm">
      <table className="w-full text-sm">
        <thead>
          <tr className="bg-slate-50 border-b border-slate-200">
            <th className="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wide">Document</th>
            <th className="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wide">Status</th>
            <th className="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wide">
              {ragMode === 'vector' ? 'Chunks' : 'Size'}
            </th>
            <th className="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wide">Indexed</th>
            <th className="px-4 py-3 text-right text-xs font-semibold text-slate-500 uppercase tracking-wide">Actions</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {docs.map(doc => (
            <tr key={doc.id} className="hover:bg-slate-50 transition-colors group">
              <td className="px-4 py-3">
                <div className="flex items-center gap-2.5 min-w-0">
                  <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-blue-50">
                    <FileText className="h-4 w-4 text-blue-600" />
                  </div>
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-slate-900 truncate max-w-xs">{doc.filename}</p>
                    <p className="text-xs text-slate-400">{fmt_bytes(doc.size_bytes)}</p>
                  </div>
                </div>
              </td>
              <td className="px-4 py-3"><StatusBadge status={doc.status} /></td>
              <td className="px-4 py-3">
                {ragMode === 'vector' ? (
                  doc.chunk_count != null ? (
                    <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 border border-emerald-200 px-2 py-0.5 text-xs font-medium text-emerald-700">
                      <Layers className="h-3 w-3" />{doc.chunk_count}
                    </span>
                  ) : <span className="text-xs text-slate-400">—</span>
                ) : (
                  <span className="text-xs text-slate-600">{fmt_bytes(doc.size_bytes)}</span>
                )}
              </td>
              <td className="px-4 py-3 text-xs text-slate-500">
                {new Date(doc.created_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}
              </td>
              <td className="px-4 py-3 text-right">
                <div className="flex items-center justify-end gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                  {doc.status === 'ready' && (
                    <button onClick={() => onViewDoc(doc)} title={ragMode === 'vector' ? 'View chunks' : 'View tree'}
                      className="p-1.5 rounded-lg hover:bg-blue-50 text-slate-400 hover:text-blue-600 transition-colors">
                      <Eye className="h-4 w-4" />
                    </button>
                  )}
                  <button onClick={() => onDeleteDoc?.(doc)} title="Delete document"
                    className="p-1.5 rounded-lg hover:bg-red-50 text-slate-400 hover:text-red-600 transition-colors">
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── KB Detail View ────────────────────────────────────────────────────────────

function KbDetail({ kb, onBack, onRefresh, onDeleteKb }: {
  kb: KnowledgeBase;
  onBack: () => void;
  onRefresh: () => void;
  onDeleteKb: (kb: KnowledgeBase) => void;
}) {
  const { documents, loadDocuments } = useDocuments();
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState<'documents' | 'wiki' | 'settings'>('documents');

  useEffect(() => { loadDocuments(kb.id); }, [kb.id]);

  const kbDocs = documents.filter(d => d.kb_id === kb.id);
  const ragMode = getKbRagMode(kb);
  const readyDocs = kbDocs.filter(d => d.status === 'ready');
  const displayDocs = kbDocs.filter(d => d.status === 'ready' || d.status === 'failed');

  return (
    <div className="flex flex-col gap-5">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-center gap-3 min-w-0">
          <button onClick={onBack} className="flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-sm text-slate-500 hover:bg-slate-100 hover:text-slate-700 transition-colors shrink-0">
            <ChevronLeft className="h-4 w-4" />
            All KBs
          </button>
          <div className="h-4 w-px bg-slate-300 shrink-0" />
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-blue-100">
            <BookOpen className="h-5 w-5 text-[var(--dm-primary)]" />
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h2 className="text-lg font-semibold text-slate-900 truncate">{kb.name}</h2>
              <RagModeBadge ragMode={ragMode} />
            </div>
            {kb.description && <p className="text-sm text-slate-500 truncate">{kb.description}</p>}
          </div>
        </div>
        <button onClick={() => onDeleteKb(kb)} title="Delete KB"
          className="p-2 rounded-lg hover:bg-red-50 text-slate-400 hover:text-red-600 transition-colors shrink-0">
          <Trash2 className="h-4 w-4" />
        </button>
      </div>

      {/* Stats + tabs */}
      <div className="flex items-center gap-6 rounded-xl border border-slate-200 bg-white px-5 py-3 shadow-sm">
        <div className="text-center">
          <p className="text-lg font-bold text-slate-900">{kbDocs.length}</p>
          <p className="text-xs text-slate-500">Documents</p>
        </div>
        <div className="h-8 w-px bg-slate-200" />
        <div className="text-center">
          <p className="text-lg font-bold text-slate-900">{readyDocs.length}</p>
          <p className="text-xs text-slate-500">Indexed</p>
        </div>
        {ragMode === 'vector' && (
          <>
            <div className="h-8 w-px bg-slate-200" />
            <div className="text-center">
              <p className="text-lg font-bold text-slate-900">
                {readyDocs.reduce((sum, d) => sum + (d.chunk_count || 0), 0)}
              </p>
              <p className="text-xs text-slate-500">Total Chunks</p>
            </div>
          </>
        )}
        <div className="ml-auto flex gap-1">
          {(
            ragMode === 'wiki'
              ? (['documents', 'wiki', 'settings'] as const)
              : ragMode === 'openkb'
              ? (['documents', 'openkb', 'settings'] as const)
              : (['documents', 'settings'] as const)
          ).map(tab => (
            <button key={tab} onClick={() => setActiveTab(tab)}
              className={`rounded-lg px-3 py-1.5 text-sm font-medium capitalize transition-colors ${activeTab === tab
                ? (ragMode === 'wiki' && tab === 'wiki') || (ragMode === 'openkb' && tab === 'openkb')
                  ? 'bg-teal-600 text-white shadow-sm'
                  : 'bg-[var(--dm-primary)] text-white shadow-sm'
                : 'text-slate-600 hover:bg-slate-100'}`}>
              {tab === 'wiki' ? 'Wiki Pages' : tab === 'openkb' ? 'Tools' : tab}
            </button>
          ))}
        </div>
      </div>

      {activeTab === 'documents' && (
        <>
          <DropZone kb_id={kb.id} onUpload={() => { loadDocuments(kb.id); onRefresh(); }} />
          <ProgressTracker kb_id={kb.id} documents={kbDocs} />

          {kbDocs.length === 0 ? (
            <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-slate-300 bg-slate-50 py-16 text-center">
              <BookOpen className="h-12 w-12 text-slate-400" />
              <p className="text-sm font-medium text-slate-600">No documents yet</p>
              <p className="text-xs text-slate-500">Upload your first document using the drop zone above</p>
            </div>
          ) : (
            <DocumentTable docs={displayDocs} ragMode={ragMode} onViewDoc={(doc) => navigate(`/documents/${doc.id}?from=/knowledge-bases`)} onDeleteDoc={async (doc) => {
              if (!confirm(`Delete "${doc.filename}"? This cannot be undone.`)) return;
              try {
                const { deleteDocument } = await import('../api/documents');
                await deleteDocument(doc.id);
                loadDocuments(kb.id);
              } catch (e: any) {
                alert(e?.response?.data?.detail || 'Failed to delete document');
              }
            }} />
          )}

          {ragMode === 'vector' && readyDocs.length > 0 && <HitTestingPanel kb={kb} />}
        </>
      )}

      {activeTab === 'openkb' && ragMode === 'openkb' && (
        <OpenKBToolsPanel kbId={kb.id} kbName={kb.name} />
      )}

      {activeTab === 'wiki' && ragMode === 'wiki' && (
        <div className="flex flex-col gap-4">
          <div className="rounded-xl border border-violet-200 bg-violet-50/50 px-5 py-4">
            <div className="flex items-center gap-2 mb-1">
              <BookOpen className="h-4 w-4 text-violet-600" />
              <h4 className="text-sm font-semibold text-violet-800">Living Knowledge Base</h4>
            </div>
            <p className="text-xs text-violet-700">
              The LLM builds and maintains these pages as documents are indexed. Topics compound — adding a new document enriches existing pages and creates new ones.
            </p>
          </div>
          <WikiPageExplorer kbId={kb.id} />
        </div>
      )}

      {activeTab === 'settings' && (
        <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <h3 className="text-sm font-semibold text-slate-700 mb-4">Knowledge Base Configuration</h3>
          <div className="flex flex-col gap-0">
            {[
              ['Name', kb.name],
              ['Description', kb.description || '—'],
              ['RAG Mode', ragMode.toUpperCase()],
              ...(kb.settings && ragMode === 'vector' ? [
                ['Index Method', (kb.settings.index_method || 'high_quality').replace('_', ' ')],
                ['Retrieval Mode', kb.settings.retrieval_mode || 'vector'],
                ['Top-K', String(kb.settings.top_k || 5)],
                ['Chunk Size', String(kb.settings.chunk_size || 1000)],
                ['Chunk Overlap', String(kb.settings.chunk_overlap || 200)],
                ['Embedding Provider', kb.settings.embedding_provider || 'bedrock'],
                ['Embedding Model', kb.settings.embedding_model || 'amazon.titan-embed-text-v2:0'],
              ] : []),
              ['Created', new Date(kb.created_at).toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' })],
            ].map(([k, v]) => (
              <div key={k} className="flex items-center justify-between py-2.5 border-b border-slate-100 last:border-0">
                <span className="text-sm text-slate-500">{k}</span>
                <span className="text-sm font-medium text-slate-800 capitalize">{v}</span>
              </div>
            ))}
          </div>
        </div>
      )}

    </div>
  );
}

// ── OpenKB Tools Panel ────────────────────────────────────────────────────────

function OpenKBToolsPanel({ kbId, kbName }: { kbId: string; kbName: string }) {
  // Lint state
  const [lintLoading, setLintLoading] = useState(false);
  const [lintResult, setLintResult] = useState<any | null>(null);

  // Skill state
  const [skillName, setSkillName] = useState('');
  const [skillIntent, setSkillIntent] = useState('');
  const [skillLoading, setSkillLoading] = useState(false);
  const [skillContent, setSkillContent] = useState<string | null>(null);

  // Deck state
  const [deckName, setDeckName] = useState('');
  const [deckIntent, setDeckIntent] = useState('');
  const [deckLoading, setDeckLoading] = useState(false);

  const runLint = async () => {
    setLintLoading(true);
    setLintResult(null);
    try {
      const { data } = await apiClient.get(`/knowledge-bases/${kbId}/openkb/lint`);
      setLintResult(data);
    } catch (e: any) {
      setLintResult({ error: e?.response?.data?.detail ?? 'Lint failed' });
    } finally {
      setLintLoading(false);
    }
  };

  const generateSkill = async () => {
    if (!skillName.trim() || !skillIntent.trim()) return;
    setSkillLoading(true);
    setSkillContent(null);
    try {
      const { data } = await apiClient.post(`/knowledge-bases/${kbId}/openkb/skills`, {
        skill_name: skillName.trim(),
        intent: skillIntent.trim(),
      });
      setSkillContent(data.content);
    } catch (e: any) {
      alert(e?.response?.data?.detail ?? 'Skill generation failed');
    } finally {
      setSkillLoading(false);
    }
  };

  const downloadSkill = () => {
    if (!skillContent) return;
    const blob = new Blob([skillContent], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${skillName || 'skill'}.md`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const generateDeck = async () => {
    if (!deckName.trim() || !deckIntent.trim()) return;
    setDeckLoading(true);
    try {
      const resp = await apiClient.post(
        `/knowledge-bases/${kbId}/openkb/decks`,
        { deck_name: deckName.trim(), intent: deckIntent.trim() },
        { responseType: 'blob' }
      );
      const url = URL.createObjectURL(new Blob([resp.data], { type: 'text/html' }));
      const a = document.createElement('a');
      a.href = url;
      a.download = `${deckName.replace(/\s+/g, '_')}.html`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e: any) {
      alert(e?.response?.data?.detail ?? 'Deck generation failed');
    } finally {
      setDeckLoading(false);
    }
  };

  const exportMarkdown = async () => {
    try {
      const resp = await apiClient.get(`/knowledge-bases/${kbId}/openkb/export`, { responseType: 'blob' });
      const url = URL.createObjectURL(new Blob([resp.data], { type: 'text/markdown' }));
      const a = document.createElement('a');
      a.href = url;
      a.download = `${kbName.replace(/\s+/g, '_')}_openkb_wiki.md`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e: any) {
      alert('Export failed');
    }
  };

  const severityColor: Record<string, string> = {
    error:   'text-red-700 bg-red-50 border-red-200',
    warning: 'text-amber-700 bg-amber-50 border-amber-200',
    info:    'text-blue-700 bg-blue-50 border-blue-200',
  };

  return (
    <div className="flex flex-col gap-5">

      {/* ── Wiki Lint ── */}
      <div className="rounded-xl border border-slate-200 bg-white overflow-hidden shadow-sm">
        <div className="px-5 py-4 border-b border-slate-200 bg-slate-50 flex items-center justify-between">
          <div>
            <h3 className="text-sm font-semibold text-slate-900">Wiki Lint</h3>
            <p className="text-xs text-slate-500 mt-0.5">Check for broken wikilinks, orphaned pages, missing summaries, and duplicate titles</p>
          </div>
          <button
            onClick={runLint}
            disabled={lintLoading}
            className="flex items-center gap-2 rounded-lg bg-slate-800 px-4 py-2 text-xs font-medium text-white hover:bg-slate-700 disabled:opacity-50 transition-colors"
          >
            {lintLoading ? (
              <><span className="inline-block w-3 h-3 border-2 border-white/30 border-t-white rounded-full animate-spin" />Running…</>
            ) : 'Run Lint'}
          </button>
        </div>

        {lintResult && !lintResult.error && (
          <div className="p-5 space-y-4">
            {/* Summary */}
            <div className="flex items-center gap-3">
              <span className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-sm font-semibold border ${lintResult.passed ? 'bg-green-50 text-green-700 border-green-200' : 'bg-red-50 text-red-700 border-red-200'}`}>
                {lintResult.passed ? '✓ Passed' : '✗ Failed'}
              </span>
              <span className="text-xs text-slate-500">{lintResult.pages_checked} pages checked</span>
              {lintResult.error_count > 0 && <span className="text-xs font-medium text-red-600">{lintResult.error_count} error{lintResult.error_count !== 1 ? 's' : ''}</span>}
              {lintResult.warning_count > 0 && <span className="text-xs font-medium text-amber-600">{lintResult.warning_count} warning{lintResult.warning_count !== 1 ? 's' : ''}</span>}
              {lintResult.issues?.length === 0 && <span className="text-xs text-green-600">No issues found</span>}
            </div>

            {/* Issues */}
            {lintResult.issues?.length > 0 && (
              <div className="space-y-2 max-h-64 overflow-y-auto">
                {lintResult.issues.map((issue: any, i: number) => (
                  <div key={i} className={`rounded-lg border px-3 py-2 text-xs ${severityColor[issue.severity] ?? severityColor.info}`}>
                    <div className="flex items-start gap-2">
                      <span className="font-semibold uppercase shrink-0">{issue.severity}</span>
                      <div>
                        <span className="font-medium">{issue.page_title}</span>
                        <span className="text-slate-600 ml-1">({issue.check})</span>
                        <p className="mt-0.5 opacity-80">{issue.detail}</p>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
        {lintResult?.error && (
          <p className="p-4 text-sm text-red-600">{lintResult.error}</p>
        )}
      </div>

      {/* ── Skill Factory ── */}
      <div className="rounded-xl border border-slate-200 bg-white overflow-hidden shadow-sm">
        <div className="px-5 py-4 border-b border-slate-200 bg-indigo-50">
          <h3 className="text-sm font-semibold text-indigo-900">Skill Factory</h3>
          <p className="text-xs text-indigo-700 mt-0.5">Generate a portable SKILL.md agent skill from this knowledge base — loadable by Claude Code, Codex, or Gemini CLI</p>
        </div>
        <div className="p-5 space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-slate-700 mb-1">Skill Name</label>
              <input
                value={skillName}
                onChange={e => setSkillName(e.target.value)}
                placeholder="e.g. hr-policy-expert"
                className="w-full rounded-lg border border-slate-200 px-3 py-2 text-xs outline-none focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100 transition-all"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-700 mb-1">Intent</label>
              <input
                value={skillIntent}
                onChange={e => setSkillIntent(e.target.value)}
                placeholder="e.g. Answer HR policy questions"
                className="w-full rounded-lg border border-slate-200 px-3 py-2 text-xs outline-none focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100 transition-all"
              />
            </div>
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={generateSkill}
              disabled={skillLoading || !skillName.trim() || !skillIntent.trim()}
              className="flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-xs font-medium text-white hover:bg-indigo-700 disabled:opacity-50 transition-colors"
            >
              {skillLoading ? (
                <><span className="inline-block w-3 h-3 border-2 border-white/30 border-t-white rounded-full animate-spin" />Generating…</>
              ) : 'Generate SKILL.md'}
            </button>
            {skillContent && (
              <button
                onClick={downloadSkill}
                className="flex items-center gap-1.5 rounded-lg border border-indigo-300 bg-indigo-50 px-4 py-2 text-xs font-medium text-indigo-700 hover:bg-indigo-100 transition-colors"
              >
                ↓ Download SKILL.md
              </button>
            )}
          </div>
          {skillContent && (
            <div className="rounded-lg border border-indigo-200 bg-indigo-50/50 p-3 max-h-48 overflow-y-auto">
              <pre className="text-xs text-indigo-900 whitespace-pre-wrap font-mono leading-relaxed">{skillContent.slice(0, 800)}{skillContent.length > 800 ? '\n…(truncated — download for full content)' : ''}</pre>
            </div>
          )}
        </div>
      </div>

      {/* ── Deck Generator ── */}
      <div className="rounded-xl border border-slate-200 bg-white overflow-hidden shadow-sm">
        <div className="px-5 py-4 border-b border-slate-200 bg-purple-50">
          <h3 className="text-sm font-semibold text-purple-900">Deck Generator</h3>
          <p className="text-xs text-purple-700 mt-0.5">Generate a self-contained HTML slide deck from this knowledge base</p>
        </div>
        <div className="p-5 space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-slate-700 mb-1">Deck Name</label>
              <input
                value={deckName}
                onChange={e => setDeckName(e.target.value)}
                placeholder="e.g. HR Policy Overview"
                className="w-full rounded-lg border border-slate-200 px-3 py-2 text-xs outline-none focus:border-purple-400 focus:ring-2 focus:ring-purple-100 transition-all"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-700 mb-1">Intent</label>
              <input
                value={deckIntent}
                onChange={e => setDeckIntent(e.target.value)}
                placeholder="e.g. Onboard new employees"
                className="w-full rounded-lg border border-slate-200 px-3 py-2 text-xs outline-none focus:border-purple-400 focus:ring-2 focus:ring-purple-100 transition-all"
              />
            </div>
          </div>
          <button
            onClick={generateDeck}
            disabled={deckLoading || !deckName.trim() || !deckIntent.trim()}
            className="flex items-center gap-2 rounded-lg bg-purple-600 px-4 py-2 text-xs font-medium text-white hover:bg-purple-700 disabled:opacity-50 transition-colors"
          >
            {deckLoading ? (
              <><span className="inline-block w-3 h-3 border-2 border-white/30 border-t-white rounded-full animate-spin" />Generating…</>
            ) : '⬇ Generate & Download Deck'}
          </button>
        </div>
      </div>

      {/* ── Export ── */}
      <div className="rounded-xl border border-slate-200 bg-white overflow-hidden shadow-sm">
        <div className="px-5 py-4 border-b border-slate-200 bg-teal-50 flex items-center justify-between">
          <div>
            <h3 className="text-sm font-semibold text-teal-900">Export Wiki</h3>
            <p className="text-xs text-teal-700 mt-0.5">Download all compiled pages as a single Markdown file — compatible with Obsidian, Notion, and any markdown editor</p>
          </div>
          <button
            onClick={exportMarkdown}
            className="flex items-center gap-2 rounded-lg bg-teal-600 px-4 py-2 text-xs font-medium text-white hover:bg-teal-700 transition-colors"
          >
            ↓ Export .md
          </button>
        </div>
      </div>

    </div>
  );
}

// ── KB Card ───────────────────────────────────────────────────────────────────

function KbCard({ kb, onSelect, onEdit, onDelete, deleting }: {
  kb: KnowledgeBase;
  onSelect: () => void;
  onEdit: (e: React.MouseEvent) => void;
  onDelete: (e: React.MouseEvent) => void;
  deleting: boolean;
}) {
  const ragMode = getKbRagMode(kb);

  return (
    <div className="group relative flex flex-col rounded-xl border border-slate-200 bg-white shadow-sm hover:shadow-md hover:border-slate-300 transition-all cursor-pointer overflow-hidden"
      onClick={onSelect}>
      <div className={`h-1.5 w-full ${ragMode === 'vector' ? 'bg-gradient-to-r from-emerald-400 to-teal-500' : ragMode === 'wiki' ? 'bg-gradient-to-r from-violet-500 to-purple-600' : 'bg-gradient-to-r from-blue-400 to-indigo-500'}`} />
      <div className="flex flex-col gap-3 p-5 flex-1">
        <div className="flex items-start justify-between gap-2">
          <div className={`flex h-10 w-10 items-center justify-center rounded-xl shrink-0 ${ragMode === 'vector' ? 'bg-emerald-100' : ragMode === 'wiki' ? 'bg-violet-100' : 'bg-blue-100'}`}>
            <BookOpen className={`h-5 w-5 ${ragMode === 'vector' ? 'text-emerald-600' : ragMode === 'wiki' ? 'text-violet-600' : 'text-blue-600'}`} />
          </div>
          <RagModeBadge ragMode={ragMode} />
        </div>
        <div className="flex-1">
          <h3 className="text-sm font-semibold text-slate-900 line-clamp-1">{kb.name}</h3>
          {kb.description && <p className="text-xs text-slate-500 mt-1 line-clamp-2">{kb.description}</p>}
        </div>
        <div className="flex items-center justify-between pt-2 border-t border-slate-100">
          <p className="text-xs text-slate-500">
            <span className="font-medium text-slate-700">{kb.document_count}</span> doc{kb.document_count !== 1 ? 's' : ''}
          </p>
          <p className="text-xs text-slate-400">
            {new Date(kb.created_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
          </p>
        </div>
      </div>
      {/* Hover action buttons */}
      <div className="absolute top-5 right-4 flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity" onClick={e => e.stopPropagation()}>
        <button onClick={onEdit} className="p-1.5 rounded-lg bg-white/90 shadow-sm hover:bg-blue-50 text-slate-500 hover:text-blue-600 transition-colors" title="Edit">
          <Edit2 className="h-3.5 w-3.5" />
        </button>
        <button onClick={onDelete} disabled={deleting} className="p-1.5 rounded-lg bg-white/90 shadow-sm hover:bg-red-50 text-slate-500 hover:text-red-600 transition-colors disabled:opacity-50" title="Delete">
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
}

// ── Edit KB Modal ─────────────────────────────────────────────────────────────

function EditKbModal({ kb, onClose, onSave }: {
  kb: KnowledgeBase;
  onClose: () => void;
  onSave: (name: string, desc: string) => Promise<void>;
}) {
  const [name, setName] = useState(kb.name);
  const [desc, setDesc] = useState(kb.description || '');
  const [saving, setSaving] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    setSaving(true);
    try { await onSave(name.trim(), desc.trim()); onClose(); }
    finally { setSaving(false); }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
      <div className="w-full max-w-md rounded-2xl bg-white shadow-2xl p-6 flex flex-col gap-5">
        <div className="flex items-center justify-between">
          <h3 className="text-lg font-semibold text-slate-900">Edit Knowledge Base</h3>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-slate-100 text-slate-400"><X className="h-5 w-5" /></button>
        </div>
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1.5">Name <span className="text-red-500">*</span></label>
            <input required value={name} onChange={e => setName(e.target.value)} placeholder="KB name"
              className="w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none focus:border-[var(--dm-primary)] focus:ring-2 focus:ring-blue-100 transition-all" />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1.5">Description</label>
            <textarea value={desc} onChange={e => setDesc(e.target.value)} rows={2} placeholder="Optional description"
              className="w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none focus:border-[var(--dm-primary)] focus:ring-2 focus:ring-blue-100 transition-all resize-none" />
          </div>
          <div className="flex gap-3 justify-end pt-1">
            <button type="button" onClick={onClose} className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 transition-colors">Cancel</button>
            <button type="submit" disabled={saving || !name.trim()} className="rounded-lg bg-[var(--dm-primary)] px-4 py-2 text-sm font-medium text-white hover:bg-[var(--dm-primary-dark)] disabled:opacity-50 transition-colors shadow-sm">
              {saving ? 'Saving…' : 'Save'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ── KB Creation Wizard ────────────────────────────────────────────────────────

const TOTAL_STEPS_PAGEINDEX = 3;
const TOTAL_STEPS_VECTOR = 6;

function KbCreationWizard({ onClose, onCreated, createKb }: {
  onClose: () => void;
  onCreated: () => void;
  createKb: (name: string, description?: string, settings?: KBSettings) => Promise<void>;
}) {
  const [step, setStep] = useState(1);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [ragMode, setRagMode] = useState<'pageindex' | 'vector' | 'wiki' | 'graph'>('pageindex');
  const [indexMethod, setIndexMethod] = useState<'high_quality' | 'economical' | 'hybrid'>('high_quality');
  const [embeddingProvider, setEmbeddingProvider] = useState<'bedrock' | 'openai'>('bedrock');
  const [embeddingModel, setEmbeddingModel] = useState('amazon.titan-embed-text-v2:0');
  const [chunkStrategy, setChunkStrategy] = useState<'recursive' | 'parent_child'>('recursive');
  const [chunkSize, setChunkSize] = useState(1000);
  const [chunkOverlap, setChunkOverlap] = useState(200);
  const [retrievalMode, setRetrievalMode] = useState<'vector' | 'fulltext' | 'hybrid'>('vector');
  const [topK, setTopK] = useState(5);
  const [scoreThresholdEnabled, setScoreThresholdEnabled] = useState(false);
  const [scoreThreshold, setScoreThreshold] = useState(0.5);
  const [semanticWeight, setSemanticWeight] = useState(0.7);

  const isVector = ragMode === 'vector';
  const totalSteps = isVector ? TOTAL_STEPS_VECTOR : TOTAL_STEPS_PAGEINDEX;
  const stepLabels = isVector
    ? ['Basic Info', 'RAG Mode', 'Index Method', 'Chunking', 'Retrieval', 'Review']
    : ['Basic Info', 'RAG Mode', 'Review'];

  const handleProviderChange = (provider: 'bedrock' | 'openai') => {
    setEmbeddingProvider(provider);
    setEmbeddingModel(provider === 'bedrock' ? 'amazon.titan-embed-text-v2:0' : 'text-embedding-3-small');
  };

  const handleCreate = async () => {
    setCreating(true);
    try {
      const settings: KBSettings = ragMode === 'vector' ? {
        rag_mode: 'vector', index_method: indexMethod, chunk_strategy: chunkStrategy,
        chunk_size: chunkSize, chunk_overlap: chunkOverlap,
        retrieval_mode: indexMethod === 'economical' ? 'fulltext' : retrievalMode,
        top_k: topK, score_threshold: scoreThresholdEnabled ? scoreThreshold : null,
        rerank_enabled: false, hybrid_semantic_weight: semanticWeight,
        embedding_provider: embeddingProvider, embedding_model: embeddingModel,
      } : ragMode === 'wiki' ? { rag_mode: 'wiki' } : ragMode === 'graph' ? { rag_mode: 'graph' } : ragMode === 'openkb' ? { rag_mode: 'openkb', pageindex_threshold: 20 } : { rag_mode: 'pageindex' };
      await createKb(name.trim(), description.trim() || undefined, settings);
      onCreated();
    } finally { setCreating(false); }
  };

  const renderStep = () => {
    if (step === 1) return (
      <div className="flex flex-col gap-4">
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1.5">Name <span className="text-red-500">*</span></label>
          <input autoFocus value={name} onChange={e => setName(e.target.value)} placeholder="e.g. Product Documentation"
            className="w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none focus:border-[var(--dm-primary)] focus:ring-2 focus:ring-blue-100 transition-all" />
        </div>
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1.5">Description <span className="text-slate-400">(optional)</span></label>
          <textarea value={description} onChange={e => setDescription(e.target.value)} rows={3}
            placeholder="Describe what documents this KB will contain…"
            className="w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none focus:border-[var(--dm-primary)] focus:ring-2 focus:ring-blue-100 transition-all resize-none" />
        </div>
      </div>
    );

    if (step === 2) return (
      <div className="flex flex-col gap-4">
        <p className="text-sm text-slate-600">Choose the retrieval method. <strong>This cannot be changed after creation.</strong></p>
        <div className="grid grid-cols-1 gap-3">
          {([
            { value: 'pageindex', icon: <Brain className="h-5 w-5 text-blue-600" />, bg: 'bg-blue-100', title: 'PageIndex', subtitle: 'Reasoning Mode', desc: 'LLM builds a hierarchical tree per document. Best for structured docs and precise section-level answers.', badge: 'No embedding cost', badgeCls: 'bg-blue-100 text-blue-700', selCls: 'border-[var(--dm-primary)] bg-blue-50 shadow-md', chkCls: 'bg-[var(--dm-primary)]' },
            { value: 'vector', icon: <Database className="h-5 w-5 text-emerald-600" />, bg: 'bg-emerald-100', title: 'Vector RAG', subtitle: 'Semantic Mode', desc: 'Documents chunked and embedded. Best for large collections with diverse topics.', badge: 'Embedding required', badgeCls: 'bg-amber-100 text-amber-700', selCls: 'border-emerald-500 bg-emerald-50 shadow-md', chkCls: 'bg-emerald-500' },
            { value: 'wiki', icon: <BookOpen className="h-5 w-5 text-violet-600" />, bg: 'bg-violet-100', title: 'Wiki', subtitle: 'Living Knowledge Base', desc: 'LLM builds and maintains cross-document wiki pages on entities, concepts, and processes. Topics compound as more documents arrive — the richer it gets over time.', badge: 'Best for growing libraries', badgeCls: 'bg-violet-100 text-violet-700', selCls: 'border-violet-500 bg-violet-50 shadow-md', chkCls: 'bg-violet-500' },
            { value: 'graph', icon: <Share2 className="h-5 w-5 text-orange-600" />, bg: 'bg-orange-100', title: 'Graph RAG', subtitle: 'Knowledge Graph', desc: 'Extracts entities and relationships into a connected graph. Best for relational questions — "how does X relate to Y?" and "what requires approval from Z?"', badge: 'Relationship-aware', badgeCls: 'bg-orange-100 text-orange-700', selCls: 'border-orange-500 bg-orange-50 shadow-md', chkCls: 'bg-orange-500' },
            { value: 'openkb', icon: <BookOpen className="h-5 w-5 text-teal-600" />, bg: 'bg-teal-100', title: 'OpenKB', subtitle: 'Compiled Wiki + PageIndex', desc: 'Compiles documents into a persistent, interlinked wiki with summaries, concept pages, and entity pages. Long PDFs (≥20 pages) use PageIndex tree indexing for precise page-range retrieval.', badge: 'Best for knowledge bases', badgeCls: 'bg-teal-100 text-teal-700', selCls: 'border-teal-500 bg-teal-50 shadow-md', chkCls: 'bg-teal-500' },
          ] as const).map(({ value, icon, bg, title, subtitle, desc, badge, badgeCls, selCls, chkCls }) => (
            <button key={value} type="button" onClick={() => setRagMode(value)}
              className={`relative flex items-start gap-4 rounded-xl border-2 p-4 text-left transition-all ${ragMode === value ? selCls : 'border-slate-200 bg-white hover:border-slate-300'}`}>
              {ragMode === value && (
                <div className={`absolute top-3 right-3 flex h-5 w-5 items-center justify-center rounded-full ${chkCls}`}>
                  <svg className="h-3 w-3 text-white" fill="currentColor" viewBox="0 0 20 20"><path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" /></svg>
                </div>
              )}
              <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg ${bg}`}>{icon}</div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-semibold text-slate-900">{title}</p>
                <p className="text-xs text-slate-500 mt-0.5 mb-1.5">{subtitle}</p>
                <p className="text-xs text-slate-600 leading-relaxed">{desc}</p>
                <span className={`mt-2 inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${badgeCls}`}>{badge}</span>
              </div>
            </button>
          ))}
        </div>
      </div>
    );

    if (isVector && step === 3) return (
      <div className="flex flex-col gap-4">
        <p className="text-sm text-slate-600">How should documents be indexed?</p>
        {[
          { value: 'high_quality', label: 'High Quality', desc: 'Semantic vector search using embedding model.' },
          { value: 'economical', label: 'Economical', desc: 'Full-text keyword search only. No embedding cost.' },
          { value: 'hybrid', label: 'Hybrid', desc: 'Vector + keyword with RRF merge.' },
        ].map(({ value, label, desc }) => (
          <label key={value} className={`flex items-start gap-3 rounded-xl border-2 p-4 cursor-pointer transition-all ${indexMethod === value ? 'border-[var(--dm-primary)] bg-blue-50' : 'border-slate-200 bg-white hover:border-slate-300'}`}>
            <input type="radio" name="indexMethod" value={value} checked={indexMethod === value} onChange={() => setIndexMethod(value as typeof indexMethod)} className="mt-0.5 accent-[var(--dm-primary)]" />
            <div><p className="text-sm font-medium text-slate-900">{label}</p><p className="text-xs text-slate-500 mt-0.5">{desc}</p></div>
          </label>
        ))}
        {indexMethod !== 'economical' && (
          <div className="flex flex-col gap-3 rounded-xl border border-slate-200 bg-slate-50 p-4">
            <p className="text-xs font-semibold text-slate-700 uppercase tracking-wide">Embedding</p>
            <select value={embeddingProvider} onChange={e => handleProviderChange(e.target.value as 'bedrock' | 'openai')}
              className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-[var(--dm-primary)]">
              <option value="bedrock">Amazon Bedrock (Titan Embed v2)</option>
              <option value="openai">OpenAI (text-embedding-3-small)</option>
            </select>
            <input value={embeddingModel} readOnly className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-500 outline-none" />
          </div>
        )}
      </div>
    );

    if (isVector && step === 4) return (
      <div className="flex flex-col gap-5">
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-2">Chunk Strategy</label>
          {[
            { value: 'recursive', label: 'Recursive (recommended)', desc: 'Splits hierarchically on paragraph/sentence boundaries.' },
            { value: 'parent_child', label: 'Parent-Child', desc: 'Large parent chunks with smaller child chunks.' },
          ].map(({ value, label, desc }) => (
            <label key={value} className={`flex items-start gap-3 rounded-xl border-2 p-3 cursor-pointer transition-all mb-2 ${chunkStrategy === value ? 'border-[var(--dm-primary)] bg-blue-50' : 'border-slate-200 bg-white hover:border-slate-300'}`}>
              <input type="radio" name="chunkStrategy" value={value} checked={chunkStrategy === value} onChange={() => setChunkStrategy(value as typeof chunkStrategy)} className="mt-0.5 accent-[var(--dm-primary)]" />
              <div><p className="text-sm font-medium text-slate-900">{label}</p><p className="text-xs text-slate-500">{desc}</p></div>
            </label>
          ))}
        </div>
        {[
          { label: 'Chunk Size', value: chunkSize, min: 200, max: 4000, step: 100, onChange: (v: number) => setChunkSize(v) },
          { label: 'Chunk Overlap', value: chunkOverlap, min: 0, max: 500, step: 25, onChange: (v: number) => setChunkOverlap(v) },
        ].map(({ label, value, min, max, step: s, onChange }) => (
          <div key={label}>
            <div className="flex items-center justify-between mb-2">
              <label className="text-sm font-medium text-slate-700">{label}</label>
              <span className="text-sm font-mono text-slate-600 bg-slate-100 px-2 py-0.5 rounded">{value}</span>
            </div>
            <input type="range" min={min} max={max} step={s} value={value} onChange={e => onChange(Number(e.target.value))} className="w-full accent-[var(--dm-primary)]" />
            <div className="flex justify-between text-xs text-slate-400 mt-1"><span>{min}</span><span>{max}</span></div>
          </div>
        ))}
      </div>
    );

    if (isVector && step === 5) return (
      <div className="flex flex-col gap-5">
        {indexMethod !== 'economical' && (
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-2">Retrieval Mode</label>
            {[
              { value: 'vector', label: 'Vector', desc: 'Pure semantic similarity search.' },
              { value: 'fulltext', label: 'Full-text', desc: 'Keyword-based search.' },
              { value: 'hybrid', label: 'Hybrid', desc: 'Combines vector + keyword with RRF.' },
            ].filter(({ value }) => indexMethod === 'high_quality' ? value !== 'fulltext' : true)
              .map(({ value, label, desc }) => (
                <label key={value} className={`flex items-start gap-3 rounded-xl border-2 p-3 cursor-pointer transition-all mb-2 ${retrievalMode === value ? 'border-[var(--dm-primary)] bg-blue-50' : 'border-slate-200 bg-white hover:border-slate-300'}`}>
                  <input type="radio" name="retrievalMode" value={value} checked={retrievalMode === value} onChange={() => setRetrievalMode(value as typeof retrievalMode)} className="mt-0.5 accent-[var(--dm-primary)]" />
                  <div><p className="text-sm font-medium text-slate-900">{label}</p><p className="text-xs text-slate-500">{desc}</p></div>
                </label>
              ))}
          </div>
        )}
        <div className="flex items-center justify-between">
          <div><label className="text-sm font-medium text-slate-700">Top-K Results</label><p className="text-xs text-slate-500">Chunks per query</p></div>
          <input type="number" min={1} max={20} value={topK} onChange={e => setTopK(Math.max(1, Math.min(20, Number(e.target.value))))}
            className="w-20 rounded-lg border border-slate-200 px-3 py-1.5 text-sm text-right outline-none focus:ring-2 focus:ring-[var(--dm-primary)]" />
        </div>
        <div className="flex flex-col gap-2">
          <label className="flex items-center gap-2 cursor-pointer">
            <input type="checkbox" checked={scoreThresholdEnabled} onChange={e => setScoreThresholdEnabled(e.target.checked)} className="rounded border-slate-300 accent-[var(--dm-primary)]" />
            <span className="text-sm font-medium text-slate-700">Enable Score Threshold</span>
          </label>
          {scoreThresholdEnabled && (
            <input type="number" min={0} max={1} step={0.05} value={scoreThreshold} onChange={e => setScoreThreshold(parseFloat(e.target.value))}
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-[var(--dm-primary)]" placeholder="0.0 – 1.0" />
          )}
        </div>
        {retrievalMode === 'hybrid' && (
          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="text-sm font-medium text-slate-700">Semantic Weight</label>
              <span className="text-sm font-mono text-slate-600 bg-slate-100 px-2 py-0.5 rounded">{semanticWeight.toFixed(2)}</span>
            </div>
            <input type="range" min={0} max={1} step={0.05} value={semanticWeight} onChange={e => setSemanticWeight(parseFloat(e.target.value))} className="w-full accent-[var(--dm-primary)]" />
            <div className="flex justify-between text-xs text-slate-400 mt-1"><span>← Keyword</span><span>Semantic →</span></div>
          </div>
        )}
      </div>
    );

    // Review
    return (
      <div className="flex flex-col gap-4">
        <p className="text-sm text-slate-600">Review your configuration before creating.</p>
        <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 flex flex-col gap-3">
          {([
            ['Name', name],
            description ? ['Description', description] : null,
            ['RAG Mode', null],
            ...(isVector ? [
              ['Index Method', indexMethod.replace('_', ' ')],
              indexMethod !== 'economical' ? ['Embedding', embeddingModel] : null,
              ['Chunk Strategy', chunkStrategy.replace('_', '-')],
              ['Chunk Size / Overlap', `${chunkSize} / ${chunkOverlap}`],
              ['Retrieval Mode', indexMethod === 'economical' ? 'fulltext' : retrievalMode],
              ['Top-K', String(topK)],
            ] : []),
          ] as (string[] | null)[]).filter(Boolean).map((row, i) => (
            <div key={i} className="flex justify-between items-center">
              <span className="text-xs font-semibold text-slate-500 uppercase tracking-wide">{row![0]}</span>
              {row![1] ? (
                <span className="text-sm text-slate-700 capitalize">{row![1]}</span>
              ) : <RagModeBadge ragMode={ragMode} />}
            </div>
          ))}
        </div>
      </div>
    );
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
      <div className="relative w-full max-w-lg rounded-2xl bg-white shadow-2xl flex flex-col max-h-[90vh]">
        <div className="flex items-center justify-between px-6 pt-6 pb-4 border-b border-slate-100">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">Create Knowledge Base</h2>
            <p className="text-xs text-slate-500 mt-0.5">{stepLabels[step - 1]}</p>
          </div>
          <button onClick={onClose} className="p-2 rounded-lg hover:bg-slate-100 text-slate-400 hover:text-slate-600 transition-colors">
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="flex items-center gap-1.5 px-6 py-3">
          {stepLabels.map((_, idx) => (
            <div key={idx} className={`flex-1 h-1.5 rounded-full transition-colors ${idx + 1 < step ? 'bg-[var(--dm-primary)]' : idx + 1 === step ? 'bg-[var(--dm-primary)] opacity-70' : 'bg-slate-200'}`} />
          ))}
        </div>
        <div className="flex-1 overflow-y-auto px-6 py-4">{renderStep()}</div>
        <div className="flex items-center justify-between px-6 py-4 border-t border-slate-100 bg-slate-50 rounded-b-2xl">
          <button type="button" onClick={() => step > 1 ? setStep(s => s - 1) : onClose()}
            className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-white transition-colors">
            {step > 1 ? 'Back' : 'Cancel'}
          </button>
          {step < totalSteps ? (
            <button type="button" disabled={step === 1 && !name.trim()} onClick={() => setStep(s => s + 1)}
              className="rounded-lg bg-[var(--dm-primary)] px-4 py-2 text-sm font-medium text-white hover:bg-[var(--dm-primary-dark)] disabled:opacity-50 transition-colors shadow-sm">
              Next
            </button>
          ) : (
            <button type="button" disabled={creating} onClick={handleCreate}
              className="rounded-lg bg-[var(--dm-primary)] px-5 py-2 text-sm font-medium text-white hover:bg-[var(--dm-primary-dark)] disabled:opacity-50 transition-colors shadow-sm">
              {creating ? 'Creating…' : 'Create'}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export function KnowledgeBases() {
  const { knowledgeBases, loadKnowledgeBases, loadDocuments, createKb, updateKb, deleteKb } = useDocuments();
  const [selectedKb, setSelectedKb] = useState<KnowledgeBase | null>(null);
  const [showWizard, setShowWizard] = useState(false);
  const [editingKb, setEditingKb] = useState<KnowledgeBase | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [search, setSearch] = useState('');

  useEffect(() => { loadKnowledgeBases(); }, []);

  const filteredKbs = search
    ? knowledgeBases.filter(kb =>
        kb.name.toLowerCase().includes(search.toLowerCase()) ||
        (kb.description || '').toLowerCase().includes(search.toLowerCase()))
    : knowledgeBases;

  const handleDelete = async (kb: KnowledgeBase, e?: React.MouseEvent) => {
    e?.stopPropagation();
    if (!confirm(`Delete "${kb.name}"? This will permanently delete all documents and files.`)) return;
    setDeleting(kb.id);
    try {
      await deleteKb(kb.id);
      if (selectedKb?.id === kb.id) setSelectedKb(null);
    } catch (error) {
      alert(`Failed to delete: ${error instanceof Error ? error.message : 'Unknown error'}`);
    } finally {
      setDeleting(null);
    }
  };

  const handleSaveEdit = async (name: string, desc: string) => {
    if (!editingKb) return;
    await updateKb(editingKb.id, name, desc || undefined);
    loadKnowledgeBases();
  };

  return (
    <>
      {showWizard && (
        <KbCreationWizard
          onClose={() => setShowWizard(false)}
          onCreated={() => { setShowWizard(false); loadKnowledgeBases(); }}
          createKb={createKb}
        />
      )}
      {editingKb && (
        <EditKbModal kb={editingKb} onClose={() => setEditingKb(null)} onSave={handleSaveEdit} />
      )}

      <div className="p-6 max-w-7xl mx-auto">
        {selectedKb ? (
          <KbDetail
            kb={selectedKb}
            onBack={() => setSelectedKb(null)}
            onRefresh={loadKnowledgeBases}
            onDeleteKb={(kb) => handleDelete(kb)}
          />
        ) : (
          <>
            <div className="flex items-center justify-between mb-6">
              <div>
                <h2 className="text-2xl font-semibold text-slate-900">Knowledge Bases</h2>
                <p className="text-sm text-slate-500 mt-0.5">{knowledgeBases.length} knowledge base{knowledgeBases.length !== 1 ? 's' : ''}</p>
              </div>
              <button onClick={() => setShowWizard(true)}
                className="flex items-center gap-2 rounded-xl bg-[var(--dm-primary)] px-4 py-2.5 text-sm font-medium text-white hover:bg-[var(--dm-primary-dark)] transition-colors shadow-sm">
                <Plus className="h-4 w-4" />
                Create Knowledge Base
              </button>
            </div>

            {knowledgeBases.length > 0 && (
              <div className="relative mb-5 max-w-xs">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
                <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search knowledge bases…"
                  className="w-full rounded-lg border border-slate-200 pl-9 pr-3 py-2 text-sm outline-none focus:border-[var(--dm-primary)] focus:ring-2 focus:ring-blue-100 transition-all" />
              </div>
            )}

            {filteredKbs.length === 0 ? (
              <div className="flex flex-col items-center justify-center gap-4 rounded-2xl border border-dashed border-slate-300 bg-slate-50 py-24 text-center">
                <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-blue-100">
                  <BookOpen className="h-8 w-8 text-blue-600" />
                </div>
                <div>
                  <p className="text-base font-semibold text-slate-700">
                    {search ? 'No knowledge bases match your search' : 'No knowledge bases yet'}
                  </p>
                  <p className="text-sm text-slate-500 mt-1">
                    {search ? 'Try a different search term' : 'Create your first knowledge base to start uploading documents'}
                  </p>
                </div>
                {!search && (
                  <button onClick={() => setShowWizard(true)}
                    className="flex items-center gap-2 rounded-xl bg-[var(--dm-primary)] px-5 py-2.5 text-sm font-medium text-white hover:bg-[var(--dm-primary-dark)] transition-colors shadow-sm">
                    <Plus className="h-4 w-4" />
                    Create Knowledge Base
                  </button>
                )}
              </div>
            ) : (
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                {filteredKbs.map(kb => (
                  <KbCard
                    key={kb.id}
                    kb={kb}
                    onSelect={() => { setSelectedKb(kb); loadDocuments(kb.id); }}
                    onEdit={(e) => { e.stopPropagation(); setEditingKb(kb); }}
                    onDelete={(e) => handleDelete(kb, e)}
                    deleting={deleting === kb.id}
                  />
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </>
  );
}
