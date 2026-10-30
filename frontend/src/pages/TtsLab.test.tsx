import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TtsLab } from "./TtsLab";

const MATRIX = {
  source: "elevenlabs.io/pricing/api, 2026-10-30", price_note: "Liste fiyatı.",
  models: [
    { id: "eleven_flash_v2_5", label: "Flash v2.5", price_per_1k_usd: 0.04, latency_note: "~75 ms", tags: false, tone_levers: "kararlılık, hız", notes: "" },
    { id: "eleven_v4_turbo", label: "v4 Turbo", price_per_1k_usd: 0.04, latency_note: "~100 ms", tags: true, tone_levers: "ses etiketleri", notes: "" },
  ],
};
const VOICES = [{ voice_id: "hesapses12345", name: "Egemen", description: "", preview_url: null, source: "account", public_owner_id: null, tags: [] }];

function mockApi() {
  const labCalls: any[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    if (url === "/api/persona/model-matrix") return new Response(JSON.stringify(MATRIX));
    if (url.startsWith("/api/persona/voices?")) return new Response(JSON.stringify({ voices: VOICES, assigned: {} }));
    if (url === "/api/persona/tts-lab") {
      labCalls.push(body);
      const tag = body.model === "eleven_v4_turbo";
      const first = tag ? 0.31 : 0.12;
      return new Response(JSON.stringify({
        model: body.model, voice_id: body.voice_id ?? "genel", tone: body.tone, seed: 1234, chars: tag ? 40 : 30,
        sent_text: tag ? `[excited] ${body.text}` : body.text, applied: { stability: 0.2 }, price_per_1k_usd: 0.04, cost_usd: 0.0012,
        median_first_audio_seconds: first,
        runs: [{ id: `lab-${labCalls.length}`, url: `/api/persona/tone-demo/lab-${labCalls.length}.wav`, first_audio_seconds: first, total_seconds: first + 0.5, audio_seconds: 3, acoustics: {} }],
      }));
    }
    return new Response("", { status: 404 });
  }));
  return labCalls;
}
afterEach(() => vi.unstubAllGlobals());

describe("TTS laboratuvarı", () => {
  it("seçilen model, ses ve tonla üretir; ölçümü matrise yazar", async () => {
    const calls = mockApi();
    render(<TtsLab />);
    await screen.findByRole("option", { name: "v4 Turbo" });
    fireEvent.change(screen.getByLabelText("Model"), { target: { value: "eleven_v4_turbo" } });
    await screen.findByRole("option", { name: "Egemen" });
    fireEvent.change(screen.getByLabelText("Ses"), { target: { value: "hesapses12345" } });
    fireEvent.change(screen.getByLabelText("Ton"), { target: { value: "sakin" } });
    fireEvent.change(screen.getByLabelText("Tekrar"), { target: { value: "2" } });
    fireEvent.click(screen.getByRole("button", { name: "Bu modelle dene" }));
    expect(await screen.findByTestId("lab-eleven_v4_turbo")).toHaveTextContent("ilk ses (medyan): 0.310 sn");
    expect(calls[0]).toMatchObject({ model: "eleven_v4_turbo", voice_id: "hesapses12345", tone: "sakin", runs: 2 });
    expect(screen.getByTestId("matrix-eleven_v4_turbo")).toHaveTextContent("0.310");
    expect(screen.getByTestId("lab-eleven_v4_turbo")).toHaveTextContent("gönderilen metin etiket içerir");
  });

  it("tüm modelleri sırayla dener ve aylık maliyeti hesaplar", async () => {
    const calls = mockApi();
    render(<TtsLab />);
    await screen.findByTestId("lab-matrix");
    fireEvent.click(screen.getByRole("button", { name: "Tüm modelleri sırayla dene" }));
    await waitFor(() => expect(calls).toHaveLength(2));
    await waitFor(() => expect(screen.getByTestId("matrix-eleven_flash_v2_5")).toHaveTextContent("0.120"));
    // Flash: 30 karakter x 0,04$/1K = 0,00120 $; 10.000 çağrı = 12,00 $
    expect(screen.getByTestId("matrix-eleven_flash_v2_5")).toHaveTextContent("0.00120");
    expect(screen.getByTestId("matrix-eleven_flash_v2_5")).toHaveTextContent("12.00");
  });

  it("hatayı gösterir", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url === "/api/persona/model-matrix") return new Response(JSON.stringify(MATRIX));
      if (url.startsWith("/api/persona/voices?")) return new Response(JSON.stringify({ voices: [], assigned: {} }));
      return new Response(JSON.stringify({ detail: { message: "ELEVENLABS_API_KEY tanımlı değil." } }), { status: 400 });
    }));
    render(<TtsLab />);
    await screen.findByTestId("lab-matrix");
    fireEvent.click(screen.getByRole("button", { name: "Bu modelle dene" }));
    expect(await screen.findByRole("note")).toHaveTextContent("ELEVENLABS_API_KEY");
  });
});
