import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ProfileProvider } from "./ProfileContext";
import { ProfileSelector } from "./ProfileSelector";

const comp = (provider: string, model: string) => ({ provider, model, warm: true });
beforeEach(() => {
  localStorage.setItem("sva.profile", "A1S");
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, status: 200, json: async () => [{
    id: "A1S", name: "A1S", purpose: "", mode: "cascade", notes: "", realtime: null, missing_env: [], issues: [], ready: true, warm: true, warmup: null,
    components: { stt: comp("deepgram", "nova-3"), llm: comp("anthropic", "haiku"), tts: comp("elevenlabs", "eleven_flash_v2_5") } }] })));
});
afterEach(() => vi.unstubAllGlobals());

it("üst çubukta yalnız profil seçici var; ElevenLabs ayarları Ayarlar sayfasına taşındı", async () => {
  render(<ProfileProvider><ProfileSelector /></ProfileProvider>);
  await screen.findByLabelText("Profil");
  expect(screen.queryByLabelText("ElevenLabs modeli")).toBeNull();
  expect(screen.queryByLabelText("Akışlı TTS")).toBeNull();
});
