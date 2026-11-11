import { useEffect, useState } from 'react';
import type { Theme } from '../api/types';

export function useApi<T>(fn: () => Promise<T>, deps: unknown[] = []): { data: T | null; error: string | null; reload: () => void } {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let alive = true;
    fn()
      .then((d) => { if (alive) { setData(d); setError(null); } })
      .catch((e) => { if (alive) setError(String(e?.message ?? e)); });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  return { data, error, reload: () => setTick((t) => t + 1) };
}

export function useTheme(): [Theme, (t: Theme) => void] {
  const [theme, setThemeState] = useState<Theme>(() => {
    const stored = localStorage.getItem('zwo-theme');
    return stored === 'light' || stored === 'dark' || stored === 'system' ? stored : 'system';
  });
  const apply = (t: Theme) => {
    const resolved = t === 'system'
      ? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
      : t;
    document.documentElement.setAttribute('data-theme', resolved);
  };
  useEffect(() => {
    apply(theme);
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const onChange = () => { if (theme === 'system') apply('system'); };
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  }, [theme]);
  const setTheme = (t: Theme) => {
    localStorage.setItem('zwo-theme', t);
    setThemeState(t);
  };
  return [theme, setTheme];
}

/** Live websocket feed; returns the latest message objects. */
export function useLiveFeed(max = 100) {
  const [events, setEvents] = useState<Record<string, unknown>[]>([]);
  const [connected, setConnected] = useState(false);
  useEffect(() => {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    let ws: WebSocket | null = null;
    let closed = false;
    const connect = () => {
      ws = new WebSocket(`${proto}://${location.host}/ws/live`);
      ws.onopen = () => setConnected(true);
      ws.onclose = () => { setConnected(false); if (!closed) setTimeout(connect, 3000); };
      ws.onmessage = (ev) => {
        try { setEvents((prev) => [...prev.slice(-max), JSON.parse(ev.data)]); } catch { /* ignore */ }
      };
    };
    connect();
    return () => { closed = true; ws?.close(); };
  }, [max]);
  return { events, connected };
}
