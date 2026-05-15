import { File, FileText } from 'lucide-react';
import { useEffect, useState } from 'react';
import { cn } from '../../lib/utils';
import type { Document, DocumentStatus } from '../../types';

interface DocumentCardProps {
  document: Document;
  queuePosition?: number; // 1-based position in processing queue (1 = actively processing)
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function useElapsedTime(active: boolean) {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    if (!active) { setSeconds(0); return; }
    const t = setInterval(() => setSeconds((s) => s + 1), 1000);
    return () => clearInterval(t);
  }, [active]);
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

const statusConfig: Record<DocumentStatus, { label: string; className: string }> = {
  uploading: { label: 'Uploading', className: 'bg-blue-50 text-blue-700 border border-blue-200' },
  processing: { label: 'Processing', className: 'bg-amber-50 text-amber-700 border border-amber-200' },
  ready: { label: 'Ready', className: 'bg-green-50 text-green-700 border border-green-200' },
  failed: { label: 'Failed', className: 'bg-red-50 text-red-700 border border-red-200' },
};

export function DocumentCard({ document, queuePosition }: DocumentCardProps) {
  const ext = document.file_type.toLowerCase().replace('.', '');
  const isTextFile = ['pdf', 'txt', 'md'].includes(ext);
  const Icon = isTextFile ? FileText : File;
  const status = statusConfig[document.status] ?? statusConfig.failed;
  const isProcessing = document.status === 'processing' || document.status === 'uploading';

  // Only count elapsed time when actively processing (position 1 or 2 with concurrency=2)
  const isActive = isProcessing && (queuePosition === undefined || queuePosition <= 2);
  const elapsed = useElapsedTime(isActive);

  return (
    <div className="relative flex flex-col gap-2 rounded-xl border border-slate-200 bg-white p-4 overflow-hidden shadow-sm hover:shadow-md transition-all duration-200">
      <div className="flex items-center gap-3">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-blue-50">
          <Icon className="h-5 w-5 text-[var(--dm-primary)]" />
        </div>

        <div className="flex-1 min-w-0">
          <p className="truncate text-sm font-medium text-slate-900">{document.filename}</p>
          <p className="text-xs text-slate-500">{formatSize(document.size_bytes)}</p>
        </div>

        {/* Only show status badge for completed/failed documents, not during processing */}
        {!isProcessing && (
          <span className={cn('shrink-0 rounded-md px-2.5 py-1 text-xs font-medium', status.className)}>
            {status.label}
          </span>
        )}
      </div>

      {isProcessing && (
        <>
          {/* Animated progress bar */}
          <div className="h-1.5 w-full rounded-full bg-slate-100 overflow-hidden">
            {isActive ? (
              <div className="h-full bg-blue-500 rounded-full animate-[progress_2s_ease-in-out_infinite]"
                style={{ width: '60%', animation: 'indeterminate 1.5s ease-in-out infinite' }} />
            ) : (
              <div className="h-full w-full bg-slate-200 rounded-full" />
            )}
          </div>

          <div className="flex items-center justify-between text-xs text-slate-500">
            {isActive ? (
              <span className="font-medium">Processing… {elapsed}</span>
            ) : (
              <span>
                Queued{queuePosition !== undefined ? ` · #${queuePosition} in line` : ''}
              </span>
            )}
            <span className="text-slate-400">~30s avg</span>
          </div>
        </>
      )}
    </div>
  );
}
