import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TtsPage } from "./TtsPage";

const MODELS = [
  { profile: "L2", profiles: ["L1", "L2"], provider: "ema", model: "", ready: true, warm: true, missing_env: [], studio_only: false },
  { profile: "S-chatterbox", profiles: ["S-chatterbox"], provider: "chatterbox", model: "", ready: true, warm: false, missing_env: [], studio_only: true },
  { profile: "A1", profiles: ["A1"], provider: "elevenlabs", model: "eleven_flash_v2_5", ready: false, warm: false, missing_env: ["ELEVENLABS_API_KEY"], studio_only: false },
];
const SID = "20261023-120000-abc123";
const SESSION = {
  id: SID, created_at: "2026-10-23T12:00:00+00:00", language: "tr", phone: false, profiles: ["L2"], done: 2, total: 2,
  state: "done", sentences: ["Birinci cümle.", "İkinci cümle."],
  clips: [
    { id: "c001-L2", sentence_idx: 0, profile: "L2", provider: "ema", model: "ema-lightning", status: "ok", first_audio_seconds: 0.07, first_audio_measured: false, rtf: 0.05, audio_seconds: 1.4, gen_seconds: 0.07 },
    { id: "c002-L2", sentence_idx: 1, profile: "L2", provider: "ema", model: "ema-lightning", status: "ok", first_audio_seconds: 0.08, first_audio_measured: false, rtf: 0.06, audio_seconds: 1.3, gen_seconds: 0.08 },
  ],
};
const BLIND = {
  session: SID, listener: "Ayşe", rated: 0,
  items: [
    { position: 1, token: "aaaaaaaaaaaaaaaa", sentence: "İkinci cümle.", rating: null },
    { position: 2, token: "bbbbbbbbbbbbbbbb", sentence: "Birinci cümle.", rating: null },
  ],
};
let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === "/api/tts/models") return new Response(JSON.stringify(MODELS));
    if (url === "/api/tts/normalize") {
      const { sentences } = JSON.parse(String(init?.body));
      return new Response(JSON.stringify(sentences.map((s: string) => s.includes("1.250.000 TL")
        ? { text: s, spoken: s.replace("1.250.000 TL", "bir milyon iki yüz elli bin lira"), changes: [{ from: "1.250.000 TL", to: "bir milyon iki yüz elli bin lira" }] }
        : { text: s, spoken: s, changes: [] })));
    }
    if (url === "/api/tts/sessions" && init?.method === "POST") return new Response(JSON.stringify({ ...SESSION, state: "running", clips: [], done: 0 }), { status: 202 });
    if (url === "/api/tts/sessions") return new Response(JSON.stringify([{ id: SID, created_at: SESSION.created_at, sentences: 2, models: ["L2"], clips: 2, phone: false }]));
    if (url === `/api/tts/sessions/${SID}`) return new Response(JSON.stringify(SESSION));
    if (url === `/api/tts/sessions/${SID}/listen`) return new Response(JSON.stringify(BLIND));
    if (url === `/api/tts/sessions/${SID}/ratings`) return new Response(JSON.stringify({ ok: true }), { status: 201 });
    if (url.includes("/warmup") && init?.method === "POST") return new Response(JSON.stringify({ state: "ready", components: {} }), { status: 202 });
    return new Response("", { status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("TtsPage", () => {
  it("lists models with status and disables models that miss credentials", async () => {
    render(<TtsPage />);
    expect(await screen.findByText(/ema/)).toBeTruthy();
    expect(screen.getByText("Sıcak")).toBeTruthy();
    expect(screen.getByText("yalnızca stüdyo")).toBeTruthy();
    expect(screen.getByText(/Eksik: ELEVENLABS_API_KEY/)).toBeTruthy();
    const boxes = screen.getAllByRole("checkbox") as HTMLInputElement[];
    expect(boxes.find((b) => b.disabled)).toBeTruthy();
  });

  it("generates clips for the sentence set and shows first-audio time and RTF", async () => {
    render(<TtsPage />);
    await screen.findByText("Sıcak");
    fireEvent.change(screen.getByLabelText("Cümle seti"), { target: { value: "Birinci cümle.\nİkinci cümle." } });
    fireEvent.click(await screen.findByRole("button", { name: /Ses üret \(2 × 1\)/ }));
    expect(await screen.findByText("0.07 sn*", {}, { timeout: 4000 })).toBeTruthy();
    const post = fetchMock.mock.calls.find((c) => c[0] === "/api/tts/sessions" && c[1]?.method === "POST");
    expect(JSON.parse(post![1].body)).toEqual({ sentences: ["Birinci cümle.", "İkinci cümle."], profiles: ["L2"], phone: false, normalize_text: true });
  });

  it("Persona hızı kutusu varsayılan kapalıdır ve açılınca isteğe persona_speed eklenir (core-005)", async () => {
    render(<TtsPage />);
    await screen.findByText("Sıcak");
    const box = screen.getByLabelText(/Persona konuşma hızını uygula/) as HTMLInputElement;
    expect(box.checked).toBe(false);
    fireEvent.click(box);
    fireEvent.change(screen.getByLabelText("Cümle seti"), { target: { value: "Birinci cümle." } });
    fireEvent.click(await screen.findByRole("button", { name: /Ses üret \(1 × 1\)/ }));
    await waitFor(() => expect(fetchMock.mock.calls.some((c) => c[0] === "/api/tts/sessions" && c[1]?.method === "POST")).toBe(true));
    const post = fetchMock.mock.calls.find((c) => c[0] === "/api/tts/sessions" && c[1]?.method === "POST");
    expect(JSON.parse(post![1].body).persona_speed).toBe(true);
  });

  it("previews how numbers, prices, dates and phones will be spoken (norm-007)", async () => {
    render(<TtsPage />);
    await screen.findByText("Sıcak");
    fireEvent.change(screen.getByLabelText("Cümle seti"), { target: { value: "Fiyat 1.250.000 TL.\nMerhaba." } });
    expect(await screen.findByText("Fiyat bir milyon iki yüz elli bin lira.")).toBeTruthy();
    expect(screen.getByText(/1 cümlede değişiklik/)).toBeTruthy();
  });

  it("can switch normalization off and sends the choice with the session", async () => {
    render(<TtsPage />);
    await screen.findByText("Sıcak");
    fireEvent.change(screen.getByLabelText("Cümle seti"), { target: { value: "Fiyat 1.250.000 TL." } });
    await screen.findByText("Fiyat bir milyon iki yüz elli bin lira.");
    fireEvent.click(screen.getByLabelText(/Metni okunur Türkçeye çevir/));
    await waitFor(() => expect(screen.queryByText("Fiyat bir milyon iki yüz elli bin lira.")).toBeNull());
    fireEvent.click(await screen.findByRole("button", { name: /Ses üret \(1 × 1\)/ }));
    await waitFor(() => expect(fetchMock.mock.calls.some((c) => c[0] === "/api/tts/sessions" && c[1]?.method === "POST")).toBe(true));
    const post = fetchMock.mock.calls.find((c) => c[0] === "/api/tts/sessions" && c[1]?.method === "POST");
    expect(JSON.parse(post![1].body).normalize_text).toBe(false);
  });

  it("prepares a studio-only model alone (evicting others)", async () => {
    render(<TtsPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Hazırla" }));
    await waitFor(() => expect(fetchMock.mock.calls.some((c) => String(c[0]).includes("/api/profiles/S-chatterbox/warmup?keep_others=false"))).toBe(true));
  });

  it("prepares a normal model with the TTS component only (no LLM key needed)", async () => {
    const cold = MODELS.map((m) => (m.profile === "L2" ? { ...m, warm: false } : m));
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url === "/api/tts/models") return new Response(JSON.stringify(cold));
      if (url === "/api/tts/sessions") return new Response("[]");
      if (url.includes("/warmup")) return new Response(JSON.stringify({ state: "ready", components: {} }), { status: 202 });
      return new Response("", { status: 404 });
    });
    render(<TtsPage />);
    fireEvent.click((await screen.findAllByRole("button", { name: "Hazırla" }))[0]);
    await waitFor(() => expect(fetchMock.mock.calls.some((c) => String(c[0]) === "/api/profiles/L2/warmup?keep_others=true&components=tts")).toBe(true));
  });

  it("listener mode hides model names and saves ratings", async () => {
    render(<TtsPage />);
    fireEvent.click(await screen.findByRole("tab", { name: "Dinleyici modu" }));
    fireEvent.change(await screen.findByLabelText("Dinleyici adı"), { target: { value: "Ayşe" } });
    fireEvent.click(screen.getByRole("button", { name: "Dinlemeye başla" }));
    expect(await screen.findByText(/Klip 1 \/ 2/)).toBeTruthy();
    expect(document.body.textContent).not.toMatch(/ema|chatterbox|elevenlabs|L2/);
    fireEvent.change(screen.getByLabelText("Doğallık"), { target: { value: "5" } });
    fireEvent.click(screen.getByRole("button", { name: "Kaydet ve sonraki" }));
    await screen.findByText(/Klip 2 \/ 2/);
    const rating = fetchMock.mock.calls.find((c) => String(c[0]).endsWith("/ratings"));
    expect(JSON.parse(rating![1].body)).toMatchObject({ listener: "Ayşe", token: "aaaaaaaaaaaaaaaa", naturalness: 5, humanlike: 3, mispronunciation: 0 });
    const audio = document.querySelector("audio")!;
    expect(audio.getAttribute("src")).toContain("/blind/bbbbbbbbbbbbbbbb/audio?listener=");
  });
});
