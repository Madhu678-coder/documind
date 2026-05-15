import {
    createKnowledgeBase,
    deleteKnowledgeBase,
    getDocument,
    getDocuments,
    getKnowledgeBases,
    updateKnowledgeBase,
    uploadDocument,
} from '../api/documents';
import { useDocumentStore } from '../stores/documentStore';

export function useDocuments() {
  const store = useDocumentStore();

  const loadKnowledgeBases = async () => {
    const kbs = await getKnowledgeBases();
    store.setKnowledgeBases(kbs);
  };

  const loadDocuments = async (kb_id?: string) => {
    const docs = await getDocuments(kb_id);
    store.setDocuments(docs);
  };

  const uploadFile = async (file: File, kb_id: string) => {
    store.addToUploadQueue({ file, kb_id, progress: 0, status: 'uploading' });

    try {
      const result = await uploadDocument(file, kb_id, (pct) => {
        store.updateUploadProgress(file.name, pct, 'uploading');
      });
      store.updateUploadProgress(file.name, 100, 'done');
      
      // Start polling for this specific document instead of reloading all
      if (result.document_id) {
        pollDocumentStatus(result.document_id);
      }
    } catch {
      store.updateUploadProgress(file.name, 0, 'error');
    }
  };

  const deleteKb = async (kb_id: string) => {
    console.log('deleteKb called with:', kb_id);
    try {
      await deleteKnowledgeBase(kb_id);
      console.log('deleteKnowledgeBase API call succeeded');
      await loadKnowledgeBases();
      console.log('Knowledge bases reloaded');
    } catch (error) {
      console.error('deleteKb error:', error);
      throw error;
    }
  };

  const createKb = async (name: string, description?: string, settings?: import('../types').KBSettings) => {
    await createKnowledgeBase(name, description, settings);
    await loadKnowledgeBases();
  };

  const updateKb = async (kb_id: string, name?: string, description?: string) => {
    await updateKnowledgeBase(kb_id, { name, description });
    await loadKnowledgeBases();
  };

  const pollDocumentStatus = (doc_id: string, interval = 3000) => {
    const timer = setInterval(async () => {
      try {
        const doc = await getDocument(doc_id);
        
        // Update the document in the store (adds if not exists)
        store.updateDocument(doc);
        
        // Stop polling when processing is complete
        if (doc.status === 'ready' || doc.status === 'failed') {
          clearInterval(timer);
        }
      } catch (error: any) {
        // Stop polling on auth errors or if document not found
        if (error?.response?.status === 401 || error?.response?.status === 404) {
          console.warn(`Stopping poll for document ${doc_id}: ${error?.response?.status}`);
          clearInterval(timer);
        }
        // For other errors, keep polling (might be temporary network issue)
      }
    }, interval);

    return () => clearInterval(timer);
  };

  return {
    documents: store.documents,
    knowledgeBases: store.knowledgeBases,
    activeKbId: store.activeKbId,
    uploadQueue: store.uploadQueue,
    loadKnowledgeBases,
    loadDocuments,
    uploadFile,
    deleteKb,
    createKb,
    updateKb,
    pollDocumentStatus,
  };
}
