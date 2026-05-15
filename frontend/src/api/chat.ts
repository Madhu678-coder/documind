import type { ChatMessage, ChatSession } from '../types';
import { apiClient } from './client';

const BASE_URL = import.meta.env.VITE_API_URL ?? '/api/v1';

export async function createSession(kb_id: string): Promise<ChatSession> {
  const { data } = await apiClient.post<ChatSession>('/chat/sessions', { kb_id });
  return data;
}

export async function getSessions(): Promise<ChatSession[]> {
  const { data } = await apiClient.get<ChatSession[]>('/chat/sessions');
  return data;
}

export async function deleteSession(session_id: string): Promise<void> {
  await apiClient.delete(`/chat/sessions/${session_id}`);
}

export async function getMessages(session_id: string): Promise<ChatMessage[]> {
  const { data } = await apiClient.get<ChatMessage[]>(`/chat/sessions/${session_id}/messages`);
  return data;
}

/**
 * Returns a raw fetch Response for SSE streaming.
 * Caller is responsible for reading the stream.
 */
export async function sendMessage(session_id: string, content: string): Promise<Response> {
  const token = localStorage.getItem('access_token');
  return fetch(`${BASE_URL}/chat/sessions/${session_id}/messages`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ content }),
  });
}
