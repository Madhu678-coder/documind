import { BookOpen, Plus, Send, Trash2 } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { MessageBubble } from '../components/chat/MessageBubble';
import { StreamingIndicator } from '../components/chat/StreamingIndicator';
import { useChat } from '../hooks/useChat';
import { useDocuments } from '../hooks/useDocuments';

export function Chat() {
  const { sessions, activeSessionId, messages, isStreaming, streamingContent, loadSessions, createSession, sendMessage, setActiveSession, deleteSession } = useChat();
  const { knowledgeBases, documents, loadKnowledgeBases, loadDocuments } = useDocuments();
  const navigate = useNavigate();

  const [input, setInput] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    loadSessions();
    loadKnowledgeBases();
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isStreaming]);

  const activeSession = sessions.find((s) => s.id === activeSessionId);
  const kbDocuments = activeSession
    ? documents.filter((d) => d.kb_id === activeSession.kb_id)
    : [];

  const handleNewSession = async (kb_id: string) => {
    // If there's already an active session for this KB with no messages, reuse it
    const existing = sessions.find((s) => s.kb_id === kb_id);
    if (existing && messages.length === 0 && activeSessionId === existing.id) {
      return; // already on an empty session for this KB
    }
    await createSession(kb_id);
    loadDocuments(kb_id);
  };

  const handleSend = async () => {
    const text = input.trim();
    if (!text || isStreaming || !activeSessionId) return;
    setInput('');
    await sendMessage(text);
    // Refresh sessions so the auto-generated title appears
    loadSessions();
  };

  const handleCitationClick = (docId: string, page: number, excerpt?: string) => {
    const params = new URLSearchParams({ from: '/chat' });
    if (page > 1) params.set('page', String(page));
    if (excerpt) params.set('highlight', excerpt);
    navigate(`/documents/${docId}?${params.toString()}`);
  };

  return (
    <div className="flex h-full overflow-hidden">

      {/* Left panel — 280px */}
      <aside className="w-[280px] shrink-0 flex flex-col border-r border-slate-200 bg-slate-50">
        {/* KB selector */}
        <div className="border-b border-slate-200 p-4">
          <p className="mb-3 text-xs font-semibold uppercase tracking-wider text-slate-500">Knowledge Base</p>
          <div className="flex flex-col gap-1.5">
            {knowledgeBases.map((kb) => {
              const isActive = activeSession?.kb_id === kb.id;
              return (
                <button
                  key={kb.id}
                  onClick={() => handleNewSession(kb.id)}
                  className={`flex items-center gap-2.5 rounded-lg px-3 py-2 text-left text-sm transition-all ${
                    isActive
                      ? 'bg-[var(--dm-primary)] text-white shadow-md ring-2 ring-blue-100'
                      : 'text-slate-700 hover:bg-white hover:shadow-sm'
                  }`}
                >
                  <div className={`flex h-7 w-7 items-center justify-center rounded-md ${
                    isActive ? 'bg-white/20' : 'bg-blue-50'
                  }`}>
                    <BookOpen className={`h-4 w-4 ${
                      isActive ? 'text-white' : 'text-[var(--dm-primary)]'
                    }`} />
                  </div>
                  <span className="font-medium">{kb.name}</span>
                </button>
              );
            })}
            {knowledgeBases.length === 0 && (
              <p className="text-xs text-slate-500 px-3">No knowledge bases. Create one first.</p>
            )}
          </div>
        </div>

        {/* Session navigator */}
        <div className="p-4 overflow-y-auto">
          <p className="mb-3 text-xs font-semibold uppercase tracking-wider text-slate-500">Sessions</p>
          <div className="flex flex-col gap-1">
            {sessions.map((s) => {
              const isActive = s.id === activeSessionId;
              return (
                <div
                  key={s.id}
                  className={`group flex items-center gap-1 rounded-lg transition-all ${
                    isActive
                      ? 'bg-gradient-to-r from-blue-50 to-blue-100 shadow-sm ring-2 ring-blue-200'
                      : 'hover:bg-white hover:shadow-sm'
                  }`}
                >
                  <button
                    onClick={() => setActiveSession(s.id)}
                    className={`flex-1 truncate px-3 py-2 text-left text-xs transition-colors ${
                      isActive
                        ? 'text-[var(--dm-primary)] font-bold'
                        : 'text-slate-700 font-medium'
                    }`}
                  >
                    {s.title || 'Untitled session'}
                  </button>
                  <button
                    onClick={(e) => { e.stopPropagation(); deleteSession(s.id); }}
                    className={`mr-2 rounded p-1 transition-all ${
                      isActive
                        ? 'text-slate-500 hover:text-red-600 hover:bg-red-50'
                        : 'text-slate-400 opacity-0 group-hover:opacity-100 hover:text-red-600 hover:bg-red-50'
                    }`}
                    aria-label="Delete session"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              );
            })}
          </div>
        </div>
      </aside>

      {/* Center panel — flex */}
      <main className="flex flex-1 flex-col min-w-0">
        {!activeSessionId ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-4 text-slate-500">
            <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-slate-100">
              <Plus className="h-8 w-8 text-slate-400" />
            </div>
            <p className="text-sm font-medium">Select a knowledge base on the left to start a new session</p>
          </div>
        ) : (
          <>
            {/* Active KB header */}
            <div className="border-b border-slate-200 bg-white px-6 py-3 shrink-0">
              <div className="flex items-center gap-3">
                <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-blue-50">
                  <BookOpen className="h-4 w-4 text-[var(--dm-primary)]" />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-xs text-slate-500 font-medium">Active Knowledge Base</p>
                  <p className="text-sm font-semibold text-slate-900 truncate">
                    {knowledgeBases.find((kb) => kb.id === activeSession?.kb_id)?.name || 'Unknown KB'}
                  </p>
                </div>
                <div className="text-xs text-slate-400 bg-slate-50 px-2.5 py-1 rounded-md border border-slate-200">
                  {kbDocuments.length} {kbDocuments.length === 1 ? 'document' : 'documents'}
                </div>
              </div>
            </div>

            {/* Messages */}
            <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-4">
              {messages.map((msg) => (
                <MessageBubble
                  key={msg.id}
                  message={msg}
                  onCitationClick={handleCitationClick}
                />
              ))}

              {isStreaming && (
                <div className="flex flex-col gap-2 items-start">
                  {streamingContent ? (
                    <div className="max-w-[80%] rounded-2xl rounded-bl-sm border border-slate-200 bg-white px-4 py-3 text-sm text-slate-800">
                      {streamingContent}
                    </div>
                  ) : (
                    <StreamingIndicator />
                  )}
                </div>
              )}

              <div ref={messagesEndRef} />
            </div>

            {/* Input */}
            <div className="border-t border-slate-200 bg-white p-4">
              <div className="flex items-end gap-3 rounded-xl border border-slate-200 bg-white px-4 py-3 shadow-sm focus-within:border-[var(--dm-primary)] focus-within:ring-2 focus-within:ring-blue-100 transition-all">
                <textarea
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault();
                      handleSend();
                    }
                  }}
                  placeholder="Ask a question about your documents…"
                  rows={1}
                  className="flex-1 resize-none bg-transparent text-sm text-slate-900 outline-none placeholder:text-slate-400"
                  aria-label="Chat input"
                />
                <button
                  onClick={handleSend}
                  disabled={!input.trim() || isStreaming}
                  className="rounded-lg bg-[var(--dm-primary)] p-2 text-white hover:bg-[var(--dm-primary-dark)] disabled:opacity-40 transition-colors shadow-sm"
                  aria-label="Send message"
                >
                  <Send className="h-4 w-4" />
                </button>
              </div>
            </div>
          </>
        )}
      </main>

    </div>
  );
}
