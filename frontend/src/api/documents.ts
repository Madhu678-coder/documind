import type { Document, KBSettings, KnowledgeBase } from '../types';
import { apiClient } from './client';

export async function uploadDocument(
  file: File,
  kb_id: string,
  onProgress?: (pct: number) => void
): Promise<{ document_id: string }> {
  const form = new FormData();
  form.append('file', file);
  form.append('kb_id', kb_id);

  const { data } = await apiClient.post<{ document_id: string }>('/documents/upload', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: (e) => {
      if (onProgress && e.total) {
        onProgress(Math.round((e.loaded / e.total) * 100));
      }
    },
  });
  return data;
}

export async function getDocuments(kb_id?: string): Promise<Document[]> {
  const { data } = await apiClient.get<Document[]>('/documents', {
    params: kb_id ? { kb_id } : undefined,
  });
  return data;
}

export async function getDocument(doc_id: string): Promise<Document> {
  const { data } = await apiClient.get<Document>(`/documents/${doc_id}`);
  return data;
}

export async function createKnowledgeBase(name: string, description?: string, settings?: KBSettings): Promise<KnowledgeBase> {
  const { data } = await apiClient.post<KnowledgeBase>('/knowledge-bases', { name, description, settings });
  return data;
}

export async function getKnowledgeBases(): Promise<KnowledgeBase[]> {
  const { data } = await apiClient.get<KnowledgeBase[]>('/knowledge-bases');
  return data;
}

export async function deleteKnowledgeBase(kb_id: string): Promise<void> {
  console.log('deleteKnowledgeBase API call:', kb_id);
  try {
    const response = await apiClient.delete(`/knowledge-bases/${kb_id}`);
    console.log('deleteKnowledgeBase response:', response.status, response.data);
  } catch (error) {
    console.error('deleteKnowledgeBase API error:', error);
    throw error;
  }
}

export async function updateKnowledgeBase(
  kb_id: string,
  updates: { name?: string; description?: string }
): Promise<KnowledgeBase> {
  const { data } = await apiClient.patch<KnowledgeBase>(`/knowledge-bases/${kb_id}`, updates);
  return data;
}
