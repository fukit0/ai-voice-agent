export type Health = { status: string; service: string; version: string; python: string; uptime_seconds: number };

export async function fetchHealth(signal?: AbortSignal): Promise<Health> {
  const res = await fetch("/api/health", { signal });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}
