// Problem sorting / ranking / trend helpers.
import type { Problem, Severity } from '../api/types';

const SEV_RANK: Record<Severity, number> = { critical: 0, high: 1, medium: 2, low: 3 };

/** Rank: severity first (critical..low), then trend (worsening first), then oldest first. */
export function rankProblems(problems: Problem[]): Problem[] {
  return [...problems].sort((a, b) => {
    const s = SEV_RANK[a.severity] - SEV_RANK[b.severity];
    if (s !== 0) return s;
    const t = b.trend - a.trend; // positive slope = worsening => first
    if (t !== 0) return t;
    return a.first_seen.localeCompare(b.first_seen);
  });
}

export function filterProblems(problems: Problem[], opts: { severity?: Severity | null; type?: string | null; includeDismissed?: boolean }): Problem[] {
  const cutoff = Date.now() - 7 * 24 * 3600 * 1000;
  return problems.filter((p) => {
    if (opts.severity && p.severity !== opts.severity) return false;
    if (opts.type && p.type !== opts.type) return false;
    if (!opts.includeDismissed && p.dismissed_until && new Date(p.dismissed_until).getTime() > cutoff) {
      return false;
    }
    return true;
  });
}

/** Distinct problem types in stable first-seen order (for filter chips). */
export function problemTypes(problems: Problem[]): string[] {
  const seen: string[] = [];
  for (const p of rankProblems(problems)) {
    if (!seen.includes(p.type)) seen.push(p.type);
  }
  return seen;
}

/** Trend arrow: >0.5 worsening, <-0.5 improving, else flat. */
export function trendArrow(slope: number): 'up' | 'down' | 'flat' {
  if (slope > 0.5) return 'up';
  if (slope < -0.5) return 'down';
  return 'flat';
}

/** Days remaining on a dismissal, or null when not dismissed. */
export function dismissalDaysLeft(dismissedUntil?: string | null, now = Date.now()): number | null {
  if (!dismissedUntil) return null;
  const ms = new Date(dismissedUntil).getTime() - now;
  if (ms <= 0) return null;
  return Math.ceil(ms / (24 * 3600 * 1000));
}
