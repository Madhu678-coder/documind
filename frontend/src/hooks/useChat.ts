import { createSession, deleteSession, getMessages, getSessions, sendMessage } from '../api/chat';
import { useChatStore } from '../stores/chatStore';
import type { ChatMessage } from '../types';

export function useChat() {
  const store = useChatStore();

  const loadSessions = async () => {
    const sessions = await getSessions();
    store.setSessions(sessions);
  };

  const loadMessages = async (session_id: string) => {
    const msgs = await getMessages(session_id);
    store.setMessages(session_id, msgs);
  };

  const createNewSession = async (kb_id: string) => {
    const session = await createSession(kb_id);
    store.setSessions([...store.sessions, session]);
    store.setActiveSession(session.id);
    return session;
  };

  const selectSession = async (id: string) => {
    store.setActiveSession(id);
    // Load messages if not already cached
    if (!store.messages[id] || store.messages[id].length === 0) {
      await loadMessages(id);
    }
  };

  const removeSession = async (id: string) => {
    await deleteSession(id);
    store.setSessions(store.sessions.filter((s) => s.id !== id));
    if (store.activeSessionId === id) {
      store.setActiveSession(null);
    }
  };

  const sendMessageToSession = async (content: string) => {
    const { activeSessionId } = store;
    if (!activeSessionId) return;

    const userMessage: ChatMessage = {
      id: crypto.randomUUID(),
      session_id: activeSessionId,
      role: 'user',
      content,
      created_at: new Date().toISOString(),
    };
    store.addMessage(activeSessionId, userMessage);
    store.setStreaming(true);
    store.updateStreamingContent('');

    try {
      const response = await sendMessage(activeSessionId, content);
      const data = await response.json();

      const assistantMessage: ChatMessage = {
        id: data.id ?? crypto.randomUUID(),
        session_id: activeSessionId,
        role: 'assistant',
        content: data.content ?? '',
        citations: data.citations,
        reasoning_trace: data.reasoning_trace,
        created_at: data.created_at ?? new Date().toISOString(),
      };
      store.updateStreamingContent(data.content ?? '');
      store.addMessage(activeSessionId, assistantMessage);
    } catch (err) {
      console.error('Chat error:', err);
    } finally {
      store.clearStreaming();
    }
  };

  const activeMessages = store.activeSessionId
    ? (store.messages[store.activeSessionId] ?? [])
    : [];

  return {
    sessions: store.sessions,
    activeSessionId: store.activeSessionId,
    messages: activeMessages,
    isStreaming: store.isStreaming,
    streamingContent: store.streamingContent,
    loadSessions,
    loadMessages,
    createSession: createNewSession,
    sendMessage: sendMessageToSession,
    setActiveSession: selectSession,
    deleteSession: removeSession,
  };
}
