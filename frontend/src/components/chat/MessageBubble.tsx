import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { cn } from '../../lib/utils';
import type { ChatMessage } from '../../types';
import { CitationBadge } from './CitationBadge';
import { ReasoningTrace } from './ReasoningTrace';

interface MessageBubbleProps {
  message: ChatMessage;
  isAdmin?: boolean;
  onCitationClick?: (docId: string, page: number, excerpt?: string) => void;
  showDisclaimer?: boolean;
}

export function MessageBubble({ message, isAdmin, onCitationClick, showDisclaimer }: MessageBubbleProps) {
  const isUser = message.role === 'user';

  return (
    <div className={cn('flex flex-col gap-2', isUser ? 'items-end' : 'items-start')}>
      <div
        className={cn(
          'max-w-[80%] rounded-2xl px-4 py-3 text-sm leading-relaxed',
          isUser
            ? 'bg-[var(--dm-primary)] text-white rounded-br-sm'
            : 'bg-white border border-slate-200 text-slate-800 rounded-bl-sm'
        )}
      >
        {isUser ? (
          message.content
        ) : (
          <div className="prose prose-sm max-w-none prose-slate
            prose-headings:font-semibold prose-headings:text-slate-800
            prose-h1:text-base prose-h2:text-sm prose-h3:text-sm
            prose-p:my-1.5 prose-p:leading-relaxed
            prose-ul:my-1.5 prose-ul:pl-4 prose-li:my-0.5
            prose-ol:my-1.5 prose-ol:pl-4
            prose-strong:text-slate-900 prose-strong:font-semibold
            prose-code:bg-slate-100 prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-code:text-xs prose-code:text-slate-700
            prose-pre:bg-slate-100 prose-pre:rounded-lg prose-pre:p-3
            prose-blockquote:border-l-2 prose-blockquote:border-[var(--dm-primary)] prose-blockquote:pl-3 prose-blockquote:text-slate-600
            prose-table:text-xs prose-th:bg-slate-50 prose-th:px-2 prose-th:py-1 prose-td:px-2 prose-td:py-1
            prose-a:text-[var(--dm-primary)] prose-a:no-underline hover:prose-a:underline">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {message.content}
            </ReactMarkdown>
          </div>
        )}
      </div>

      {showDisclaimer && !isUser && (
        <div className="max-w-[80%] rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
          ⚠ This response may have lower confidence. Please verify with source documents.
        </div>
      )}

      {!isUser && message.citations && message.citations.length > 0 && (
        <div className="flex flex-wrap gap-1.5 max-w-[80%] overflow-visible">
          {message.citations.map((citation, i) => (
            <CitationBadge
              key={i}
              citation={citation}
              index={i}
              onOpen={() => onCitationClick?.(citation.document_id, citation.page_number, citation.excerpt)}
            />
          ))}
        </div>
      )}

      {!isUser && message.reasoning_trace && message.reasoning_trace.length > 0 && (
        <div className="max-w-[80%]">
          <ReasoningTrace trace={message.reasoning_trace} isAdmin={isAdmin} messageId={message.id} />
        </div>
      )}
    </div>
  );
}
