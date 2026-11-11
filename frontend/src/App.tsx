import { useEffect, useState } from 'react';
import { api } from './api/client';
import { useApi, useTheme, useLiveFeed } from './hooks/useApp';
import { Pill } from './components/ui';
import Overview from './views/Overview';
import MeshMap from './views/MeshMap';
import ProblemsView from './views/Problems';
import History from './views/History';
import Advisor from './views/Advisor';
import Settings from './views/Settings';
import Setup from './views/Setup';
import NodeDetailDrawer from './components/NodeDetailDrawer';

const TABS = ['Overview', 'Mesh Map', 'Problems', 'History', 'Advisor', 'Settings'] as const;
export type Tab = (typeof TABS)[number];

export default function App() {
  const [tab, setTab] = useState<Tab>('Overview');
  const [theme, setTheme] = useTheme();
  const [setupDone, setSetupDone] = useState<boolean | null>(null);
  const [detailNodeId, setDetailNodeId] = useState<number | null>(null);
  const { connected } = useLiveFeed();
  const version = useApi(() => api.version());

  useEffect(() => {
    api.setupStatus().then((s) => setSetupDone(s.configured)).catch(() => setSetupDone(true));
  }, []);

  if (setupDone === false) {
    return <Setup onDone={() => setSetupDone(true)} />;
  }

  const openNode = (id: number) => setDetailNodeId(id);

  return (
    <div className="app-shell">
      <header className="app-header">
        <h1>Z-Wave Health Observatory</h1>
        <nav className="tabs">
          {TABS.map((t) => (
            <button key={t} className={t === tab ? 'active' : ''} onClick={() => setTab(t)}>{t}</button>
          ))}
        </nav>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 8, alignItems: 'center' }}>
          <Pill tone={connected ? 'ok' : 'warn'}>{connected ? 'live' : 'offline'}</Pill>
          <select
            aria-label="Theme"
            value={theme}
            onChange={(e) => setTheme(e.target.value as 'light' | 'dark' | 'system')}
            style={{ width: 'auto' }}
          >
            <option value="system">Theme: system</option>
            <option value="light">Theme: light</option>
            <option value="dark">Theme: dark</option>
          </select>
        </div>
      </header>

      {tab === 'Overview' && <Overview onOpenNode={openNode} />}
      {tab === 'Mesh Map' && <MeshMap onOpenNode={openNode} />}
      {tab === 'Problems' && <ProblemsView onOpenNode={openNode} />}
      {tab === 'History' && <History />}
      {tab === 'Advisor' && <Advisor onOpenNode={openNode} />}
      {tab === 'Settings' && <Settings />}

      {detailNodeId !== null && (
        <NodeDetailDrawer nodeId={detailNodeId} onClose={() => setDetailNodeId(null)} />
      )}

      <footer className="dim" style={{ marginTop: 24, fontSize: '0.78rem' }}>
        {version.data ? `api ${version.data.api}` : ''} · frontend 0.1.0
      </footer>
    </div>
  );
}
