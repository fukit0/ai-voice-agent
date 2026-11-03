// Aramalar API'si (lab-004). api.ts Mac'te yazılamadığı için ayrı dosya.
async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail?.message ?? `HTTP ${res.status}`);
  }
  return res.json();
}

// ---- Aramalar (lab-004): /api/calls ----
export type CallRow = {
  id: string; profile: string; started_at: string | null; scenario: string | null; outcome: string | null;
  duration_s: number | null; turns: number; answers: number; unanswered: number;
  first_audio_p50_s: number | null; first_audio_max_s: number | null;
  stt_p50_s: number | null; llm_p50_s: number | null; tts_first_p50_s: number | null; tts_total_p50_s: number | null;
  barge_ins: number; stt_rejected: number; stt: string | null; llm: string | null; tts: string | null;
  tts_tone: string | null; tts_speed: number | null; phone_filter: boolean; realtime: boolean; has_audio: boolean;
  cost_usd: number | null; gpu_s: number | null;   // eval-003: eski kayıtlarda null (sıfır değil)
};
export type CallList = { calls: CallRow[]; total: number; facets: { profiles: string[]; scenarios: string[]; outcomes: string[] } };
export type CallTurn = { turn: number; greeting?: boolean; stt_s?: number; llm_s?: number; tts_first_s?: number; tts_total_s?: number;
  first_audio_after_end_s?: number; held_s?: number; stt_rejected?: boolean; user_seconds?: number; stt_conf?: number;
  // Serbest cevap (docs/serbest-cevap-qwen.md): kaynak, süre, thinking açık mıydı, hangi model
  reply_source?: "qwen" | "pool"; free_reply_s?: number; free_reply_fallback?: string; free_reply_thinking?: boolean; free_reply_model?: string };
export type CallAnswer = { step: string; code?: string; title?: string; kind?: string; value: unknown; utterance?: string; unanswered?: boolean };
// Detayda `turns` ve `answers` özetteki sayıların yerine listelerdir (backend calls.detail).
// eval-003: arama başına kaynak ve maliyet (backend usage.py). Sağlayıcı sayı vermediyse kalem null'dır.
export type CallUsage = {
  items: { duration_s: number; user_speech_s: number; agent_speech_s: number; speech_share: number | null; stt_minutes: number; stt_calls: number;
    llm_calls: number; llm_input_tokens: number | null; llm_output_tokens: number | null; tts_chars: number; tts_calls: number; tts_audio_s: number; gpu_s: number };
  missing: string[];
  cost: { currency: string; by_component: Record<string, number | null>; total: number | null; complete: boolean; unpriced: string[];
    prices_verified: boolean; note: string };
};
export type CallDetail = Omit<CallRow, "turns" | "answers"> & {
  transcript: { role: string; text: string; t?: number }[]; turns: CallTurn[]; answers: CallAnswer[];
  path: string[]; prompt: unknown; stats: Record<string, number>; audio_url: string | null; usage?: CallUsage | null;
};
export type CompareGroup = {
  key: string; label: string; sessions: number; turns: number;
  first_audio: { p50: number; p95: number; min: number; max: number } | null;
  stages: { stt: number | null; llm: number | null; tts_first: number | null; tts_total: number | null };
  outcomes: Record<string, number>; avg_duration_s: number | null; avg_answers: number | null;
  barge_ins_per_call: number; stt_rejected_total: number; tts: string[]; tones: string[]; realtime: boolean;
  usage_calls: number; avg_cost_usd: number | null; cost_complete: boolean; avg_gpu_s: number | null; avg_stt_minutes: number | null; avg_tts_chars: number | null;
  fast_turns?: number; fast_share?: number | null; first_audio_fast_p50?: number | null; first_audio_llm_p50?: number | null;
  meets_p50_target: boolean; enough_sessions: boolean; is_baseline: boolean; delta_p50_s: number | null; delta_pct: number | null;
};
export type CompareResult = { group: "profile" | "call" | "variant"; baseline: string | null; groups: CompareGroup[]; p50_target_s: number; min_sessions: number; definition: string };

async function callsGet<T>(url: string, signal?: AbortSignal): Promise<T> {
  return json<T>(await fetch(url, { signal }));
}
const qs = (o: Record<string, string | number | undefined | null>) => {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(o)) if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : "";
};
export const fetchCalls = (f: { profile?: string; scenario?: string; outcome?: string } = {}, signal?: AbortSignal) =>
  callsGet<CallList>(`/api/calls${qs(f)}`, signal);
export const fetchCall = (id: string, signal?: AbortSignal) => callsGet<CallDetail>(`/api/calls/${id}`, signal);
export const fetchCompare = (q: { group: "profile" | "call" | "variant"; ids?: string[]; baseline?: string; profile?: string; scenario?: string; outcome?: string },
                             signal?: AbortSignal) =>
  callsGet<CompareResult>(`/api/calls/compare${qs({ ...q, ids: q.ids?.join(",") })}`, signal);
