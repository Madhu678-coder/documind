import { BookOpen } from 'lucide-react';
import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { DocumentCard } from '../components/upload/DocumentCard';
import { useDocuments } from '../hooks/useDocuments';

export function Library() {
  const { knowledgeBases, documents, loadKnowledgeBases, loadDocuments } = useDocuments();
  const navigate = useNavigate();

  useEffect(() => {
    loadKnowledgeBases();
    loadDocuments();
  }, []);

  return (
    <div className="p-6 flex flex-col gap-8">
      <h2 className="text-2xl font-semibold text-slate-900">Document Library</h2>

      {knowledgeBases.length === 0 && (
        <p className="text-sm text-slate-500">No knowledge bases found. Create one to get started.</p>
      )}

      {knowledgeBases.map((kb) => {
        const kbDocs = documents.filter((d) => d.kb_id === kb.id);
        return (
          <section key={kb.id}>
            <div className="flex items-center gap-2.5 mb-4">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-blue-50">
                <BookOpen className="h-4 w-4 text-[var(--dm-primary)]" />
              </div>
              <h3 className="text-base font-semibold text-slate-900">{kb.name}</h3>
              <span className="text-xs text-slate-500">({kbDocs.length} doc{kbDocs.length !== 1 ? 's' : ''})</span>
            </div>

            {kbDocs.length === 0 ? (
              <p className="text-sm text-slate-500 pl-10">No documents in this knowledge base.</p>
            ) : (
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                {kbDocs.map((doc) => (
                  <button
                    key={doc.id}
                    onClick={() => navigate(`/documents/${doc.id}?from=/library`)}
                    className="text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--dm-primary)] rounded-xl"
                    aria-label={`View document ${doc.filename}`}
                  >
                    <DocumentCard document={doc} />
                  </button>
                ))}
              </div>
            )}
          </section>
        );
      })}

    </div>
  );
}
