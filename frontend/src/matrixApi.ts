// Kıyas matrisi API'si (lab-005). api.ts Mac'te yazılamadığı için ayrı dosya.
export type CriterionId = "latency" | "naturalness" | "accuracy" | "wer" | "resources";
export type Weights = Record<CriterionId, number>;
export type Metric = { value: number; unit: string; score: number; n: number | null; note: string | null };
export type LicenseInfo = { kind: string; model: string; license: string; commercial_ok: boolean | null; verified: boolean };
export type MatrixRow = {
  profile: string; name: string; mode: string; components: { kind: string; provider: string; model: string }[];
  metrics: Record<CriterionId, Metric | null>; total: number | null; coverage: number; missing: CriterionId[];
  eliminated: boolean; license: LicenseInfo[]; license_unknown: string[]; rank: number | null;
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
