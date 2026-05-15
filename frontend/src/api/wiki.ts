import { apiClient } from './client';
import type { WikiPage, WikiPageDetail } from '../types';

export const getWikiPages = (kbId: string, docId?: string) =>
  apiClient.get<WikiPage[]>(`/knowledge-bases/${kbId}/wiki-pages`, {
    params: docId ? { doc_id: docId } : undefined,
  });

export const getWikiPage = (kbId: string, pageId: string) =>
  apiClient.get<WikiPageDetail>(`/knowledge-bases/${kbId}/wiki-pages/${pageId}`);
