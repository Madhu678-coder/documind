import { useEffect, useState } from 'react';
import { fetchDocumentInsights, type DocumentInsights, type KeyEntities } from '../../api/insights';

// ── Types ──────────────────────────────────────────────────────────────────────

interface DocumentSummaryProps {
  docId: string;
}

// ── Helpers ────────────────────────────────────────────────────────────────────

function parseBullets(summary: string): string[] {
  return summary
    .split('\n')
    .map((line) => line.replace(/^[-•*]\s*/, '').trim())
    .filter(Boolean);
}

// ── Skeleton ───────────────────────────────────────────────────────────────────

function Skeleton() {
  return (
    <div
      className="rounded-xl border border-slate-200 bg-white p-6 space-y-6 animate-pulse shadow-sm"
      aria-busy="true"
      aria-label="Loading document insights"
    >
      {/* header */}
      <div className="h-6 w-48 rounded bg-slate-200" />

      {/* summary bullets */}
      <div className="space-y-2">
        {[...Array(5)].map((_, i) => (
          <div key={i} className="h-4 rounded bg-slate-100" style={{ width: `${75 + (i % 3) * 8}%` }} />
        ))}
      </div>

      {/* entities */}
      <div className="space-y-3">
        <div className="h-4 w-24 rounded bg-slate-200" />
        <div className="flex flex-wrap gap-2">
          {[...Array(6)].map((_, i) => (
            <div key={i} className="h-6 w-20 rounded-full bg-slate-100" />
          ))}
        </div>
      </div>

      {/* tags */}
      <div className="flex flex-wrap gap-2">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="h-6 w-16 rounded-full bg-slate-100" />
        ))}
      </div>
    </div>
  );
}

// ── EntityChipGroup ────────────────────────────────────────────────────────────

interface EntityChipGroupProps {
  label: string;
  items: string[];
}

function EntityChipGroup({ label, items }: EntityChipGroupProps) {
  if (!items.length) return null;
  return (
    <div className="space-y-1.5">
      <span className="text-xs font-semibold uppercase tracking-wide text-slate-600">{label}</span>
      <div className="flex flex-wrap gap-2">
        {items.map((item) => (
          <span
            key={item}
            className="inline-flex items-center px-2.5 py-1 rounded-md text-xs font-medium bg-blue-50 text-blue-700 border border-blue-200"
          >
            {item}
          </span>
        ))}
      </div>
    </div>
  );
}

// ── ComplexityBar ──────────────────────────────────────────────────────────────

function ComplexityBar({ score }: { score: number }) {
  const pct = Math.round(Math.min(Math.max(score, 0), 1) * 100);
  const label = pct < 34 ? 'Low' : pct < 67 ? 'Medium' : 'High';
  const barColor = pct < 34 ? '#22c55e' : pct < 67 ? '#f59e0b' : '#ef4444';

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between text-xs text-slate-600">
        <span className="font-semibold uppercase tracking-wide">Complexity</span>
        <span className="font-semibold" style={{ color: barColor }}>
          {label} ({pct}%)
        </span>
      </div>
      <div className="h-2 w-full rounded-full bg-slate-100 overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{ width: `${pct}%`, background: barColor }}
          role="progressbar"
          aria-valuenow={pct}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label={`Complexity: ${label}`}
        />
      </div>
    </div>
  );
}

// ── DocumentSummary ────────────────────────────────────────────────────────────

export function DocumentSummary({ docId }: DocumentSummaryProps) {
  const [data, setData] = useState<DocumentInsights | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    fetchDocumentInsights(docId)
      .then((res) => {
        if (!cancelled) {
          setData(res);
          setLoading(false);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err?.response?.data?.detail ?? err?.message ?? 'Failed to load insights.');
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [docId]);

  if (loading) return <Skeleton />;

  if (error) {
    return (
      <div
        className="rounded-xl border border-red-200 bg-red-50 p-6 text-sm text-red-700 shadow-sm"
        role="alert"
      >
        <p className="font-semibold mb-1">Could not load insights</p>
        <p className="text-red-600">{error}</p>
      </div>
    );
  }

  if (!data) return null;

  if (data.rag_mode !== 'pageindex') {
    return (
      <div className="rounded-xl border border-slate-200 bg-white p-6 text-sm text-slate-500 shadow-sm">
        Insights are not available for Vector RAG documents in this view.
      </div>
    );
  }

  const bullets = data.executive_summary ? parseBullets(data.executive_summary) : [];
  const entities: KeyEntities = data.key_entities ?? {};

  return (
    <div className="rounded-xl border border-slate-200 bg-white overflow-hidden shadow-sm">
      {/* Header */}
      <div className="px-6 py-4 border-b border-slate-200 bg-slate-50">
        <h2 className="text-lg font-semibold text-slate-900">
          Document Insights
        </h2>
      </div>

      <div className="px-6 py-5 space-y-6">
        {/* Executive Summary */}
        {bullets.length > 0 && (
          <section aria-labelledby="exec-summary-heading">
            <h3
              id="exec-summary-heading"
              className="text-sm font-semibold uppercase tracking-wide text-slate-600 mb-3"
            >
              Executive Summary
            </h3>
            <ul className="space-y-2.5">
              {bullets.map((bullet, i) => (
                <li key={i} className="flex items-start gap-2.5 text-sm text-slate-700 leading-relaxed">
                  <span
                    className="mt-1.5 shrink-0 w-1.5 h-1.5 rounded-full bg-[var(--dm-primary)]"
                    aria-hidden="true"
                  />
                  {bullet}
                </li>
              ))}
            </ul>
          </section>
        )}

        {/* Key Entities */}
        {data.key_entities && (
          <section aria-labelledby="entities-heading">
            <h3
              id="entities-heading"
              className="text-sm font-semibold uppercase tracking-wide text-slate-600 mb-3"
            >
              Key Entities
            </h3>
            <div className="space-y-3">
              <EntityChipGroup label="People" items={entities.people ?? []} />
              <EntityChipGroup label="Organizations" items={entities.organizations ?? []} />
              <EntityChipGroup label="Dates" items={entities.dates ?? []} />
              <EntityChipGroup label="Amounts" items={entities.amounts ?? []} />
            </div>
          </section>
        )}

        {/* Document Tags */}
        {data.document_tags && data.document_tags.length > 0 && (
          <section aria-labelledby="tags-heading">
            <h3
              id="tags-heading"
              className="text-sm font-semibold uppercase tracking-wide text-slate-600 mb-3"
            >
              Tags
            </h3>
            <div className="flex flex-wrap gap-2">
              {data.document_tags.map((tag) => (
                <span
                  key={tag}
                  className="inline-flex items-center px-3 py-1 rounded-md text-xs font-medium bg-amber-100 text-amber-800 border border-amber-200"
                >
                  {tag}
                </span>
              ))}
            </div>
          </section>
        )}

        {/* Complexity Score */}
        {data.complexity_score !== null && data.complexity_score !== undefined && (
          <section aria-labelledby="complexity-heading">
            <ComplexityBar score={data.complexity_score} />
          </section>
        )}
      </div>
    </div>
  );
}
