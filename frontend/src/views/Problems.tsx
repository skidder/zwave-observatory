import { useMemo, useState } from 'react';
import { api } from '../api/client';
import { useApi } from '../hooks/useApp';
import { Card, SeverityChip, Chart, Btn, ConfirmModal, type ConfirmSpec } from '../components/ui';
import { rankProblems, filterProblems, problemTypes, trendArrow, dismissalDaysLeft } from '../lib/problems';
import type { Problem, Severity } from '../api/types';

const SEVERITIES: (Severity | 'all')[] = ['all', 'critical', 'high', 'medium', 'low'];

export default function ProblemsView({ onOpenNode }: { onOpenNode: (id: number) => void }) {
  const problems = useApi(() => api.problems());
  const [sevFilter, setSevFilter] = useState<Severity | 'all'>('all');
  const [typeFilter, setTypeFilter] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<ConfirmSpec | null>(null);

  const all = useMemo(() => rankProblems((problems.data ?? []) as Problem[]), [problems.data]);
  const types = useMemo(() => problemTypes(all), [all]);
  const filtered = filterProblems(all, { severity: sevFilter === 'all' ? null : sevFilter, type: typeFilter });

  const evidenceOption = (p: Problem) => ({
    grid: { left: 40, right: 8, top: 8, bottom: 24 },
    xAxis: { type: 'category', data: p.evidence.map((e) => new Date(e.ts).toLocaleDateString()) },
    yAxis: { type: 'value', splitLine: { lineStyle: { color: 'var(--grid)' } } },
    series: [{ type: 'bar', data: p.evidence.map((e) => e.value), itemStyle: { color: 'var(--accent)' } }],
  });

  return (
    <Card>
      <div className="row" style={{ justifyContent: 'space-between', marginBottom: 10 }}>
        <div className="row">
          {SEVERITIES.map((s) => (
            <span key={s} className={`chip ${sevFilter === s ? 'active' : ''}`} onClick={() => setSevFilter(s)}>{s}</span>
          ))}
          <span className="dim">|</span>
          <span className={`chip ${typeFilter === null ? 'active' : ''}`} onClick={() => setTypeFilter(null)}>all types</span>
          {types.map((t) => (
            <span key={t} className={`chip ${typeFilter === t ? 'active' : ''}`} onClick={() => setTypeFilter(t)}>{t}</span>
          ))}
        </div>
      </div>

      <table className="data">
        <thead>
          <tr>
            <th>Severity</th><th>Type</th><th>Node</th><th>First seen</th><th>Trend (14d)</th><th></th>
          </tr>
        </thead>
        <tbody>
          {filtered.map((p) => {
            const arrow = trendArrow(p.trend);
            const daysLeft = dismissalDaysLeft(p.dismissed_until);
            return (
              <FragmentRow
                key={p.id} p={p} arrow={arrow} daysLeft={daysLeft}
                expanded={expanded === p.id}
                evidenceOption={evidenceOption(p)}
                onToggle={() => setExpanded(expanded === p.id ? null : p.id)}
                onOpenNode={onOpenNode}
                onDismiss={() => setConfirm({
                  title: 'Dismiss problem',
                  body: `Dismiss "${p.message}" for 7 days?`,
                  confirmLabel: 'Dismiss',
                  onConfirm: async () => { await api.dismissProblem(p.id); problems.reload(); },
                })}
                onFix={() => setConfirm({
                  title: `Fix: ${p.type}`,
                  body: `Attempt an automated fix for "${p.message}"?`,
                  confirmLabel: 'Fix',
                  onConfirm: async () => {
                    if (p.node_id != null) await api.nodeAction(p.node_id, 'heal');
                    problems.reload();
                  },
                })}
              />
            );
          })}
          {filtered.length === 0 && (
            <tr><td colSpan={6} className="dim">No problems match the current filters.</td></tr>
          )}
        </tbody>
      </table>

      <ConfirmModal spec={confirm} onClose={() => setConfirm(null)} />
    </Card>
  );
}

import { Fragment } from 'react';
function FragmentRow({ p, arrow, daysLeft, expanded, evidenceOption, onToggle, onOpenNode, onDismiss, onFix }: {
  p: Problem; arrow: 'up' | 'down' | 'flat'; daysLeft: number | null; expanded: boolean;
  evidenceOption: Record<string, unknown>; onToggle: () => void;
  onOpenNode: (id: number) => void; onDismiss: () => void; onFix: () => void;
}) {
  const arrowSym = arrow === 'up' ? '▲ worsening' : arrow === 'down' ? '▼ improving' : '— flat';
  return (
    <Fragment key={p.id}>
      <tr className="clickable" onClick={onToggle}>
        <td><SeverityChip severity={p.severity} /></td>
        <td>{p.type}</td>
        <td>{p.node_id != null && <a href="#" onClick={(e) => { e.stopPropagation(); onOpenNode(p.node_id!); }}>Node {p.node_id}</a>}</td>
        <td className="num">{new Date(p.first_seen).toLocaleString()}</td>
        <td className="num">{arrowSym} ({p.trend.toFixed(2)}/day)</td>
        <td style={{ whiteSpace: 'nowrap' }}>
          {daysLeft != null && <span className="dim" style={{ marginRight: 8 }}>dismissed ({daysLeft}d left)</span>}
          <Btn onClick={() => { onFix(); }}>Fix</Btn>{' '}
          <Btn onClick={() => { onDismiss(); }}>Dismiss 7d</Btn>
        </td>
      </tr>
      {expanded && (
        <tr>
          <td colSpan={6}>
            <div style={{ padding: 8 }}>
              <p style={{ marginTop: 0 }}>{p.message}</p>
              <Chart option={evidenceOption as never} height={200} />
            </div>
          </td>
        </tr>
      )}
    </Fragment>
  );
}
