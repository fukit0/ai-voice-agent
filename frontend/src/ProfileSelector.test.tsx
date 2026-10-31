import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ProfileProvider } from "./ProfileContext";
import { ProfileSelector } from "./ProfileSelector";

const comp = (provider: string, model: string) => ({ provider, model, warm: true });
const profile = (id: string, tts: ReturnType<typeof comp>, extra = {}) => ({
  id, name: id, purpose: "", mode: "cascade", notes: "",
  components: { stt: comp("deepgram", "nova-3"), llm: comp("anthropic", "haiku"), tts },
  realtime: null, missing_env: [], issues: [], ready: true, warm: true, warmup: null, ...extra,
});
const MODELS = [
  { id: "eleven_flash_v2_5", label: "Flash v2.5", price_per_1k_usd: 0.04, latency_note: "", tags: false, notes: "" },
  { id: "eleven_v3", label: "v3", price_per_1k_usd: 0.08, latency_note: "", tags: true, notes: "" },
];
let puts: unknown[] = [];
let a1sModel = "eleven_flash_v2_5";
let a1sStream = true;

beforeEach(() => {
  puts = [];
  a1sModel = "eleven_flash_v2_5";
  a1sStream = true;
  localStorage.setItem("sva.profile", "A1S");
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const ok = (b: unknown) => ({ ok: true, status: 200, json: async () => b });
    if (url === "/api/profiles") {
      return ok([profile("L2", comp("ema", "")),
        profile("A1S", comp("elevenlabs", a1sModel), { tts_streaming: a1sStream, ...(a1sModel !== "eleven_flash_v2_5" ? { tts_default_model: "eleven_flash_v2_5" } : {}) })]);
    }
    if (url === "/api/profiles/tts-models") return ok({ profiles: [], models: MODELS });
    if (url.endsWith("/tts-streaming")) {
      puts.push([url, JSON.parse(String(init?.body))]);
      a1sStream = JSON.parse(String(init?.body)).streaming;
      return ok({});
    }
    if (url.endsWith("/tts-model")) {
      puts.push([url, JSON.parse(String(init?.body))]);
      a1sModel = JSON.parse(String(init?.body)).model;
      return ok({});
    }
    throw new Error(`beklenmeyen istek ${url}`);
  }));
});
afterEach(() => vi.unstubAllGlobals());

it("ElevenLabs'li profilde model seçilir ve kaydedilir; yeni model ekranda görünür, varsayılana dönülebilir", async () => {
  render(<ProfileProvider><ProfileSelector /></ProfileProvider>);
  const sel = await screen.findByLabelText("ElevenLabs modeli");
  expect((sel as HTMLSelectElement).value).toBe("eleven_flash_v2_5");
  fireEvent.change(sel, { target: { value: "eleven_v3" } });
  await waitFor(() => expect(puts).toEqual([["/api/profiles/A1S/tts-model", { model: "eleven_v3" }]]));
  await waitFor(() => expect((screen.getByLabelText("ElevenLabs modeli") as HTMLSelectElement).value).toBe("eleven_v3"));
  fireEvent.click(await screen.findByRole("button", { name: "Varsayılana dön" }));
  await waitFor(() => expect(puts[1]).toEqual(["/api/profiles/A1S/tts-model", { model: "eleven_flash_v2_5" }]));
});

it("Akışlı TTS kutusu profilde açılıp kapatılır", async () => {
  render(<ProfileProvider><ProfileSelector /></ProfileProvider>);
  const box = (await screen.findByLabelText("Akışlı TTS")) as HTMLInputElement;
  expect(box.checked).toBe(true);
  fireEvent.click(box);
  await waitFor(() => expect(puts).toEqual([["/api/profiles/A1S/tts-streaming", { streaming: false }]]));
  await waitFor(() => expect((screen.getByLabelText("Akışlı TTS") as HTMLInputElement).checked).toBe(false));
});

it("ElevenLabs olmayan profilde model seçici görünmez", async () => {
  localStorage.setItem("sva.profile", "L2");
  render(<ProfileProvider><ProfileSelector /></ProfileProvider>);
  await screen.findByLabelText("Profil");
  expect(screen.queryByLabelText("ElevenLabs modeli")).toBeNull();
  expect(screen.queryByLabelText("Akışlı TTS")).toBeNull();
});
