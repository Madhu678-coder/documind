// Document status
export type DocumentStatus = 'uploading' | 'processing' | 'ready' | 'failed';

// Chat types
export interface Citation {
  document_id: string;
  filename: string;
  page_number: number;
  node_id: string;
  excerpt: string;
}

export interface ReasoningTrace {
  step: number;
  node_id: string;
  reasoning: string;
  confidence: number;
}

export interface ChatMessage {
  id: string;
  session_id: string;
  role: 'user' | 'assistant';
  content: string;
  citations?: Citation[];
  reasoning_trace?: ReasoningTrace[];
  created_at: string;
}

export interface ChatSession {
  id: string;
  kb_id: string;
  title: string;
  created_at: string;
}

// Document types
export interface Document {
  id: string;
  kb_id: string;
  filename: string;
  file_type: string;
  size_bytes: number;
  status: DocumentStatus;
  created_at: string;
  chunk_count?: number | null;
}

export interface KBSettings {
  rag_mode: 'pageindex' | 'vector' | 'wiki';
  index_method?: 'high_quality' | 'economical' | 'hybrid';
  chunk_strategy?: 'recursive' | 'parent_child';
  chunk_size?: number;
  chunk_overlap?: number;
  retrieval_mode?: 'vector' | 'fulltext' | 'hybrid';
  top_k?: number;
  score_threshold?: number | null;
  rerank_enabled?: boolean;
  hybrid_semantic_weight?: number;
  embedding_provider?: string;
  embedding_model?: string;
}

export interface KnowledgeBase {
  id: string;
  workspace_id: string;
  name: string;
  description?: string;
  document_count: number;
  created_at: string;
  settings?: KBSettings;
  rag_mode?: 'pageindex' | 'vector' | 'wiki'; // derived from settings by backend
}

export interface WikiPage {
  id: string;
  kb_id: string;
  title: string;
  summary: string | null;
  page_type: 'entity' | 'concept' | 'process' | 'event' | 'general';
  source_doc_count: number;
  related_titles: string[];
  updated_at: string;
}

export interface WikiPageDetail extends WikiPage {
  content: string;
  source_doc_ids: string[];
  workspace_id: string;
  llm_model_used: string | null;
  created_at: string;
}

export interface ModelProviderConfig {
  id: string;
  workspace_id: string;
  provider_type: 'llm' | 'embedding' | 'rerank';
  provider_name: string;
  model_id: string;
  region?: string;
  extra_config: Record<string, unknown>;
  is_default: boolean;
  created_at: string;
}

export interface UploadItem {
  file: File;
  kb_id: string;
  progress: number;
  status: 'pending' | 'uploading' | 'done' | 'error';
}

// Eval types
export interface EvalResult {
  id: string;
  message_id: string;
  document_id: string;
  faithfulness_score: number;
  faithfulness_reason: string;
  answer_relevancy_score: number;
  contextual_precision_score: number;
  contextual_recall_score: number;
  hallucination_score: number;
  overall_pass: boolean;
  eval_model: string;
  triggered_by: string;
  evaluated_at: string;
}

export interface EvalConfig {
  id?: string;
  workspace_id?: string;
  faithfulness_threshold: number;
  answer_relevancy_threshold: number;
  contextual_precision_threshold: number;
  contextual_recall_threshold: number;
  hallucination_threshold: number;
  multi_turn_enabled: boolean;
}
