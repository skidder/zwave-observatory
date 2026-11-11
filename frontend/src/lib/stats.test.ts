import { describe, it, expect, vi, afterEach } from 'vitest';
import { dropRatePct, slope, mean, worstNodes } from './stats';

afterEach(() => vi.restoreAllMocks());

describe('dropRatePct', () => {
  it('computes drops over tx+rx', () => {
    expect(dropRatePct(5, 100, 0)).toBeCloseTo(5);
    expect(dropRatePct(3, 40, 60)).toBeCloseTo(3);
  });
  it('returns 0 with no traffic', () => {
    expect(dropRatePct(4, 0, 0)).toBe(0);
  });
});

describe('slope / mean', () => {
  it('fits a line', () => {
    expect(slope([1, 2, 3])).toBeCloseTo(1);
    expect(slope([3, 2, 1])).toBeCloseTo(-1);
    expect(slope([5, 5, 5])).toBeCloseTo(0);
    expect(slope([4])).toBe(0);
  });
  it('means', () => {
    expect(mean([2, 4])).toBe(3);
    expect(mean([])).toBe(0);
  });
});

describe('worstNodes (mocked fetch shape)', () => {
  it('ranks by drop rate and slices top n', async () => {
    const payload = [
      { id: 1, name: 'a', stats: { drops: 10, tx: 100, rx: 0 } },
      { id: 2, name: 'b', stats: { drops: 1, tx: 100, rx: 0 } },
      { id: 3, name: 'c', stats: { drops: 0, tx: 0, rx: 0 } },
      { id: 4, name: 'd', stats: { drops: 5, tx: 0, rx: 50 } },
    ];
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => payload,
    }));
    const res = await fetch('/api/nodes').then((r) => r.json());
    const worst = worstNodes(res as { id: number; name: string; stats: { drops: number; tx: number; rx: number } }[], 2);
    expect(worst.map((w) => w.node.id)).toEqual([1, 4]);
    expect(worst[0].rate).toBeCloseTo(10);
  });
});
