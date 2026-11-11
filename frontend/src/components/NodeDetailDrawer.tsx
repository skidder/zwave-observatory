import { useMemo, useState } from 'react';
import { api } from '../api/client';
import { useApi } from '../hooks/useApp';
import { Card, Chart, GradeBadge, Pill, Btn, ConfirmModal, type ConfirmSpec } from '../components/ui';
import { gradeColor } from '../lib/healthScore';
import { dropRatePct } from '../lib/stats';
import type { ZwaveNode } from '../api/types';

const ACTIONS = [
  { key: 'ping', label: 'Ping' },
  { key: 'refresh', label: 'Refresh' },
  { key: 'heal', label: 'Heal' },
  { key: 'refresh-routes', label: 'Refresh routes' },
] as const;

export default function NodeDetailDrawer({ nodeId, onClose }: { nodeId: number; onClose: () => void }) {
  const node = useApi(() => api.node(nodeId), [nodeId]);
  const audit = useApi(() => api.audit(), [nodeId]);
  const rssiHistory = useApi(() => api.history('rssi', 14), [nodeId]);
  const framesHistory = useApi(() => api.history('frames', 14), [nodeId]);
  const [confirm, setConfirm] = useState<ConfirmSpec | null>(null);
  const [editingParam, setEditingParam] = useState<number | null>(null);
  const [paramValue, setParamValue] = useState('');

  const n = node.data as ZwaveNode | null;
  const rate = n ? dropRatePct(n.stats.drops, n.stats.tx, n.stats.rx) : 0;

  const auditMarkers = useMemo(() => {
    return (audit.data ?? [])
      .filter((a) => a.node_id === nodeId)
      .map((a) => ({ ts: a.ts, label: a.kind }));
  }, [audit.data, nodeId]);

  const markers = (series: { ts: string; value: number }[]) => ({
    markLine: {
      symbol: 'none',
      lineStyle: { color: 'var(--warn)', type: 'dashed' as const },
      data: auditMarkers
        .filter((m) => series.some((p) => new Date(p.ts) >= new Date(m.ts)))
        .map((m) => ({ xAxis: m.ts, name: m.label })),
      label: { formatter: (p: { name: string }) => p.name },
    },
  });

  const rssiOption = useMemo(() => {
    const payload = rssiHistory.data;
    const arr = Array.isArray(payload) ? payload : payload ? [payload] : [];
    const s = arr[0];
    return {
      grid: { left: 46, right: 10, top: 10, bottom: 26 },
      xAxis: { type: 'category', data: (s?.series ?? []).map((p) => new Date(p.ts).toLocaleDateString()) },
      yAxis: { type: 'value', splitLine: { lineStyle: { color: 'var(--grid)' } } },
      series: [{ type: 'line', showSymbol: false, data: (s?.series ?? []).map((p) => p.value), ...(markers(s?.series ?? []) as object) }],
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rssiHistory.data, auditMarkers]);

  const framesOption = useMemo(() => {
    const payload = framesHistory.data;
    const arr = Array.isArray(payload) ? payload : payload ? [payload] : [];
    const s = arr.find((x) => x.key === String(nodeId)) ?? arr[0];
    return {
      grid: { left: 46, right: 10, top: 10, bottom: 26 },
      xAxis: { type: 'category', data: (s?.series ?? []).map((p) => new Date(p.ts).toLocaleDateString()) },
      yAxis: { type: 'value', splitLine: { lineStyle: { color: 'var(--grid)' } } },
      series: [
        { type: 'line', showSymbol: false, name: 'frames', data: (s?.series ?? []).map((p) => p.value), ...(markers(s?.series ?? []) as object) },
      ],
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [framesHistory.data, auditMarkers, nodeId]);

  return (
    <aside className="drawer" role="dialog" aria-label={`Node ${nodeId} details`}>
      <button className="drawer-close" onClick={onClose} aria-label="Close">✕</button>
      <h2 style={{ marginRight: 32 }}>
        {n ? (n.name || `Node ${n.id}`) : `Node ${nodeId}`}
        {n && <span className="row" style={{ marginLeft: 10 }}><GradeBadge grade={n.grade} /></span>}
      </h2>
      {n && (
        <div className="row dim" style={{ fontSize: '0.85rem' }}>
          {n.loc && <span>📍 {n.loc}</span>}
          <Pill tone={n.power === 'mains' ? 'dim' : 'warn'}>{n.power}</Pill>
          {n.sleeping && <Pill tone="dim">sleeping</Pill>}
          {n.dead && <Pill tone="danger">dead</Pill>}
        </div>
      )}

      {n && (
        <>
          <div className="stat-grid mt">
            <div><div className="stat-label">TX</div><div className="stat-value num">{n.stats.tx}</div></div>
            <div><div className="stat-label">RX</div><div className="stat-value num">{n.stats.rx}</div></div>
            <div><div className="stat-label">Drops</div><div className="stat-value num">{n.stats.drops}</div></div>
            <div><div className="stat-label">Timeouts</div><div className="stat-value num">{n.stats.timeouts}</div></div>
            <div><div className="stat-label">RTT</div><div className="stat-value num">{n.stats.rtt_ms} ms</div></div>
            <div><div className="stat-label">RSSI</div><div className="stat-value num">{n.stats.rssi} dBm</div></div>
            <div><div className="stat-label">SNR</div><div className="stat-value num">{n.stats.snr} dB</div></div>
            <div><div className="stat-label">Drop rate</div><div className="stat-value num">{rate.toFixed(1)}%</div></div>
          </div>

          <div className="card mt" style={{ background: 'var(--panel-2)', boxShadow: 'none' }}>
            <div className="stat-label">Score</div>
            <div className="row" style={{ gap: 12 }}>
              <GradeBadge grade={n.grade} size={34} />
              <span style={{ color: gradeColor(n.grade), fontWeight: 600 }}>
                {n.grade === 'A' ? 'healthy' : n.grade === 'B' ? 'good' : n.grade === 'C' ? 'fair' : 'degraded'}
              </span>
            </div>
            <div className="dim mt" style={{ fontSize: '0.82rem' }}>Penalties shown in the network score panel on Overview.</div>
          </div>

          <h4 className="mt">Route path</h4>
          <RouteDiagram nodeId={n.id} repeaters={n.routes.repeaters} direct={n.routes.direct} />

          <h4 className="mt">History (14d)</h4>
          <div className="stat-label">Frames</div>
          <Chart option={framesOption as never} height={150} />
          <div className="stat-label mt">Drops & RSSI</div>
          <Chart option={rssiOption as never} height={150} />
          <p className="dim" style={{ fontSize: '0.78rem' }}>Dashed markers = audit log events (heals, config changes).</p>

          <h4 className="mt">Home Assistant entities</h4>
          {n.ha_entities.length === 0 && <p className="dim">None linked.</p>}
          <table className="data">
            <tbody>
              {n.ha_entities.map((e) => (
                <tr key={e.entity_id}><td>{e.name}</td><td><code style={{ fontSize: '0.78rem' }}>{e.entity_id}</code></td><td className="num">{e.state}</td></tr>
              ))}
            </tbody>
          </table>

          <h4 className="mt">Config parameters</h4>
          <table className="data">
            <thead><tr><th>#</th><th>Name</th><th>Value</th><th></th></tr></thead>
            <tbody>
              {n.params.map((p) => (
                <tr key={p.id}>
                  <td className="num">{p.id}</td>
                  <td>{p.name}{p.referenced_steps && p.referenced_steps.length > 0 && (
                    <div className="dim" style={{ fontSize: '0.75rem' }}>referenced by automation: {p.referenced_steps.join(', ')}</div>
                  )}</td>
                  <td className="num">{p.value}</td>
                  <td>
                    <Btn onClick={() => { setEditingParam(p.id); setParamValue(String(p.value)); }}>Edit</Btn>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {editingParam !== null && (
            <div className="warn-block">
              <div className="stat-label" style={{ marginBottom: 4 }}>Edit parameter #{editingParam}</div>
              <div className="row">
                <input type="text" value={paramValue} onChange={(e) => setParamValue(e.target.value)} style={{ width: 120 }} />
                <Btn onClick={() => setConfirm({
                  title: `Set parameter #${editingParam}`,
                  body: `Write value "${paramValue}" to node ${n.id}? This may affect automations that reference this parameter.`,
                  confirmLabel: 'Write parameter',
                  onConfirm: async () => { await api.nodeAction(n.id, 'params' as never); },
                })}>Save</Btn>
                <Btn onClick={() => setEditingParam(null)}>Cancel</Btn>
              </div>
            </div>
          )}

          <h4 className="mt">Actions</h4>
          <div className="row">
            {ACTIONS.map((a) => (
              <Btn key={a.key} onClick={() => setConfirm({
                title: `${a.label} node ${n.id}`,
                body: `Run "${a.label}" on ${n.name || `node ${n.id}`}? This will be recorded in the audit log.`,
                confirmLabel: a.label,
                onConfirm: async () => { await api.nodeAction(n.id, a.key); node.reload(); },
              })}>{a.label}</Btn>
            ))}
          </div>
        </>
      )}
      {node.error && <p style={{ color: 'var(--danger)' }}>Failed to load node: {node.error}</p>}
      <ConfirmModal spec={confirm} onClose={() => setConfirm(null)} />
    </aside>
  );
}

function RouteDiagram({ nodeId, repeaters, direct }: { nodeId: number; repeaters: number[]; direct: boolean }) {
  const chain = [nodeId, ...repeaters, 1];
  return (
    <div className="row" style={{ gap: 6 }}>
      {chain.map((id, i) => (
        <span key={`${id}-${i}`} className="row" style={{ gap: 6 }}>
          {i > 0 && <span className="dim">→</span>}
          <span
            style={{
              display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
              minWidth: 34, height: 30, padding: '0 6px',
              borderRadius: id === 1 ? 999 : 8,
              border: `2px solid ${id === 1 ? 'var(--accent)' : 'var(--grid)'}`,
              color: id === 1 ? 'var(--accent)' : 'var(--text)',
              fontWeight: 600, fontSize: '0.8rem',
            }}
          >{id}</span>
        </span>
      ))}
      <span className="dim" style={{ fontSize: '0.8rem' }}>{direct ? '· direct LWR' : repeaters.length > 0 ? `· ${repeaters.length} repeater(s)` : '· no known route'}</span>
    </div>
  );
}
