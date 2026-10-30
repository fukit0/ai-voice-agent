import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App, ROUTER_FUTURE } from "../App";

// lab-005: Kıyas matrisi ekranı — yeni koşu sonrası güncellenir, ağırlık değişince yeniden hesaplanır, eksik veri uydurulmaz.

const CRIT = [
  { id: "latency", label: "Gecikme", source: "s", rule: "r" }, { id: "naturalness", label: "Doğallık (kör dinleme)", source: "s", rule: "r" },
  { id: "accuracy", label: "Cevap doğruluğu", source: "s", rule: "r" }, { id: "wer", label: "STT hatası (WER)", source: "s", rule: "r" },
  { id: "resources", label: "Kaynak kullanımı", source: "s", rule: "r" },
];
const DEFAULTS = { latency: 30, naturalness: 25, accuracy: 25, wer: 10, resources: 10 };
const metric = (value: number, unit: string, score: number, n = 5) => ({ value, unit, score, n, note: null });
const none = { latency: null, naturalness: null, accuracy: null, wer: null, resources: null };

function body(weights: Record<string, number>, rows: unknown[]) {
  const sum = Object.values(weights).reduce((a, b) => a + b, 0);
  return { criteria: CRIT.map((c) => ({ ...c, weight: weights[c.id], weight_pct: weights[c.id] / sum * 100 })), weights, defaults: DEFAULTS,
    min_coverage: 0.5, rows, generated_at: "2026-10-30T12:00:00+00:00", notes: ["Kaynak kullanımı ölçülmüyor (eval-003 başlamadı)."] };
}
const ROW = (over: Record<string, unknown>) => ({ profile: "L1", name: "Hızlı", mode: "cascade", components: [{ kind: "TTS", provider: "ema", model: "ema-l" }],
  metrics: none, total: null, coverage: 0, missing: [], eliminated: false, license: [], license_unknown: [], rank: null, ...over });

function mock(handler: (weights: string | null) => unknown) {
  const fetchMock = vi.fn(async (url: string) => {
    if (url.startsWith("/api/health")) return new Response(JSON.stringify({ status: "ok", version: "0.1.0" }));
    if (url.startsWith("/api/profiles")) return new Response("[]");
    if (url.startsWith("/api/matrix")) return new Response(JSON.stringify(handler(new URL(url, "http://x").searchParams.get("weights"))));
    return new Response("", { status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}
const open = () => render(<MemoryRouter initialEntries={["/matrix"]} future={ROUTER_FUTURE}><App /></MemoryRouter>);

beforeEach(() => { try { localStorage.clear(); } catch { /* yok */ } });
afterEach(() => vi.unstubAllGlobals());

describe("Kıyas matrisi", () => {
  it("ölçüm yoksa boş durumu gösterir, puan uydurmaz", async () => {
    mock(() => body(DEFAULTS, [ROW({})]));
    open();
    expect(await screen.findByTestId("matrix-empty")).toHaveTextContent("Henüz ölçüm yok");
    expect(within(screen.getByTestId("row-L1")).getAllByText("ölçülmedi")).toHaveLength(5);
    expect(screen.getByTestId("row-L1")).toHaveTextContent("yetersiz veri");
  });

  it("yeni koşu sonrası Yenile ekranı günceller", async () => {
    let calls = 0;
    mock(() => body(DEFAULTS, [ROW(++calls === 1 ? {} : {
      metrics: { ...none, latency: metric(1.5, "sn", 83.3) }, total: 83.3, coverage: 0.3, rank: 1 })]));
    open();
    await screen.findByTestId("row-L1");
    expect(screen.getByTestId("row-L1")).toHaveTextContent("yetersiz veri");
    fireEvent.click(screen.getByRole("button", { name: "Yenile" }));
    await waitFor(() => expect(screen.getByTestId("row-L1")).toHaveTextContent("1,50 sn"));
    expect(screen.getByTestId("row-L1")).toHaveTextContent("83,3");
  });

  it("ağırlık değişince yeni ağırlıkla istek atar, ekran yeni puanları gösterir ve ağırlığı saklar", async () => {
    const seen: (string | null)[] = [];
    mock((w) => {
      seen.push(w);
      const lat = w?.includes("latency:100");
      return body(lat ? { latency: 100, naturalness: 0, accuracy: 0, wer: 0, resources: 0 } : DEFAULTS,
        [ROW({ metrics: { ...none, latency: metric(1.2, "sn", 100), accuracy: metric(0.4, "oran", 40) }, total: lat ? 100 : 70, coverage: 1, rank: 1 })]);
    });
    open();
    await screen.findByTestId("row-L1");
    expect(screen.getByTestId("row-L1")).toHaveTextContent("70,0");
    fireEvent.change(screen.getByLabelText("Gecikme ağırlığı"), { target: { value: "100" } });
    for (const k of ["Doğallık (kör dinleme)", "Cevap doğruluğu", "STT hatası (WER)", "Kaynak kullanımı"])
      fireEvent.change(screen.getByLabelText(`${k} ağırlığı`), { target: { value: "0" } });
    await waitFor(() => expect(seen[seen.length - 1]).toBe("latency:100,naturalness:0,accuracy:0,wer:0,resources:0"), { timeout: 2000 });
    await waitFor(() => expect(screen.getByTestId("row-L1")).toHaveTextContent("100,0"));
    expect(JSON.parse(localStorage.getItem("sva.matrix.weights")!)).toMatchObject({ latency: 100, accuracy: 0 });
  });

  it("elenen ve lisansı belirsiz profilleri işaretler; sıralı satırlar önce gelir", async () => {
    mock(() => body(DEFAULTS, [
      ROW({ profile: "A", eliminated: true, license: [{ kind: "TTS", model: "x:y", license: "L", commercial_ok: false, verified: true }] }),
      ROW({ profile: "B", license_unknown: ["ema:"], total: 50, coverage: 1, rank: 2, metrics: { ...none, latency: metric(2, "sn", 50) } }),
      ROW({ profile: "C", total: 90, coverage: 1, rank: 1, metrics: { ...none, latency: metric(1.2, "sn", 100) } }),
    ]));
    open();
    await screen.findByTestId("row-A");
    const ids = within(screen.getByTestId("matrix-table")).getAllByRole("row").slice(1).map((r) => r.getAttribute("data-testid"));
    expect(ids).toEqual(["row-C", "row-B", "row-A"]);
    expect(screen.getByTestId("row-A")).toHaveTextContent("Elendi");
    expect(screen.getByTestId("row-B")).toHaveTextContent("Lisans belirsiz");
  });

  it("hata durumunda mesaj gösterir", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => url.startsWith("/api/matrix")
      ? new Response(JSON.stringify({ detail: { message: "Bilinmeyen kriter: x" } }), { status: 422 }) : new Response("[]")));
    open();
    expect(await screen.findByRole("alert")).toHaveTextContent("Bilinmeyen kriter: x");
  });
});
