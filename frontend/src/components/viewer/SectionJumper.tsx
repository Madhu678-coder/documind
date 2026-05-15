import { useEffect } from 'react';
import { useUIStore } from '../../stores/uiStore';

interface SectionJumperProps {
  /** Document ID to open in the PDF viewer */
  docId: string | null;
  /** Page number to jump to */
  page: number | null;
}

/**
 * Headless component — syncs docId + page into uiStore so PDFViewer reacts.
 * Render this once in the Chat page; call setJump to trigger navigation.
 */
export function SectionJumper({ docId, page }: SectionJumperProps) {
  const { setPdfDoc, setPdfPage } = useUIStore();

  useEffect(() => {
    if (docId !== null) setPdfDoc(docId);
    if (page !== null) setPdfPage(page);
  }, [docId, page, setPdfDoc, setPdfPage]);

  return null;
}
