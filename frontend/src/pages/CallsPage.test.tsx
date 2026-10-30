import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CallsPage } from "./CallsPage";

const row = (o: Record<string, unknown>) => ({
  id: "aaaaaaaaaaa1", profile: "L2", started_at: "2026-10-30T10:00:00", scenario: "anket", outcome: "completed", duration_s: 42,
  turns: 3, answers: 2, unanswered: 0, first_audio_p50_s: 1.4, first_audio_max_s: 2, stt_p50_s: 0.4, llm_p50_s: 0.8,
  tts_first_p50_s: 0.2, tts_total_p50_s: 0.9, barge_ins: 0, stt_rejected: 0, stt: "mlx", llm: "qwen", tts: "ema", tts_tone: null,
  tts_speed: 1, phone_filter: false, realtime: false, has_audio: true, ...o,
});
const CALLS = [
  row({}),
  row({ id: "bbbbbbbbbbb1", profile: "L2-EL", started_at: "2026-10-30T12:00:00", first_audio_p50_s: 1.9, tts: "elevenlabs:eleven_v4_turbo", tts_tone: "enerjik", has_audio: false }),
];
const group = (o: Record<string, unknown>) => ({
  key: "L2", label: "L2", sessions: 6, turns: 18, first_audio: { p50: 1.4, p95: 2.2, min: 1, max: 2.5 },
  stages: { stt: 0.4, llm: 0.8, tts_first: 0.2, tts_total: 0.9 }, outcomes: { completed: 5, refused: 1 }, avg_duration_s: 40, avg_answers: 2,
  barge_ins_per_call: 0.5, stt_rejected_total: 0, tts: ["ema"], tones: [], realtime: false, meets_p50_target: false, enough_sessions: true,
  usage_calls: 6, avg_cost_usd: 0.0041, cost_complete: true, avg_gpu_s: 12.34, avg_stt_minutes: 0.5, avg_tts_chars: 300,
  is_baseline: true, delta_p50_s: 0, delta_pct: 0, ...o,
});
const COMPARE = {
  group: "profile", baseline: "L2", p50_target_s: 1.2, min_sessions: 5, definition: "Gecikme: VAD bitişinden ilk sese.",
  groups: [group({}), group({ key: "L2-EL", label: "L2-EL", sessions: 2, enough_sessions: false, first_audio: { p50: 1.9, p95: 2.4, min: 1.5, max: 2.5 },
    is_baseline: false, delta_p50_s: 0.5, delta_pct: 35.7, tts: ["elevenlabs:eleven_v4_turbo"], tones: ["enerjik"] })],
};
const USAGE = {
  items: { duration_s: 60, user_speech_s: 20, agent_speech_s: 25, speech_share: 0.75, stt_minutes: 0.33, stt_calls: 5, llm_calls: 6,
    llm_input_tokens: 3000, llm_output_tokens: 120, tts_chars: 640, tts_calls: 7, tts_audio_s: 24, gpu_s: 0 },
  missing: [], cost: { currency: "USD", by_component: { stt: 0.003, llm: 0.00036, tts: 0.0256 }, total: 0.02896, complete: true, unpriced: [],
    prices_verified: false, note: "yerel bileşenler 0" },
};
const DETAIL = {
  ...row({}), turns: [{ turn: 0, greeting: true, first_audio_after_end_s: 9 }, { turn: 1, first_audio_after_end_s: 1.4, stt_s: 0.4, llm_s: 0.8, tts_first_s: 0.2 }],
  answers: [{ step: "Q1", title: "Memnuniyet", kind: "yesno", value: "evet", utterance: "evet memnunum", unanswered: false }],
  transcript: [{ role: "agent", text: "Merhaba, kısa bir anket." }, { role: "user", text: "Tamam" }], path: ["intro"], prompt: null, stats: {},
  audio_url: "/api/voice/recordings/aaaaaaaaaaa1.wav", usage: USAGE,
};

function mockApi(opts: { empty?: boolean } = {}) {
  const urls: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    urls.push(url);
    const ok = (b: unknown) => new Response(JSON.stringify(b));
    if (url.startsWith("/api/calls/compare")) {
      if (opts.empty) return ok({ ...COMPARE, groups: [] });
      if (url.includes("group=call")) return ok({ ...COMPARE, group: "call", baseline: "aaaaaaaaaaa1", groups: [group({ key: "aaaaaaaaaaa1", label: "L2 · 10-30 10:00", sessions: 1 })] });
      return ok(COMPARE);
    }
    if (url.startsWith("/api/calls/aaaaaaaaaaa1")) return ok(DETAIL);
    if (url.startsWith("/api/calls/bbbbbbbbbbb1")) return ok({ ...DETAIL, audio_url: null, has_audio: false });
    if (url.startsWith("/api/calls")) {
      return ok({ calls: opts.empty ? [] : CALLS, total: opts.empty ? 0 : 2, facets: { profiles: ["L2", "L2-EL"], scenarios: ["anket"], outcomes: ["completed"] } });
    }
    return new Response("", { status: 404 });
  }));
  return urls;
}
afterEach(() => vi.unstubAllGlobals());

describe("Aramalar", () => {
  it("profil bazlı kıyası farkla, hedef rozetiyle ve 'örnek az' uyarısıyla gösterir", async () => {
    mockApi();
    render(<CallsPage />);
    const base = await screen.findByTestId("cmp-L2");
    expect(base).toHaveTextContent("taban");
    expect(base).toHaveTextContent("1.40 sn");
    expect(base).toHaveTextContent("≥ 1.2");                       // hedefi tutmuyor
    const el = screen.getByTestId("cmp-L2-EL");
    expect(el).toHaveTextContent("+0.50 sn (+36%)");
    expect(el).toHaveTextContent("örnek az");                        // < 5 arama
    expect(el).toHaveTextContent("enerjik");
    expect(base).not.toHaveTextContent("örnek az");
    expect(screen.getByTestId("compare-table")).toBeInTheDocument();
    expect(screen.getByText(/Gecikme: VAD bitişinden ilk sese/)).toBeInTheDocument();   // tanım ekranda
  });

  it("tabanı değiştirir (sunucuya baseline iletir)", async () => {
    const urls = mockApi();
    render(<CallsPage />);
    fireEvent.click(await screen.findByRole("button", { name: "L2-EL tabanı yap" }));
    await waitFor(() => expect(urls.some((u) => u.includes("/compare") && u.includes("baseline=L2-EL"))).toBe(true));
  });

  it("aramaları listeler, süzgeci sunucuya iletir ve detayı ses kaydıyla açar", async () => {
    const urls = mockApi();
    render(<CallsPage />);
    fireEvent.click(await screen.findByRole("tab", { name: /Aramalar/ }));
    const r1 = await screen.findByTestId("call-aaaaaaaaaaa1");
    expect(r1).toHaveTextContent("L2");
    expect(r1).toHaveTextContent("var");
    expect(screen.getByTestId("call-bbbbbbbbbbb1")).toHaveTextContent("yok");     // ses kaydı yok
    expect(screen.getByTestId("call-bbbbbbbbbbb1")).toHaveTextContent("elevenlabs:eleven_v4_turbo · enerjik");
    fireEvent.change(screen.getByLabelText("Profil"), { target: { value: "L2-EL" } });
    await waitFor(() => expect(urls.some((u) => u.startsWith("/api/calls?") && u.includes("profile=L2-EL"))).toBe(true));
    fireEvent.click(within(r1).getByRole("button", { name: "aaaaaa detayını aç" }));
    const detail = await screen.findByTestId("call-detail");
    expect(await within(detail).findByTestId("call-audio")).toHaveAttribute("src", "/api/voice/recordings/aaaaaaaaaaa1.wav");
    expect(detail).toHaveTextContent("Memnuniyet");
    expect(detail).toHaveTextContent("evet memnunum");
    expect(detail).toHaveTextContent("Merhaba, kısa bir anket.");
    expect(detail).toHaveTextContent("açılış");                                   // tur tablosunda açılış turu işaretli
    fireEvent.click(within(detail).getByRole("button", { name: "Detayı kapat" }));
    expect(screen.queryByTestId("call-detail")).toBeNull();
  });

  it("ses kaydı olmayan aramanın detayında uyarı gösterir", async () => {
    mockApi();
    render(<CallsPage />);
    fireEvent.click(await screen.findByRole("tab", { name: /Aramalar/ }));
    fireEvent.click(await screen.findByRole("button", { name: "bbbbbb detayını aç" }));
    const detail = await screen.findByTestId("call-detail");
    expect(await within(detail).findByText(/Ses kaydı yok/)).toBeInTheDocument();
    expect(within(detail).queryByTestId("call-audio")).toBeNull();
  });

  it("seçilen aramaları karşılaştırır", async () => {
    const urls = mockApi();
    render(<CallsPage />);
    fireEvent.click(await screen.findByRole("tab", { name: /Aramalar/ }));
    const go = screen.getByRole("button", { name: /Seçilenleri karşılaştır/ });
    expect(go).toBeDisabled();
    fireEvent.click(await screen.findByRole("checkbox", { name: /L2 .*aramasını seç/ }));
    fireEvent.click(go);
    expect(await screen.findByTestId("cmp-aaaaaaaaaaa1")).toHaveTextContent("L2 · 10-30 10:00");
    expect(urls.some((u) => u.includes("group=call") && u.includes("ids=aaaaaaaaaaa1"))).toBe(true);
  });

  it("kayıt yokken yönlendirici boş durum gösterir", async () => {
    mockApi({ empty: true });
    render(<CallsPage />);
    expect(await screen.findByText(/Kıyaslanacak arama yok/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: /Aramalar/ }));
    expect(await screen.findByText(/Henüz arama yok/)).toBeInTheDocument();
  });

  it("API hatasını gösterir", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail: { message: "Sunucu hatası" } }), { status: 500 })));
    render(<CallsPage />);
    expect((await screen.findAllByRole("alert"))[0]).toHaveTextContent("Sunucu hatası");
  });

  it("kaynak ve maliyeti gösterir: kalemler, toplam ve doğrulanmamış fiyat uyarısı", async () => {
    mockApi();
    render(<CallsPage />);
    fireEvent.click(await screen.findByRole("tab", { name: /Aramalar/ }));
    fireEvent.click(within(await screen.findByTestId("call-aaaaaaaaaaa1")).getByRole("button", { name: "aaaaaa detayını aç" }));
    const panel = await screen.findByTestId("call-usage");
    expect(panel).toHaveTextContent("0.33 dk");
    expect(panel).toHaveTextContent("3.000 giriş / 120 çıkış token");
    expect(panel).toHaveTextContent("640 karakter");
    expect(panel).toHaveTextContent("$0.0290");
    expect(panel).toHaveTextContent("doğrulanmadı");
  });

  it("eski kayıtta ölçüm yok notunu gösterir, sıfır yazmaz", async () => {
    mockApi();
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      const ok = (b: unknown) => new Response(JSON.stringify(b));
      if (url.startsWith("/api/calls/compare")) return ok(COMPARE);
      if (url.startsWith("/api/calls/aaaaaaaaaaa1")) return ok({ ...DETAIL, usage: null });
      return ok({ calls: CALLS, total: 2, facets: { profiles: [], scenarios: [], outcomes: [] } });
    }));
    render(<CallsPage />);
    fireEvent.click(await screen.findByRole("tab", { name: /Aramalar/ }));
    fireEvent.click(within(await screen.findByTestId("call-aaaaaaaaaaa1")).getByRole("button", { name: "aaaaaa detayını aç" }));
    expect(await screen.findByText(/kaynak ölçümü yok/)).toBeInTheDocument();
  });

  it("kıyas tablosunda arama başına maliyet ve GPU saniyesi görünür; eksik kalem uyarılır", async () => {
    mockApi();
    render(<CallsPage />);
    expect(await screen.findByTestId("cmp-L2")).toHaveTextContent("$0.0041");
    expect(screen.getByTestId("cmp-L2")).toHaveTextContent("12.3");
    expect(screen.getByTestId("cmp-L2")).not.toHaveTextContent("eksik");
  });
});
