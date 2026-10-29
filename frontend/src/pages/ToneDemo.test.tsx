import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ToneDemo } from "./ToneDemo";

const PROFILES = [
  { id: "p-ema", components: { tts: { provider: "ema", model: "ema-lightning" } } },
  { id: "p-el", components: { tts: { provider: "elevenlabs", model: "eleven_flash_v2_5" } } },
];
const clip = (tone: string, label: string, applied: object) => ({
  tone, label, id: `c-${tone}`, url: `/api/persona/tone-demo/c-${tone}.wav`, seconds: 0.4, applied,
  acoustics: { seconds: 3, words_per_sec: 3.1, pitch_median_hz: 180, pitch_std_semitones: 2.4 },
});

function mockApi() {
  const calls: { url: string; body?: any }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ url, body });
    if (url === "/api/profiles") return new Response(JSON.stringify(PROFILES));
    if (url === "/api/persona/tones") return new Response(JSON.stringify({ tones: [], demo_text: "Merhaba Ahmet Bey." }));
    if (url === "/api/persona/tone-demo") {
      return new Response(JSON.stringify({
        profile: body.profile, provider: "elevenlabs", model: body.model ?? "eleven_flash_v2_5", seed: 1234, tag_model: body.model === "eleven_v4_turbo",
        takes_tone: true, text: body.text,
        clips: [clip("samimi", "Samimi", { stability: 0.45 }), clip("enerjik", "Enerjik", { stability: 0.2, speed: 1.15 })],
      }));
    }
    return new Response("", { status: 404 });
  }));
  return calls;
}
afterEach(() => vi.unstubAllGlobals());

describe("Ton demosu", () => {
  it("profil ve modeli seçip klipleri parametre ve akustik sayılarla gösterir", async () => {
    const calls = mockApi();
    render(<ToneDemo />);
    await waitFor(() => expect(screen.getByLabelText(/Cümle/)).toHaveValue("Merhaba Ahmet Bey."));
    fireEvent.change(await screen.findByLabelText("Profil (TTS)"), { target: { value: "p-el" } });
    fireEvent.change(await screen.findByLabelText("ElevenLabs modeli"), { target: { value: "eleven_v4_turbo" } });
    fireEvent.click(screen.getByRole("button", { name: "Dört tonu üret" }));
    expect(await screen.findByTestId("tone-enerjik")).toHaveTextContent("speed: 1.15");
    expect(screen.getByTestId("tone-samimi")).toHaveTextContent("perde (Hz): 180");
    const sent = calls.find((c) => c.url === "/api/persona/tone-demo")!.body;
    expect(sent).toMatchObject({ profile: "p-el", model: "eleven_v4_turbo", text: "Merhaba Ahmet Bey." });
    expect(screen.getByRole("button", { name: "Sırayla çal" })).toBeInTheDocument();
  });

  it("ElevenLabs olmayan profilde model seçimi çıkmaz ve model gönderilmez", async () => {
    const calls = mockApi();
    render(<ToneDemo />);
    await screen.findByLabelText("Profil (TTS)");
    expect(screen.queryByLabelText("ElevenLabs modeli")).toBeNull();
    fireEvent.click(await screen.findByRole("button", { name: "Dört tonu üret" }));
    await screen.findByTestId("tone-results");
    expect(calls.find((c) => c.url === "/api/persona/tone-demo")!.body.model).toBeNull();
  });
});
