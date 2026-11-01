import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PersonaPage } from "./PersonaPage";

const BASE = {
  name: "Elif", tone: "samimi", address: "bey_hanim", max_sentences: 2, max_words_per_sentence: 14, speed: 1,
  acknowledgements: ["Anladım.", "Not aldım."], avoid_phrases: ["Sayın müşterimiz"], extra_rules: "",
};
const STATS = { utterances: 3, sentences: 3, avg_words_per_sentence: 6, max_words: 12, over_limit: [], over_limit_rate: 0, avoid_hits: [] };
const view = (p = BASE) => ({
  persona: p, defaults: BASE, options: { tone: ["samimi", "resmi"], address: ["bey_hanim", "ad", "siz"] },
  prompt: `Sen ${p.name} adlı bir görevlisisin.`, greeting: `Merhaba, ben ${p.name}. Size kısa bir anket yapabilir miyim?`,
  preview_ack: p.acknowledgements, prompt_stats: STATS,
});

function mockApi() {
  let saved = BASE;
  const calls: { url: string; method: string; body?: any }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ url, method, body });
    if (url === "/api/persona/preview") return new Response(JSON.stringify(body.name ? { problems: [], ...view(body) } : { problems: ["Ad 1-30 karakter olmalı."] }));
    if (url === "/api/persona" && method === "PUT") { saved = body; return new Response(JSON.stringify(view(saved))); }
    if (url === "/api/persona/reset") { saved = BASE; return new Response(JSON.stringify(view(saved))); }
    if (url.startsWith("/api/persona/report")) return new Response(JSON.stringify({ persona: BASE, sessions: [], total: null }));
    if (url === "/api/persona") return new Response(JSON.stringify(view(saved)));
    return new Response("", { status: 404 });
  }));
  return calls;
}
afterEach(() => vi.unstubAllGlobals());

describe("Persona ekranı (core-005)", () => {
  it("neye etki ettiğini açıkça söyler: anket, yalnız serbest sohbet, realtime", async () => {
    mockApi();
    render(<PersonaPage />);
    const scope = await screen.findByTestId("persona-scope");
    expect(scope).toHaveTextContent("Anket aramalarında");
    expect(scope).toHaveTextContent("Yalnızca serbest sohbette");
    expect(scope).toHaveTextContent("Realtime profillerde");
    expect(await screen.findByText(/Anket aramalarında ve realtime profillerde kullanılmaz/)).toBeInTheDocument();
  });
  it("persona alanlarını gösterir, ad değişince açılış cümlesi ve istem güncellenir, kaydeder", async () => {
    const calls = mockApi();
    render(<PersonaPage />);
    const name = await screen.findByLabelText("Ajanın adı");
    expect(name).toHaveValue("Elif");
    expect(screen.getByTestId("persona-greeting")).toHaveTextContent("ben Elif");
    const save = screen.getByRole("button", { name: "Kaydet" });
    expect(save).toBeDisabled();                       // değişiklik yok
    fireEvent.change(name, { target: { value: "Zeynep" } });
    await waitFor(() => expect(screen.getByTestId("persona-greeting")).toHaveTextContent("ben Zeynep"));
    expect(screen.getByTestId("persona-prompt")).toHaveTextContent("Zeynep adlı");
    fireEvent.click(save);
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Kaydedildi"));
    expect(calls.find((c) => c.method === "PUT")!.body.name).toBe("Zeynep");
  });

  it("geçersiz girişte sorunu gösterir ve kaydı kapatır; varsayılana döner", async () => {
    mockApi();
    render(<PersonaPage />);
    const name = await screen.findByLabelText("Ajanın adı");
    fireEvent.change(name, { target: { value: "" } });
    expect(await screen.findByRole("alert")).toHaveTextContent("Ad 1-30 karakter");
    expect(screen.getByRole("button", { name: "Kaydet" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Varsayılana dön" }));
    await waitFor(() => expect(screen.getByLabelText("Ajanın adı")).toHaveValue("Elif"));
  });

  it("onay sözlerini satır satır alır ve rapor boşken bunu söyler", async () => {
    const calls = mockApi();
    render(<PersonaPage />);
    const acks = await screen.findByLabelText(/Doğal onay sözleri/);
    expect(acks).toHaveValue("Anladım.\nNot aldım.");
    fireEvent.click(screen.getByRole("button", { name: "Raporu getir" }));
    expect(await screen.findByTestId("persona-report-empty")).toBeInTheDocument();
    expect(calls.some((c) => c.url.startsWith("/api/persona/report"))).toBe(true);
  });
});

describe("Persona konuşma hızı", () => {
  it("hız kaydırıcısı değeri kaydeder", async () => {
    const calls = mockApi();
    render(<PersonaPage />);
    const speed = await screen.findByLabelText(/Konuşma hızı/);
    fireEvent.change(speed, { target: { value: "1.2" } });
    await waitFor(() => expect(screen.getByRole("button", { name: "Kaydet" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Kaydet" }));
    await waitFor(() => expect(calls.find((c) => c.method === "PUT")!.body.speed).toBe(1.2));
  });
});


describe("PersonaPage cevaba bağlı tepkiler (hum-001)", () => {
  afterEach(() => vi.unstubAllGlobals());
  it("kova metinleri satır satır kaydedilir, oran gönderilir", async () => {
    const calls = mockApi();
    render(<PersonaPage />);
    const box = await screen.findByLabelText(/Yüksek puan/);
    fireEvent.change(box, { target: { value: "Harika.\nSağ olun." } });
    fireEvent.change(screen.getByLabelText(/Tepki oranı/), { target: { value: "0.8" } });
    fireEvent.click(screen.getByRole("button", { name: /Kaydet/ }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    const put = calls.find((c) => c.method === "PUT")!;
    expect(put.body.reactions).toEqual({ score_high: ["Harika.", "Sağ olun."] });
    expect(put.body.reaction_rate).toBe(0.8);
  });
});
