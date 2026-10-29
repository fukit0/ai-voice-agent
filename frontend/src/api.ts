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

export type SttChannel = "mix" | "left" | "right";

// channel: stereo ses kaydında (core-013) sol = müşteri, sağ = ajan; prompt: Whisper alan ipucu (MLX), verilirse aynı model ipuçlu da koşar.
export function compareStt(audio: Blob, filename: string, profiles: string[], reference: string,
                           channel: SttChannel = "mix", prompt = ""): Promise<SttRun> {
  const form = new FormData();
  form.append("audio", audio, filename);
  form.append("profiles", profiles.join(","));
  form.append("reference", reference);
  form.append("channel", channel);
  form.append("prompt", prompt);
  return fetch("/api/stt/compare", { method: "POST", body: form }).then((r) => json<SttRun>(r));
}

// ---- TTS stüdyosu (lab-001) ----
export type TtsModel = {
  profile: string; profiles: string[]; provider: string; model: string; ready: boolean; warm: boolean;
  missing_env: string[]; studio_only: boolean;
};
export type TtsClip = {
  id: string; sentence_idx: number; profile: string; provider: string; model: string;
  status: "ok" | "cold" | "not_ready" | "failed"; error?: string;
  gen_seconds?: number; first_audio_seconds?: number; first_audio_measured?: boolean;
  audio_seconds?: number; rtf?: number; rms_dbfs?: number; sample_rate?: number;
};
export type NormalizePreview = { text: string; spoken: string; changes: { from: string; to: string }[] };
export type TtsSession = {
  id: string; created_at: string; language: string; phone: boolean; sentences: string[]; profiles: string[];
  spoken?: string[]; text_normalized?: boolean;
  clips: TtsClip[]; done: number; total: number; state: "running" | "done" | "failed"; error?: string;
};
export type TtsSessionSummary = { id: string; created_at: string; sentences: number; models: string[]; clips: number; phone: boolean };
export type BlindRating = { naturalness: number; humanlike: number; mispronunciation: number; comment?: string };
export type BlindItem = { position: number; token: string; sentence: string; rating: BlindRating | null };
export type BlindView = { session: string; listener: string; items: BlindItem[]; rated: number };
export type TtsSummaryRow = { profile: string; model: string; ratings: number; naturalness: number; humanlike: number; mispronunciation: number };

const post = (url: string, body: unknown) =>
  fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

export const fetchTtsModels = () => fetch("/api/tts/models").then((r) => json<TtsModel[]>(r));
export const fetchTtsSessions = () => fetch("/api/tts/sessions").then((r) => json<TtsSessionSummary[]>(r));
export const fetchTtsSession = (id: string) => fetch(`/api/tts/sessions/${id}`).then((r) => json<TtsSession>(r));
export const createTtsSession = (sentences: string[], profiles: string[], phone: boolean, normalizeText = true) =>
  post("/api/tts/sessions", { sentences, profiles, phone, normalize_text: normalizeText }).then((r) => json<TtsSession>(r));
export const previewNormalize = (sentences: string[]) =>
  post("/api/tts/normalize", { sentences }).then((r) => json<NormalizePreview[]>(r));
export const ttsClipUrl = (sid: string, clip: string) => `/api/tts/sessions/${sid}/clips/${clip}/audio`;
export const startListening = (sid: string, listener: string, restart = false) =>
  post(`/api/tts/sessions/${sid}/listen`, { listener, restart }).then((r) => json<BlindView>(r));
export const blindAudioUrl = (sid: string, token: string, listener: string) =>
  `/api/tts/sessions/${sid}/blind/${token}/audio?listener=${encodeURIComponent(listener)}`;
export const rateClip = (sid: string, listener: string, token: string, r: BlindRating) =>
  post(`/api/tts/sessions/${sid}/ratings`, { listener, token, ...r }).then((res) => json<{ ok: boolean }>(res));
export const ttsRatingsCsvUrl = (sid: string) => `/api/tts/sessions/${sid}/ratings.csv`;
export const fetchTtsSummary = (sid: string) => fetch(`/api/tts/sessions/${sid}/summary`).then((r) => json<TtsSummaryRow[]>(r));

// ---- LLM fonksiyon çağrısı testi (eval-llm) ----
export type EvalModel = {
  profile: string; profiles: string[]; provider: string; model: string; ready: boolean; warm: boolean;
  missing_env: string[];
};
export type EvalRow = {
  id: string; node: string; utterance: string; raw: string; seconds: number | null;
  expected: { intent: string; value: unknown; branch: string };
  parsed: { intent?: string; value?: unknown } | null; got_branch: string | null; problem: string | null;
  json_valid: boolean; schema_valid: boolean; intent_ok: boolean; value_ok: boolean; branch_ok: boolean; full_ok: boolean;
};
export type EvalSummary = {
  n: number; n_answers: number; json_valid_rate: number | null; schema_valid_rate: number | null;
  intent_rate: number | null; normalize_rate: number | null; branch_rate: number | null; full_rate: number | null;
  latency_p50: number | null; latency_p95: number | null;
  by_type: Record<string, { n: number; full_rate: number | null; branch_rate: number | null }>;
};
export type EvalResult = {
  profile: string; provider: string; model: string; status: "ok" | "cold" | "not_ready" | "failed";
  error?: string; summary?: EvalSummary; rows?: EvalRow[];
};
export type EvalRun = { id: string; created_at: string; n_samples: number; results: EvalResult[] };
export type EvalRunSummary = { id: string; created_at: string; n_samples: number; models: string[]; best_full_rate: number | null };

export const fetchEvalModels = () => fetch("/api/eval/llm/models").then((r) => json<EvalModel[]>(r));
export const fetchEvalRuns = () => fetch("/api/eval/llm/runs").then((r) => json<EvalRunSummary[]>(r));
export const fetchEvalRun = (id: string) => fetch(`/api/eval/llm/runs/${id}`).then((r) => json<EvalRun>(r));
export const runLlmEval = (profiles: string[], limit?: number) =>
  fetch("/api/eval/llm/run", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ profiles, ...(limit ? { limit } : {}) }),
  }).then((r) => json<EvalRun>(r));

// ---- Senaryolar (lab-003) ----
export type ScenarioBranch = { on: string; to: string; to_title: string };
export type ScenarioStep = {
  key: string; title: string; code: string | null; group: string; kind: string; condition: string | null;
  dtmf: boolean; min: number; max: number; longAnswer: boolean; outcome: string | null; applicable: boolean;
  choices: { value: string; label: string; dtmf?: string }[]; defaultText: string; text: string; edited: boolean;
  placeholders: string[]; branches: ScenarioBranch[]; spoken: string; chars: number;
};
export type ScenarioOutcome = { key: string; label: string; tone: string; description: string };
export type ScenarioSummary = { key: string; label: string; shortLabel: string; description: string; steps: number; outcomes: ScenarioOutcome[]; problems: string[] };
export type ScenarioDoc = {
  key: string; label: string; description: string; outcomes: ScenarioOutcome[]; placeholders: Record<string, string>;
  sample_values: Record<string, string>; problems: string[]; steps: ScenarioStep[];
};

export const fetchScenarios = () => fetch("/api/scenarios").then((r) => json<ScenarioSummary[]>(r));
export const fetchScenario = (key: string) => fetch(`/api/scenarios/${key}`).then((r) => json<ScenarioDoc>(r));
export const saveStepText = (key: string, step: string, text: string) =>
  fetch(`/api/scenarios/${key}/steps/${step}/text`, {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }),
  }).then((r) => json<ScenarioStep>(r));
export const resetStepText = (key: string, step: string) =>
  fetch(`/api/scenarios/${key}/steps/${step}/text`, { method: "DELETE" }).then((r) => json<ScenarioStep>(r));
export const previewScenarioText = (key: string, text: string) =>
  fetch(`/api/scenarios/${key}/preview`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }),
  }).then((r) => json<{ spoken: string; chars: number; unknown_placeholders: string[] }>(r));

// ---- Persona (core-005) ----------------------------------------------------------------------------------
export type PersonaFields = {
  name: string; tone: string; address: string; max_sentences: number; max_words_per_sentence: number; speed: number;
  acknowledgements: string[]; avoid_phrases: string[]; extra_rules: string;
};
export type PersonaStats = {
  utterances: number; sentences: number; avg_words_per_sentence: number | null; max_words: number | null;
  over_limit: { text: string; words: number }[]; over_limit_rate: number | null; avoid_hits: string[];
};
export type PersonaView = {
  persona: PersonaFields; defaults: PersonaFields; options: { tone: string[]; address: string[] };
  prompt: string; greeting: string; preview_ack: (string | null)[]; prompt_stats: PersonaStats;
};
export type PersonaPreview = { problems: string[] } & Partial<PersonaView>;
export type PersonaReport = {
  persona: PersonaFields;
  sessions: (PersonaStats & { id: string; profile: string | null; started_at: string | null })[];
  total: PersonaStats | null;
};

async function personaCall<T>(url: string, method = "GET", body?: unknown): Promise<T> {
  const res = await fetch(url, body === undefined ? { method } : { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!res.ok) {
    let text = `HTTP ${res.status}`;
    try { const j = await res.json(); text = j.detail?.message ?? j.detail ?? text; } catch { /* gövde yok */ }
    throw new Error(String(text));
  }
  return res.json();
}
export const fetchPersona = () => personaCall<PersonaView>("/api/persona");
export const savePersona = (p: PersonaFields) => personaCall<PersonaView>("/api/persona", "PUT", p);
export const resetPersona = () => personaCall<PersonaView>("/api/persona/reset", "POST");
export const previewPersona = (p: PersonaFields) => personaCall<PersonaPreview & { prompt_stats?: PersonaStats }>("/api/persona/preview", "POST", p);
export const fetchPersonaReport = () => personaCall<PersonaReport>("/api/persona/report");
