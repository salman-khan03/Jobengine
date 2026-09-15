// Thin typed client for the FastAPI backend (src/jobengine/api.py).
// One place owns the base URL and fetch/json boilerplate so pages
// don't repeat error handling or guess at response shapes.

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8765";
const CORE_API_URL = process.env.NEXT_PUBLIC_CORE_API_URL ?? "http://127.0.0.1:8080";
const CORE_API_KEY = process.env.NEXT_PUBLIC_CORE_API_KEY;

export interface Job {
  dedup_key: string;
  id: string;
  source_repo: "intern" | "newgrad";
  company: string;
  company_norm: string;
  title: string;
  category: string;
  active: number;
  is_visible: number;
  terms: string; // JSON-encoded string[] as stored in the DB
  date_posted: number;
  date_updated: number;
  url: string;
  locations: string; // JSON-encoded string[]
  sponsorship_simplify: string;
  sponsor_tier: string;
  sponsor_lca_count: number;
  sponsor_match: string;
}

export interface JobsSummary {
  [tier: string]: number;
}

export type ApplicationStatus =
  | "saved"
  | "applied"
  | "heard_back"
  | "oa"
  | "interview"
  | "offer"
  | "rejected"
  | "withdrawn";

export interface Application {
  app_id: number;
  dedup_key: string | null;
  company: string;
  title: string;
  source: string;
  status: ApplicationStatus;
  applied_date: string;
  last_update: string;
  url: string;
  notes: string;
  contact_email: string;
}

export interface StatusEvent {
  status: string;
  note: string;
  occurred_at: string;
}

class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

function authHeaders(token?: string): Record<string, string> {
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(res.status, body.detail ? JSON.stringify(body.detail) : res.statusText);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

async function coreRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${CORE_API_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(CORE_API_KEY ? { "X-API-Key": CORE_API_KEY } : {}),
      ...init?.headers,
    },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(res.status, body.detail ?? res.statusText);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

export function parseJson<T>(raw: string, fallback: T): T {
  try {
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

export interface JobsQuery {
  grad?: "intern" | "newgrad";
  tier?: string; // comma-separated
  location?: string; // comma-separated
  max?: number;
  company?: string;
  skill?: string;
}

interface CoreJob {
  dedupKey: string;
  company: string;
  title: string;
  category: "intern" | "newgrad";
  locations: string[];
  terms: string[];
  url: string;
  sponsorTier: string;
  sponsorLcaCount: number;
  sponsorMatch: string;
  datePosted: number;
}

interface CoreApplication {
  appId: number;
  dedupKey: string;
  company: string;
  title: string;
  source: string;
  status: ApplicationStatus;
  appliedDate: string;
  lastUpdate: string;
  url: string;
  notes: string;
  contactEmail: string;
}

function fromCoreJob(job: CoreJob): Job {
  return {
    dedup_key: job.dedupKey, id: job.dedupKey, source_repo: job.category,
    company: job.company, company_norm: job.company.toLowerCase(), title: job.title,
    category: job.category, active: 1, is_visible: 1, terms: JSON.stringify(job.terms),
    date_posted: job.datePosted, date_updated: job.datePosted, url: job.url,
    locations: JSON.stringify(job.locations), sponsorship_simplify: "",
    sponsor_tier: job.sponsorTier, sponsor_lca_count: job.sponsorLcaCount,
    sponsor_match: job.sponsorMatch,
  };
}

function fromCoreApplication(row: CoreApplication): Application {
  return {
    app_id: row.appId, dedup_key: row.dedupKey || null, company: row.company,
    title: row.title, source: row.source, status: row.status,
    applied_date: row.appliedDate, last_update: row.lastUpdate, url: row.url,
    notes: row.notes, contact_email: row.contactEmail,
  };
}

export interface SemanticMatch extends Job {
  distance: number; // cosine distance, lower = closer
}

// Mirrors analytics.summary() in src/jobengine/analytics.py. `error_rate`
// counts 5xx only — a 401 on an expired token is the API working correctly,
// so client errors are reported separately rather than folded in.
export interface RouteStats {
  route: string;
  requests: number;
  p50_ms: number;
  p95_ms: number;
  errors: number;
}

export interface AnalyticsSummary {
  window_hours: number;
  requests: number;
  registered_users: number;
  active_users: number;
  error_rate: number;
  client_error_rate: number;
  throughput_rps: number;
  latency_ms: { p50: number; p95: number; p99: number; max: number };
  by_route: RouteStats[];
}

export interface Health {
  status: string;
  version: string;
  backend: string;
}

// --- RoleRadar V2 (evidence-grounded decisions) -----------------------------
// Mirrors src/roleradar/models.py. Kept structurally identical to the wire
// format rather than reshaped: the whole point of the feature is that the
// client can show the same citation chain the scorer used, and every rename
// on the way through is a chance for the two to drift.

export type Verdict = "apply" | "stretch" | "skip" | "blocked";
export type VerdictStatus = "ok" | "risk" | "blocked" | "unknown";
export type CoverageStatus = "strong" | "partial" | "missing";

export interface EvidenceUnit {
  evidence_id: string;
  kind: "project" | "experience" | "education" | "skill" | "training";
  label: string;
  text: string;
  source: string; // JSON path into resume.json, e.g. "projects[0].bullets[2]"
  skills: string[];
}

export interface ConstraintVerdict {
  constraint_id: string;
  kind: string;
  status: VerdictStatus;
  reason: string;
  profile_field: string;
}

export interface SkillCoverage {
  requirement_id: string;
  requirement_text: string;
  skill: string | null;
  importance: "required" | "preferred";
  status: CoverageStatus;
  score: number;
  evidence_ids: string[];
  rationale: string;
}

export interface ScoreBreakdown {
  required_coverage: number;
  preferred_coverage: number;
  semantic_similarity: number;
  seniority_fit: number;
  risk_penalty: number;
  weights: Record<string, number>;
}

export interface SavedDecision {
  decision_id: number;
  job_key: string;
  title: string;
  company: string;
  score: number;
  verdict: Verdict;
  created_at: string;
  payload: Decision;
}

export interface Decision {
  decision_id?: number;
  job_key: string;
  title: string;
  company: string;
  verdict: Verdict;
  score: number;
  confidence: number;
  gate: { passed: boolean; verdicts: ConstraintVerdict[] };
  coverages: SkillCoverage[];
  breakdown: ScoreBreakdown;
  explanation: string;
  explanation_source: "llm" | "deterministic";
  cited_evidence_ids: string[];
  generated_at: string;
  evidence: Record<string, EvidenceUnit>;
}

export interface RankingReport {
  n: number;
  positives: number;
  base_rate: number;
  ndcg_at_5: number;
  ndcg_at_10: number;
  precision_at_5: number;
  precision_at_10: number;
  lift_at_5: number;
  lift_at_10: number;
  brier: number | null;
  score_kind?: "match_score";
  spearman: number;
  calibration: { bin: string; n: number; predicted_mid: number; observed_rate: number }[];
  funnel: Record<string, number>;
  underpowered: boolean;
  note: string;
}

export interface ModelInfo {
  version: string;
  weights: Record<string, number>;
  thresholds: Record<string, number>;
  evidence_scores: Record<string, number>;
  max_risk_penalty: number;
  llm: { used_for: string; grounding: string };
}

export const api = {
  getJobs(q: JobsQuery = {}): Promise<Job[]> {
    const params = new URLSearchParams();
    if (q.grad) params.set("seniority", q.grad === "intern" ? "INTERN" : "NEW_GRAD");
    q.tier?.split(",").filter(Boolean).forEach((value) => params.append("tier", value));
    q.location?.split(",").filter(Boolean).forEach((value) => params.append("location", value));
    if (q.company) params.set("company", q.company);
    if (q.skill) params.set("skill", q.skill);
    params.set("limit", String(q.max ?? 100));
    return coreRequest<CoreJob[]>(`/api/v1/jobs?${params}`).then((rows) => rows.map(fromCoreJob));
  },
  getJobsSummary(): Promise<JobsSummary> {
    return coreRequest("/api/v1/jobs/tiers");
  },
  semanticSearchJobs(text: string, max = 10): Promise<SemanticMatch[]> {
    return request("/api/jobs/semantic-search", {
      method: "POST",
      body: JSON.stringify({ text, max }),
    });
  },
  getHealth(): Promise<Health> {
    return request("/api/health");
  },
  getAnalytics(token: string, hours = 24): Promise<AnalyticsSummary> {
    return request(`/api/analytics/summary?hours=${hours}`, {
      headers: authHeaders(token),
    });
  },
  // Everything below requires a signed-in user's bearer token — see auth.ts
  // and api.py's `current_user` dependency. Each application row is scoped
  // to whoever created it; there is no "shared" or "anonymous" view.
  getApplications(token: string, status?: string): Promise<Application[]> {
    return coreRequest<CoreApplication[]>("/api/v1/applications", {
      headers: authHeaders(token),
    }).then((rows) => rows.filter((row) => !status || row.status === status).map(fromCoreApplication));
  },
  getApplicationsSummary(token: string): Promise<Record<string, number>> {
    return request("/api/applications/summary", { headers: authHeaders(token) });
  },
  createApplication(
    token: string,
    body: {
      company: string;
      title: string;
      source: string;
      dedup_key?: string | null;
      status?: string;
      url?: string;
      notes?: string;
    },
  ): Promise<{ app_id: number }> {
    return coreRequest<CoreApplication>("/api/v1/applications", {
      method: "POST",
      headers: authHeaders(token),
      body: JSON.stringify({
        company: body.company, title: body.title, source: body.source,
        dedupKey: body.dedup_key, url: body.url, notes: body.notes,
      }),
    }).then((row) => ({ app_id: row.appId }));
  },
  updateStatus(token: string, appId: number, status: string, note = ""): Promise<{ ok: boolean }> {
    return coreRequest<CoreApplication>(`/api/v1/applications/${appId}/status`, {
      method: "POST",
      headers: authHeaders(token),
      body: JSON.stringify({ status, note }),
    }).then(() => ({ ok: true }));
  },
  deleteApplication(token: string, appId: number): Promise<{ ok: boolean }> {
    return coreRequest<void>(`/api/v1/applications/${appId}`, {
      method: "DELETE",
      headers: authHeaders(token),
    }).then(() => ({ ok: true }));
  },
  // --- RoleRadar V2 ---------------------------------------------------------
  // `decide` works signed-out when the caller supplies its own resume, which
  // is what makes the demo on /radar usable without an account.
  decide(body: {
    job?: { title: string; company: string; locations?: string };
    job_key?: string;
    jd_text?: string;
    resume?: unknown;
    profile?: Record<string, unknown>;
    use_llm?: boolean;
    save?: boolean;
  }, token?: string): Promise<Decision> {
    return coreRequest("/api/v2/decide", {
      method: "POST",
      headers: authHeaders(token),
      body: JSON.stringify(body),
    });
  },
  getDecisions(token: string): Promise<{ decisions: SavedDecision[]; count: number }> {
    return coreRequest<{ decisions: (Omit<SavedDecision, "payload"> & { payload: string })[]; count: number }>(
      "/api/v2/decisions", { headers: authHeaders(token) },
    ).then((result) => ({
      ...result,
      decisions: result.decisions.map((row) => {
        const payload = JSON.parse(row.payload) as Decision;
        return { ...row, payload: { ...payload, evidence: payload.evidence ?? {} } };
      }),
    }));
  },
  getModelInfo(): Promise<ModelInfo> {
    return coreRequest("/api/v2/model");
  },
  getEvaluation(token: string): Promise<RankingReport> {
    return coreRequest("/api/v2/evaluation", { headers: authHeaders(token) });
  },
  getFunnel(token: string): Promise<{ funnel: Record<string, number>; total: number }> {
    return coreRequest("/api/v2/outcomes/funnel", { headers: authHeaders(token) });
  },
  recordOutcome(token: string, job_key: string, stage: string, note = ""):
    Promise<{ application_id: number }> {
    return coreRequest("/api/v2/outcomes", {
      method: "POST",
      headers: authHeaders(token),
      body: JSON.stringify({ job_key, stage, note }),
    });
  },
  getHistory(token: string, appId: number): Promise<StatusEvent[]> {
    return request(`/api/applications/${appId}/history`, { headers: authHeaders(token) });
  },
};
