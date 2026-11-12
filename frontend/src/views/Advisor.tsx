import { useState } from 'react';
import { api } from '../api/client';
import { useApi } from '../hooks/useApp';
import { Card, Btn, ConfirmModal, Pill, type ConfirmSpec } from '../components/ui';
import type { AdvisorReport, Recommendation, RecommendationAction } from '../api/types';

/** Client-side rate limit: one re-run per 15 minutes. */
const RERUN_COOLDOWN_MS = 15 * 60 * 1000;
const RERUN_KEY = 'zwo-advisor-last-run';

function rerunBlocked(): string | null {
  const last = Number(localStorage.getItem(RERUN_KEY) ?? 0);
  const remainMs = last + RERUN_COOLDOWN_MS - Date.now();
  return remainMs > 0 ? `Rate limited — try again in ${Math.ceil(remainMs / 60000)} min` : null;
}

function verificationPending(action: RecommendationAction): string | null {
  if (action.applied && !action.verified && action.verification_started) {
    const days = Math.max(0, 3 - Math.floor((Date.now() - new Date(action.verification_started).getTime()) / 86400000));
    return `verification pending (${days} days left)`;
  }
  return null;
}

function RecCard({ rec, onOpenNode, onApplied }: { rec: Recommendation; onOpenNode: (id: number) => void; onApplied?: () => void }) {
  const [confirm, setConfirm] = useState<ConfirmSpec | null>(null);
  const [showTranscript, setShowTranscript] = useState(false);
  const conf = rec.confidence >= 0.8 ? ['ok', 'high'] : rec.confidence >= 0.5 ? ['warn', 'medium'] : ['danger', 'low'] as const;

  const applyAction = (a: RecommendationAction) => setConfirm({
    title: 'Apply action',
    body: `Apply: ${a.description}?`,
    confirmLabel: 'Apply',
    onConfirm: async () => {
      // rec.id is "r{report_id}-{index}" (from the backend report adapter)
      const m = /^r(\d+)-(\d+)$/.exec(rec.id);
      if (m) await api.advisorApply(Number(m[1]), Number(m[2]));
      onApplied?.();
    },
  });

  return (
    <Card>
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <h3 style={{ margin: 0 }}>Diagnosis</h3>
        <Pill tone={conf[0] as 'ok' | 'warn' | 'danger'}>confidence: {conf[1]} ({Math.round(rec.confidence * 100)}%)</Pill>
      </div>
      <p>{rec.diagnosis}</p>

      <details>
        <summary>Evidence links ({rec.evidence_links.length})</summary>
        <ul>
          {rec.evidence_links.map((l) => <li key={l} className="dim" style={{ fontSize: '0.85rem' }}>{l}</li>)}
        </ul>
      </details>

      <h4 className="mt">Proposed actions</h4>
      {rec.actions.map((a) => {
        const pending = verificationPending(a);
        return (
          <div key={a.id} className="row" style={{ justifyContent: 'space-between', padding: '6px 0', borderBottom: '1px solid var(--grid)' }}>
            <div>
              <span>{a.description}</span>
              <span style={{ marginLeft: 8 }} title={a.validation}>
                {a.validation === 'ok' && <Pill tone="ok">validated</Pill>}
                {a.validation === 'pending' && <Pill tone="dim">pending</Pill>}
                {a.validation === 'failed' && <Pill tone="danger">validation failed</Pill>}
              </span>
              {a.validation === 'failed' && a.validation_error && (
                <div className="dim" style={{ fontSize: '0.8rem' }}>Reason: {a.validation_error}</div>
              )}
              {pending && <div className="dim" style={{ fontSize: '0.8rem' }}>{pending}</div>}
            </div>
            <div style={{ display: 'flex', gap: 6 }}>
              <Btn kind="primary" disabled={a.validation === 'failed' || !!a.applied || !!pending}
                title={a.validation === 'failed' ? a.validation_error : undefined}
                onClick={() => applyAction(a)}>{a.applied ? 'Applied' : 'Fix'}</Btn>
            </div>
          </div>
        );
      })}

      {rec.blocked_reason && <div className="warn-block">Blocked duplicate: {rec.blocked_reason}</div>}

      <div className="row mt">
        <Btn onClick={() => setShowTranscript(!showTranscript)}>{showTranscript ? 'Hide' : 'Show'} tool transcript</Btn>
      </div>
      {showTranscript && (
        <pre style={{ background: 'var(--panel-2)', padding: 10, borderRadius: 8, fontSize: '0.78rem', maxHeight: 240, overflow: 'auto' }}>
          {rec.diagnosis /* transcript served via report detail; placeholder shows markdown */}
        </pre>
      )}
      <ConfirmModal spec={confirm} onClose={() => setConfirm(null)} />
      {rec.verdict && <div className="dim mt" style={{ fontSize: '0.8rem' }}>verdict: {rec.verdict}</div>}
    </Card>
  );
}

export default function Advisor({ onOpenNode }: { onOpenNode?: (id: number) => void }) {
  const latest = useApi(() => api.advisorLatest());
  const history = useApi(() => api.advisorHistory());
  const ledger = useApi(() => api.advisorLedger());
  const [busy, setBusy] = useState(false);
  const [report, setReport] = useState<AdvisorReport | null>(null);
  const [investigating, setInvestigating] = useState<string | null>(null);

  const blocked = rerunBlocked();
  const current = report ?? latest.data;

  const rerun = async () => {
    if (rerunBlocked()) return;
    setBusy(true);
    try {
      const r = await api.advisorAnalyze();
      localStorage.setItem(RERUN_KEY, String(Date.now()));
      setReport(r);
      latest.reload();
    } finally {
      setBusy(false);
    }
  };

  const investigate = async (rec: Recommendation) => {
    setInvestigating(rec.id);
    try {
      const r = await api.advisorInvestigate(rec.id);
      setReport(r);
    } finally {
      setInvestigating(null);
    }
  };

  return (
    <div className="grid" style={{ gridTemplateColumns: 'minmax(0,1fr)' }}>
      <Card>
        <div className="row" style={{ justifyContent: 'space-between' }}>
          <h3>Advisor</h3>
          <div className="row dim" style={{ fontSize: '0.85rem' }}>
            {current && (
              <>
                <span>run {new Date(current.run_at).toLocaleString()}</span>
                <span>· {current.model}</span>
                <span className="num">· {current.tokens ? `${current.tokens.input ?? 0}+${current.tokens.output ?? 0} tok` : 'token usage unavailable'}{current.cost_usd != null ? ` · $${current.cost_usd.toFixed(4)}` : ''}</span>
              </>
            )}
          </div>
          <Btn kind="primary" disabled={busy || !!blocked} title={blocked ?? undefined} onClick={rerun}>
            {busy ? 'Analyzing…' : 'Re-run analysis'}
          </Btn>
        </div>
        {blocked && <div className="warn-block">{blocked}</div>}
      </Card>

      {(current?.recommendations ?? []).map((rec) => (
        <RecCard key={rec.id} rec={rec} onOpenNode={onOpenNode ?? (() => {})} onApplied={() => { latest.reload(); ledger.reload(); }} />
      ))}

      {investigating && <Card><span className="dim">Investigating {investigating}…</span></Card>}

      {current?.markdown && (
        <Card>
          <details>
            <summary>Investigate panel — markdown report</summary>
            <pre style={{ whiteSpace: 'pre-wrap', fontSize: '0.85rem' }}>{current.markdown}</pre>
          </details>
        </Card>
      )}

      <Card>
        <h3>Past recommendations</h3>
        <table className="data">
          <thead><tr><th>Run</th><th>Diagnosis</th><th>Verdict</th><th>Note</th></tr></thead>
          <tbody>
            {(history.data ?? []).flatMap((r) =>
              r.recommendations.map((rec) => (
                <tr key={rec.id}>
                  <td className="num">{new Date(r.run_at).toLocaleDateString()}</td>
                  <td>{rec.diagnosis}</td>
                  <td>{rec.verdict ?? 'pending'}</td>
                  <td className="dim">{rec.blocked_reason ?? ''}</td>
                </tr>
              )),
            )}
            {(ledger.data ?? []).length === 0 && (history.data ?? []).length === 0 && (
              <tr><td colSpan={4} className="dim">No past recommendations.</td></tr>
            )}
          </tbody>
        </table>
      </Card>
    </div>
  );
}
