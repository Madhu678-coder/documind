export type RagMode = "pageindex" | "vector" | "wiki" | "graph" | "openkb";
export type RetrievalMode = "vector" | "fulltext" | "hybrid";

export interface ModeSpec {
  rag_mode: RagMode;
  retrieval_mode?: RetrievalMode | null;
}

export interface QuestionSpec {
  id: string;
  question: string;
  expected_answer?: string | null;
  is_unanswerable?: boolean;
  expected_source_documents?: string[];
}

export type DatasetSourceType = "folder_path" | "s3" | "confluence" | "gdrive" | "sharepoint";

export interface RunCreatePayload {
  name: string;
  dataset_source_type: DatasetSourceType;
  dataset_source_ref: string;
  modes: ModeSpec[];
  questions: QuestionSpec[];
}

export interface QuestionDraftRequest {
  dataset_source_type: DatasetSourceType;
  dataset_source_ref: string;
  count?: number;
}

export interface QuestionDraft {
  question: string;
  expected_answer?: string | null;
  is_unanswerable: boolean;
  expected_source_documents: string[];
}

export interface QuestionDraftResponse {
  document_names: string[];
  questions: QuestionDraft[];
}

export interface QueryResult {
  id: string;
  question_id: string;
  question: string;
  expected_answer?: string | null;
  is_unanswerable: boolean;
  expected_source_documents: string[];
  actual_answer?: string | null;
  node_ids_visited: string[];
  cited_doc_names: string[];
  citation_count: number;
  citation_precision?: number | null;
  citation_recall?: number | null;
  latency_ms?: number | null;
  faithfulness_score?: number | null;
  faithfulness_reason?: string | null;
  answer_relevancy_score?: number | null;
  contextual_precision_score?: number | null;
  contextual_recall_score?: number | null;
  hallucination_score?: number | null;
  overall_pass?: boolean | null;
  eval_model?: string | null;
  eval_status: "pending" | "scored" | "timeout" | "error";
  refused_correctly?: boolean | null;
  error?: string | null;
}

export interface ModeResult {
  id: string;
  rag_mode: RagMode;
  retrieval_mode?: RetrievalMode | null;
  kb_id?: string | null;
  status: "pending" | "ingesting" | "querying" | "completed" | "failed";
  documents_ingested: number;
  documents_failed: number;
  avg_ingestion_time_seconds?: number | null;
  total_size_bytes?: number | null;
  faithfulness_mean?: number | null;
  answer_relevancy_mean?: number | null;
  contextual_precision_mean?: number | null;
  contextual_recall_mean?: number | null;
  hallucination_mean?: number | null;
  pass_rate?: number | null;
  p50_latency_ms?: number | null;
  p95_latency_ms?: number | null;
  unanswerable_total: number;
  unanswerable_handled: number;
  unanswerable_handled_rate?: number | null;
  citation_metrics_supported: boolean;
  citation_precision_mean?: number | null;
  citation_recall_mean?: number | null;
  error?: string | null;
  query_results: QueryResult[];
}

export interface RunDetail {
  id: string;
  name: string;
  status: "pending" | "running" | "completed" | "failed";
  dataset_source_type: string;
  dataset_source_ref: string;
  document_names: string[];
  modes: ModeSpec[];
  questions: QuestionSpec[];
  error?: string | null;
  created_at: string;
  completed_at?: string | null;
  mode_results: ModeResult[];
}

export interface RunSummary {
  id: string;
  name: string;
  status: string;
  created_at: string;
  completed_at?: string | null;
  mode_count: number;
}
