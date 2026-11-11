// Thin fetch wrapper over the backend API.

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
  if (!res.ok) {
    throw new Error(`${init?.method ?? 'GET'} ${path} failed: ${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  version: () => request<import('./types').VersionInfo>('/api/version'),
  controller: () => request<import('./types').Controller>('/api/controller'),
  nodes: () => request<import('./types').ZwaveNode[]>('/api/nodes'),
  node: (id: number) => request<import('./types').ZwaveNode>(`/api/nodes/${id}`),
  nodeAction: (id: number, action: 'ping' | 'refresh' | 'heal' | 'refresh-routes') =>
    request<{ ok: boolean; detail?: string }>(`/api/nodes/${id}/${action}`, { method: 'POST' }),
  problems: () => request<import('./types').Problem[]>('/api/problems'),
  dismissProblem: (id: string) =>
    request<{ ok: boolean }>(`/api/problems/${id}/dismiss`, { method: 'POST' }),
  score: () => request<import('./types').Score>('/api/score'),
  history: (kind: 'frames' | 'rssi' | 'controller' | 'drops', days: number) =>
    request<import('./types').HistorySeries[] | import('./types').HistorySeries>(
      `/api/history/${kind}?days=${days}`,
    ),
  audit: () => request<import('./types').AuditEntry[]>('/api/audit'),
  mesh: () => request<import('./types').MeshGraph>('/api/mesh'),
  advisorAnalyze: () =>
    request<import('./types').AdvisorReport>('/api/advisor/analyze', { method: 'POST' }),
  advisorInvestigate: (recId: string) =>
    request<import('./types').AdvisorReport>('/api/advisor/investigate', {
      method: 'POST',
      body: JSON.stringify({ id: recId }),
    }),
  advisorLatest: () => request<import('./types').AdvisorReport | null>('/api/advisor/latest'),
  advisorHistory: () => request<import('./types').AdvisorReport[]>('/api/advisor/history'),
  advisorLedger: () =>
    request<{ id: string; verdict: string; blocked_reason?: string }[]>('/api/advisor/ledger'),
  advisorApply: (reportId: number, index: number) =>
    request(`/api/advisor/apply`, { method: 'POST', body: JSON.stringify({ report_id: reportId, index }) }),
  setupStatus: () => request<import('./types').SetupStatus>('/api/setup/status'),
  setupTest: (step: 'hass' | 'zwjs' | 'influx' | 'llm', cfg: Record<string, unknown>) =>
    request<import('./types').SetupResult>(`/api/setup/test/${step}`, {
      method: 'POST',
      body: JSON.stringify(cfg),
    }),
  setupComplete: (cfg: Record<string, unknown>) =>
    request<{ ok: boolean }>('/api/setup/complete', {
      method: 'POST',
      body: JSON.stringify(cfg),
    }),
};
