import { useEffect } from 'react';
import { useDocuments } from '../../hooks/useDocuments';
import type { Document } from '../../types';
import { DocumentCard } from './DocumentCard';

interface ProgressTrackerProps {
  kb_id: string;
  documents: Document[];
}

export function ProgressTracker({ kb_id: _kb_id, documents }: ProgressTrackerProps) {
  const { pollDocumentStatus } = useDocuments();

  const processing = documents.filter(
    (d) => d.status === 'processing' || d.status === 'uploading'
  );

  const processingIds = processing.map((d) => d.id).join(',');

  useEffect(() => {
    if (processing.length === 0) return;
    const cleanups = processing.map((doc) => pollDocumentStatus(doc.id));
    return () => cleanups.forEach((fn) => fn());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [processingIds]);

  if (processing.length === 0) return null;

  const activeCount = Math.min(processing.length, 2); // concurrency=2
  const queuedCount = Math.max(0, processing.length - activeCount);

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Processing</p>
        <p className="text-xs text-slate-400">
          {activeCount} active{queuedCount > 0 ? ` · ${queuedCount} queued` : ''}
        </p>
      </div>
      {processing.map((doc, idx) => (
        <DocumentCard key={doc.id} document={doc} queuePosition={idx + 1} />
      ))}
    </div>
  );
}
