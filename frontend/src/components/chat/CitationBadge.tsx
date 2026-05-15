import { FileText } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import type { Citation } from '../../types';

interface CitationBadgeProps {
  citation: Citation;
  index: number;
  onOpen?: () => void; // opens PDF drawer
}

export function CitationBadge({ citation, index, onOpen }: CitationBadgeProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  const shortName = citation.filename.replace(/\.[^.]+$/, '');
  const label = shortName.length > 18 ? shortName.slice(0, 16) + '…' : shortName;

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  return (
    <div ref={ref} className="relative inline-block">
      {/* Badge — only toggles popover, does NOT open drawer */}
      <button
        onClick={(e) => { e.stopPropagation(); setOpen((v) => !v); }}
        className="inline-flex items-center gap-1 rounded-full border border-slate-300 bg-slate-100 px-2.5 py-0.5 text-xs font-medium text-slate-600 hover:border-blue-400 hover:bg-blue-50 hover:text-blue-700 transition-colors"
        aria-label={`Citation ${index + 1}: ${citation.filename}`}
      >
        <FileText className="h-3 w-3 shrink-0" />
        <span>{label}</span>
        <span className="text-slate-400 text-[10px]">p.{citation.page_number}</span>
      </button>

      {/* Popover */}
      {open && (
        <div
          className="absolute z-[9999] w-72 rounded-xl border border-slate-200 bg-white shadow-xl"
          style={{ bottom: 'calc(100% + 8px)', left: 0 }}
        >
          {/* Caret */}
          <div className="absolute -bottom-[7px] left-5 h-3 w-3 rotate-45 border-b border-r border-slate-200 bg-white" />

          <div className="p-3">
            {/* Header */}
            <div className="flex items-center gap-2 mb-2">
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-blue-50">
                <FileText className="h-4 w-4 text-blue-600" />
              </div>
              <div className="min-w-0">
                <p className="truncate text-sm font-semibold text-slate-800 leading-tight">
                  {citation.filename}
                </p>
                <p className="text-xs text-slate-400">Page {citation.page_number}</p>
              </div>
            </div>

            {/* Excerpt */}
            {citation.excerpt && (
              <p className="text-xs leading-relaxed text-slate-600 border-l-2 border-blue-400 pl-2 italic line-clamp-3">
                "{citation.excerpt}"
              </p>
            )}

            {/* Open button */}
            <button
              onClick={() => { setOpen(false); onOpen?.(); }}
              className="mt-3 w-full rounded-lg border border-blue-200 bg-blue-50 py-1.5 text-xs font-medium text-blue-700 hover:bg-blue-600 hover:text-white hover:border-blue-600 transition-colors"
            >
              Open in document viewer
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
