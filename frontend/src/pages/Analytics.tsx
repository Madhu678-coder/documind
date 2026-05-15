import { type FormEvent, useEffect, useState } from 'react';
import { BarChart2, TrendingDown, MessageSquare, Zap } from 'lucide-react';
import { apiClient } from '../api/client';
import { getEvalConfig, updateEvalConfig } from '../api/eval';
import { QualityMonitor } from '../components/insights/QualityMonitor';
import type { EvalConfig } from '../types';

// In a real app this would come from the auth store
const IS_ADMIN = true;

// ── Analytics types ──────────────────────────────────────────────────────────

interface TopQuery {
  kb_id: string;
  kb_name: string;
  query_text: string;
  count: number;
}

interface ConfidenceBucket {
  range: string;
  count: number;
}

interface LowConfidenceQuery {
  message_id: string;
  session_id: string;
  query_text: string;
  confidence_score: number;
  kb_name: string;
  created_at: string;
}

interface AnalyticsData {
  topQueries: TopQuery[];
  confidenceBuckets: ConfidenceBucket[];
  lowConfidenceQueries: LowConfidenceQuery[];
}

function emptyAnalytics(): AnalyticsData {
  return { topQueries: [], confidenceBuckets: [], lowConfidenceQueries: [] };
}

// ── Confidence Bar Chart ─────────────────────────────────────────────────────

function ConfidenceBarChart({ buckets }: { buckets: ConfidenceBucket[] }) {
  if (!buckets.length)
    return <p className="text-sm text-slate-400 py-4">No data available.</p>;

  const W = 480; const H = 160;
  const PAD = { top: 16, right: 20, bottom: 40, left: 44 };
  const cW = W - PAD.left - PAD.right;
  const cH = H - PAD.top - PAD.bottom;
  const maxCount = Math.max(...buckets.map((b) => b.count), 1);
  const barW = cW / buckets.length;
  const barColors = ['#ef4444', '#f97316', '#f59e0b', '#84cc16', '#22c55e'];

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Answer confidence distribution">
      {[0, 0.25, 0.5, 0.75, 1].map((t) => {
        const y = PAD.top + (1 - t) * cH;
        return (
          <g key={t}>
            <line x1={PAD.left} y1={y} x2={W - PAD.right} y2={y} stroke="#e2e8f0" strokeWidth="1" />
            <text x={PAD.left - 6} y={y + 4} textAnchor="end" fontSize="10" fill="#94a3b8">
              {Math.round(t * maxCount)}
            </text>
          </g>
        );
      })}
      {buckets.map((bucket, i) => {
        const bH = (bucket.count / maxCount) * cH;
        const x = PAD.left + i * barW;
        const y = PAD.top + cH - bH;
        return (
          <g key={bucket.range}>
            <rect x={x + 4} y={y} width={barW - 8} height={bH} fill={barColors[i] ?? 'var(--dm-primary)'} fillOpacity="0.85" rx="3">
              <title>{`${bucket.range}: ${bucket.count} queries`}</title>
            </rect>
            {bH > 14 && (
              <text x={x + barW / 2} y={y + 12} textAnchor="middle" fontSize="10" fill="white" fontWeight="600">
                {bucket.count}
              </text>
            )}
            <text x={x + barW / 2} y={H - 8} textAnchor="middle" fontSize="10" fill="#64748b">
              {bucket.range}
            </text>
          </g>
        );
      })}
      <line x1={PAD.left} y1={PAD.top} x2={PAD.left} y2={PAD.top + cH} stroke="#cbd5e1" strokeWidth="1" />
      <line x1={PAD.left} y1={PAD.top + cH} x2={W - PAD.right} y2={PAD.top + cH} stroke="#cbd5e1" strokeWidth="1" />
      <text x={10} y={PAD.top + cH / 2} textAnchor="middle" fontSize="10" fill="#94a3b8"
        transform={`rotate(-90, 10, ${PAD.top + cH / 2})`}>
        Queries
      </text>
    </svg>
  );
}

// ── Chat Analytics Section ───────────────────────────────────────────────────

function ChatAnalytics() {
  const [data, setData] = useState<AnalyticsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [errorDetails, setErrorDetails] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function fetchAnalytics() {
      setLoading(true);
      try {
        const [topRes, distRes, lowRes] = await Promise.allSettled([
          apiClient.get<{ queries: TopQuery[] }>('/eval/analytics/top-queries?limit=10'),
          apiClient.get<{ buckets: ConfidenceBucket[] }>('/eval/analytics/confidence-distribution'),
          apiClient.get<{ queries: LowConfidenceQuery[] }>('/eval/analytics/low-confidence?limit=10'),
        ]);
        if (cancelled) return;
        setData({
          topQueries: topRes.status === 'fulfilled' ? topRes.value.data.queries : [],
          confidenceBuckets: distRes.status === 'fulfilled' ? distRes.value.data.buckets : [],
          lowConfidenceQueries: lowRes.status === 'fulfilled' ? lowRes.value.data.queries : [],
        });
      } catch {
        if (!cancelled) {
          setData(emptyAnalytics());
          setErrorDetails('Failed to fetch analytics. Check backend connection.');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    fetchAnalytics();
    return () => { cancelled = true; };
  }, []);

  if (loading) {
    return (
      <section className="rounded-xl border border-slate-200 bg-white p-6 animate-pulse">
        <div className="h-6 w-48 rounded bg-slate-200 mb-6" />
        <div className="space-y-3">
          <div className="h-4 w-full rounded bg-slate-100" />
          <div className="h-4 w-5/6 rounded bg-slate-100" />
          <div className="h-4 w-4/6 rounded bg-slate-100" />
        </div>
      </section>
    );
  }

  if (!data) return null;

  const maxCount = Math.max(...data.topQueries.map((q) => q.count), 1);

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-6 flex flex-col gap-6 shadow-sm">
      <div className="flex items-center gap-2">
        <MessageSquare className="h-5 w-5 text-[var(--dm-primary)]" />
        <h3 className="text-lg font-semibold text-slate-900">Chat Analytics</h3>
      </div>

      {errorDetails && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          {errorDetails}
        </div>
      )}

      {/* Top Queries */}
      <div>
        <h4 className="text-sm font-semibold text-slate-700 mb-3">Top 10 Queries by Knowledge Base</h4>
        <div className="overflow-x-auto rounded-lg border border-slate-200">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-slate-50 text-left">
                <th className="px-4 py-3 text-xs font-semibold text-slate-600 uppercase tracking-wide">#</th>
                <th className="px-4 py-3 text-xs font-semibold text-slate-600 uppercase tracking-wide">Knowledge Base</th>
                <th className="px-4 py-3 text-xs font-semibold text-slate-600 uppercase tracking-wide">Query</th>
                <th className="px-4 py-3 text-xs font-semibold text-slate-600 uppercase tracking-wide text-right">Count</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {data.topQueries.length === 0 ? (
                <tr><td colSpan={4} className="px-4 py-6 text-center text-sm text-slate-400">No queries yet.</td></tr>
              ) : data.topQueries.map((q, i) => (
                <tr key={`${q.kb_id}-${i}`} className="hover:bg-slate-50 transition-colors">
                  <td className="px-4 py-3 text-slate-500 tabular-nums">{i + 1}</td>
                  <td className="px-4 py-3">
                    <span className="inline-block rounded-md px-2.5 py-1 text-xs font-medium bg-blue-50 text-blue-700 border border-blue-200">
                      {q.kb_name}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-slate-700 max-w-xs truncate" title={q.query_text}>{q.query_text}</td>
                  <td className="px-4 py-3 text-right">
                    <div className="flex items-center justify-end gap-2">
                      <div className="h-1.5 rounded-full bg-slate-100 w-16 overflow-hidden">
                        <div className="h-full rounded-full" style={{ width: `${(q.count / maxCount) * 100}%`, background: 'var(--dm-primary)' }} />
                      </div>
                      <span className="tabular-nums font-medium text-slate-700 w-6 text-right">{q.count}</span>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Confidence Distribution */}
      <div>
        <h4 className="text-sm font-semibold text-slate-600 mb-3">Answer Confidence Distribution</h4>
        <div className="rounded-lg border border-slate-100 bg-slate-50 p-4">
          <ConfidenceBarChart buckets={data.confidenceBuckets} />
          <p className="text-xs text-slate-400 mt-2 text-center">Confidence score ranges (0 = low, 1 = high)</p>
        </div>
      </div>

      {/* Low Confidence Queries */}
      <div>
        <h4 className="text-sm font-semibold text-slate-600 mb-3">Low-Confidence Queries</h4>
        {data.lowConfidenceQueries.length === 0 ? (
          <p className="text-sm text-slate-400 py-2">No low-confidence queries found.</p>
        ) : (
          <ul className="space-y-2">
            {data.lowConfidenceQueries.map((q) => {
              const pct = Math.round(q.confidence_score * 100);
              const color = pct < 30 ? '#ef4444' : pct < 50 ? '#f97316' : '#f59e0b';
              return (
                <li key={q.message_id} className="flex items-start gap-3 rounded-lg border border-slate-100 bg-slate-50 px-4 py-3">
                  <span
                    className="shrink-0 mt-0.5 inline-flex items-center justify-center w-12 h-6 rounded-full text-xs font-bold"
                    style={{ background: `${color}20`, color }}
                  >
                    {pct}%
                  </span>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-slate-700 truncate" title={q.query_text}>{q.query_text}</p>
                    <p className="text-xs text-slate-400 mt-0.5">
                      {q.kb_name} · {new Date(q.created_at).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
                    </p>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </section>
  );
}

// ── Eval Thresholds ──────────────────────────────────────────────────────────

function ThresholdField({ label, value, onChange }: { label: string; value: number; onChange: (v: number) => void }) {
  return (
    <div className="flex items-center justify-between gap-4">
      <label className="text-sm text-slate-700">{label}</label>
      <input
        type="number" min={0} max={1} step={0.01}
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        className="w-24 rounded-lg border border-slate-200 px-3 py-1.5 text-sm text-right outline-none focus:ring-2 focus:ring-[var(--dm-primary)]"
      />
    </div>
  );
}

function EvalThresholds() {
  const [config, setConfig] = useState<EvalConfig | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    getEvalConfig().then(setConfig).catch(() => {});
  }, []);

  const handleChange = (key: keyof EvalConfig, value: number | boolean) => {
    setConfig((prev) => prev ? { ...prev, [key]: value } : prev);
  };

  const handleSave = async (e: FormEvent) => {
    e.preventDefault();
    if (!config) return;
    setSaving(true);
    try {
      const updated = await updateEvalConfig(config);
      setConfig(updated);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } finally {
      setSaving(false);
    }
  };

  if (!config) return null;

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="flex items-center gap-2 mb-4">
        <Zap className="h-5 w-5 text-amber-500" />
        <h3 className="text-lg font-semibold text-slate-900">Evaluation Thresholds</h3>
      </div>
      <form onSubmit={handleSave} className="flex flex-col gap-4">
        <ThresholdField label="Faithfulness threshold" value={config.faithfulness_threshold} onChange={(v) => handleChange('faithfulness_threshold', v)} />
        <ThresholdField label="Answer relevancy threshold" value={config.answer_relevancy_threshold} onChange={(v) => handleChange('answer_relevancy_threshold', v)} />
        <ThresholdField label="Contextual precision threshold" value={config.contextual_precision_threshold} onChange={(v) => handleChange('contextual_precision_threshold', v)} />
        <ThresholdField label="Contextual recall threshold" value={config.contextual_recall_threshold} onChange={(v) => handleChange('contextual_recall_threshold', v)} />
        <ThresholdField label="Hallucination threshold (max)" value={config.hallucination_threshold} onChange={(v) => handleChange('hallucination_threshold', v)} />
        <label className="flex items-center gap-2 text-sm text-slate-700 cursor-pointer">
          <input type="checkbox" checked={config.multi_turn_enabled} onChange={(e) => handleChange('multi_turn_enabled', e.target.checked)} className="rounded border-slate-300 text-[var(--dm-primary)] focus:ring-[var(--dm-primary)]" />
          Enable multi-turn evaluation
        </label>
        <div className="flex items-center gap-3 pt-2">
          <button type="submit" disabled={saving} className="rounded-lg bg-[var(--dm-primary)] px-4 py-2 text-sm font-medium text-white hover:bg-[var(--dm-primary-dark)] disabled:opacity-50 transition-colors shadow-sm">
            {saving ? 'Saving…' : 'Save'}
          </button>
          {saved && <span className="text-sm text-green-600 font-medium">Saved</span>}
        </div>
      </form>
    </section>
  );
}

// ── Main Analytics Page ──────────────────────────────────────────────────────

export function Analytics() {
  return (
    <div className="p-6 max-w-5xl flex flex-col gap-6">
      <div className="flex items-center gap-3">
        <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-violet-100">
          <BarChart2 className="h-5 w-5 text-violet-600" />
        </div>
        <div>
          <h2 className="text-2xl font-semibold text-slate-900">Analytics</h2>
          <p className="text-sm text-slate-500">DeepEval quality metrics and chat analytics</p>
        </div>
      </div>

      {IS_ADMIN && <EvalThresholds />}
      {IS_ADMIN && <QualityMonitor faithfulnessThreshold={0.85} />}
      {IS_ADMIN && <ChatAnalytics />}
      {!IS_ADMIN && (
        <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-slate-300 bg-slate-50 py-16 text-center">
          <TrendingDown className="h-12 w-12 text-slate-400" />
          <p className="text-sm font-medium text-slate-600">Analytics are admin-only</p>
        </div>
      )}
    </div>
  );
}
