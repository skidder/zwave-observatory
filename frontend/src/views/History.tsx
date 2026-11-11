import { useMemo, useState } from 'react';
import { api } from '../api/client';
import { useApi } from '../hooks/useApp';
import { Card, Chart } from '../components/ui';

const RANGES = [1, 7, 14, 30, 90];

export default function History() {
  const [days, setDays] = useState(14);
  const controller = useApi(() => api.history('controller', days), [days]);
  const frames = useApi(() => api.history('frames', days), [days]);
  const drops = useApi(() => api.history('drops', days), [days]);
  const rssi = useApi(() => api.history('rssi', days), [days]);

  const grid = { left: 46, right: 12, top: 40, bottom: 26 };

  const toLines = (res: { data: unknown }) => {
    const payload = res.data;
    const arr = (Array.isArray(payload) ? payload : payload ? [payload] : []) as { key?: string; series?: { ts: string; value: number }[] }[];
    return arr.filter((s) => Array.isArray(s.series)).map((s) => ({
      name: s.key ?? 'series',
      type: 'line' as const,
      showSymbol: false,
      smooth: true,
      data: (s.series ?? []).map((p) => [p.ts, p.value]),
    }));
  };

  const timeAxis = (data: { ts: string; value: number }[][]) => {
    const ts = new Set<string>();
    for (const series of data) for (const p of series) ts.add(p.ts);
    return [...ts].sort().map((t) => new Date(t).toLocaleDateString());
  };

  const controllerOption = useMemo(() => {
    const payload = controller.data;
    const arr = Array.isArray(payload) ? payload : payload ? [payload] : [];
    const jam = arr.find((s) => s.key === 'jam_share');
    const f = arr.find((s) => s.key === 'frames_per_day');
    const d = arr.find((s) => s.key === 'dropped_per_day');
    const c = arr.find((s) => s.key === 'collisions');
    return {
      grid,
      legend: { top: 0, type: 'scroll', textStyle: { color: 'var(--text-dim)', fontSize: 10 } },
      xAxis: { type: 'category', data: timeAxis([jam?.series ?? f?.series ?? [], d?.series ?? [], c?.series ?? []]) },
      yAxis: { type: 'value', splitLine: { lineStyle: { color: 'var(--grid)' } } },
      series: [jam, f, d, c].filter(Boolean).map((s) => ({
        name: s!.key,
        type: 'line' as const,
        areaStyle: s!.key === 'jam_share' ? { opacity: 0.15 } : undefined,
        showSymbol: false,
        data: s!.series.map((p) => [new Date(p.ts).toLocaleDateString(), p.value]),
      })),
    };
  }, [controller.data]);

  const framesOption = useMemo(() => ({
    grid,
    xAxis: { type: 'category', data: timeAxis((Array.isArray(frames.data) ? frames.data : []).map((s) => s.series)) },
    yAxis: { type: 'value', splitLine: { lineStyle: { color: 'var(--grid)' } } },
    series: toLines(frames),
  }), [frames.data]);

  const dropsOption = useMemo(() => ({ grid, xAxis: { type: 'category', data: [] }, yAxis: { type: 'value' }, series: toLines(drops) }), [drops.data]);
  const rssiOption = useMemo(() => ({ grid, xAxis: { type: 'category', data: [] }, yAxis: { type: 'value' }, series: toLines(rssi) }), [rssi.data]);

  return (
    <div className="grid cols-2">
      <Card>
        <div className="row" style={{ justifyContent: 'space-between' }}>
          <h3>History</h3>
          <div className="row">
            {RANGES.map((d) => (
              <span key={d} className={`chip ${days === d ? 'active' : ''}`} onClick={() => setDays(d)}>{d}d</span>
            ))}
          </div>
        </div>
        <h3 className="mt">Controller</h3>
        <Chart option={controllerOption as never} height={260} />
      </Card>

      <Card>
        <h3>Per-node</h3>
        <div className="row dim" style={{ fontSize: '0.85rem', marginBottom: 8 }}>
          <span>Select nodes to compare — top talkers, drop rate and RSSI.</span>
        </div>
        <div className="stat-label">Frames/day</div>
        <Chart option={framesOption as never} height={180} />
        <div className="stat-label mt">Drops/day</div>
        <Chart option={dropsOption as never} height={180} />
        <div className="stat-label mt">RSSI</div>
        <Chart option={rssiOption as never} height={180} />
      </Card>
    </div>
  );
}
