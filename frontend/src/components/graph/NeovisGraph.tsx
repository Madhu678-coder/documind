import { useEffect, useRef, useState } from 'react';
import { Loader2, Maximize2, Minimize2 } from 'lucide-react';
import { apiClient } from '../../api/client';

interface GraphViewerProps {
  kbId: string;
  docId?: string;
}

const TYPE_COLORS: Record<string, string> = {
  organization: '#4e79a7',
  person: '#f28e2b',
  role: '#e15759',
  policy: '#76b7b2',
  process: '#59a14f',
  category: '#edc948',
  location: '#9c755f',
  amount: '#ff9da7',
  department: '#b07aa1',
  document: '#bab0ac',
  concept: '#4e79a7',
  rule: '#e15759',
};

export function NeovisGraph({ kbId, docId }: GraphViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [stats, setStats] = useState<{ nodes: number; edges: number } | null>(null);
  const [selectedNode, setSelectedNode] = useState<any>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [entityTypes, setEntityTypes] = useState<string[]>([]);
  const networkRef = useRef<any>(null);

  useEffect(() => {
    if (!containerRef.current || !kbId) return;

    setLoading(true);
    setError(null);

    apiClient.get(`/knowledge-bases/${kbId}/graph/visualization`, {
        params: docId ? { doc_id: docId } : undefined,
      })
      .then(({ data }) => {
        if (!data.nodes || data.nodes.length === 0) {
          setError('No graph data yet. Upload documents to build the knowledge graph.');
          setLoading(false);
          return;
        }

        setStats({ nodes: data.nodes.length, edges: data.edges.length });

        // Collect unique entity types for legend
        const types = [...new Set(data.nodes.map((n: any) => n.type))].filter(Boolean) as string[];
        setEntityTypes(types);

        // Load vis-network from CDN
        const loadAndRender = () => {
          const vis = (window as any).vis;
          if (!vis || !containerRef.current) {
            setError('Failed to load visualization library');
            setLoading(false);
            return;
          }

          const nodes = new vis.DataSet(
            data.nodes.map((n: any) => ({
              id: n.id,
              label: n.label,
              title: `${n.label} (${n.type})\n${n.description || ''}`,
              color: {
                background: TYPE_COLORS[n.type] || '#aaa',
                border: darken(TYPE_COLORS[n.type] || '#aaa'),
                highlight: { background: lighten(TYPE_COLORS[n.type] || '#aaa'), border: TYPE_COLORS[n.type] || '#aaa' },
                hover: { background: lighten(TYPE_COLORS[n.type] || '#aaa'), border: TYPE_COLORS[n.type] || '#aaa' },
              },
              size: Math.min(Math.max((n.mentions || 1) * 8 + 10, 14), 40),
              font: {
                size: 12,
                color: '#1e293b',
                face: 'Inter, system-ui, sans-serif',
                strokeWidth: 3,
                strokeColor: '#ffffff',
              },
              shape: 'dot',
              borderWidth: 2,
            }))
          );

          const edges = new vis.DataSet(
            data.edges.map((e: any, i: number) => ({
              id: e.id || `edge-${i}`,
              from: e.source,
              to: e.target,
              label: e.label || '',
              title: `${e.source_name || ''} → ${e.target_name || ''}\n${e.label}: ${e.description || ''}`,
              arrows: { to: { enabled: true, scaleFactor: 0.4, type: 'arrow' } },
              color: { color: '#94a3b8', highlight: '#334155', hover: '#64748b', opacity: 0.7 },
              width: 1.2,
              font: { size: 9, color: '#64748b', align: 'horizontal', strokeWidth: 2, strokeColor: '#ffffff' },
              smooth: { type: 'continuous' },
              hoverWidth: 0.5,
              selectionWidth: 1,
            }))
          );

          const options = {
            physics: {
              forceAtlas2Based: {
                gravitationalConstant: -60,
                centralGravity: 0.008,
                springLength: 200,
                springConstant: 0.015,
                damping: 0.4,
                avoidOverlap: 0.9,
              },
              solver: 'forceAtlas2Based',
              stabilization: { iterations: 250, fit: true },
              maxVelocity: 25,
              minVelocity: 0.5,
            },
            interaction: {
              hover: true,
              tooltipDelay: 150,
              zoomView: true,
              dragView: true,
              multiselect: false,
              navigationButtons: false,
            },
            nodes: {
              shape: 'dot',
              borderWidth: 2,
              shadow: { enabled: true, size: 6, x: 2, y: 2, color: 'rgba(0,0,0,0.08)' },
            },
            edges: {
              selectionWidth: 2,
              smooth: { type: 'continuous' },
            },
            layout: {
              improvedLayout: true,
              randomSeed: 42,
            },
          };

          const network = new vis.Network(containerRef.current, { nodes, edges }, options);
          networkRef.current = network;

          network.on('click', (params: any) => {
            if (params.nodes.length > 0) {
              const nodeId = params.nodes[0];
              const nodeData = data.nodes.find((n: any) => n.id === nodeId);
              setSelectedNode(nodeData);
            } else {
              setSelectedNode(null);
            }
          });

          network.on('stabilizationIterationsDone', () => {
            network.fit({ animation: { duration: 500 } });
            setLoading(false);
          });

          setTimeout(() => setLoading(false), 4000);
        };

        if ((window as any).vis) {
          loadAndRender();
        } else {
          const script = document.createElement('script');
          script.src = 'https://cdn.jsdelivr.net/npm/vis-network@9.1.9/standalone/umd/vis-network.min.js';
          script.async = true;
          script.onload = loadAndRender;
          script.onerror = () => {
            setError('Failed to load visualization library from CDN');
            setLoading(false);
          };
          document.head.appendChild(script);
        }
      })
      .catch((err) => {
        setError(err?.response?.data?.detail || 'Failed to load graph data');
        setLoading(false);
      });

    return () => {
      if (networkRef.current) {
        networkRef.current.destroy();
        networkRef.current = null;
      }
    };
  }, [kbId]);

  if (error) {
    return (
      <div className="flex h-full items-center justify-center p-4">
        <div className="rounded-xl border border-orange-200 bg-orange-50 p-4 text-center max-w-sm">
          <p className="text-sm font-medium text-orange-700 mb-1">{error}</p>
        </div>
      </div>
    );
  }

  return (
    <div className={`relative flex flex-col h-full ${isFullscreen ? 'fixed inset-0 z-50 bg-white' : ''}`}>
      {/* Toolbar */}
      <div className="flex items-center justify-between border-b border-slate-200 px-3 py-2 shrink-0 bg-white">
        <span className="text-xs text-slate-500">
          {stats ? `${stats.nodes} entities · ${stats.edges} relationships` : 'Loading...'}
        </span>
        <div className="flex items-center gap-1">
          <button
            onClick={() => networkRef.current?.fit({ animation: { duration: 300 } })}
            className="rounded px-2 py-1 hover:bg-slate-100 text-xs text-slate-600 font-medium"
          >
            Fit
          </button>
          <button
            onClick={() => setIsFullscreen(f => !f)}
            className="rounded p-1.5 hover:bg-slate-100 text-slate-500"
          >
            {isFullscreen ? <Minimize2 className="h-3.5 w-3.5" /> : <Maximize2 className="h-3.5 w-3.5" />}
          </button>
        </div>
      </div>

      {/* Graph canvas */}
      <div className="flex-1 relative bg-slate-50">
        {loading && (
          <div className="absolute inset-0 flex items-center justify-center bg-white/90 z-10">
            <Loader2 className="h-5 w-5 animate-spin text-orange-500" />
            <span className="ml-2 text-sm text-slate-500">Rendering graph...</span>
          </div>
        )}
        <div ref={containerRef} className="h-full w-full" />

        {/* Legend */}
        {!loading && entityTypes.length > 0 && (
          <div className="absolute bottom-3 right-3 bg-white/90 backdrop-blur rounded-lg border border-slate-200 px-2.5 py-2 shadow-sm z-10">
            <div className="flex flex-wrap gap-x-3 gap-y-1 max-w-[280px]">
              {entityTypes.map(type => (
                <div key={type} className="flex items-center gap-1.5">
                  <span
                    className="w-2 h-2 rounded-full shrink-0"
                    style={{ backgroundColor: TYPE_COLORS[type] || '#aaa' }}
                  />
                  <span className="text-[9px] text-slate-500 capitalize">{type}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Selected node info */}
      {selectedNode && (
        <div className="absolute bottom-3 left-3 right-3 rounded-xl border border-slate-200 bg-white/95 backdrop-blur p-3 shadow-lg z-20">
          <div className="flex items-start justify-between">
            <div className="flex items-center gap-2">
              <span
                className="w-3 h-3 rounded-full shrink-0"
                style={{ backgroundColor: TYPE_COLORS[selectedNode.type] || '#aaa' }}
              />
              <div>
                <p className="text-sm font-semibold text-slate-800">{selectedNode.label}</p>
                <p className="text-xs text-slate-500 capitalize">{selectedNode.type} · {selectedNode.mentions} mention(s)</p>
              </div>
            </div>
            <button onClick={() => setSelectedNode(null)} className="text-slate-400 hover:text-slate-600 text-sm leading-none">✕</button>
          </div>
          {selectedNode.description && (
            <p className="mt-2 text-xs text-slate-600 leading-relaxed border-l-2 border-orange-300 pl-2">{selectedNode.description}</p>
          )}
        </div>
      )}
    </div>
  );
}

function darken(hex: string): string {
  try {
    const r = Math.max(0, parseInt(hex.slice(1, 3), 16) - 40);
    const g = Math.max(0, parseInt(hex.slice(3, 5), 16) - 40);
    const b = Math.max(0, parseInt(hex.slice(5, 7), 16) - 40);
    return `#${r.toString(16).padStart(2, '0')}${g.toString(16).padStart(2, '0')}${b.toString(16).padStart(2, '0')}`;
  } catch { return hex; }
}

function lighten(hex: string): string {
  try {
    const r = Math.min(255, parseInt(hex.slice(1, 3), 16) + 50);
    const g = Math.min(255, parseInt(hex.slice(3, 5), 16) + 50);
    const b = Math.min(255, parseInt(hex.slice(5, 7), 16) + 50);
    return `#${r.toString(16).padStart(2, '0')}${g.toString(16).padStart(2, '0')}${b.toString(16).padStart(2, '0')}`;
  } catch { return hex; }
}
