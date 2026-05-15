import { create } from 'zustand';
import type { ChatMessage, ChatSession } from '../types';

interface ChatState {
  sessions: ChatSession[];
  activeSessionId: string | null;
  messages: Record<string, ChatMessage[]>;
  isStreaming: boolean;
  streamingContent: string;

  setSessions: (sessions: ChatSession[]) => void;
  setActiveSession: (id: string | null) => void;
  setMessages: (sessionId: string, messages: ChatMessage[]) => void;
  addMessage: (sessionId: string, message: ChatMessage) => void;
  updateStreamingContent: (content: string) => void;
  setStreaming: (streaming: boolean) => void;
  clearStreaming: () => void;
}

export const useChatStore = create<ChatState>((set) => ({
  sessions: [],
  activeSessionId: null,
  messages: {},
  isStreaming: false,
  streamingContent: '',

  setSessions: (sessions) => set({ sessions }),

  setActiveSession: (id) => set({ activeSessionId: id }),

  setMessages: (sessionId, messages) =>
    set((state) => ({
      messages: { ...state.messages, [sessionId]: messages },
    })),

  addMessage: (sessionId, message) =>
    set((state) => ({
      messages: {
        ...state.messages,
        [sessionId]: [...(state.messages[sessionId] ?? []), message],
      },
    })),

  updateStreamingContent: (content) => set({ streamingContent: content }),

  setStreaming: (streaming) => set({ isStreaming: streaming }),

  clearStreaming: () => set({ isStreaming: false, streamingContent: '' }),
}));
