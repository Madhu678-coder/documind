import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import ModeSelector from "../components/ModeSelector";
import type { DatasetSourceType, ModeSpec, QuestionSpec } from "../types";

let qidCounter = 1;
function newQuestion(): QuestionSpec {
  return {
    id: `q${qidCounter++}`,
    question: "",
    expected_answer: "",
    is_unanswerable: false,
    expected_source_documents: [],
  };
}

const SOURCE_TYPE_INFO: Record<
  DatasetSourceType,
  { label: string; fieldLabel: string; placeholder: string; help: string }
> = {
  folder_path: {
    label: "Folder path (mounted into this service)",
    fieldLabel: "Folder path",
    placeholder: "/data/my-dataset",
    help: "Must be mounted as a Docker volume for the benchmark-suite api container (see docker-compose.yml).",
  },
  s3: {
    label: "S3 datasource connection",
    fieldLabel: "S3 location",
    placeholder: "s3://my-bucket/my-prefix",
    help: "Uses the ambient AWS credential chain already configured for this host — never paste keys here.",
  },
  confluence: {
    label: "Confluence space",
    fieldLabel: "Space key (optionally scoped to a page)",
    placeholder: "ENG or ENG:123456",
    help: "Pulls every page in the space, or one page + its descendants if you add :PAGEID. Requires BENCHMARK_CONFLUENCE_BASE_URL/_EMAIL/_API_TOKEN on the api container.",
  },
  gdrive: {
    label: "Google Drive folder",
    fieldLabel: "Drive folder ID",
    placeholder: "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs",
    help: "The ID segment from the folder's URL. Share the folder with the service account's email first — requires BENCHMARK_GDRIVE_SERVICE_ACCOUNT_JSON on the api container.",
  },
  sharepoint: {
    label: "SharePoint / OneDrive folder",
    fieldLabel: "Site + folder path",
    placeholder: "contoso.sharepoint.com|/sites/Compliance|Shared Documents/Policies",
    help: "Format: hostname|/sites/site-name|folder/path. Requires an Azure AD app registration (BENCHMARK_AZURE_TENANT_ID/_CLIENT_ID/_CLIENT_SECRET) with admin-consented Graph Sites.Read.All.",
  },
};

export default function NewRunPage() {
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [sourceType, setSourceType] = useState<DatasetSourceType>("folder_path");
  const [sourceRef, setSourceRef] = useState("");
  const [modes, setModes] = useState<ModeSpec[]>([{ rag_mode: "pageindex" }, { rag_mode: "vector", retrieval_mode: "vector" }]);
  const [questions, setQuestions] = useState<QuestionSpec[]>([newQuestion(), newQuestion(), newQuestion()]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [genCount, setGenCount] = useState(8);
  const [generating, setGenerating] = useState(false);
  const [genError, setGenError] = useState<string | null>(null);

  function updateQuestion(id: string, patch: Partial<QuestionSpec>) {
    setQuestions((qs) => qs.map((q) => (q.id === id ? { ...q, ...patch } : q)));
  }

  function removeQuestion(id: string) {
    setQuestions((qs) => qs.filter((q) => q.id !== id));
  }

  async function handleGenerate() {
    setGenError(null);
    if (!sourceRef.trim()) {
      setGenError("Point to a dataset location first (step 1) — generation reads the same dataset a real run would use.");
      return;
    }
    setGenerating(true);
    try {
      const result = await api.generateQuestionDrafts({
        dataset_source_type: sourceType,
        dataset_source_ref: sourceRef.trim(),
        count: genCount,
      });
      const drafted: QuestionSpec[] = result.questions.map((d) => ({
        ...newQuestion(),
        question: d.question,
        expected_answer: d.expected_answer ?? "",
        is_unanswerable: d.is_unanswerable,
        expected_source_documents: d.expected_source_documents,
      }));
      setQuestions((qs) => {
        const existingHasContent = qs.some((q) => q.question.trim());
        return existingHasContent ? [...qs, ...drafted] : drafted;
      });
    } catch (e) {
      setGenError((e as Error).message);
    } finally {
      setGenerating(false);
    }
  }

  async function handleSubmit() {
    setError(null);
    if (!name.trim()) return setError("Give this run a name.");
    if (!sourceRef.trim()) return setError("Point to a dataset location for the selected source type.");
    if (modes.length === 0) return setError("Select at least one RAG mode.");
    const validQuestions = questions.filter((q) => q.question.trim());
    if (validQuestions.length === 0) return setError("Add at least one test question.");
    const payloadQuestions = validQuestions.map((q) => ({
      ...q,
      expected_source_documents: (q.expected_source_documents ?? []).filter((d) => d.trim()),
    }));

    setSubmitting(true);
    try {
      const run = await api.createRun({
        name: name.trim(),
        dataset_source_type: sourceType,
        dataset_source_ref: sourceRef.trim(),
        modes,
        questions: payloadQuestions,
      });
      navigate(`/runs/${run.id}`);
    } catch (e) {
      setError((e as Error).message);
      setSubmitting(false);
    }
  }

  return (
    <div>
      <h2>New benchmark run</h2>
      {error && <div className="error-banner">{error}</div>}

      <div className="card">
        <h2>1. Dataset</h2>
        <label>Run name</label>
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. Kavach360 policy docs — July benchmark"
        />

        <label>Source type</label>
        <select
          value={sourceType}
          onChange={(e) => {
            setSourceType(e.target.value as DatasetSourceType);
            setSourceRef("");
          }}
        >
          {(Object.keys(SOURCE_TYPE_INFO) as DatasetSourceType[]).map((key) => (
            <option key={key} value={key}>
              {SOURCE_TYPE_INFO[key].label}
            </option>
          ))}
        </select>

        <label>{SOURCE_TYPE_INFO[sourceType].fieldLabel}</label>
        <input
          type="text"
          value={sourceRef}
          onChange={(e) => setSourceRef(e.target.value)}
          placeholder={SOURCE_TYPE_INFO[sourceType].placeholder}
        />
        <div className="help-text">{SOURCE_TYPE_INFO[sourceType].help}</div>
      </div>

      <div className="card">
        <h2>2. RAG modes to compare</h2>
        <ModeSelector selected={modes} onChange={setModes} />
      </div>

      <div className="card">
        <h2>3. Test questions</h2>
        <div className="help-text" style={{ marginBottom: 10 }}>
          The identical question set runs against every selected mode's KB, so scores are
          comparable. Mark a question "unanswerable" to test whether a mode correctly refuses
          instead of fabricating an answer — scored against DocuMind's own hallucination metric.
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
          <span style={{ fontSize: 13 }}>Generate</span>
          <input
            type="number"
            min={1}
            max={20}
            value={genCount}
            onChange={(e) => setGenCount(Math.max(1, Math.min(20, Number(e.target.value) || 1)))}
            style={{ width: 60 }}
          />
          <span style={{ fontSize: 13 }}>draft questions from the dataset</span>
          <button
            className="btn-secondary btn"
            type="button"
            onClick={handleGenerate}
            disabled={generating || !sourceRef.trim()}
          >
            {generating ? "Generating…" : "Generate"}
          </button>
        </div>
        <div className="help-text" style={{ marginBottom: 10 }}>
          Ingests the dataset into a temporary pageindex KB in DocuMind and asks it to draft a
          fact / multi-doc / unanswerable mix — review and edit every draft below before running.
          Takes as long as a normal document upload; the scratch KB is deleted afterward.
        </div>
        {genError && <div className="error-banner">{genError}</div>}

        {questions.map((q) => (
          <div key={q.id} style={{ marginBottom: 10, border: "1px solid #eceff2", borderRadius: 6, padding: 10 }}>
            <div className="question-row" style={{ marginBottom: 6 }}>
              <input
                type="text"
                placeholder="Question"
                value={q.question}
                onChange={(e) => updateQuestion(q.id, { question: e.target.value })}
              />
              <input
                type="text"
                placeholder="Expected answer (optional)"
                value={q.expected_answer ?? ""}
                onChange={(e) => updateQuestion(q.id, { expected_answer: e.target.value })}
                disabled={q.is_unanswerable}
              />
              <button className="btn-secondary btn" onClick={() => removeQuestion(q.id)} type="button">
                Remove
              </button>
            </div>
            <label style={{ display: "flex", alignItems: "center", gap: 6, fontWeight: 400, fontSize: 12, marginTop: 0 }}>
              <input
                type="checkbox"
                checked={!!q.is_unanswerable}
                onChange={(e) => updateQuestion(q.id, { is_unanswerable: e.target.checked })}
              />
              This question should be unanswerable from the dataset (tests hallucination resistance)
            </label>
            {!q.is_unanswerable && (
              <div style={{ marginTop: 6 }}>
                <input
                  type="text"
                  placeholder="Expected source document(s), comma-separated (optional, e.g. policy.pdf, handbook.docx)"
                  value={(q.expected_source_documents ?? []).join(", ")}
                  onChange={(e) =>
                    updateQuestion(q.id, {
                      expected_source_documents: e.target.value
                        .split(",")
                        .map((s) => s.trim())
                        .filter(Boolean),
                    })
                  }
                />
                <div className="help-text" style={{ marginTop: 2 }}>
                  Scored into citation precision/recall — only meaningful for pageindex/vector
                  modes today (see README).
                </div>
              </div>
            )}
          </div>
        ))}
        <button className="btn-secondary btn" onClick={() => setQuestions((qs) => [...qs, newQuestion()])} type="button">
          + Add question
        </button>
      </div>

      <button className="btn" onClick={handleSubmit} disabled={submitting}>
        {submitting ? "Starting…" : "Run benchmark"}
      </button>
    </div>
  );
}
