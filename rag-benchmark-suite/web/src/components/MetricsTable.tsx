import type { ModeResult } from "../types";
import MetricBar from "./MetricBar";
import StatusBadge from "./StatusBadge";

const THRESHOLDS = {
  faithfulness: 0.85,
  answer_relevancy: 0.8,
  contextual_precision: 0.75,
  contextual_recall: 0.75,
  hallucination: 0.15,
};

function modeLabel(mr: ModeResult): string {
  return mr.retrieval_mode ? `${mr.rag_mode} · ${mr.retrieval_mode}` : mr.rag_mode;
}

function formatBytes(bytes: number | null | undefined): string {
  if (!bytes) return "—";
  const mb = bytes / (1024 * 1024);
  return mb >= 1 ? `${mb.toFixed(1)} MB` : `${Math.round(bytes / 1024)} KB`;
}

function formatRatio(value: number | null | undefined): string {
  return value !== null && value !== undefined ? value.toFixed(2) : "—";
}

export default function MetricsTable({ modeResults }: { modeResults: ModeResult[] }) {
  return (
    <table className="metrics-table">
      <thead>
        <tr>
          <th>Mode</th>
          <th>Status</th>
          <th>Ingested</th>
          <th>Storage</th>
          <th>Faithfulness ≥ .85</th>
          <th>Relevancy ≥ .80</th>
          <th>Ctx Precision ≥ .75</th>
          <th>Ctx Recall ≥ .75</th>
          <th>Hallucination ≤ .15</th>
          <th>Pass rate</th>
          <th>Unanswerable handled</th>
          <th>Citation P / R</th>
          <th>p50 / p95 latency</th>
        </tr>
      </thead>
      <tbody>
        {modeResults.map((mr) => (
          <tr key={mr.id}>
            <td>
              <strong>{modeLabel(mr)}</strong>
            </td>
            <td>
              <StatusBadge status={mr.status} />
            </td>
            <td>
              {mr.documents_ingested}
              {mr.documents_failed > 0 ? ` (${mr.documents_failed} failed)` : ""}
            </td>
            <td>{formatBytes(mr.total_size_bytes)}</td>
            <td>
              <MetricBar value={mr.faithfulness_mean} threshold={THRESHOLDS.faithfulness} />
            </td>
            <td>
              <MetricBar value={mr.answer_relevancy_mean} threshold={THRESHOLDS.answer_relevancy} />
            </td>
            <td>
              <MetricBar value={mr.contextual_precision_mean} threshold={THRESHOLDS.contextual_precision} />
            </td>
            <td>
              <MetricBar value={mr.contextual_recall_mean} threshold={THRESHOLDS.contextual_recall} />
            </td>
            <td>
              <MetricBar
                value={mr.hallucination_mean}
                threshold={THRESHOLDS.hallucination}
                higherIsBetter={false}
              />
            </td>
            <td>{mr.pass_rate !== null && mr.pass_rate !== undefined ? `${Math.round(mr.pass_rate * 100)}%` : "—"}</td>
            <td>
              {mr.unanswerable_total > 0
                ? `${mr.unanswerable_handled}/${mr.unanswerable_total} (${Math.round(
                    (mr.unanswerable_handled_rate ?? 0) * 100
                  )}%)`
                : "—"}
            </td>
            <td>
              {mr.citation_metrics_supported ? (
                `${formatRatio(mr.citation_precision_mean)} / ${formatRatio(mr.citation_recall_mean)}`
              ) : (
                <span title="doc_name isn't a real filename for this mode yet — see README" style={{ color: "#aab1b8" }}>
                  N/A
                </span>
              )}
            </td>
            <td>
              {mr.p50_latency_ms ? `${Math.round(mr.p50_latency_ms)}ms` : "—"} /{" "}
              {mr.p95_latency_ms ? `${Math.round(mr.p95_latency_ms)}ms` : "—"}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
