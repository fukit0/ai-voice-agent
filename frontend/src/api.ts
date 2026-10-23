export type Health = { status: string; service: string; version: string; python: string; uptime_seconds: number };

export async function fetchHealth(signal?: AbortSignal): Promise<Health> {
  const res = await fetch("/api/health", { signal });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export type ComponentStatus = { provider: string; model: string; missing_env?: string[] } | null;

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
};

export async function fetchProfiles(signal?: AbortSignal): Promise<ProfileStatus[]> {
  const res = await fetch("/api/profiles", { signal });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}
