import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { FreeReplySettings } from "./FreeReplySettings";

const base = {
  enabled: true, model: "qwen3:30b-a3b-instruct-2507-q4_K_M", timeout_s: 1.5,
  defaults: { enabled: true, model: "qwen3:30b-a3b-instruct-2507-q4_K_M", timeout_s: 1.5 },
  overridden: [] as string[], categories: ["counter", "clarify"], timeout_range: [0.3, 5], prompt: { version: "1", hash: "abc" },
  status: { reachable: true, warm: false, model: "qwen3:30b-a3b-instruct-2507-q4_K_M" },
};
let state = { ...base };
let puts: unknown[] = [];
beforeEach(() => {
  state = { ...base };
  puts = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const ok = (b: unknown) => ({ ok: true, status: 200, json: async () => b });
    if (url === "/api/free-reply" && (!init || init.method !== "PUT")) return ok(state);
    if (url === "/api/free-reply") {
      const patch = JSON.parse(String(init?.body));
      puts.push(patch);
      state = { ...state, ...Object.fromEntries(Object.entries(patch).map(([k, v]) => [k, v ?? (base.defaults as Record<string, unknown>)[k]])),
                overridden: Object.entries(patch).filter(([, v]) => v !== null).map(([k]) => k) };
      return ok(state);
    }
    throw new Error(`beklenmeyen istek ${url}`);
  }));
});
afterEach(() => vi.unstubAllGlobals());

it("açık/kapalı, zaman aşımı kaydedilir ve varsayılana dönülür; soğuk durum görünür", async () => {
  render(<FreeReplySettings />);
  const box = (await screen.findByLabelText("Serbest cevap")) as HTMLInputElement;
  expect(box.checked).toBe(true);
  expect(screen.getByText(/Soğuk → havuz/)).toBeInTheDocument();
  fireEvent.click(box);
  await waitFor(() => expect(puts).toEqual([{ enabled: false }]));
  await waitFor(() => expect((screen.getByLabelText("Serbest cevap") as HTMLInputElement).checked).toBe(false));
  fireEvent.change(screen.getByLabelText("Serbest cevap zaman aşımı"), { target: { value: "0,8" } });
  const saves = screen.getAllByRole("button", { name: "Kaydet" });
  fireEvent.click(saves[1]);
  await waitFor(() => expect(puts[1]).toEqual({ timeout_s: 0.8 }));
  fireEvent.click(await screen.findByRole("button", { name: "Varsayılana dön" }));
  await waitFor(() => expect(puts[2]).toEqual({ enabled: null, model: null, timeout_s: null }));
});

it("aralık dışı zaman aşımında kaydet kapalı; Ollama yoksa havuz uyarısı", async () => {
  state = { ...base, status: { reachable: false, warm: false, model: base.model } };
  render(<FreeReplySettings />);
  await screen.findByText(/Ollama'ya ulaşılamıyor/);
  fireEvent.change(screen.getByLabelText("Serbest cevap zaman aşımı"), { target: { value: "30" } });
  expect(screen.getAllByRole("button", { name: "Kaydet" })[1]).toBeDisabled();
});
