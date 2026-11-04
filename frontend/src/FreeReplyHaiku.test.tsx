import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { FreeReplySettings } from "./FreeReplySettings";

// Serbest cevap arka ucu (docs/serbest-cevap-haiku.md): Arka uç seçimi, Haiku modeli/zaman aşımı, anahtar durumu, Haiku kıyas satırı.
const M = "qwen3:30b-a3b-instruct-2507-q4_K_M";
const group = (o: Record<string, unknown> = {}) => ({
  turns: 0, called: 0, qwen_rate: null, fallback_rate: null, fallback_reasons: {}, mean_s: null, p50_s: null, p95_s: null, models: [], ...o,
});
const defaults = { enabled: true, model: M, timeout_s: 1.5, thinking: false, thinking_model: "t", thinking_timeout_s: 8,
  backend: "auto", haiku_model: null, haiku_timeout_s: 3.0 };   // 2026-11-03: Haiku ölçümüne göre 2,0 -> 2,5 -> 3,0 sn (geniş kapsam max 3,54 sn)
const base = {
  ...defaults, defaults, overridden: [] as string[], categories: ["counter", "clarify"], timeout_range: [0.3, 5], thinking_timeout_range: [1, 30],
  thinking_max_tokens: 768, prompt: { version: "3", hash: "abc" }, status: { reachable: false, warm: false, model: M },
  backends: ["auto", "haiku", "qwen"], haiku_default_model: "claude-haiku-5-5", haiku_timeout_range: [0.3, 5], haiku_max_tokens: 120,
  haiku_status: { key_present: false, model: "claude-haiku-5-5", model_from_profile: true },
  stats: { last: 200, turns: 4, off: group({ turns: 1 }), on: group(),
           haiku: group({ turns: 3, called: 3, mean_s: 1.1, p50_s: 1.0, p95_s: 1.9, fallback_rate: 0.333, fallback_reasons: { timeout: 1 }, cost_usd_total: 0.00021 }) },
};
let state: Record<string, unknown> = { ...base };
let puts: Record<string, unknown>[] = [];
beforeEach(() => {
  state = { ...base };
  puts = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const ok = (b: unknown) => ({ ok: true, status: 200, json: async () => b });
    if (url !== "/api/free-reply") throw new Error(`beklenmeyen istek ${url}`);
    if (!init || init.method !== "PUT") return ok(state);
    const patch = JSON.parse(String(init.body)) as Record<string, unknown>;
    puts.push(patch);
    const next = { ...state, ...Object.fromEntries(Object.entries(patch).map(([k, v]) => [k, v ?? (defaults as Record<string, unknown>)[k]])) };
    const overridden = Object.keys(defaults).filter((k) => next[k] !== (defaults as Record<string, unknown>)[k]);
    state = { ...next, overridden };
    return ok(state);
  }));
});
afterEach(() => vi.unstubAllGlobals());

it("arka uç seçimi kaydedilir; anahtar yoksa havuz uyarısı görünür; ayrı varsayılana dönüş", async () => {
  render(<FreeReplySettings />);
  const sel = (await screen.findByLabelText("Serbest cevap arka ucu")) as HTMLSelectElement;
  expect(sel.value).toBe("auto");
  expect(screen.getByText(/ANTHROPIC_API_KEY yok → havuz/)).toBeInTheDocument();
  expect(screen.getByText(/profilindeki LLM Anthropic ise/)).toBeInTheDocument();
  fireEvent.change(sel, { target: { value: "haiku" } });
  await waitFor(() => expect(puts).toEqual([{ backend: "haiku" }]));
  // Qwen'in "Varsayılana dön"ü arka uç alanları için çıkmaz; arka ucun kendi dönüşü var
  expect(screen.queryByRole("button", { name: "Varsayılana dön" })).toBeNull();
  fireEvent.click(await screen.findByRole("button", { name: "Arka ucu varsayılana dön" }));
  await waitFor(() => expect(puts[1]).toEqual({ backend: null, haiku_model: null, haiku_timeout_s: null }));
});

it("Haiku zaman aşımı aralıkta kaydedilir; model boş bırakılırsa profilden (null) gönderilir", async () => {
  render(<FreeReplySettings />);
  const t = await screen.findByLabelText("Haiku zaman aşımı");
  expect((t as HTMLInputElement).value).toBe("3");
  expect(screen.getByText(/Varsayılan 3,0 sn ölçüme dayanır/)).toBeInTheDocument();
  const saveOf = (label: string) => within(screen.getByLabelText(label).closest("dd") as HTMLElement).getByRole("button", { name: "Kaydet" });
  fireEvent.change(t, { target: { value: "9" } });
  expect(saveOf("Haiku zaman aşımı")).toBeDisabled();
  fireEvent.change(t, { target: { value: "3,0" } });
  expect(saveOf("Haiku zaman aşımı")).toBeDisabled();      // varsayılanla aynı değer: değişiklik yok
  fireEvent.change(t, { target: { value: "3,2" } });
  fireEvent.click(saveOf("Haiku zaman aşımı"));
  await waitFor(() => expect(puts[0]).toEqual({ haiku_timeout_s: 3.2 }));
  const m = screen.getByLabelText("Haiku modeli");
  expect(saveOf("Haiku modeli")).toBeDisabled();            // boş = profilden; değişiklik yok
  fireEvent.change(m, { target: { value: "claude-haiku-x" } });
  fireEvent.click(saveOf("Haiku modeli"));
  await waitFor(() => expect(puts[1]).toEqual({ haiku_model: "claude-haiku-x" }));
  fireEvent.change(screen.getByLabelText("Haiku modeli"), { target: { value: "" } });
  fireEvent.click(saveOf("Haiku modeli"));
  await waitFor(() => expect(puts[2]).toEqual({ haiku_model: null }));
});

it("kıyas tablosunda Haiku satırı ve tahmini maliyet görünür", async () => {
  render(<FreeReplySettings />);
  const table = await screen.findByRole("table", { name: "Thinking kıyası" });
  const rows = within(table).getAllByRole("row");
  expect(rows).toHaveLength(4);
  expect(rows[3]).toHaveTextContent("Haiku");
  expect(rows[3]).toHaveTextContent("1.00 sn");
  expect(rows[3]).toHaveTextContent("timeout 1");
  expect(screen.getByText(/Haiku tahmini maliyet 0\.0002 USD/)).toBeInTheDocument();
});

it("eski backend (arka uç alanı yok): arka uç satırları gösterilmez", async () => {
  const { backend: _b, backends: _bs, haiku_status: _h, ...old } = base;
  state = old;
  render(<FreeReplySettings />);
  await screen.findByLabelText("Serbest cevap");
  expect(screen.queryByLabelText("Serbest cevap arka ucu")).toBeNull();
  expect(screen.queryByLabelText("Haiku zaman aşımı")).toBeNull();
});
