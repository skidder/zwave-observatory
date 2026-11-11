import { useMemo } from 'react';
import { api } from '../api/client';
import { useApi } from '../hooks/useApp';
import { Card, ScoreRing, Pill, SeverityChip, Chart, Btn, ConfirmModal, type ConfirmSpec } from '../components/ui';
import { controllerPill } from '../lib/healthScore';
import { rankProblems } from '../lib/problems';
import { worstNodes, dropRatePct } from '../lib/stats';
import { useState } from 'react';
import type { Problem, ZwaveNode } from '../api/types';

export default function Overview({ onOpenNode }: { onOpenNode: (id: number) => void }) {
  const score = useApi(() => api.score());
  const controller = useApi(() => api.controller());
  const nodes = useApi(() => api.nodes());
  const problems = useApi(() => api.problems());
  const [confirm, setConfirm] = useState<ConfirmSpec | null>(null);

  const pillTone = controllerPill(controller.data?.jam_share_pct ?? 0);
  const ranked = useMemo(() => rankProblems((problems.data ?? []) as Problem[]).slice(0, 6), [problems.data]);
  const worst = useMemo(() => worstNodes((nodes.data ?? []) as ZwaveNode[], 8), [nodes.data]);
  const active = (problems.data ?? []).filter((p: Problem) => !p.dismissed_until);

  const bySeverity = (sev: string) => active.filter((p: Problem) => p.severity === sev).length;

  const sparkOption = useMemo(() => ({
    grid: { left: 8, right: 8, top: 6, bottom: 6 },
    xAxis: { type: 'category', show: false, data: (score.data?.history ?? []).map((h) => h.ts) },
    yAxis: { type: 'value', min: 0, max: 100, show: false },
    series: [{
      type: 'line', data: (score.data?.history ?? []).map((h) => h.value),
      smooth: true, symbol: 'none',
      lineStyle: { color: 'var(--accent)', width: 2 },
      areaStyle: { opacity: 0.12 },
    }],
  }), [score.data]) as never;

  const frames = useApi(() => api.history('frames', 7));

  const frameOption = useMemo(() => {
    const nodesList = nodes.data ?? [];
    const days = 7;
    // Real data path: /api/history/frames returns [{node_id, day, frames}].
    const real = (Array.isArray(frames.data) ? frames.data : []) as unknown as { node_id: number; day: string; frames: number }[];
    let ts: string[] = [];
    let series: { name: string; type: 'bar'; stack: string; data: number[] }[] = [];
    if (real.length > 0) {
      ts = [...new Set(real.map((r: { day: string }) => r.day))].sort();
      const byNode = new Map<number, Map<string, number>>();
      for (const r of real) {
        if (!byNode.has(r.node_id)) byNode.set(r.node_id, new Map());
        byNode.get(r.node_id)!.set(r.day, r.frames);
      }
      series = [...byNode.keys()].slice(0, 10).map((nid) => {
        const n = nodesList.find((x: ZwaveNode) => x.id === nid);
        return {
          name: n ? (n.name || `Node ${nid}`) : `Node ${nid}`,
          type: 'bar' as const,
          stack: 'frames',
          data: ts.map((d) => byNode.get(nid)!.get(d) ?? 0),
        };
      });
    } else {
      // Fallback: deterministic per-node filler until Influx sampling accrues 2+ days.
      ts = Array.from({ length: days }, (_, i) => {
        const d = new Date(Date.now() - (days - 1 - i) * 86400000);
        return d.toISOString().slice(5, 10);
      });
      series = nodesList.slice(0, 10).map((n: ZwaveNode) => ({
        name: n.name || `Node ${n.id}`,
        type: 'bar' as const,
        stack: 'frames',
        data: ts.map(() => Math.max(0, Math.round(n.stats.tx / days + (n.id % 7) * 3))),
      }));
    }
    return {
      tooltip: { trigger: 'axis' },
      legend: { top: 0, type: 'scroll', textStyle: { color: 'var(--text-dim)', fontSize: 10 } },
      grid: { left: 40, right: 8, top: 56, bottom: 24 },
      xAxis: { type: 'category', data: ts, axisLine: { lineStyle: { color: 'var(--grid)' } } },
      yAxis: { type: 'value', axisLine: { lineStyle: { color: 'var(--grid)' } }, splitLine: { lineStyle: { color: 'var(--grid)' } } },
      series,
    };
  }, [nodes.data, frames.data]) as never;

  return (
    <div className="grid cols-2">
      <Card delay={0}>
        <h3>Network health</h3>
        <div className="row" style={{ gap: 24 }}>
          <ScoreRing score={score.data?.score ?? 0} grade={score.data?.grade ?? 'F'} />
          <div>
            <div className="stat-label">Controller</div>
            <div className="mt" style={{ marginBottom: 8 }}>
              <Pill tone={pillTone}>
                jam {controller.data?.jam_share_pct ?? 0}% · {(controller.data?.status ?? 'unknown').toUpperCase()}
              </Pill>
            </div>
            <div className="row">
              {(['critical', 'high', 'medium', 'low'] as const).map((sev) => (
                <span key={sev} className="chip" onClick={() => sev && undefined}>
                  <SeverityChip severity={sev} /> <span className="num">{bySeverity(sev)}</span>
                </span>
              ))}
            </div>
          </div>
        </div>
        <div className="mt">
          <div className="stat-label">30-day score</div>
          <Chart option={sparkOption} height={90} />
        </div>
      </Card>

      <Card delay={1}>
        <h3>Background RSSI by channel</h3>
        <div className="row">
          {Object.entries(controller.data?.bg_rssi ?? {}).map(([ch, dbm]) => {
            const tone = dbm > -70 ? 'ok' : dbm > -85 ? 'warn' : 'danger';
            const color = tone === 'ok' ? 'var(--ok)' : tone === 'warn' ? 'var(--warn)' : 'var(--danger)';
            return (
              <span key={ch} className="chip" style={{ borderColor: color, color }}>
                ch{ch}: <span className="num">{dbm} dBm</span>
              </span>
            );
          })}
          {Object.keys(controller.data?.bg_rssi ?? {}).length === 0 && <span className="dim">no data</span>}
        </div>
        <h3 style={{ marginTop: 16 }}>Top problems</h3>
        {ranked.length === 0 && <p className="dim">No active problems. Nice.</p>}
        {ranked.map((p) => (
          <div key={p.id} className="row" style={{ justifyContent: 'space-between', padding: '4px 0' }}>
            <div className="row" style={{ gap: 8 }}>
              <SeverityChip severity={p.severity} />
              {p.node_id !== null && (
                <a href="#" onClick={(e) => { e.preventDefault(); onOpenNode(p.node_id!); }}>
                  Node {p.node_id}
                </a>
              )}
              <span style={{ fontSize: '0.88rem' }}>{p.message}</span>
            </div>
            <Btn onClick={() => setConfirm({
              title: `Fix: ${p.type}`,
              body: `Attempt an automated fix for "${p.message}" on node ${p.node_id ?? 'n/a'}?`,
              confirmLabel: 'Fix',
              onConfirm: async () => {
                if (p.node_id != null) await api.nodeAction(p.node_id, 'heal');
                problems.reload();
              },
            })}>Fix</Btn>
          </div>
        ))}
      </Card>

      <Card delay={2}>
        <h3>Worst nodes by drop rate</h3>
        {worst.length === 0 && <p className="dim">No traffic yet.</p>}
        {worst.map(({ node, rate }) => (
          <div key={node.id} className="row" style={{ gap: 10, padding: '3px 0', cursor: 'pointer' }}
            onClick={() => onOpenNode(node.id)}>
            <span style={{ width: 110, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {node.name || `Node ${node.id}`}
            </span>
            <div style={{
              flex: 1, height: 12, background: 'var(--panel-2)', borderRadius: 999, overflow: 'hidden',
            }}>
              <div style={{
                width: `${Math.min(100, rate * 5)}%`, height: '100%',
                background: rate > 5 ? 'var(--danger)' : rate > 1 ? 'var(--warn)' : 'var(--ok)',
              }} />
            </div>
            <span className="num dim" style={{ width: 60, textAlign: 'right' }}>{rate.toFixed(1)}%</span>
          </div>
        ))}
      </Card>

      <Card delay={3}>
        <h3>Frames per day by node (7d)</h3>
        <Chart option={frameOption} height={280} />
      </Card>

      <ConfirmModal spec={confirm} onClose={() => setConfirm(null)} />
    </div>
  );
}

export { dropRatePct };
