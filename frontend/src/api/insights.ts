import { apiClient } from './client';

export interface KeyEntities {
  people?: string[];
  organizations?: string[];
  dates?: string[];
  amounts?: string[];
}

// PageIndex response shape
export interface PageIndexInsights {
  doc_id: string;
  rag_mode: 'pageindex';
  executive_summary: string | null;
  key_entities: KeyEntities | null;
  document_tags: string[] | null;
  complexity_score: number | null;
  tree_json: object;
}

// Vector RAG response shape
export interface ChunkInsight {
  id: string;
  chunk_index: number;
  text: string;
  page_number: number;
  char_start: number;
  char_end: number;
  has_embedding: boolean;
  metadata: Record<string, unknown>;
}

export interface VectorInsights {
  doc_id: string;
  rag_mode: 'vector';
  chunk_count: number;
  embedded_count: number;
  page_count: number;
  chunks: ChunkInsight[];
}

export type DocumentInsights = PageIndexInsights | VectorInsights;

export async function fetchDocumentInsights(docId: string): Promise<DocumentInsights> {
  const { data } = await apiClient.get<DocumentInsights>(`/insights/${docId}`);
  return data;
}
