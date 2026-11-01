// Kıyas matrisi API'si (lab-005). api.ts Mac'te yazılamadığı için ayrı dosya.
export type CriterionId = "latency" | "naturalness" | "accuracy" | "completion" | "wer" | "resources";
export type Weights = Record<CriterionId, number>;
export type Metric = { value: number; unit: string; score: number; n: number | null; note: string | null };
export type LicenseInfo = { kind: string; model: string; license: string; commercial_ok: boolean | null; verified: boolean };
export type DecisionStatus = "aday" | "secildi" | "elendi";
export type Decision = { status: DecisionStatus; reason: string; decided_at: string | null; snapshot: { total: number | null; coverage: number | null } | null };
export type MatrixRow = {
  profile: string; name: string; mode: string; components: { kind: string; provider: string; model: string }[];
  metrics: Record<CriterionId, Metric | null>; total: number | null; coverage: number; missing: CriterionId[];
  not_applicable?: Partial<Record<CriterionId, string>>;
  decision?: Decision; eliminated: boolean; license: LicenseInfo[]; license_unknown: string[]; rank: number | null;
};
export type Matrix = {
  criteria: { id: CriterionId; label: string; source: string; rule: string; weight: number; weight_pct: number }[];
  weights: Weights; defaults: Weights; min_coverage: number; rows: MatrixRow[]; generated_at: string; notes: string[];
};

export async function fetchMatrix(weights?: Weights, signal?: AbortSignal): Promise<Matrix> {
  const q = weights ? "?weights=" + (Object.entries(weights) as [string, number][]).map(([k, v]) => `${k}:${v}`).join(",") : "";
  const res = await fetch(`/api/matrix${q}`, { signal });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail?.message ?? `HTTP ${res.status}`);
  }
  return res.json();
}

async function check(res: Response): Promise<Response> {
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail?.message ?? `HTTP ${res.status}`);
  }
  return res;
}

/** Profil kararı kaydeder (elendi/secildi için gerekçe zorunlu; aday = kaydı sil). */
export async function saveDecision(profile: string, status: DecisionStatus, reason: string): Promise<Decision> {
  const res = await check(await fetch(`/api/matrix/decisions/${encodeURIComponent(profile)}`, {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status, reason }),
  }));
  return res.json();
}

/** Demo için profil bazlı karar özeti (Markdown). */
export async function fetchDecisionReport(): Promise<string> {
  return (await check(await fetch("/api/matrix/decisions/report"))).text();
}
