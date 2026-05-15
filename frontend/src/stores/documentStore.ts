import { create } from 'zustand';
import type { Document, KnowledgeBase, UploadItem } from '../types';

interface DocumentState {
  documents: Document[];
  knowledgeBases: KnowledgeBase[];
  activeKbId: string | null;
  uploadQueue: UploadItem[];

  setDocuments: (documents: Document[]) => void;
  updateDocument: (doc: Document) => void;
  setKnowledgeBases: (kbs: KnowledgeBase[]) => void;
  setActiveKb: (id: string | null) => void;
  addToUploadQueue: (item: UploadItem) => void;
  updateUploadProgress: (filename: string, progress: number, status?: UploadItem['status']) => void;
  removeFromUploadQueue: (filename: string) => void;
}

export const useDocumentStore = create<DocumentState>((set) => ({
  documents: [],
  knowledgeBases: [],
  activeKbId: null,
  uploadQueue: [],

  setDocuments: (documents) => set({ documents }),

  updateDocument: (doc) =>
    set((state) => ({
      documents: state.documents.some((d) => d.id === doc.id)
        ? state.documents.map((d) => (d.id === doc.id ? doc : d))
        : [...state.documents, doc],
    })),

  setKnowledgeBases: (knowledgeBases) => set({ knowledgeBases }),

  setActiveKb: (id) => set({ activeKbId: id }),

  addToUploadQueue: (item) =>
    set((state) => ({ uploadQueue: [...state.uploadQueue, item] })),

  updateUploadProgress: (filename, progress, status) =>
    set((state) => ({
      uploadQueue: state.uploadQueue.map((item) =>
        item.file.name === filename
          ? { ...item, progress, ...(status ? { status } : {}) }
          : item
      ),
    })),

  removeFromUploadQueue: (filename) =>
    set((state) => ({
      uploadQueue: state.uploadQueue.filter((item) => item.file.name !== filename),
    })),
}));
