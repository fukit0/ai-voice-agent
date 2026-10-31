import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { FastPathSettings } from "./FastPathSettings";
import { ProfileProvider } from "./ProfileContext";

const comp = (provider: string, model: string) => ({ provider, model, warm: true });
const prof = (id: string, mode: string, fp: boolean, def: boolean | null) => ({
  id, name: id, purpose: "", mode, notes: "", realtime: null, missing_env: [], issues: [], ready: true, warm: true, warmup: null,
  fast_path: fp, fast_path_default: def,
  components: { stt: comp("x", "m"), llm: comp("y", "m"), tts: comp("z", "m") },
});
let puts: unknown[] = [];
let on = false;
beforeEach(() => {
  puts = []; on = false;
  localStorage.setItem("sva.profile", "L2-EL");
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const ok = (b: unknown) => ({ ok: true, status: 200, json: async () => b });
    if (url === "/api/profiles") return ok([prof("L2-EL", "cascade", on, on ? false : null), prof("A2", "realtime", false, null)]);
    if (url.endsWith("/fast-path")) { puts.push([url, JSON.parse(String(init?.body))]); on = !!JSON.parse(String(init?.body)).enabled; return ok({}); }
    throw new Error(`beklenmeyen istek ${url}`);
  }));
});
afterEach(() => vi.unstubAllGlobals());
const open = () => render(<MemoryRouter><ProfileProvider><FastPathSettings /></ProfileProvider></MemoryRouter>);

it("hızlı yol açılır, kaydedilir, varsayılana dönülür ve kıyas ekranına yönlendirir", async () => {
  open();
  const box = (await screen.findByLabelText("Hızlı yol")) as HTMLInputElement;
  expect(box.checked).toBe(false);
  fireEvent.click(box);
  await waitFor(() => expect(puts).toEqual([["/api/profiles/L2-EL/fast-path", { enabled: true }]]));
  await waitFor(() => expect((screen.getByLabelText("Hızlı yol") as HTMLInputElement).checked).toBe(true));
  expect(screen.getByRole("link", { name: /Profil \+ hızlı yol/ })).toHaveAttribute("href", "/calls");
  fireEvent.click(await screen.findByRole("button", { name: "Varsayılana dön" }));
  await waitFor(() => expect(puts[1]).toEqual(["/api/profiles/L2-EL/fast-path", { enabled: null }]));
});

it("realtime profilde uygulanmadığını söyler", async () => {
  localStorage.setItem("sva.profile", "A2");
  open();
  await screen.findByText(/hızlı yol uygulanmaz/);
  expect(screen.queryByLabelText("Hızlı yol")).toBeNull();
});
