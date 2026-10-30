// Kıyas koşusu API'si (eval-001). api.ts Mac'te yazılamadığı için ayrı dosya.
export type PfMode = "off" | "on" | "both";
export type SetPersona = {
  id: string; name: string; description: string; gender: string; age: string; speed: number; gain_db: number;
  noise_snr_db: number | null; reaction_s: number; voice_id: string | null; clips: number; clips_needed: number;
};
export type SetStatus = {
  personas: SetPersona[]; paths: { id: string; name: string; description: string }[]; texts: number; calls: number; ready: boolean;
  build: { state: "idle" | "running" | "done" | "error"; done: number; total: number; error: string | null };
};
export type RunCall = {
  index: number; persona: string; path: string; phone_filter: boolean; status: string; session_id?: string; outcome?: string | null;
  answers?: number; unanswered?: number; turns?: number; first_audio_p50_s?: number | null; error?: string;
};
export type Run = {
  id: string; profile: string; phone_filter: PfMode; created_at: string; finished_at: string | null;
  status: "running" | "done" | "cancelled" | "error"; total: number; done: number; error: string | null; calls: RunCall[];
};
export type RunSummary = Omit<Run, "calls" | "error">;

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail?.message ?? `HTTP ${res.status}`);
  }
  return res.json();
}
const post = (url: string, body?: unknown) =>
  fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });

export const fetchSet = (signal?: AbortSignal) => fetch("/api/evalrun/set", { signal }).then((r) => json<SetStatus>(r));
export const buildSet = () => post("/api/evalrun/set/build").then((r) => json<{ started: boolean }>(r));
export const startRun = (profile: string, phone_filter: PfMode) =>
  post("/api/evalrun/runs", { profile, phone_filter }).then((r) => json<{ run_id: string; total: number }>(r));
export const fetchRun = (id: string, signal?: AbortSignal) => fetch(`/api/evalrun/runs/${id}`, { signal }).then((r) => json<Run>(r));
export const fetchRuns = (signal?: AbortSignal) => fetch("/api/evalrun/runs", { signal }).then((r) => json<RunSummary[]>(r));
export const cancelRun = (id: string) => post(`/api/evalrun/runs/${id}/cancel`).then((r) => json<{ cancelled: boolean }>(r));
