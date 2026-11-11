import { useEffect, useRef, useState, type ReactNode } from 'react';
import * as echarts from 'echarts';
import type { Severity, HealthGrade } from '../api/types';
import { severityColor, gradeColor } from '../lib/healthScore';

/* ---------- ECharts wrapper (reads CSS custom properties for theme) ---------- */

function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

export function Chart({ option, height = 260, onEvents }: {
  option: echarts.EChartsOption;
  height?: number;
  onEvents?: Record<string, (params: unknown) => void>;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current);
    chartRef.current = chart;
    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(ref.current);
    if (onEvents) {
      for (const [ev, handler] of Object.entries(onEvents)) chart.on(ev, handler as never);
    }
    return () => { ro.disconnect(); chart.dispose(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    chartRef.current?.setOption({
      textStyle: { color: cssVar('--text-dim'), fontFamily: 'inherit' },
      ...option,
    }, { notMerge: true });
  }, [option]);

  return <div ref={ref} style={{ width: '100%', height }} />;
}

/* ---------- Chips, pills, cards ---------- */

export function SeverityChip({ severity }: { severity: Severity | string }) {
  const c = severityColor(severity);
  return (
    <span style={{
      display: 'inline-block', padding: '1px 9px', borderRadius: 999,
      background: c, color: 'var(--bg)', fontSize: '0.75rem', fontWeight: 600,
    }}>{severity}</span>
  );
}

export function GradeBadge({ grade, size = 22 }: { grade: HealthGrade; size?: number }) {
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
      width: size, height: size, borderRadius: '50%',
      border: `2px solid ${gradeColor(grade)}`, color: gradeColor(grade),
      fontWeight: 600, fontSize: size * 0.5,
    }}>{grade}</span>
  );
}

export function Pill({ tone, children }: { tone: 'ok' | 'warn' | 'danger' | 'dim'; children: ReactNode }) {
  const color = tone === 'ok' ? 'var(--ok)' : tone === 'warn' ? 'var(--warn)' : tone === 'danger' ? 'var(--danger)' : 'var(--text-dim)';
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 6,
      padding: '2px 12px', borderRadius: 999, border: `1px solid ${color}`, color,
      fontSize: '0.8rem', fontWeight: 600,
    }}>{children}</span>
  );
}

export function Card({ children, style, delay = 0 }: { children: ReactNode; style?: React.CSSProperties; delay?: number }) {
  return (
    <div className="card stagger" style={{ ...style, animationDelay: `${delay * 60}ms` }}>{children}</div>
  );
}

/* ---------- Score ring ---------- */

export function ScoreRing({ score, grade, size = 140 }: { score: number; grade: HealthGrade; size?: number }) {
  const [shown, setShown] = useState(0);
  useEffect(() => {
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reduced) { setShown(score); return; }
    const start = performance.now();
    let raf = 0;
    const step = (t: number) => {
      const p = Math.min(1, (t - start) / 900);
      setShown(Math.round(score * (1 - Math.pow(1 - p, 3))));
      if (p < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [score]);

  const r = size / 2 - 10;
  const circ = 2 * Math.PI * r;
  const col = gradeColor(grade);
  return (
    <div style={{ position: 'relative', width: size, height: size }}>
      <svg width={size} height={size}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--grid)" strokeWidth={9} />
        <circle
          cx={size / 2} cy={size / 2} r={r} fill="none" stroke={col} strokeWidth={9}
          strokeLinecap="round" strokeDasharray={circ}
          strokeDashoffset={circ * (1 - shown / 100)}
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
          style={{ transition: 'stroke-dashoffset 50ms linear' }}
        />
      </svg>
      <div style={{
        position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column',
        alignItems: 'center', justifyContent: 'center',
      }}>
        <span className="num" style={{ fontSize: size * 0.28, fontWeight: 600, lineHeight: 1 }}>{shown}</span>
        <span style={{ color: col, fontWeight: 600 }}>{grade}</span>
      </div>
    </div>
  );
}

/* ---------- Confirmation modal ---------- */

export interface ConfirmSpec {
  title: string;
  body: string;
  confirmLabel?: string;
  onConfirm: () => Promise<void> | void;
}

export function ConfirmModal({ spec, onClose }: { spec: ConfirmSpec | null; onClose: () => void }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  if (!spec) return null;
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h3>{spec.title}</h3>
        <p style={{ color: 'var(--text-dim)' }}>{spec.body}</p>
        {err && <p style={{ color: 'var(--danger)' }}>{err}</p>}
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 12 }}>
          <button className="btn" onClick={onClose}>Cancel</button>
          <button
            className="btn btn-primary"
            disabled={busy}
            onClick={async () => {
              setBusy(true); setErr(null);
              try { await spec.onConfirm(); onClose(); }
              catch (e) { setErr(String((e as Error).message)); }
              finally { setBusy(false); }
            }}
          >{busy ? 'Working…' : spec.confirmLabel ?? 'Confirm'}</button>
        </div>
      </div>
    </div>
  );
}

/* ---------- Small buttons ---------- */

export function Btn({ children, onClick, kind = 'default', disabled, title }: {
  children: ReactNode; onClick?: () => void; kind?: 'default' | 'primary' | 'danger'; disabled?: boolean; title?: string;
}) {
  return (
    <button
      className={`btn ${kind === 'primary' ? 'btn-primary' : kind === 'danger' ? 'btn-danger' : ''}`}
      onClick={onClick} disabled={disabled} title={title}
    >{children}</button>
  );
}
