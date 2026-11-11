// Health score <-> letter grade mapping and penalty math.
import type { HealthGrade, ScorePenalty } from '../api/types';

/** Map a 0-100 score to a letter grade. Band edges: >=90 A, >=75 B, >=60 C, >=40 D, else F. */
export function gradeForScore(score: number): HealthGrade {
  if (score >= 90) return 'A';
  if (score >= 75) return 'B';
  if (score >= 60) return 'C';
  if (score >= 40) return 'D';
  return 'F';
}

export function clampScore(n: number): number {
  return Math.max(0, Math.min(100, Math.round(n)));
}

/** Start at 100 and subtract penalty points; grades derive from the clamped score. */
export function computeScore(penalties: ScorePenalty[]): { score: number; grade: HealthGrade } {
  const total = penalties.reduce((sum, p) => sum + p.points, 0);
  const score = clampScore(100 - total);
  return { score, grade: gradeForScore(score) };
}

/** Severity -> color variable for chips. */
export function severityColor(sev: string): string {
  switch (sev) {
    case 'critical':
    case 'high':
      return 'var(--danger)';
    case 'medium':
      return 'var(--warn)';
    default:
      return 'var(--text-dim)';
  }
}

export function gradeColor(grade: HealthGrade): string {
  switch (grade) {
    case 'A':
    case 'B':
      return 'var(--ok)';
    case 'C':
      return 'var(--warn)';
    default:
      return 'var(--danger)';
  }
}

/** Controller pill severity from jam share: 0 green, 5-15 amber, >15 red. */
export function controllerPill(jamSharePct: number): 'ok' | 'warn' | 'danger' {
  if (jamSharePct > 15) return 'danger';
  if (jamSharePct >= 5) return 'warn';
  return 'ok';
}
