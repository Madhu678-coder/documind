import { NavLink, Route, Routes } from "react-router-dom";
import NewRunPage from "./pages/NewRunPage";
import RunsListPage from "./pages/RunsListPage";
import RunDetailPage from "./pages/RunDetailPage";

export default function App() {
  return (
    <div className="app-shell">
      <header className="top-bar">
        <div>
          <h1>DocuMind RAG Benchmark Suite</h1>
          <div className="subtitle">Compare pageindex, vector, wiki, graph &amp; openkb on the same dataset</div>
        </div>
        <nav>
          <NavLink to="/" end className={({ isActive }) => (isActive ? "active" : "")}>
            Runs
          </NavLink>
          <NavLink to="/new" className={({ isActive }) => (isActive ? "active" : "")}>
            New Run
          </NavLink>
        </nav>
      </header>
      <div className="page">
        <Routes>
          <Route path="/" element={<RunsListPage />} />
          <Route path="/new" element={<NewRunPage />} />
          <Route path="/runs/:runId" element={<RunDetailPage />} />
        </Routes>
      </div>
    </div>
  );
}
