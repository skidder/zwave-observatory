import { useState } from 'react';
import { api } from '../api/client';
import { useApi, useTheme } from '../hooks/useApp';
import { Card, Btn } from '../components/ui';
import { dismissalDaysLeft } from '../lib/problems';

/** Score threshold config is displayed read-only (backend-owned). */
const DEFAULT_THRESHOLDS = [
  { name: 'A / B boundary', value: 90 },
  { name: 'B / C boundary', value: 75 },
  { name: 'C / D boundary', value: 60 },
  { name: 'D / F boundary', value: 40 },
  { name: 'Controller jam share amber', value: '5%' },
  { name: 'Controller jam share red', value: '15%' },
];

export default function Settings() {
  const [theme, setTheme] = useTheme();
  const audit = useApi(() => api.audit());
  const problems = useApi(() => api.problems());
  const [busy, setBusy] = useState(false);
  void audit;

  const dismissed = (problems.data ?? []).filter((p) => dismissalDaysLeft(p.dismissed_until) != null);

  return (
    <div className="grid cols-2">
      <Card>
        <h3>Backend</h3>
        <p className="dim" style={{ fontSize: '0.88rem' }}>
          URL (read-only, served via same origin): <code>{typeof window !== 'undefined' ? window.location.origin : ''}</code>
        </p>
        <p className="dim" style={{ fontSize: '0.88rem' }}>API endpoints are proxied from <code>/api</code>; live events via <code>/ws/live</code>.</p>
      </Card>

      <Card>
        <h3>Appearance</h3>
        <div className="row">
          {(['light', 'dark', 'system'] as const).map((t) => (
            <span key={t} className={`chip ${theme === t ? 'active' : ''}`} onClick={() => setTheme(t)}>{t}</span>
          ))}
        </div>
        <p className="dim mt" style={{ fontSize: '0.82rem' }}>Stored in localStorage; 'system' follows your OS preference.</p>
      </Card>

      <Card>
        <h3>Score thresholds</h3>
        <table className="data">
          <thead><tr><th>Boundary</th><th>Value</th></tr></thead>
          <tbody>
            {DEFAULT_THRESHOLDS.map((t) => (
              <tr key={t.name}><td>{t.name}</td><td className="num">{t.value}</td></tr>
            ))}
          </tbody>
        </table>
        <p className="dim mt" style={{ fontSize: '0.82rem' }}>Read-only — thresholds are owned by the backend scoring service.</p>
      </Card>

      <Card>
        <h3>Advisor configuration</h3>
        <table className="data">
          <tbody>
            <tr><td>Model</td><td><code>llama-3.1-8b-instruct</code> (reported by backend)</td></tr>
            <tr><td>API key</td><td><code>••••••••</code> (masked)</td></tr>
            <tr><td>Analyze endpoint</td><td><code>POST /api/advisor/analyze</code></td></tr>
            <tr><td>Investigate endpoint</td><td><code>POST /api/advisor/investigate</code></td></tr>
          </tbody>
        </table>
      </Card>

      <Card>
        <h3>Problem dismissals</h3>
        {dismissed.length === 0 && <p className="dim">No active dismissals.</p>}
        {dismissed.map((p) => (
          <div key={p.id} className="row" style={{ justifyContent: 'space-between', padding: '4px 0' }}>
            <span>{p.message}</span>
            <span className="dim num">{dismissalDaysLeft(p.dismissed_until)}d left</span>
          </div>
        ))}
        <div className="mt">
          <Btn disabled={busy || dismissed.length === 0} onClick={async () => {
            setBusy(true);
            try { await Promise.all(dismissed.map((p) => api.dismissProblem(p.id))); problems.reload(); }
            finally { setBusy(false); }
          }}>Clear dismissals (re-show now)</Btn>
        </div>
      </Card>
    </div>
  );
}
