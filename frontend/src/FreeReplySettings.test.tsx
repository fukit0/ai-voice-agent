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

// off-004: düzenlenebilir sistem istemi
const DEF = "Sen {ASISTAN} adında bir asistansın.";
const promptState = {
  ...base, system_prompt: null as string | null, default_system_prompt: DEF, frame: "Sabit kurallar (değiştirilemez): veri.",
  effective_system_prompt: "Sen Ayşe adında bir asistansın.\nSabit kurallar (değiştirilemez): veri.\nBilinen gerçekler: kayıt",
  system_prompt_max: 40, fallback_text: "Kusura bakmayın.", fallback_text_max: 200, use_pool_fallback_only: true,
  wide_scope_backends: ["haiku"], never_llm: ["identity", "hold", "support"], prompt: { version: "6", hash: "def", custom: false },
};

it("sistem istemi: varsayılan görünür, sayaç, kaydet / geri al / varsayılana sıfırla", async () => {
  state = { ...promptState } as typeof state;
  render(<FreeReplySettings />);
  const area = (await screen.findByLabelText("Sistem istemi")) as HTMLTextAreaElement;
  expect(area.value).toBe(DEF);
  expect(screen.getByText("Varsayılan")).toBeInTheDocument();
  expect(screen.getByText(/kapatılamaz/)).toBeInTheDocument();
  expect(screen.getByText(/ÇALIŞMAZ: cevap, ret, DNC, geri arama, hızlı yol/)).toBeInTheDocument();
  const row = area.closest("dd") as HTMLElement;
  const btn = (name: string) => Array.from(row.querySelectorAll("button")).find((b) => b.textContent === name) as HTMLButtonElement;
  expect(btn("Kaydet")).toBeDisabled();
  expect(btn("Varsayılana sıfırla")).toBeDisabled();
  fireEvent.change(area, { target: { value: "Kısa konuş." } });
  expect(screen.getByLabelText("Karakter sayısı").textContent).toBe("11 / 40");
  fireEvent.click(btn("Geri al"));
  expect(area.value).toBe(DEF);
  fireEvent.change(area, { target: { value: "x".repeat(41) } });
  expect(btn("Kaydet")).toBeDisabled();
  fireEvent.change(area, { target: { value: "Kısa konuş." } });
  fireEvent.click(btn("Kaydet"));
  await waitFor(() => expect(puts).toEqual([{ system_prompt: "Kısa konuş." }]));
  state = { ...state, system_prompt: "Kısa konuş.", prompt: { version: "6", hash: "cus", custom: true } } as typeof state;
});

it("özel istemde rozet ve sıfırlama; etkin istem önizlemesi; yedek cümle ve geniş kapsam kaydı", async () => {
  state = { ...promptState, system_prompt: "Kısa konuş.", prompt: { version: "6", hash: "cus", custom: true } } as typeof state;
  render(<FreeReplySettings />);
  const area = (await screen.findByLabelText("Sistem istemi")) as HTMLTextAreaElement;
  expect(area.value).toBe("Kısa konuş.");
  expect(screen.getByText("Özel istem")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Etkin istemi göster" }));
  expect(screen.getByLabelText("Etkin istem").textContent).toContain("Bilinen gerçekler");
  fireEvent.click(screen.getByRole("button", { name: "Varsayılana sıfırla" }));
  await waitFor(() => expect(puts[0]).toEqual({ system_prompt: null }));
  fireEvent.change(screen.getByLabelText("LLM yedek cümlesi"), { target: { value: "Not aldım." } });
  const fb = screen.getByLabelText("LLM yedek cümlesi").closest("dd") as HTMLElement;
  fireEvent.click(fb.querySelector("button") as HTMLButtonElement);
  await waitFor(() => expect(puts[1]).toEqual({ fallback_text: "Not aldım." }));
  fireEvent.click(screen.getByLabelText("Geniş kapsam"));
  await waitFor(() => expect(puts[2]).toEqual({ use_pool_fallback_only: false }));
});

it("eski backend istem alanlarını vermezse bölüm gösterilmez", async () => {
  render(<FreeReplySettings />);
  await screen.findByLabelText("Serbest cevap");
  expect(screen.queryByLabelText("Sistem istemi")).toBeNull();
});
