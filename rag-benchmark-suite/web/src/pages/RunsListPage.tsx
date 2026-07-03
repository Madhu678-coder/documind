import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import type { RunSummary } from "../types";
import StatusBadge from "../components/StatusBadge";

export default function RunsListPage() {
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    try {
      setRuns(await api.listRuns());
    } catch (e) {
      setError((e as Error).message);
    }
  }

  useEffect(() => {
    load();
    const interval = setInterval(load, 5000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div>
      <div className="toolbar">
        <h2 style={{ margin: 0 }}>Benchmark runs</h2>
        <Link to="/new" className="btn">
          + New run
        </Link>
      </div>

      {error && <div className="error-banner">{error}</div>}

      <div className="card">
        {runs === null ? (
          <div className="empty-state">Loading…</div>
        ) : runs.length === 0 ? (
          <div className="empty-state">
            No runs yet. Start one to compare pageindex, vector, wiki, graph and openkb on the
            same dataset.
          </div>
        ) : (
          <table className="runs-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Status</th>
                <th>Modes</th>
                <th>Created</th>
                <th>Completed</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.id}>
                  <td>
                    <Link to={`/runs/${r.id}`}>{r.name}</Link>
                  </td>
                  <td>
                    <StatusBadge status={r.status} />
                  </td>
                  <td>{r.mode_count}</td>
                  <td>{new Date(r.created_at).toLocaleString()}</td>
                  <td>{r.completed_at ? new Date(r.completed_at).toLocaleString() : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
