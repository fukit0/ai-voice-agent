export type Health = { status: string; service: string; version: string; python: string; uptime_seconds: number };

export async function fetchHealth(signal?: AbortSignal): Promise<Health> {
  const res = await fetch("/api/health", { signal });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export type ComponentStatus = { provider: string; model: string; missing_env?: string[]; warm?: boolean } | null;

export type ProfileStatus = {
  id: string;
  name: string;
  purpose: string;
  mode: "cascade" | "realtime";
  notes: string;
  components: { stt: ComponentStatus; llm: ComponentStatus; tts: ComponentStatus };
  realtime: { provider: string; model: string } | null;
  missing_env: string[];
  issues: string[];
  ready: boolean;
  warm: boolean;
  warmup: WarmupJob | null;
};

export type WarmupComponent = {
  state: "pending" | "loading" | "measuring" | "ready" | "degraded" | "failed";
  provider?: string;
  model?: string;
  load_seconds?: number;
  warm_seconds?: number;
  final_seconds?: number;
  error?: string;
  missing_env?: string[];
};

export type WarmupJob = {
  profile: string;
  state: "running" | "ready" | "degraded" | "failed";
  seconds: number | null;
  evicted: string[];
  components: Record<string, WarmupComponent>;
  error: string | null;
};

export async function fetchProfiles(signal?: AbortSignal): Promise<ProfileStatus[]> {
  const res = await fetch("/api/profiles", { signal });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail?.message ?? `HTTP ${res.status}`);
  }
  return res.json();
}

export const startWarmup = (id: string, keepOthers = false, components?: string) =>
  fetch(`/api/profiles/${id}/warmup?keep_others=${keepOthers}${components ? `&components=${components}` : ""}`, {
    method: "POST",
  }).then((r) => json<WarmupJob>(r));

export const getWarmup = (id: string) => fetch(`/api/profiles/${id}/warmup`).then((r) => json<WarmupJob>(r));

// ---- STT test (lab-002) ----
export type SttModel = {
  profile: string; // modeli kullanan ilk profil (Hazırla bu profille yapılır)
  profiles: string[];
  provider: string;
  model: string;
  ready: boolean;
  warm: boolean;
  missing_env: string[];
};

export type SttResult = {
  profile: string;
  provider: string;
  model: string;
  status: "ok" | "cold" | "not_ready" | "failed";
  error?: string;
  text?: string;
  seconds?: number;
  rtf?: number;
  wer?: number | null;
  ref_words?: number;
  substitutions?: number;
  deletions?: number;
  insertions?: number;
};

export type SttRun = {
  id: string;
  created_at: string;
  filename: string | null;
  audio_seconds: number;
  reference: string;
  results: SttResult[];
};

export type SttRunSummary = {
  id: string;
  created_at: string;
  filename: string | null;
  audio_seconds: number;
  reference: string;
  models: string[];
  best_wer: number | null;
};

export const fetchSttModels = () => fetch("/api/stt/models").then((r) => json<SttModel[]>(r));
export const fetchSttRuns = () => fetch("/api/stt/runs").then((r) => json<SttRunSummary[]>(r));
export const fetchSttRun = (id: string) => fetch(`/api/stt/runs/${id}`).then((r) => json<SttRun>(r));
export const sttAudioUrl = (id: string) => `/api/stt/runs/${id}/audio`;

export function compareStt(audio: Blob, filename: string, profiles: string[], reference: string): Promise<SttRun> {
  const form = new FormData();
  form.append("audio", audio, filename);
  form.append("profiles", profiles.join(","));
  form.append("reference", reference);
  return fetch("/api/stt/compare", { method: "POST", body: form }).then((r) => json<SttRun>(r));
}
