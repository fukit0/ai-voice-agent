import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ProfileProvider } from "../ProfileContext";
import type { VoiceHooks } from "../voice";
import { PlaygroundPage } from "./PlaygroundPage";

const startVoice = vi.fn();
vi.mock("../voice", () => ({ startVoice: (...a: unknown[]) => startVoice(...a) }));

const PROFILES = [{
  id: "L2", name: "Dengeli", purpose: "", mode: "cascade", realtime: null, notes: "", ready: true, warm: true, issues: [], missing_env: [], warmup: null,
  components: { stt: { provider: "mlx_whisper", model: "w", warm: true }, llm: { provider: "ollama", model: "q", warm: true },
    tts: { provider: "ema", model: "", warm: true } },
}];

let hooks: VoiceHooks;
const close = vi.fn(async () => {});
beforeEach(() => {
  startVoice.mockReset();
  close.mockClear();
  startVoice.mockImplementation(async (_p: string, h: VoiceHooks) => { hooks = h; return { sessionId: "s1", close }; });
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(PROFILES))));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const renderPage = () => render(<ProfileProvider><PlaygroundPage /></ProfileProvider>);

describe("Playground (core-001)", () => {
  it("Başlat aktif profille bağlanır; durum, transkript ve tur gecikmesi canlı akar; Durdur kapatır", async () => {
    renderPage();
    const start = await screen.findByRole("button", { name: "Başlat" });
    await waitFor(() => expect(start).toBeEnabled());
    fireEvent.click(start);
    await waitFor(() => expect(startVoice).toHaveBeenCalledWith("L2", expect.any(Object)));
    act(() => {
      hooks.onEvent({ type: "state", state: "listening" });
      hooks.onEvent({ type: "transcript", role: "agent", text: "Merhaba, ben Ayşe.", t: 0.5 });
      hooks.onEvent({ type: "transcript", role: "user", text: "merhaba", t: 3 });
      hooks.onEvent({ type: "turn", turn: 2, stt_s: 0.4, llm_s: 0.3, tts_first_s: 0.1, first_audio_after_end_s: 0.9, endpoint_wait_ms: 600 });
      hooks.onEvent({ type: "state", state: "speaking" });
    });
    expect(screen.getByTestId("voice-state")).toHaveTextContent("Konuşuyor");
    expect(screen.getByTestId("voice-lines")).toHaveTextContent("Ajan: Merhaba, ben Ayşe.");
    expect(screen.getByTestId("voice-lines")).toHaveTextContent("Siz: merhaba");
    expect(screen.getByTestId("voice-latency")).toHaveTextContent("STT 0.40 sn");
    expect(screen.getByTestId("voice-latency")).toHaveTextContent("ilk sese 0.90 sn");
    fireEvent.click(screen.getByRole("button", { name: "Durdur" }));
    await waitFor(() => expect(close).toHaveBeenCalled());
    expect(await screen.findByRole("button", { name: "Başlat" })).toBeInTheDocument();
  });

  it("mikrofon izni / soğuk profil hatasını gösterir ve Başlat'ı geri açar", async () => {
    startVoice.mockRejectedValueOnce(new Error("L2 profili hazır değil (STT soğuk). Önce 'Hazırla' ile modelleri yükleyin."));
    renderPage();
    const start = await screen.findByRole("button", { name: "Başlat" });
    await waitFor(() => expect(start).toBeEnabled());
    fireEvent.click(start);
    expect(await screen.findByRole("alert")).toHaveTextContent("Hazırla");
    expect(screen.getByRole("button", { name: "Başlat" })).toBeEnabled();
  });

  it("söz kesme sayısını ve sunucu hatasını gösterir", async () => {
    renderPage();
    const start = await screen.findByRole("button", { name: "Başlat" });
    await waitFor(() => expect(start).toBeEnabled());
    fireEvent.click(start);
    await waitFor(() => expect(startVoice).toHaveBeenCalled());
    act(() => {
      hooks.onEvent({ type: "state", state: "listening" });
      hooks.onEvent({ type: "barge_in" });
      hooks.onEvent({ type: "error", message: "RuntimeError: stt patladı" });
    });
    expect(screen.getByText("söz kesme: 1")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("stt patladı");
  });
});
