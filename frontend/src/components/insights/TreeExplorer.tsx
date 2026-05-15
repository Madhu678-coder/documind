import { AnimatePresence, motion } from 'framer-motion';
import { BookOpen, ChevronDown, ChevronRight, FileText, Hash, Layers } from 'lucide-react';
import { useCallback, useState } from 'react';

// ── Types ──────────────────────────────────────────────────────────────────────

export interface TreeNode {
  node_id: string;
  title: string;
  page_start: number;
  page_end: number;
  depth: number;
  text: string;
  children?: TreeNode[];
}

export interface TreeJson {
  doc_id: string;
  title: string;
  nodes: TreeNode[];
}

interface TreeExplorerProps {
  treeJson: TreeJson;
  docTitle?: string;
}

// ── Helpers ────────────────────────────────────────────────────────────────────

function buildBreadcrumb(
  nodes: TreeNode[],
  targetId: string,
  path: TreeNode[] = []
): TreeNode[] | null {
  for (const node of nodes) {
    const current = [...path, node];
    if (node.node_id === targetId) return current;
    if (node.children?.length) {
      const found = buildBreadcrumb(node.children, targetId, current);
      if (found) return found;
    }
  }
  return null;
}

function depthIcon(depth: number) {
  if (depth === 0) return <BookOpen size={14} />;
  if (depth === 1) return <Layers size={14} />;
  if (depth === 2) return <Hash size={14} />;
  return <FileText size={14} />;
}

// ── TreeNodeRow ────────────────────────────────────────────────────────────────

interface TreeNodeRowProps {
  node: TreeNode;
  selectedId: string | null;
  onSelect: (node: TreeNode) => void;
}

function TreeNodeRow({ node, selectedId, onSelect }: TreeNodeRowProps) {
  const [open, setOpen] = useState(node.depth < 2);
  const hasChildren = !!node.children?.length;
  const isSelected = node.node_id === selectedId;

  const handleToggle = useCallback(
    (e: React.MouseEvent) => {
      e.stopPropagation();
      if (hasChildren) setOpen((v) => !v);
    },
    [hasChildren]
  );

  const handleSelect = useCallback(() => {
    onSelect(node);
  }, [node, onSelect]);

  const indent = node.depth * 16;

  return (
    <div>
      <button
        onClick={handleSelect}
        className={[
          'w-full flex items-center gap-2.5 px-4 py-2.5 text-left text-sm rounded-lg transition-all',
          'focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--dm-primary)]',
          isSelected
            ? 'bg-blue-50 text-[var(--dm-primary)] font-semibold shadow-sm'
            : 'text-slate-700 hover:bg-white hover:shadow-sm',
        ].join(' ')}
        style={{ paddingLeft: `${indent + 16}px` }}
        aria-expanded={hasChildren ? open : undefined}
        aria-selected={isSelected}
      >
        {/* expand/collapse toggle */}
        <span
          onClick={handleToggle}
          className="shrink-0 text-slate-400 hover:text-[var(--dm-primary)] transition-colors"
          role="button"
          aria-label={open ? 'Collapse' : 'Expand'}
          tabIndex={-1}
        >
          {hasChildren ? (
            open ? <ChevronDown size={16} /> : <ChevronRight size={16} />
          ) : (
            <span className="w-[16px] inline-block" />
          )}
        </span>

        {/* depth icon */}
        <span className={isSelected ? 'text-[var(--dm-primary)]' : 'text-slate-500'}>
          {depthIcon(node.depth)}
        </span>

        {/* title */}
        <span className="truncate flex-1">{node.title}</span>

        {/* page range badge */}
        <span className={`shrink-0 text-xs tabular-nums ${isSelected ? 'text-blue-600' : 'text-slate-500'}`}>
          p.{node.page_start}–{node.page_end}
        </span>
      </button>

      {/* children */}
      <AnimatePresence initial={false}>
        {hasChildren && open && (
          <motion.div
            key="children"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2, ease: 'easeInOut' }}
            style={{ overflow: 'hidden' }}
          >
            {node.children!.map((child) => (
              <TreeNodeRow
                key={child.node_id}
                node={child}
                selectedId={selectedId}
                onSelect={onSelect}
              />
            ))}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// ── Breadcrumb ─────────────────────────────────────────────────────────────────

interface BreadcrumbProps {
  path: TreeNode[];
  onNavigate: (node: TreeNode) => void;
}

function Breadcrumb({ path, onNavigate }: BreadcrumbProps) {
  if (!path.length) return null;

  return (
    <nav
      aria-label="Tree breadcrumb"
      className="flex items-center flex-wrap gap-1 text-xs text-slate-500 px-5 py-3 border-b border-slate-200 bg-slate-50"
    >
      <span className="text-slate-500 font-medium">Root</span>
      {path.map((node, i) => (
        <span key={node.node_id} className="flex items-center gap-1">
          <ChevronRight size={12} className="text-slate-400 shrink-0" />
          <button
            onClick={() => onNavigate(node)}
            className={[
              'hover:text-[var(--dm-primary)] transition-colors focus:outline-none focus-visible:underline',
              i === path.length - 1
                ? 'text-[var(--dm-primary)] font-semibold'
                : 'text-slate-600',
            ].join(' ')}
          >
            {node.title}
          </button>
        </span>
      ))}
    </nav>
  );
}

// ── Preview Panel ──────────────────────────────────────────────────────────────

interface PreviewPanelProps {
  node: TreeNode | null;
}

function PreviewPanel({ node }: PreviewPanelProps) {
  if (!node) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-slate-400 gap-3 p-8">
        <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-slate-100">
          <FileText size={32} strokeWidth={1.5} className="text-slate-400" />
        </div>
        <p className="text-sm text-center text-slate-500">Select a node to preview its section text</p>
      </div>
    );
  }

  return (
    <motion.div
      key={node.node_id}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2 }}
      className="flex flex-col h-full overflow-hidden"
    >
      {/* header */}
      <div className="px-6 py-4 border-b border-slate-200 bg-white">
        <h3 className="font-semibold text-slate-900 text-base leading-snug">{node.title}</h3>
        <p className="text-xs text-slate-500 mt-1.5">
          Pages {node.page_start}–{node.page_end} · Depth {node.depth}
        </p>
      </div>

      {/* body */}
      <div className="flex-1 overflow-y-auto px-6 py-5">
        {node.text ? (
          <p className="text-sm text-slate-700 leading-relaxed whitespace-pre-wrap">{node.text}</p>
        ) : (
          <p className="text-sm text-slate-500 italic">No text available for this section.</p>
        )}
      </div>
    </motion.div>
  );
}

// ── TreeExplorer (main) ────────────────────────────────────────────────────────

export function TreeExplorer({ treeJson, docTitle }: TreeExplorerProps) {
  const [selectedNode, setSelectedNode] = useState<TreeNode | null>(null);

  const breadcrumbPath = selectedNode
    ? buildBreadcrumb(treeJson.nodes ?? [], selectedNode.node_id) ?? []
    : [];

  const handleSelect = useCallback((node: TreeNode) => {
    setSelectedNode(node);
  }, []);

  return (
    <div className="flex flex-col h-full rounded-xl border border-slate-200 overflow-hidden bg-white shadow-sm">
      {/* top bar */}
      <div className="flex items-center gap-3 px-5 py-4 border-b border-slate-200 bg-[var(--dm-primary)]">
        <BookOpen size={18} className="text-white shrink-0" />
        <h2 className="text-white font-semibold text-sm truncate">
          {docTitle ?? treeJson.title}
        </h2>
      </div>

      {/* breadcrumb */}
      <Breadcrumb path={breadcrumbPath} onNavigate={handleSelect} />

      {/* body: tree + preview */}
      <div className="flex flex-1 overflow-hidden">
        {/* tree panel */}
        <div className="w-80 shrink-0 border-r border-slate-200 overflow-y-auto py-3 bg-slate-50">
          {(treeJson.nodes ?? []).length === 0 ? (
            <p className="text-xs text-slate-500 px-4 py-3">No nodes in this tree.</p>
          ) : (
            (treeJson.nodes ?? []).map((node) => (
              <TreeNodeRow
                key={node.node_id}
                node={node}
                selectedId={selectedNode?.node_id ?? null}
                onSelect={handleSelect}
              />
            ))
          )}
        </div>

        {/* preview panel */}
        <div className="flex-1 overflow-hidden bg-white">
          <PreviewPanel node={selectedNode} />
        </div>
      </div>
    </div>
  );
}
