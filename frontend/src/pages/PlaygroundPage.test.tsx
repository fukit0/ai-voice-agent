import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
const setPhone = vi.fn();
const SCENARIOS = [{ key: "anket", label: "Çağrı Merkezi Memnuniyet Anketi", shortLabel: "Anket", description: "", steps: 33, outcomes: [], problems: [] }];
beforeEach(() => {
  startVoice.mockReset();
  close.mockClear();
  startVoice.mockImplementation(async (_p: string, h: VoiceHooks) => { hooks = h; return { sessionId: "s1", close, setPhoneFilter: setPhone }; });
  setPhone.mockClear();
  vi.stubGlobal("fetch", vi.fn(async (url: string) =>
    new Response(JSON.stringify(url === "/api/scenarios" ? SCENARIOS : PROFILES))));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const renderPage = () => render(<ProfileProvider><PlaygroundPage /></ProfileProvider>);

describe("Playground (core-001)", () => {
  it("Başlat aktif profille bağlanır; durum, transkript ve tur gecikmesi canlı akar; Durdur kapatır", async () => {
    renderPage();
    const start = await screen.findByRole("button", { name: "Başlat" });
    await waitFor(() => expect(start).toBeEnabled());
    fireEvent.click(start);
    await waitFor(() => expect(startVoice).toHaveBeenCalledWith("L2", expect.any(Object), { scenario: "anket", phoneFilter: false, record: false }));
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
    const row = within(screen.getByTestId("voice-latency")).getAllByRole("row")[1];
    for (const cell of ["0.40 sn", "0.30 sn", "0.10 sn", "0.90 sn", "0.6 sn"]) expect(row).toHaveTextContent(cell);
    fireEvent.click(screen.getByRole("button", { name: "Durdur" }));
    await waitFor(() => expect(close).toHaveBeenCalled());
    expect(await screen.findByRole("button", { name: "Başlat" })).toBeInTheDocument();
  });

  it("realtime tur gecikmesi uçtan uca gösterilir; STT/LLM/TTS sütunu yoktur ve arayüzde böyle belirtilir (core-011)", async () => {
    renderPage();
    const start = await screen.findByRole("button", { name: "Başlat" });
    await waitFor(() => expect(start).toBeEnabled());
    fireEvent.click(start);
    await waitFor(() => expect(startVoice).toHaveBeenCalled());
    act(() => {
      hooks.onEvent({ type: "turn", turn: 1, greeting: true, realtime: true, speak_s: 0.5 });
      hooks.onEvent({ type: "turn", turn: 2, realtime: true, answer_s: 0.7, speak_s: 0.6, first_audio_after_end_s: 1.3 });
      hooks.onEvent({ type: "turn", turn: 3, realtime: true, no_tool_call: true, speak_s: 0.5, first_audio_after_end_s: 1.1 });
    });
    expect(screen.getByTestId("realtime-note")).toHaveTextContent("ayrı STT / LLM / TTS süresi yoktur");
    const table = screen.getByTestId("voice-latency");
    expect(within(table).queryByText("STT")).not.toBeInTheDocument();
    const rows = within(table).getAllByRole("row");
    for (const cell of ["0.70 sn", "0.60 sn", "1.30 sn"]) expect(rows[2]).toHaveTextContent(cell);
    expect(rows[3]).toHaveTextContent("fonksiyon çağrılmadı");
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

describe("Playground senaryo modu (lab-003)", () => {
  it("senaryo ve telefon filtresi ile başlar; aktif düğüm, çıkarılan cevaplar ve sonuç canlı görünür; filtre canlı değişir", async () => {
    renderPage();
    const select = await screen.findByLabelText("Senaryo");
    await waitFor(() => expect(select).toHaveValue("anket"));
    fireEvent.click(screen.getByRole("checkbox", { name: /Telefon filtresi/ }));
    const start = screen.getByRole("button", { name: "Başlat" });
    await waitFor(() => expect(start).toBeEnabled());
    fireEvent.click(start);
    await waitFor(() => expect(startVoice).toHaveBeenCalledWith("L2", expect.any(Object), { scenario: "anket", phoneFilter: true, record: false }));
    act(() => {
      hooks.onEvent({ type: "state", state: "listening" });
      hooks.onEvent({ type: "node", key: "q2", code: "Q2", title: "Temsilciden genel memnuniyet", kind: "Score", group: "Temsilci Değerlendirmesi", spoken: "…", terminal: false });
      hooks.onEvent({ type: "answer", step: "q2", code: "Q2", title: "Temsilciden genel memnuniyet", kind: "Score", value: 8, utterance: "sekiz veririm", unanswered: false });
      hooks.onEvent({ type: "answer", step: "q5", code: "Q5", title: "Bekleme süresi", kind: "Duration", value: null, utterance: "", unanswered: true });
    });
    expect(screen.getByTestId("active-node")).toHaveTextContent("Temsilciden genel memnuniyet");
    expect(screen.getByTestId("active-node")).toHaveTextContent("adım 1 / 33");
    const answers = screen.getByTestId("voice-answers");
    expect(answers).toHaveTextContent("Q2");
    expect(answers).toHaveTextContent("8");
    expect(answers).toHaveTextContent("“sekiz veririm”");
    expect(answers).toHaveTextContent("cevap yok");
    fireEvent.click(screen.getByRole("checkbox", { name: /Telefon filtresi/ }));   // konuşma sürerken kapat
    expect(setPhone).toHaveBeenCalledWith(false);
    act(() => hooks.onEvent({ type: "outcome", outcome: "tamamlandi", label: "Anket tamamlandı" }));
    expect(screen.getByTestId("voice-outcome")).toHaveTextContent("Anket tamamlandı");
  });

  it("söz kesme süresini gösterir; yarım cümlede 'devamını bekliyor' göstergesi açılıp kapanır", async () => {
    renderPage();
    const start = await screen.findByRole("button", { name: "Başlat" });
    await waitFor(() => expect(start).toBeEnabled());
    fireEvent.click(start);
    await waitFor(() => expect(startVoice).toHaveBeenCalled());
    act(() => hooks.onEvent({ type: "state", state: "listening" }));
    act(() => hooks.onEvent({ type: "barge_in", cut_ms: 142 }));
    expect(screen.getByText(/söz kesme: 1 · son: 142 ms/)).toBeInTheDocument();
    act(() => hooks.onEvent({ type: "hold", on: true, text: "evet ama" }));
    expect(screen.getByTestId("voice-hold")).toHaveTextContent("devamını bekliyor");
    act(() => hooks.onEvent({ type: "hold", on: false }));
    expect(screen.queryByTestId("voice-hold")).not.toBeInTheDocument();
  });

  it("senaryosuz serbest sohbet seçilirse senaryo gönderilmez", async () => {
    renderPage();
    const select = await screen.findByLabelText("Senaryo");
    await waitFor(() => expect(select).toHaveValue("anket"));
    fireEvent.change(select, { target: { value: "" } });
    const start = screen.getByRole("button", { name: "Başlat" });
    await waitFor(() => expect(start).toBeEnabled());
    fireEvent.click(start);
    await waitFor(() => expect(startVoice).toHaveBeenCalledWith("L2", expect.any(Object), { scenario: undefined, phoneFilter: false, record: false }));
    expect(screen.queryByTestId("active-node")).not.toBeInTheDocument();
  });
  it("ses kaydı varsayılan kapalıdır; açılırsa record:true gönderilir, durdurunca kayıt oynatıcısı ve silme çıkar (core-013)", async () => {
    renderPage();
    const toggle = await screen.findByTestId("record-toggle");
    expect(toggle).not.toBeChecked();
    expect(screen.queryByTestId("recording-box")).toBeNull();
    fireEvent.click(toggle);
    const start = await screen.findByRole("button", { name: "Başlat" });
    await waitFor(() => expect(start).toBeEnabled());
    fireEvent.click(start);
    await waitFor(() => expect(startVoice).toHaveBeenCalledWith("L2", expect.any(Object), { scenario: "anket", phoneFilter: false, record: true }));
    expect(screen.getByTestId("record-toggle")).toBeDisabled();            // konuşma sürerken değiştirilemez
    fireEvent.click(screen.getByRole("button", { name: "Durdur" }));
    const box = await screen.findByTestId("recording-box");
    expect(within(box).getByTestId("recording-audio")).toHaveAttribute("src", "/api/voice/recordings/s1.wav");
    fireEvent.click(within(box).getByRole("button", { name: "Kaydı sil" }));
    await waitFor(() => expect(screen.queryByTestId("recording-box")).toBeNull());
    expect(fetch).toHaveBeenCalledWith("/api/voice/recordings/s1", { method: "DELETE" });
  });
});
