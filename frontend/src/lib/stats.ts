// Drop-rate and related stat calculations.

/** Drop rate as a percentage of tx+rx; 0 when there is no traffic. */
export function dropRatePct(drops: number, tx: number, rx: number): number {
  const total = tx + rx;
  if (total <= 0) return 0;
  return (drops / total) * 100;
}

/** Linear least-squares slope over (t = day index, y = value). Used for trend arrows. */
export function slope(values: number[]): number {
  const n = values.length;
  if (n < 2) return 0;
  const meanX = (n - 1) / 2;
  const meanY = values.reduce((a, b) => a + b, 0) / n;
  let num = 0;
  let den = 0;
  for (let i = 0; i < n; i++) {
    num += (i - meanX) * (values[i] - meanY);
    den += (i - meanX) ** 2;
  }
  return den === 0 ? 0 : num / den;
}

/** Simple mean; 0 for empty input. */
export function mean(values: number[]): number {
  if (values.length === 0) return 0;
  return values.reduce((a, b) => a + b, 0) / values.length;
}

/** Worst nodes by drop rate, descending, top n. */
export function worstNodes<T extends { stats: { drops: number; tx: number; rx: number } }>(
  nodes: T[],
  n = 8,
): { node: T; rate: number }[] {
  return nodes
    .filter((nd) => !nd.stats || (nd.stats.tx + nd.stats.rx) > 0 || nd.stats.drops > 0)
    .map((nd) => ({ node: nd, rate: dropRatePct(nd.stats.drops, nd.stats.tx, nd.stats.rx) }))
    .sort((a, b) => b.rate - a.rate)
    .slice(0, n);
}
