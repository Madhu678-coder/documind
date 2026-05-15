import { create } from 'zustand';

interface UIState {
  leftPanelOpen: boolean;
  rightPanelOpen: boolean;
  activeKbId: string | null;
  pdfViewerPage: number;
  pdfViewerDocId: string | null;
  pdfViewerHighlight: string | null;
  createKbModalOpen: boolean;

  toggleLeftPanel: () => void;
  toggleRightPanel: () => void;
  setActiveKb: (id: string | null) => void;
  setPdfPage: (page: number) => void;
  setPdfDoc: (docId: string | null) => void;
  setPdfHighlight: (text: string | null) => void;
  setCreateKbModal: (open: boolean) => void;
}

export const useUIStore = create<UIState>((set) => ({
  leftPanelOpen: true,
  rightPanelOpen: false,
  activeKbId: null,
  pdfViewerPage: 1,
  pdfViewerDocId: null,
  pdfViewerHighlight: null,
  createKbModalOpen: false,

  toggleLeftPanel: () => set((state) => ({ leftPanelOpen: !state.leftPanelOpen })),
  toggleRightPanel: () => set((state) => ({ rightPanelOpen: !state.rightPanelOpen })),
  setActiveKb: (id) => set({ activeKbId: id }),
  setPdfPage: (page) => set({ pdfViewerPage: page }),
  setPdfDoc: (docId) => set({ pdfViewerDocId: docId }),
  setPdfHighlight: (text) => set({ pdfViewerHighlight: text }),
  setCreateKbModal: (open) => set({ createKbModalOpen: open }),
}));
