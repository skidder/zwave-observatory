import { describe, it, expect } from 'vitest';
import { rankProblems, filterProblems, problemTypes, trendArrow, dismissalDaysLeft } from './problems';
import type { Problem } from '../api/types';

const P = (over: Partial<Problem>): Problem => ({
  id: 'p',
  severity: 'medium',
  type: 'flaky',
  node_id: 1,
  message: 'm',
  first_seen: '2026-01-01T00:00:00Z',
  trend: 0,
  evidence: [],
  ...over,
});

describe('rankProblems', () => {
  it('sorts by severity, then worsening trend, then first-seen', () => {
    const ranked = rankProblems([
      P({ id: 'med-worse', severity: 'medium', trend: 2 }),
      P({ id: 'low', severity: 'low' }),
      P({ id: 'crit', severity: 'critical', trend: -1 }),
      P({ id: 'crit-old', severity: 'critical', trend: -1, first_seen: '2025-01-01T00:00:00Z' }),
      P({ id: 'med-flat', severity: 'medium', trend: 0 }),
    ]);
    expect(ranked.map((p) => p.id)).toEqual(['crit-old', 'crit', 'med-worse', 'med-flat', 'low']);
  });
  it('does not mutate input', () => {
    const input = [P({ id: 'b', severity: 'low' }), P({ id: 'a', severity: 'high' })];
    rankProblems(input);
    expect(input.map((p) => p.id)).toEqual(['b', 'a']);
  });
});

describe('filterProblems', () => {
  const now = Date.now();
  const soon = new Date(now + 3 * 24 * 3600 * 1000).toISOString();
  const past = new Date(now - 8 * 24 * 3600 * 1000).toISOString();

  it('hides active dismissals unless included', () => {
    const problems = [P({ id: 'live' }), P({ id: 'hidden', dismissed_until: soon })];
    expect(filterProblems(problems, {}).map((p) => p.id)).toEqual(['live']);
    expect(filterProblems(problems, { includeDismissed: true }).map((p) => p.id)).toEqual(['live', 'hidden']);
  });
  it('shows expired dismissals', () => {
    const problems = [P({ id: 'expired', dismissed_until: past })];
    expect(filterProblems(problems, {}).map((p) => p.id)).toEqual(['expired']);
  });
  it('filters by severity and type', () => {
    const problems = [P({ id: 'a', severity: 'high', type: 'x' }), P({ id: 'b', severity: 'low', type: 'y' })];
    expect(filterProblems(problems, { severity: 'high' }).map((p) => p.id)).toEqual(['a']);
    expect(filterProblems(problems, { type: 'y' }).map((p) => p.id)).toEqual(['b']);
  });
});

describe('problemTypes', () => {
  it('returns distinct types', () => {
    expect(problemTypes([P({ type: 'a' }), P({ type: 'b' }), P({ type: 'a' })])).toEqual(['a', 'b']);
  });
});

describe('trendArrow + dismissalDaysLeft', () => {
  it('classifies slope', () => {
    expect(trendArrow(2)).toBe('up');
    expect(trendArrow(-1)).toBe('down');
    expect(trendArrow(0.2)).toBe('flat');
  });
  it('computes days left', () => {
    const soon = new Date(Date.now() + 36 * 3600 * 1000).toISOString();
    expect(dismissalDaysLeft(soon)).toBe(2);
    expect(dismissalDaysLeft(null)).toBeNull();
    expect(dismissalDaysLeft('2000-01-01T00:00:00Z')).toBeNull();
  });
});
