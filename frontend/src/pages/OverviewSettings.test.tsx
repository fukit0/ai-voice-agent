import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App, ROUTER_FUTURE } from "../App";
import { mmss, median } from "./OverviewPage";

// ui-001: Genel Bakış (hesaplar gerçek kayıtlardan), Ayarlar, tema ve çekmece menü.

const row = (over: Record<string, unknown>) => ({
  id: "a", profile: "L1", started_at: new Date().toISOString().slice(0, 19), scenario: "anket", outcome: "completed", duration_s: 120,
  turns: 10, answers: 6, unanswered: 1, first_audio_p50_s: 1.0, first_audio_max_s: 2, stt_p50_s: 0.3, llm_p50_s: 0.4, tts_first_p50_s: 0.2,
  tts_total_p50_s: 1, barge_ins: 2, stt_rejected: 1, stt: "w", llm: "q", tts: "e", tts_tone: null, tts_speed: null, phone_filter: false,
  realtime: false, has_audio: true, ...over,
});

const PROFILE = {
  id: "L1", name: "Hızlı", purpose: "", mode: "cascade", notes: "",
  components: { stt: { provider: "mlx_whisper", model: "turbo" }, llm: { provider: "ollama", model: "gemma" }, tts: { provider: "ema", model: "ema-l" } },
  realtime: null, missing_env: ["DEEPGRAM_API_KEY"], issues: [], ready: false, warm: false, warmup: null,
};

function mock(calls: unknown[]) {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url.startsWith("/api/health")) return new Response(JSON.stringify({ status: "ok", version: "0.1.0" }));
    if (url.startsWith("/api/calls")) return new Response(JSON.stringify({ calls, total: calls.length, facets: { profiles: [], scenarios: [], outcomes: [] } }));
    if (url.startsWith("/api/profiles")) return new Response(JSON.stringify([PROFILE]));
    return new Response("", { status: 404 });
  }));
}
const renderAt = (path: string) => render(<MemoryRouter initialEntries={[path]} future={ROUTER_FUTURE}><App /></MemoryRouter>);

beforeEach(() => { try { localStorage.clear(); } catch { /* yok */ } document.documentElement.removeAttribute("data-theme"); });
afterEach(() => vi.unstubAllGlobals());

describe("Genel Bakış", () => {
  it("kayıt yoksa boş durumu ve Yeni Arama bağlantısını gösterir, sayı uydurmaz", async () => {
    mock([]);
    renderAt("/overview");
    expect(await screen.findByTestId("overview-empty")).toHaveTextContent("Henüz arama kaydı yok");
    expect(screen.queryByTestId("kpis")).not.toBeInTheDocument();
  });

  it("KPI'ları kayıtlardan hesaplar: sayı, tamamlanma, süre, medyan tepki, söz kesme", async () => {
    mock([
      row({ id: "1", outcome: "completed", duration_s: 60, first_audio_p50_s: 0.9, barge_ins: 1 }),
      row({ id: "2", outcome: "refused", duration_s: 180, first_audio_p50_s: 1.5, barge_ins: 3 }),
      row({ id: "3", outcome: "completed", duration_s: 120, first_audio_p50_s: 1.1, barge_ins: 0 }),
    ]);
    renderAt("/overview");
    const kpis = await screen.findByTestId("kpis");
    expect(kpis).toHaveTextContent("3arama");                  // görüşme sayısı
    expect(kpis).toHaveTextContent("%66,7 tamamlanma");        // 2/3
    expect(kpis).toHaveTextContent("02:00");                   // ortalama 120 sn
    expect(kpis).toHaveTextContent("1,10");                    // medyan(0.9, 1.5, 1.1)
    expect(kpis).toHaveTextContent("4kez");                    // 1+3+0
    expect(kpis).toHaveTextContent("hedef ≤ 1,2 sn");
    expect(within(screen.getByTestId("recent-calls")).getAllByRole("row")).toHaveLength(4);   // başlık + 3
  });

  it("tarih aralığı eski kayıtları eler", async () => {
    mock([row({ id: "new" }), row({ id: "old", started_at: "2020-01-01T10:00:00" })]);
    renderAt("/overview");
    await screen.findByTestId("kpis");
    expect(screen.getByTestId("kpis")).toHaveTextContent("2arama");
    fireEvent.click(screen.getByRole("button", { name: "7 gün" }));
    expect(screen.getByTestId("kpis")).toHaveTextContent("1arama");
  });

  it("yardımcılar: medyan ve mm:ss", () => {
    expect(median([])).toBeNull();
    expect(median([3, 1, 2])).toBe(2);
    expect(median([1, 2, 3, 4])).toBe(2.5);
    expect(mmss(null)).toBe("—");
    expect(mmss(142)).toBe("02:22");
  });
});

describe("Ayarlar", () => {
  it("etkin profili, eksik anahtarı ve doğrulanmamış süzgeci dürüstçe gösterir", async () => {
    mock([]);
    renderAt("/settings");
    expect(await screen.findByText("Eksik: DEEPGRAM_API_KEY")).toBeInTheDocument();
    expect(screen.getByText("ollama · gemma")).toBeInTheDocument();
    expect(screen.getByText("Deneysel · doğrulanmadı")).toBeInTheDocument();
  });
});

describe("Kabuk (ui-001)", () => {
  it("tema düğmesi temayı değiştirir ve tercihi saklar", async () => {
    mock([]);
    renderAt("/overview");
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    fireEvent.click(screen.getByRole("button", { name: "Açık tema" }));
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
    expect(localStorage.getItem("sva.theme")).toBe("light");
    expect(screen.getByRole("button", { name: "Koyu tema" })).toBeInTheDocument();
  });

  it("çekmece menü düğmeyle açılır ve ekran değişince kapanır", async () => {
    mock([]);
    const { container } = renderAt("/overview");
    const layout = container.querySelector(".layout")!;
    fireEvent.click(screen.getByRole("button", { name: "Menü" }));
    expect(layout.className).toContain("drawer-open");
    fireEvent.click(within(screen.getByRole("navigation", { name: "Lab ekranları" })).getByRole("link", { name: "Ayarlar" }));
    expect(layout.className).not.toContain("drawer-open");
  });

  it("Yeni Arama düğmesi Playground'a gider", () => {
    mock([]);
    renderAt("/overview");
    expect(screen.getByRole("link", { name: /Yeni Arama/ })).toHaveAttribute("href", "/playground");
  });
});
