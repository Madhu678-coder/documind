import type { ModeSpec } from "../types";

const OPTIONS: { spec: ModeSpec; label: string; hint: string }[] = [
  { spec: { rag_mode: "pageindex" }, label: "PageIndex", hint: "vectorless tree reasoning (default)" },
  { spec: { rag_mode: "vector", retrieval_mode: "vector" }, label: "Vector", hint: "embedding similarity" },
  { spec: { rag_mode: "vector", retrieval_mode: "fulltext" }, label: "Vector · Full-text", hint: "keyword search" },
  { spec: { rag_mode: "vector", retrieval_mode: "hybrid" }, label: "Vector · Hybrid", hint: "vector + full-text" },
  { spec: { rag_mode: "wiki" }, label: "Wiki", hint: "LLM-maintained wiki pages" },
  { spec: { rag_mode: "graph" }, label: "Graph", hint: "Neo4j entity graph" },
  { spec: { rag_mode: "openkb" }, label: "OpenKB", hint: "compiled summary/concept/entity pages" },
];

function keyOf(spec: ModeSpec): string {
  return spec.retrieval_mode ? `${spec.rag_mode}:${spec.retrieval_mode}` : spec.rag_mode;
}

export default function ModeSelector({
  selected,
  onChange,
}: {
  selected: ModeSpec[];
  onChange: (modes: ModeSpec[]) => void;
}) {
  const selectedKeys = new Set(selected.map(keyOf));

  function toggle(spec: ModeSpec) {
    const key = keyOf(spec);
    if (selectedKeys.has(key)) {
      onChange(selected.filter((s) => keyOf(s) !== key));
    } else {
      onChange([...selected, spec]);
    }
  }

  return (
    <div className="mode-grid">
      {OPTIONS.map((opt) => {
        const key = keyOf(opt.spec);
        const checked = selectedKeys.has(key);
        return (
          <label key={key} className={`mode-check ${checked ? "checked" : ""}`}>
            <input type="checkbox" checked={checked} onChange={() => toggle(opt.spec)} />
            <span>
              <strong>{opt.label}</strong>
              <div className="help-text">{opt.hint}</div>
            </span>
          </label>
        );
      })}
    </div>
  );
}
