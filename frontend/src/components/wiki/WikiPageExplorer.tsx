import { useEffect, useState } from 'react';
import { BookOpen, ChevronDown, ChevronUp, FileText, Link, Loader2 } from 'lucide-react';
import { getWikiPages, getWikiPage } from '../../api/wiki';
import type { WikiPage, WikiPageDetail } from '../../types';

const PAGE_TYPE_STYLES: Record<string, { bg: string; text: string; label: string }> = {
  entity:  { bg: 'bg-blue-100',   text: 'text-blue-700',   label: 'Entity'  },
  concept: { bg: 'bg-amber-100',  text: 'text-amber-700',  label: 'Concept' },
  process: { bg: 'bg-green-100',  text: 'text-green-700',  label: 'Process' },
  event:   { bg: 'bg-red-100',    text: 'text-red-700',    label: 'Event'   },
  general: { bg: 'bg-slate-100',  text: 'text-slate-700',  label: 'General' },
};

function getPageTypeStyle(pageType: string) {
  return PAGE_TYPE_STYLES[pageType] ?? PAGE_TYPE_STYLES.general;
}

function formatRelativeDate(iso: string): string {
  if (!iso) return '';
  const d = new Date(iso);
  const now = new Date();
  const diff = Math.floor((now.getTime() - d.getTime()) / 1000);
  if (diff < 60) return 'just now';
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

// ── Simple markdown renderer (headers, bold, bullets, blockquotes) ─────────────
function MarkdownContent({ content, onNavigate }: { content: string; onNavigate?: (title: string) => void }) {
  const lines = content.split('\n');
  const elements: React.ReactNode[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (line.startsWith('## ')) {
      elements.push(<h3 key={i} className="text-sm font-semibold text-slate-800 mt-4 mb-1">{line.slice(3)}</h3>);
    } else if (line.startsWith('# ')) {
      elements.push(<h2 key={i} className="text-base font-semibold text-slate-900 mt-4 mb-1">{line.slice(2)}</h2>);
    } else if (line.startsWith('> ')) {
      elements.push(
        <blockquote key={i} className="border-l-4 border-amber-400 bg-amber-50 px-3 py-2 text-xs text-amber-800 rounded my-2">
          {line.slice(2)}
        </blockquote>
      );
    } else if (line.startsWith('- ') || line.startsWith('* ')) {
      elements.push(
        <li key={i} className="ml-4 text-xs text-slate-600 list-disc">
          <InlineMarkdown text={line.slice(2)} onNavigate={onNavigate} />
        </li>
      );
    } else if (line.trim() === '') {
      elements.push(<div key={i} className="h-2" />);
    } else {
      elements.push(
        <p key={i} className="text-xs text-slate-600 leading-relaxed">
          <InlineMarkdown text={line} onNavigate={onNavigate} />
        </p>
      );
    }
    i++;
  }
  return <div className="space-y-0.5">{elements}</div>;
}

function InlineMarkdown({ text, onNavigate }: { text: string; onNavigate?: (title: string) => void }) {
  // Render **bold** and [[wikilinks]] inline
  const parts = text.split(/(\*\*[^*]+\*\*|\[\[[^\]]+\]\])/g);
  return (
    <>
      {parts.map((part, idx) =>
        part.startsWith('**') && part.endsWith('**')
          ? <strong key={idx} className="font-semibold text-slate-800">{part.slice(2, -2)}</strong>
          : part.startsWith('[[') && part.endsWith(']]')
            ? <button key={idx} onClick={() => onNavigate?.(part.slice(2, -2))} className="text-violet-600 font-medium hover:text-violet-800 hover:underline cursor-pointer">{part.slice(2, -2)}</button>
            : <span key={idx}>{part}</span>
      )}
    </>
  );
}

// ── Single wiki page card ─────────────────────────────────────────────────────
function WikiPageCard({ page, kbId, onNavigate }: { page: WikiPage; kbId: string; onNavigate?: (title: string) => void }) {
  const [expanded, setExpanded] = useState(false);
  const [detail, setDetail] = useState<WikiPageDetail | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);

  const typeStyle = getPageTypeStyle(page.page_type);

  const handleExpand = async () => {
    if (!expanded && !detail) {
      setLoadingDetail(true);
      try {
        const { data } = await getWikiPage(kbId, page.id);
        setDetail(data);
      } catch { /* ignore */ } finally {
        setLoadingDetail(false);
      }
    }
    setExpanded(v => !v);
  };

  return (
    <div className="rounded-xl border border-slate-200 bg-white shadow-sm overflow-hidden">
      {/* Card header */}
      <div className="px-4 py-3 flex items-start gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium ${typeStyle.bg} ${typeStyle.text}`}>
              {typeStyle.label}
            </span>
          </div>
          <p className="text-sm font-semibold text-slate-900 truncate">{page.title}</p>
          {page.summary && (
            <p className="text-xs text-slate-500 mt-0.5 line-clamp-2">{page.summary}</p>
          )}
        </div>
        <button
          onClick={handleExpand}
          className="flex-shrink-0 p-1 rounded-lg hover:bg-slate-100 text-slate-400 hover:text-slate-600 transition-colors"
          title={expanded ? 'Collapse' : 'Expand'}
        >
          {loadingDetail
            ? <Loader2 className="h-4 w-4 animate-spin" />
            : expanded
              ? <ChevronUp className="h-4 w-4" />
              : <ChevronDown className="h-4 w-4" />}
        </button>
      </div>

      {/* Card footer */}
      <div className="px-4 pb-3 flex items-center gap-4 text-xs text-slate-400">
        <span className="flex items-center gap-1">
          <FileText className="h-3 w-3" />
          {page.source_doc_count} {page.source_doc_count === 1 ? 'source' : 'sources'}
        </span>
        {page.related_titles.length > 0 && (
          <span className="flex items-center gap-1">
            <Link className="h-3 w-3" />
            {page.related_titles.length} related
          </span>
        )}
        <span className="ml-auto">{formatRelativeDate(page.updated_at)}</span>
      </div>

      {/* Expanded content */}
      {expanded && detail && (
        <div className="border-t border-slate-100 px-4 py-4">
          <MarkdownContent content={detail.content} onNavigate={onNavigate} />
          {detail.related_titles.length > 0 && (
            <div className="mt-4">
              <p className="text-xs font-medium text-slate-500 mb-2">Related pages</p>
              <div className="flex flex-wrap gap-1.5">
                {detail.related_titles.map(title => (
                  <button
                    key={title}
                    onClick={() => onNavigate?.(title)}
                    className="px-2.5 py-1 rounded-md text-xs font-medium bg-violet-50 text-violet-700 border border-violet-200 hover:bg-violet-100 hover:border-violet-300 cursor-pointer transition-colors"
                  >
                    {title}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Main explorer ─────────────────────────────────────────────────────────────
interface WikiPageExplorerProps {
  kbId: string;
  /** When set, only shows pages sourced from this document */
  filterDocId?: string;
}

export function WikiPageExplorer({ kbId, filterDocId }: WikiPageExplorerProps) {
  const [pages, setPages] = useState<WikiPage[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [highlightTitle, setHighlightTitle] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getWikiPages(kbId, filterDocId)
      .then(({ data }) => {
        if (cancelled) return;
        setPages(data);
      })
      .catch(() => {
        if (!cancelled) setError('Failed to load wiki pages.');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [kbId, filterDocId]);

  const handleNavigate = (title: string) => {
    setHighlightTitle(title);
    // Scroll to the target card
    setTimeout(() => {
      const el = document.getElementById(`wiki-page-${title.replace(/\s+/g, '-').toLowerCase()}`);
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'center' });
        // Flash highlight
        el.classList.add('ring-2', 'ring-violet-400');
        setTimeout(() => {
          el.classList.remove('ring-2', 'ring-violet-400');
          setHighlightTitle(null);
        }, 2000);
      }
    }, 100);
  };

  const displayPages = pages;

  if (loading) {
    return (
      <div className="space-y-3">
        {[1, 2, 3].map(i => (
          <div key={i} className="animate-pulse h-20 rounded-xl bg-slate-100" />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-600">
        {error}
      </div>
    );
  }

  if (displayPages.length === 0) {
    return (
      <div className="flex flex-col items-center gap-3 py-10 text-center">
        <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-violet-100">
          <BookOpen className="h-6 w-6 text-violet-500" />
        </div>
        <div>
          <p className="text-sm font-medium text-slate-700">No wiki pages yet</p>
          <p className="text-xs text-slate-400 mt-1">
            {filterDocId
              ? 'No wiki pages were extracted from this document.'
              : 'Add documents to start building the wiki. Topics compound as more documents arrive.'}
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <p className="text-xs text-slate-400">
          {displayPages.length} {displayPages.length === 1 ? 'page' : 'pages'} — click to expand content
        </p>
      </div>
      {displayPages.map(page => (
        <div key={page.id} id={`wiki-page-${page.title.replace(/\s+/g, '-').toLowerCase()}`} className="transition-all duration-300">
          <WikiPageCard page={page} kbId={kbId} onNavigate={handleNavigate} />
        </div>
      ))}
    </div>
  );
}
