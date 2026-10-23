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
  state: "pending" | "loading" | "measuring" | "ready" | "failed";
  provider?: string;
  model?: string;
  load_seconds?: number;
  warm_seconds?: number;
  error?: string;
  missing_env?: string[];
};

export type WarmupJob = {
  profile: string;
  state: "running" | "ready" | "failed";
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

export const startWarmup = (id: string, keepOthers = false) =>
  fetch(`/api/profiles/${id}/warmup?keep_others=${keepOthers}`, { method: "POST" }).then((r) => json<WarmupJob>(r));

export const getWarmup = (id: string) => fetch(`/api/profiles/${id}/warmup`).then((r) => json<WarmupJob>(r));
