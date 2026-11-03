import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ReactionSettings } from "./ReactionSettings";

const base = {
  enabled: true, default: true, overridden: false, reaction_rate: 0.8,
  pool_sizes: { score_high: 4, yes: 4 }, acknowledgements: ["Anladım.", "Teşekkür ederim."],
};
let state = { ...base };
let puts: unknown[] = [];
beforeEach(() => {
  state = { ...base };
  puts = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const ok = (b: unknown) => ({ ok: true, status: 200, json: async () => b });
    if (url !== "/api/reactions") throw new Error(`beklenmeyen istek ${url}`);
    if (init?.method === "PUT") {
      const { enabled } = JSON.parse(String(init.body));
      puts.push({ enabled });
      state = { ...state, enabled: enabled ?? base.default, overridden: enabled !== null && enabled !== base.default };
    }
    return ok(state);
  }));
});
afterEach(() => vi.unstubAllGlobals());

it("varsayılan açık; kapatınca PUT gider, eski onay sözleri ve havuzun saklandığı görünür; varsayılana dönülür", async () => {
  render(<ReactionSettings />);
  const box = (await screen.findByLabelText("Cevaba bağlı tepkiler")) as HTMLInputElement;
  expect(box.checked).toBe(true);
  expect(screen.getByText("Açık")).toBeInTheDocument();
  expect(screen.getByText(/Anladım\. · Teşekkür ederim\./)).toBeInTheDocument();
  expect(screen.getByText(/Tepki havuzu \(8 cümle\)/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Varsayılana dön" })).not.toBeInTheDocument();
  fireEvent.click(box);
  await waitFor(() => expect(puts).toEqual([{ enabled: false }]));
  await waitFor(() => expect((screen.getByLabelText("Cevaba bağlı tepkiler") as HTMLInputElement).checked).toBe(false));
  expect(screen.getByText("Kapalı")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Varsayılana dön" }));
  await waitFor(() => expect(puts[1]).toEqual({ enabled: null }));
  await waitFor(() => expect((screen.getByLabelText("Cevaba bağlı tepkiler") as HTMLInputElement).checked).toBe(true));
});

it("yüklenemezse hata gösterir", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("ağ yok"); }));
  render(<ReactionSettings />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Yüklenemedi");
});
