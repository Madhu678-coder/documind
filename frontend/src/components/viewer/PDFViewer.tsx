import { ChevronLeft, ChevronRight, ZoomIn, ZoomOut } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Document, Page, pdfjs } from 'react-pdf';
import 'react-pdf/dist/Page/AnnotationLayer.css';
import 'react-pdf/dist/Page/TextLayer.css';

pdfjs.GlobalWorkerOptions.workerSrc = `https://unpkg.com/pdfjs-dist@${pdfjs.version}/build/pdf.worker.min.js`;

const ZOOM_STEP = 0.25;
const ZOOM_MIN = 0.5;
const ZOOM_MAX = 3.0;
const ZOOM_DEFAULT = 1.0;
const BASE_WIDTH = 750;

interface PDFViewerProps {
  url: string | null;
  currentPage?: number;
  highlight?: string;
  onPageChange?: (page: number) => void;
}

function normalize(s: string) {
  return s.replace(/\s+/g, ' ').trim().toLowerCase();
}

/** Try to highlight text spans. Returns true if any match found. */
function highlightTextLayer(container: HTMLElement, excerpt: string): boolean {
  // Clear previous highlights
  container.querySelectorAll('.pdf-highlight').forEach((el) => {
    const span = el as HTMLElement;
    span.style.background = '';
    span.classList.remove('pdf-highlight');
  });

  if (!excerpt) return false;

  const target = normalize(excerpt).slice(0, 120);
  const firstWords = target.split(' ').slice(0, 4).join(' ');
  const spans = Array.from(container.querySelectorAll('.react-pdf__Page__textContent span')) as HTMLElement[];

  console.log('[Highlight] Attempting highlight:', { excerpt: excerpt.slice(0, 80), firstWords, spanCount: spans.length });

  if (spans.length === 0) return false; // image PDF — no text layer

  // Strategy 1: Accumulate text and find a window that contains the first words
  let accumulated = '';
  const allTexts: string[] = [];
  for (const span of spans) {
    const text = normalize(span.textContent ?? '');
    if (text) allTexts.push(text);
    accumulated += ' ' + text;
  }
  accumulated = accumulated.trim();

  // Find the position of firstWords in accumulated text
  const matchPos = accumulated.indexOf(firstWords);
  if (matchPos === -1) {
    // Strategy 2: Try with just the first 3 words
    const shorterKey = target.split(' ').slice(0, 3).join(' ');
    const shortPos = accumulated.indexOf(shorterKey);
    if (shortPos === -1) {
      console.log('[Highlight] No match found. First 200 chars of page text:', accumulated.slice(0, 200));
      return false;
    }
  }

  // Find which spans contain the matching text
  let charCount = 0;
  const matchStart = matchPos !== -1 ? matchPos : accumulated.indexOf(target.split(' ').slice(0, 3).join(' '));
  const matchEnd = matchStart + Math.min(target.length, 300);
  const toHighlight: HTMLElement[] = [];

  for (const span of spans) {
    const text = normalize(span.textContent ?? '');
    if (!text) continue;
    const spanStart = charCount;
    const spanEnd = charCount + text.length + 1; // +1 for the space separator
    charCount = spanEnd;

    // Check if this span overlaps with the match range
    if (spanEnd > matchStart && spanStart < matchEnd) {
      toHighlight.push(span);
    }
    // Stop after we've well passed the match
    if (spanStart > matchEnd + 50) break;
  }

  // If we only found 1 span, also highlight its neighbors for visibility
  if (toHighlight.length === 1) {
    const idx = spans.indexOf(toHighlight[0]);
    const start = Math.max(0, idx - 1);
    const end = Math.min(spans.length, idx + 4);
    toHighlight.length = 0;
    for (let i = start; i < end; i++) {
      if (spans[i].textContent?.trim()) toHighlight.push(spans[i]);
    }
  }

  if (toHighlight.length === 0) {
    console.log('[Highlight] Match found in text but could not map to spans');
    return false;
  }

  console.log('[Highlight] Highlighting', toHighlight.length, 'spans');
  toHighlight.forEach((span) => {
    span.style.background = 'rgba(251, 191, 36, 0.55)';
    span.style.borderRadius = '2px';
    span.classList.add('pdf-highlight');
  });

  toHighlight[0].scrollIntoView({ behavior: 'smooth', block: 'center' });
  return true;
}

/** For image PDFs: show a banner at the top of the page indicating the excerpt */
function showImagePdfBanner(container: HTMLElement, excerpt: string) {
  container.querySelectorAll('.pdf-image-banner').forEach((el) => el.remove());
  if (!excerpt) return;

  const pageEl = container.querySelector('.react-pdf__Page') as HTMLElement | null;
  if (!pageEl) return;

  const banner = document.createElement('div');
  banner.className = 'pdf-image-banner';
  banner.style.cssText = `
    position: absolute;
    top: 8px;
    left: 50%;
    transform: translateX(-50%);
    background: rgba(251, 191, 36, 0.95);
    color: #78350f;
    font-size: 11px;
    font-style: italic;
    padding: 6px 12px;
    border-radius: 6px;
    max-width: 90%;
    text-align: center;
    z-index: 10;
    box-shadow: 0 2px 8px rgba(0,0,0,0.15);
    pointer-events: none;
    line-height: 1.4;
  `;
  const short = excerpt.length > 120 ? excerpt.slice(0, 120) + '…' : excerpt;
  banner.textContent = `📌 "${short}"`;

  // Page canvas wrapper is position:relative — append banner inside it
  pageEl.style.position = 'relative';
  pageEl.appendChild(banner);
}

export function PDFViewer({ url, currentPage = 1, highlight, onPageChange }: PDFViewerProps) {
  const [numPages, setNumPages] = useState<number>(0);
  const [page, setPage] = useState(currentPage);
  const [zoom, setZoom] = useState(ZOOM_DEFAULT);
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  // Fetch PDF as blob with auth header
  useEffect(() => {
    if (!url) { setBlobUrl(null); return; }
    setIsLoading(true);
    let objectUrl: string | null = null;
    const token = localStorage.getItem('access_token') ?? '';
    fetch(url, { headers: { Authorization: `Bearer ${token}` } })
      .then((res) => {
        if (!res.ok) throw new Error(`PDF fetch failed: ${res.status}`);
        return res.blob();
      })
      .then((blob) => {
        objectUrl = URL.createObjectURL(blob);
        setBlobUrl(objectUrl);
      })
      .catch(() => setBlobUrl(null))
      .finally(() => setIsLoading(false));
    return () => {
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [url]);

  useEffect(() => {
    setPage(currentPage);
  }, [currentPage, url]);

  // Fallback: attempt highlighting when page or highlight changes, regardless of text layer events
  useEffect(() => {
    if (!highlight || !containerRef.current || !blobUrl) return;

    const attempts = [500, 1200, 2500];
    let cancelled = false;

    const tryHighlight = (attemptIndex: number) => {
      if (cancelled || attemptIndex >= attempts.length || !containerRef.current) return;

      setTimeout(() => {
        if (cancelled || !containerRef.current) return;
        const spans = containerRef.current.querySelectorAll('.react-pdf__Page__textContent span');
        if (spans.length > 0) {
          const found = highlightTextLayer(containerRef.current, highlight);
          if (found) return;
        }
        tryHighlight(attemptIndex + 1);
      }, attempts[attemptIndex]);
    };

    tryHighlight(0);
    return () => { cancelled = true; };
  }, [highlight, page, blobUrl]);

  const goTo = (p: number) => {
    const clamped = Math.max(1, Math.min(p, numPages));
    setPage(clamped);
    onPageChange?.(clamped);
  };

  const zoomIn = () => setZoom((z) => Math.min(+(z + ZOOM_STEP).toFixed(2), ZOOM_MAX));
  const zoomOut = () => setZoom((z) => Math.max(+(z - ZOOM_STEP).toFixed(2), ZOOM_MIN));
  const resetZoom = () => setZoom(ZOOM_DEFAULT);

  const handleTextLayerRendered = useCallback(() => {
    if (!highlight || !containerRef.current) return;

    // Retry highlighting with increasing delays — text layer may be re-rendered
    const attempts = [200, 500, 1000, 2000];
    let found = false;

    const tryHighlight = (attemptIndex: number) => {
      if (found || attemptIndex >= attempts.length || !containerRef.current) return;

      setTimeout(() => {
        if (!containerRef.current) return;
        const spans = containerRef.current.querySelectorAll('.react-pdf__Page__textContent span');
        if (spans.length > 0) {
          const result = highlightTextLayer(containerRef.current, highlight);
          if (result) {
            found = true;
            return;
          }
        }
        // Try again with next delay
        tryHighlight(attemptIndex + 1);
      }, attempts[attemptIndex]);
    };

    tryHighlight(0);
  }, [highlight, page]);

  // For image PDFs the text layer never fires — trigger banner on page render
  const handlePageRenderSuccess = useCallback(() => {
    if (!highlight || !containerRef.current) return;
    setTimeout(() => {
      if (!containerRef.current) return;
      const spans = containerRef.current.querySelectorAll('.react-pdf__Page__textContent span');
      if (spans.length === 0) {
        showImagePdfBanner(containerRef.current, highlight);
      }
    }, 1500); // Longer delay to give text layer time to render first
  }, [highlight, page]);

  if (!url) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-slate-400">
        Click a citation to open the document
      </div>
    );
  }

  if (isLoading || !blobUrl) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-slate-400">
        <div className="animate-pulse">Loading document…</div>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      {/* Toolbar */}
      <div className="flex items-center justify-between border-b border-slate-200 px-3 py-2 text-xs text-slate-600 gap-2 shrink-0">
        <div className="flex items-center gap-1">
          <button
            onClick={() => goTo(page - 1)}
            disabled={page <= 1}
            className="rounded p-1 hover:bg-slate-100 disabled:opacity-30 transition-colors"
            aria-label="Previous page"
          >
            <ChevronLeft className="h-4 w-4" />
          </button>
          <span className="tabular-nums min-w-[80px] text-center">
            {page} / {numPages || '—'}
          </span>
          <button
            onClick={() => goTo(page + 1)}
            disabled={page >= numPages}
            className="rounded p-1 hover:bg-slate-100 disabled:opacity-30 transition-colors"
            aria-label="Next page"
          >
            <ChevronRight className="h-4 w-4" />
          </button>
        </div>

        <div className="flex items-center gap-1">
          <button onClick={zoomOut} disabled={zoom <= ZOOM_MIN} className="rounded p-1 hover:bg-slate-100 disabled:opacity-30 transition-colors" aria-label="Zoom out">
            <ZoomOut className="h-4 w-4" />
          </button>
          <button onClick={resetZoom} className="rounded px-2 py-0.5 text-xs font-mono hover:bg-slate-100 transition-colors min-w-[48px] text-center" title="Reset zoom">
            {Math.round(zoom * 100)}%
          </button>
          <button onClick={zoomIn} disabled={zoom >= ZOOM_MAX} className="rounded p-1 hover:bg-slate-100 disabled:opacity-30 transition-colors" aria-label="Zoom in">
            <ZoomIn className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* PDF canvas */}
      <div ref={containerRef} className="flex-1 overflow-auto flex justify-center bg-slate-100 p-4">
        <Document
          file={blobUrl}
          onLoadSuccess={({ numPages: n }) => setNumPages(n)}
          loading={<div className="animate-pulse rounded bg-slate-200 h-64 w-96" />}
          error={<div className="text-sm text-red-500 p-4">Failed to load PDF.</div>}
        >
          <Page
            pageNumber={page}
            width={Math.round(BASE_WIDTH * zoom)}
            renderTextLayer={true}
            renderAnnotationLayer={true}
            onRenderSuccess={handlePageRenderSuccess}
            onRenderTextLayerSuccess={handleTextLayerRendered}
            // Suppress AbortException from cancelled text layer renders
            onRenderTextLayerError={(err) => {
              if (!String(err).includes('AbortException') && !String(err).includes('cancelled')) {
                console.warn('Text layer error:', err);
              }
            }}
          />
        </Document>
      </div>
    </div>
  );
}
