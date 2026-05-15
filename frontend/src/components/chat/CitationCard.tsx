import { BookOpen } from 'lucide-react';
import type { Citation } from '../../types';

interface CitationCardProps {
  citation: Citation;
  onClick?: () => void;
}

export function CitationCard({ citation, onClick }: CitationCardProps) {
  return (
    <button
      onClick={onClick}
      className="flex items-start gap-2 rounded-lg border border-[var(--dm-primary-light)] bg-[var(--dm-surface)] px-3 py-2 text-left text-xs hover:bg-[var(--dm-primary-light)] transition-colors w-full"
      aria-label={`View citation from ${citation.filename}, page ${citation.page_number}`}
    >
      <BookOpen className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[var(--dm-primary)]" />
      <div className="min-w-0">
        <p className="font-medium text-[var(--dm-primary)] truncate">{citation.filename}</p>
        <p className="text-slate-500 truncate">Page {citation.page_number}</p>
        {citation.excerpt && (
          <p className="mt-1 text-slate-600 line-clamp-2 italic">"{citation.excerpt}"</p>
        )}
      </div>
    </button>
  );
}
