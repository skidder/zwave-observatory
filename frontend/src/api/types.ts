// Shared API types

export type Theme = 'light' | 'dark' | 'system';

export type Severity = 'critical' | 'high' | 'medium' | 'low';
export type HealthGrade = 'A' | 'B' | 'C' | 'D' | 'F';

export interface Controller {
  status: 'online' | 'offline' | 'degraded';
  jam_share_pct: number;
  frames_per_day: number;
  dropped_per_day: number;
  collisions_per_day: number;
  bg_rssi: Record<string, number>; // channel -> dBm
}

export interface ScorePenalty {
  reason: string;
  points: number;
  node_id?: number;
}

export interface Score {
  score: number; // 0-100
  grade: HealthGrade;
  penalties: ScorePenalty[];
  history: { ts: string; value: number }[];
}

export interface NodeStats {
  tx: number;
  rx: number;
  drops: number;
  timeouts: number;
  rtt_ms: number;
  rssi: number;
  snr: number;
}

export interface ZwaveNode {
  id: number;
  name: string;
  loc: string;
  is_controller: boolean;
  power: 'mains' | 'battery';
  sleeping: boolean;
  dead: boolean;
  grade: HealthGrade;
  stats: NodeStats;
  routes: { direct: boolean; repeaters: number[] };
  neighbors: number[];
  lwr_rssi?: number;
  nlwr_rssi?: number;
  ha_entities: { entity_id: string; state: string; name: string }[];
  params: { id: number; name: string; value: number | string; referenced_steps?: string[] }[];
}

export interface Problem {
  id: string;
  severity: Severity;
  type: string;
  node_id: number | null;
  message: string;
  first_seen: string;
  trend: number; // 14d slope of occurrences/day
  dismissed_until?: string | null;
  evidence: { ts: string; value: number }[];
}

export interface AuditEntry {
  ts: string;
  actor: string;
  kind: string;
  node_id?: number | null;
  detail: string;
}

export interface RecommendationAction {
  id: string;
  description: string;
  kind: string;
  validation: 'ok' | 'failed' | 'pending';
  validation_error?: string;
  applied?: boolean;
  verified?: boolean;
  verification_started?: string;
}

export interface Recommendation {
  id: string;
  created: string;
  diagnosis: string;
  confidence: number; // 0-1
  evidence_links: string[];
  actions: RecommendationAction[];
  verdict?: 'applied' | 'partial' | 'rejected' | 'pending';
  blocked_reason?: string;
}

export interface AdvisorReport {
  run_at: string;
  model: string;
  tokens: { input: number; output: number };
  cost_usd: number;
  recommendations: Recommendation[];
  markdown: string;
  transcript: string;
}

export interface SetupStatus {
  configured: boolean;
  step: string | null;
}

export interface SetupResult {
  ok: boolean;
  error?: string;
}

export interface HistorySeries {
  key: string;
  series: { ts: string; value: number }[];
}

export interface MeshNode {
  id: number;
  label: string;
  is_controller: boolean;
  power: 'mains' | 'battery';
  grade: HealthGrade;
  sleeping: boolean;
  dead: boolean;
  problems: number;
}

export interface MeshEdge {
  source: number;
  target: number;
  kind: 'lwr' | 'nlwr' | 'neighbor';
  rssi?: number;
}

export interface MeshGraph {
  nodes: MeshNode[];
  edges: MeshEdge[];
  routes_as_of: string;
}

export interface VersionInfo {
  app: string;
  api: string;
  zwave_js_ui?: string;
}
