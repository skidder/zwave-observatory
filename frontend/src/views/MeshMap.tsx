import { useEffect, useMemo, useRef, useState } from 'react';
import cytoscape, { type Core, type ElementDefinition } from 'cytoscape';
import coseBilkent from 'cytoscape-cose-bilkent';
import { api } from '../api/client';
import { useApi } from '../hooks/useApp';
import { gradeColor } from '../lib/healthScore';
import { Btn } from '../components/ui';
import type { MeshGraph } from '../api/types';

cytoscape.use(coseBilkent);

function cssVar(name: string, fallback: string): string {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

export default function MeshMap({ onOpenNode }: { onOpenNode: (id: number) => void }) {
  const mesh = useApi(() => api.mesh());
  const nodes = useApi(() => api.nodes());
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const [query, setQuery] = useState('');
  const [onlyProblems, setOnlyProblems] = useState(false);

  const problemCounts = useMemo(() => {
    const m = new Map<number, number>();
    for (const n of nodes.data ?? []) if (n.stats.drops > 0) m.set(n.id, (m.get(n.id) ?? 0) + 1);
    return m;
  }, [nodes.data]);

  useEffect(() => {
    const graph = mesh.data as MeshGraph | null;
    if (!graph || !containerRef.current) return;
    const bg = cssVar('--panel-2', '#eee');
    const grid = cssVar('--grid', '#ccc');
    const text = cssVar('--text', '#333');

    const q = query.trim().toLowerCase();
    const hiddenIds = new Set<number>();
    for (const n of graph.nodes) {
      const label = n.label.toLowerCase();
      if (q && !label.includes(q) && String(n.id) !== q) hiddenIds.add(n.id);
      if (onlyProblems && n.problems === 0) hiddenIds.add(n.id);
    }

    const elements: ElementDefinition[] = graph.nodes
      .filter((n) => !hiddenIds.has(n.id))
      .map((n) => ({
        data: {
          id: `n${n.id}`,
          label: n.label,
          color: gradeColor(n.grade),
          controller: n.is_controller,
          power: n.power,
          sleeping: n.sleeping,
          dead: n.dead,
        },
      }));
    for (const e of graph.edges) {
      if (hiddenIds.has(e.source) || hiddenIds.has(e.target)) continue;
      elements.push({
        data: { id: `e${e.source}-${e.target}-${e.kind}`, source: `n${e.source}`, target: `n${e.target}`, kind: e.kind, rssi: e.rssi },
      });
    }

    const cy = cytoscape({
      container: containerRef.current,
      elements,
      layout: { name: 'cose-bilkent', animate: false, idealEdgeLength: 110, nodeRepulsion: 8000 } as never,
      style: [
        {
          selector: 'node',
          style: {
            label: 'data(label)',
            'background-color': 'data(color)',
            color: text,
            'font-size': 10,
            width: 26,
            height: 26,
            'text-valign': 'bottom',
            'text-margin-y': 4,
          },
        },
        {
          selector: 'node[controller]',
          style: {
            width: 42, height: 42,
            'border-width': 6, 'border-color': cssVar('--accent', '#1A5276'),
            'background-color': cssVar('--accent', '#1A5276'),
          },
        },
        { selector: 'node[power = "battery"]', style: shapeDiamond() },
        { selector: 'node[sleeping]', style: { opacity: 0.55 } },
        { selector: 'node[dead]', style: { opacity: 0.3, 'background-color': cssVar('--danger', '#C0392B') } },
        {
          selector: 'edge[kind = "lwr"]',
          style: { 'line-color': grid, width: 2 },
        },
        { selector: 'edge[kind = "nlwr"]', style: { 'line-style': 'dashed', 'line-color': cssVar('--edge-nlwr', '#888'), width: 1.5 } },
        { selector: 'edge[kind = "neighbor"]', style: { 'line-color': bg, width: 1, opacity: 0.5 } },
      ],
    });
    // LWR edges labeled with RSSI.
    cy.edges('[kind = "lwr"]').style('label', (el: cytoscape.EdgeSingular) => {
      const rssi = el.data('rssi');
      return rssi != null ? `${rssi} dBm` : '';
    });
    cy.on('tap', 'node', (evt) => {
      const id = Number(evt.target.id().replace(/^n/, ''));
      onOpenNode(id);
    });
    cyRef.current = cy;
    return () => { cy.destroy(); cyRef.current = null; };
  }, [mesh.data, query, onlyProblems, onOpenNode]);

  return (
    <div className="card">
      <div className="row" style={{ justifyContent: 'space-between', marginBottom: 8 }}>
        <div className="row">
          <input
            type="text" placeholder="Filter nodes…" value={query}
            onChange={(e) => setQuery(e.target.value)} style={{ width: 200 }}
          />
          <label className="row" style={{ gap: 4, fontSize: '0.85rem' }}>
            <input type="checkbox" checked={onlyProblems} onChange={(e) => setOnlyProblems(e.target.checked)} />
            only problems
          </label>
        </div>
        <div className="row">
          <span className="dim" style={{ fontSize: '0.78rem' }}>
            routes as of {mesh.data ? new Date(mesh.data.routes_as_of).toLocaleString() : '…'}
          </span>
          <Btn onClick={() => mesh.reload()}>Refresh</Btn>
        </div>
      </div>
      <div ref={containerRef} style={{ height: 560, border: '1px solid var(--grid)', borderRadius: 'var(--radius)' }} />
      <div className="row dim mt" style={{ fontSize: '0.78rem', gap: 16 }}>
        <span>● mains</span><span>◆ battery</span>
        <span>— solid LWR (RSSI labeled)</span><span>╌ dashed NLWR</span><span>faint neighbor links</span>
        <span>double ring = controller</span><span>X dead</span><span>badge sleeping</span>
      </div>
    </div>
  );
}

function shapeDiamond() {
  // cytoscape shape names: diamond is built in
  return { shape: 'diamond' as const, width: 26, height: 26 };
}
