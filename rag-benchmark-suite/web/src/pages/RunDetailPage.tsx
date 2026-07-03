import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api";
import type { RunDetail } from "../types";
import MetricsTable from "../components/MetricsTable";
import StatusBadge from "../components/StatusBadge";

export default function RunDetailPage() {
  const { runId } = useParams<{ runId: string }>();
  const [run, setRun] = useState<RunDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!runId) return;
    let cancelled = false;

    async function load() {
      try {
        const data = await api.getRun(runId!);
        if (!cancelled) setRun(data);
      } catch (e) {
        if (!cancelled) setError((e as Error).message);
      }
    }

    load();
    const interval = setInterval(() => {
      if (run?.status === "completed" || run?.status === "failed") return;
      load();
    }, 4000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, run?.status]);

  if (error) return <div className="error-banner">{error}</div>;
  if (!run) return <div className="empty-state">Loading…</div>;

  return (
    <div>
      <div className="toolbar">
        <div>
          <h2 style={{ margin: 0 }}>{run.name}</h2>
          <div className="help-text">
            {run.dataset_source_type === "folder_path" ? "Folder" : run.dataset_source_type}:{" "}
            {run.dataset_source_ref} · {run.document_names.length} document(s)
          </div>
        </div>
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <StatusBadge status={run.status} />
          <a className="btn btn-secondary" href={api.exportUrl(run.id)} target="_blank" rel="noreferrer">
            Download raw JSON
          </a>
        </div>
      </div>

      {run.error && <div className="error-banner">{run.error}</div>}

      <div className="card">
        <h2>Metrics by mode</h2>
        {run.mode_results.length === 0 ? (
          <div className="empty-state">Provisioning knowledge bases…</div>
        ) : (
          <MetricsTable modeResults={run.mode_results} />
        )}
      </div>

      {run.mode_results.map((mr) => (
        <div className="mode-section card" key={mr.id}>
          <div className="mode-section-header">
            <h3>
              {mr.rag_mode}
              {mr.retrieval_mode ? ` · ${mr.retrieval_mode}` : ""}
            </h3>
            <StatusBadge status={mr.status} />
            {mr.error && <span style={{ color: "#d1453b", fontSize: 12 }}>{mr.error}</span>}
          </div>
          {mr.query_results.length === 0 ? (
            <div className="help-text">No answers yet.</div>
          ) : (
            mr.query_results.map((qr) => (
              <div className="query-detail" key={qr.id}>
                <div className="question">
                  {qr.question}
                  {qr.is_unanswerable && (
                    <span
                      style={{
                        marginLeft: 8,
                        fontSize: 10,
                        fontWeight: 700,
                        textTransform: "uppercase",
                        padding: "2px 8px",
                        borderRadius: 999,
                        background: qr.refused_correctly ? "#e3f5ea" : qr.refused_correctly === false ? "#fbe6e4" : "#e8ecef",
                        color: qr.refused_correctly ? "#2f9e5b" : qr.refused_correctly === false ? "#d1453b" : "#555",
                      }}
                    >
                      unanswerable · {qr.refused_correctly === true ? "refused correctly" : qr.refused_correctly === false ? "fabricated an answer" : "not yet scored"}
                    </span>
                  )}
                </div>
                <div className="answer">{qr.actual_answer || "(no answer)"}</div>
                <div className="help-text" style={{ marginTop: 6 }}>
                  eval: {qr.eval_status}
                  {qr.faithfulness_score !== null && qr.faithfulness_score !== undefined
                    ? ` · faithfulness ${qr.faithfulness_score.toFixed(2)}`
                    : ""}
                  {qr.latency_ms ? ` · ${Math.round(qr.latency_ms)}ms` : ""}
                  {qr.error ? ` · error: ${qr.error}` : ""}
                </div>
                {qr.expected_source_documents.length > 0 && (
                  <div className="help-text" style={{ marginTop: 2 }}>
                    expected: {qr.expected_source_documents.join(", ")} · cited:{" "}
                    {qr.cited_doc_names.length > 0 ? qr.cited_doc_names.join(", ") : "(none)"}
                    {qr.citation_precision !== null && qr.citation_precision !== undefined
                      ? ` · precision ${qr.citation_precision.toFixed(2)}`
                      : ""}
                    {qr.citation_recall !== null && qr.citation_recall !== undefined
                      ? ` · recall ${qr.citation_recall.toFixed(2)}`
                      : ""}
                  </div>
                )}
              </div>
            ))
          )}
        </div>
      ))}
    </div>
  );
}
