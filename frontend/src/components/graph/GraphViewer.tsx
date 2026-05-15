import { useCallback, useEffect, useRef, useState } from 'react';
import { Loader2, Maximize2, Minimize2, ZoomIn, ZoomOut } from 'lucide-react';
import ForceGraph2D from 'react-force-graph-2d';
import { apiClient } from '../../api/client';

interface GraphNode {
  id: string;
  label: string;
  type: string;
  description: string;
  color: string;
  size: number;
  mentions: number;
}

interface GraphEdge {
  id: string;
  source: string;
  target: string;
  label: string;
  type: string;
  description: string;
  weight: number;
}

interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

interface GraphViewerProps {
  kbId: string;
}

export function GraphViewer({ kbId }: GraphViewerProps) {
  const [graphData, setGraphData] = useState<GraphData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const graphRef = useRef<any>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setLoading(true);
    apiClient.get(`/knowledge-bases/${kbId}/graph/visualization`)
      .then(({ data }) => {
        // Transform edges to use 'source' and 'target' as node IDs
        const formattedData = {
          nodes: data.nodes.map((n: GraphNode) => ({ ...n, val: n.size })),
          links: data.edges.map((e: GraphEdge) => ({
            ...e,
            source: e.source,
            target: e.target,
          })),
        };
        setGraphData(formattedData as any);
        setLoading(false);
      })
      .catch((err) => {
        setError(err?.response?.data?.detail || 'Failed to load graph');
        setLoading(false);
      });
  }, [kbId]);

  const handleNodeClick = useCallback((node: any) => {
    setSelectedNode(node);
    // Center on clicked node
    if (graphRef.current) {
      graphRef.current.centerAt(node.x, node.y, 500);
      graphRef.current.zoom(2, 500);
    }
  }, []);

  const handleZoomIn = () => graphRef.current?.zoom(graphRef.current.zoom() * 1.5, 300);
  const handleZoomOut = () => graphRef.current?.zoom(graphRef.current.zoom() / 1.5, 300);
  const handleFit = () => graphRef.current?.zoomToFit(400, 50);

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-orange-500" />
        <span className="ml-2 text-sm text-slate-500">Loading graph...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex h-full items-center justify-center p-4">
        <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-600">
          {error}
        </div>
      </div>
    );
  }

  if (!graphData || (graphData.nodes.length === 0)) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 p-4 text-center">
        <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-orange-100">
          <svg className="h-6 w-6 text-orange-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
          </svg>
        </div>
        <p className="text-sm font-medium text-slate-700">No graph data yet</p>
        <p className="text-xs text-slate-400">Upload documents to build the knowledge graph.</p>
      </div>
    );
  }

  return (
    <div ref={containerRef} className={`relative flex flex-col h-full ${isFullscreen ? 'fixed inset-0 z-50 bg-white' : ''}`}>
      {/* Toolbar */}
      <div className="flex items-center justify-between border-b border-slate-200 px-3 py-2 shrink-0">
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-500">
            {graphData.nodes.length} entities · {(graphData as any).links?.length || 0} relationships
          </span>
        </div>
        <div className="flex items-center gap-1">
          <button onClick={handleZoomIn} className="rounded p-1.5 hover:bg-slate-100 text-slate-500" title="Zoom in">
            <ZoomIn className="h-3.5 w-3.5" />
          </button>
          <button onClick={handleZoomOut} className="rounded p-1.5 hover:bg-slate-100 text-slate-500" title="Zoom out">
            <ZoomOut className="h-3.5 w-3.5" />
          </button>
          <button onClick={handleFit} className="rounded px-2 py-1 hover:bg-slate-100 text-xs text-slate-500" title="Fit to view">
            Fit
          </button>
          <button onClick={() => setIsFullscreen(f => !f)} className="rounded p-1.5 hover:bg-slate-100 text-slate-500" title="Toggle fullscreen">
            {isFullscreen ? <Minimize2 className="h-3.5 w-3.5" /> : <Maximize2 className="h-3.5 w-3.5" />}
          </button>
        </div>
      </div>

      {/* Graph canvas */}
      <div className="flex-1 relative">
        <ForceGraph2D
          ref={graphRef}
          graphData={graphData}
          nodeLabel={(node: any) => `${node.label} (${node.type})\n${node.description || ''}`}
          nodeColor={(node: any) => node.color || '#aaa'}
          nodeVal={(node: any) => node.size || 10}
          nodeCanvasObject={(node: any, ctx: CanvasRenderingContext2D, globalScale: number) => {
            const label = node.label;
            const fontSize = Math.max(10 / globalScale, 3);
            ctx.font = `${fontSize}px Sans-Serif`;
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';

            // Draw node circle
            const radius = Math.sqrt(node.size || 10) * 1.5;
            ctx.beginPath();
            ctx.arc(node.x, node.y, radius, 0, 2 * Math.PI);
            ctx.fillStyle = node.color || '#aaa';
            ctx.fill();

            // Draw border if selected
            if (selectedNode && selectedNode.id === node.id) {
              ctx.strokeStyle = '#000';
              ctx.lineWidth = 2 / globalScale;
              ctx.stroke();
            }

            // Draw label
            ctx.fillStyle = '#333';
            ctx.fillText(label, node.x, node.y + radius + fontSize);
          }}
          linkLabel={(link: any) => `${link.label}: ${link.description || ''}`}
          linkColor={() => '#cbd5e1'}
          linkWidth={(link: any) => Math.max((link.weight || 1) * 0.5, 0.5)}
          linkDirectionalArrowLength={4}
          linkDirectionalArrowRelPos={0.9}
          onNodeClick={handleNodeClick}
          cooldownTicks={100}
          width={containerRef.current?.clientWidth || 600}
          height={isFullscreen ? window.innerHeight - 50 : (containerRef.current?.clientHeight || 400) - 40}
        />
      </div>

      {/* Selected node info panel */}
      {selectedNode && (
        <div className="absolute bottom-4 left-4 right-4 rounded-xl border border-slate-200 bg-white/95 backdrop-blur p-3 shadow-lg">
          <div className="flex items-start justify-between">
            <div>
              <p className="text-sm font-semibold text-slate-800">{selectedNode.label}</p>
              <p className="text-xs text-slate-500">{selectedNode.type} · {selectedNode.mentions} mention(s)</p>
            </div>
            <button onClick={() => setSelectedNode(null)} className="text-slate-400 hover:text-slate-600 text-xs">✕</button>
          </div>
          {selectedNode.description && (
            <p className="mt-1.5 text-xs text-slate-600 leading-relaxed">{selectedNode.description}</p>
          )}
        </div>
      )}
    </div>
  );
}
