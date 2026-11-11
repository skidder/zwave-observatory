import { describe, it, expect } from 'vitest';
import { gradeForScore, computeScore, controllerPill, clampScore } from './healthScore';

describe('gradeForScore', () => {
  it('maps band edges correctly', () => {
    expect(gradeForScore(100)).toBe('A');
    expect(gradeForScore(90)).toBe('A');
    expect(gradeForScore(89.9)).toBe('B');
    expect(gradeForScore(75)).toBe('B');
    expect(gradeForScore(60)).toBe('C');
    expect(gradeForScore(40)).toBe('D');
    expect(gradeForScore(0)).toBe('F');
    expect(gradeForScore(39)).toBe('F');
  });
});

describe('computeScore', () => {
  it('starts at 100/A with no penalties', () => {
    expect(computeScore([])).toEqual({ score: 100, grade: 'A' });
  });
  it('subtracts penalty points and clamps to 0', () => {
    expect(computeScore([{ reason: 'x', points: 12 }])).toEqual({ score: 88, grade: 'B' });
    expect(computeScore([{ reason: 'x', points: 200 }])).toEqual({ score: 0, grade: 'F' });
  });
  it('rounds fractional scores', () => {
    expect(clampScore(88.4)).toBe(88);
    expect(clampScore(-5)).toBe(0);
  });
});

describe('controllerPill', () => {
  it('green at 0, amber 5-15, red >15', () => {
    expect(controllerPill(0)).toBe('ok');
    expect(controllerPill(4.9)).toBe('ok');
    expect(controllerPill(5)).toBe('warn');
    expect(controllerPill(15)).toBe('warn');
    expect(controllerPill(15.1)).toBe('danger');
  });
});
