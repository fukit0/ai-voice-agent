import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { FreeReplySettings } from "./FreeReplySettings";

const M = "qwen3:30b-a3b-instruct-2507-q4_K_M";
const TM = "qwen3:30b-a3b-thinking-2507-q4_K_M";
const group = (o: Record<string, unknown> = {}) => ({
  turns: 0, called: 0, qwen_rate: null, fallback_rate: null, fallback_reasons: {}, mean_s: null, p50_s: null, p95_s: null, models: [], ...o,
});
const defaults = { enabled: true, model: M, timeout_s: 1.5, thinking: false, thinking_model: TM, thinking_timeout_s: 8 };
const base = {
  ...defaults, defaults, overridden: [] as string[], categories: ["counter", "clarify"], timeout_range: [0.3, 5], thinking_timeout_range: [1, 30],
  thinking_max_tokens: 768, prompt: { version: "2", hash: "abc" }, status: { reachable: true, warm: true, model: M },
  stats: { last: 200, turns: 5, off: group({ turns: 3, called: 3, mean_s: 0.9, p50_s: 0.8, p95_s: 1.4, fallback_rate: 0.333, fallback_reasons: { audit: 1 } }),
           on: group({ turns: 2, called: 2, mean_s: 5.1, p50_s: 4.6, p95_s: 6.2, fallback_rate: 0, qwen_rate: 1 }) },
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
    state = { ...next, overridden, thinking_status: next.thinking ? { reachable: true, warm: false, model: next.thinking_model } : undefined };
    return ok(state);
  }));
});
afterEach(() => vi.unstubAllGlobals());

it("thinking ayrı açılır, serbest cevap ayarını değiştirmez; uyarı ve soğuk thinking modeli görünür", async () => {
  render(<FreeReplySettings />);
  const box = (await screen.findByLabelText("Qwen thinking")) as HTMLInputElement;
  expect(box.checked).toBe(false);
  expect(screen.queryByText(/canlı demoda kapalı tutun/)).toBeNull();
  fireEvent.click(box);
  await waitFor(() => expect(puts).toEqual([{ thinking: true }]));
  await screen.findByText(/canlı demoda kapalı tutun/);
  expect(screen.getByText(/Thinking modeli soğuk → havuz/)).toBeInTheDocument();
  expect((screen.getByLabelText("Serbest cevap") as HTMLInputElement).checked).toBe(true);
  // Serbest cevabın kendi "Varsayılana dön"ü thinking için çıkmaz; thinking'in ayrı dönüşü var
  expect(screen.queryByRole("button", { name: "Varsayılana dön" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Thinking varsayılana dön" }));
  await waitFor(() => expect(puts[1]).toEqual({ thinking: null, thinking_model: null, thinking_timeout_s: null }));
});

it("thinking modeli ve zaman aşımı kaydedilir; aralık dışı değerde kaydet kapalı", async () => {
  render(<FreeReplySettings />);
  const t = await screen.findByLabelText("Thinking zaman aşımı");
  const saves = () => screen.getAllByRole("button", { name: "Kaydet" });   // 0 model, 1 zaman aşımı, 2 thinking modeli, 3 thinking zaman aşımı
  fireEvent.change(t, { target: { value: "40" } });
  expect(saves()[3]).toBeDisabled();
  fireEvent.change(t, { target: { value: "12,5" } });
  fireEvent.click(saves()[3]);
  await waitFor(() => expect(puts[0]).toEqual({ thinking_timeout_s: 12.5 }));
  fireEvent.change(screen.getByLabelText("Thinking modeli"), { target: { value: "qwen3:8b" } });
  fireEvent.click(saves()[2]);
  await waitFor(() => expect(puts[1]).toEqual({ thinking_model: "qwen3:8b" }));
});

it("açık/kapalı kıyas özeti gösterilir", async () => {
  render(<FreeReplySettings />);
  const table = await screen.findByRole("table", { name: "Thinking kıyası" });
  const rows = within(table).getAllByRole("row");
  expect(rows[1]).toHaveTextContent("Kapalı");
  expect(rows[1]).toHaveTextContent("0.80 sn");
  expect(rows[1]).toHaveTextContent("audit 1");
  expect(rows[2]).toHaveTextContent("Açık");
  expect(rows[2]).toHaveTextContent("6.20 sn");
});

it("eski backend (thinking alanı yok) için satır gösterilmez", async () => {
  const { thinking: _t, thinking_model: _m, thinking_timeout_s: _s, stats: _st, ...old } = base;
  state = old;
  render(<FreeReplySettings />);
  await screen.findByLabelText("Serbest cevap");
  expect(screen.queryByLabelText("Qwen thinking")).toBeNull();
});
