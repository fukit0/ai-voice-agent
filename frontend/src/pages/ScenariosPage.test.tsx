import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ScenarioDoc, ScenarioStep } from "../api";
import { ScenariosPage } from "./ScenariosPage";

const step = (o: Partial<ScenarioStep>): ScenarioStep => ({
  key: "x", title: "X", code: null, group: "Giriş", kind: "YesNo", condition: null, dtmf: true, min: 1, max: 10,
  longAnswer: false, outcome: null, applicable: true, choices: [], defaultText: "Müsait misiniz?", text: "Müsait misiniz?",
  edited: false, placeholders: [], branches: [], spoken: "Müsait misiniz?", chars: 15, ...o,
});
const DOC: ScenarioDoc = {
  key: "anket", label: "Çağrı Merkezi Memnuniyet Anketi", description: "", problems: [],
  outcomes: [{ key: "tamamlandi", label: "Anket tamamlandı", tone: "success", description: "" }],
  placeholders: { HITAP: "Hitap", Q2: "Q2 puanı" }, sample_values: {},
  steps: [
    step({ key: "musaitlik", title: "Müsaitlik", branches: [
      { on: "Evet", to: "q3", to_title: "Son 3 ayda ankete katılım" }, { on: "Hayır", to: "randevu", to_title: "Randevu" }] }),
    step({ key: "q3", title: "Son 3 ayda ankete katılım", code: "Q3", group: "Eleme", defaultText: "Katıldınız mı?", text: "Katıldınız mı?", spoken: "Katıldınız mı?" }),
    step({ key: "kapanis", title: "Kapanış", group: "Kapanış", kind: "Terminal", dtmf: false, outcome: "tamamlandi", spoken: "İyi günler." }),
  ],
};

const calls: { url: string; init?: RequestInit }[] = [];
let saved = false;
beforeEach(() => {
  calls.length = 0;
  saved = false;
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    if (url === "/api/scenarios") return new Response(JSON.stringify([{ key: "anket", label: DOC.label, shortLabel: "Anket", description: "", steps: 3, outcomes: [], problems: [] }]));
    if (url === "/api/scenarios/anket") return new Response(JSON.stringify(saved ? { ...DOC, steps: DOC.steps.map((x, i) => i ? x : { ...x, text: "Merhaba {HITAP}", edited: true }) } : DOC));
    if (url.endsWith("/preview")) return new Response(JSON.stringify({ spoken: "Merhaba Ahmet Bey", chars: 10, unknown_placeholders: [] }));
    if (url.endsWith("/text") && init?.method === "PUT") { saved = true; return new Response(JSON.stringify(step({ key: "musaitlik" }))); }
    return new Response("{}", { status: 404 });
  }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("Senaryolar (lab-003)", () => {
  it("adımları gruplar, ilk adımı ve cevaba göre akışı gösterir; akıştaki bağlantı adıma geçer", async () => {
    render(<ScenariosPage />);
    const nav = await screen.findByRole("navigation", { name: "Adımlar" });
    expect(within(nav).getByText("Eleme")).toBeInTheDocument();
    expect(within(nav).getByRole("button", { name: /Müsaitlik/ })).toHaveAttribute("aria-current", "true");
    const flow = screen.getByTestId("scenario-flow");
    expect(flow).toHaveTextContent("Evet");
    fireEvent.click(within(flow).getByRole("button", { name: "Son 3 ayda ankete katılım" }));
    expect(await screen.findByRole("heading", { level: 3, name: "Son 3 ayda ankete katılım" })).toBeInTheDocument();
    expect(screen.getByRole("textbox")).toHaveValue("Katıldınız mı?");
  });

  it("terminal adım sonucu gösterir", async () => {
    render(<ScenariosPage />);
    fireEvent.click(await screen.findByRole("button", { name: /Kapanış/ }));
    expect(await screen.findByText(/Anket tamamlandı/)).toBeInTheDocument();
  });

  it("yer tutucu eklenir, önizleme güncellenir, Kaydet PUT eder", async () => {
    render(<ScenariosPage />);
    const box = await screen.findByRole("textbox");
    const save = screen.getByRole("button", { name: "Kaydet" });
    expect(save).toBeDisabled();
    fireEvent.change(box, { target: { value: "Merhaba " } });
    fireEvent.click(screen.getByRole("button", { name: "{HITAP}" }));
    expect((box as HTMLTextAreaElement).value).toContain("{HITAP}");
    await waitFor(() => expect(screen.getByTestId("scenario-spoken")).toHaveTextContent("Merhaba Ahmet Bey"));
    fireEvent.click(save);
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/steps/musaitlik/text") && c.init?.method === "PUT")).toBe(true));
    expect(await screen.findByText(/Kaydedildi/)).toBeInTheDocument();
    expect(screen.getByRole("textbox")).toHaveValue("Merhaba {HITAP}"); // kayıt sonrası sunucudaki metin yüklendi, mesaj kaldı
  });

  it("kaydetme hatasını gösterir", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockImplementation(async (url: string, init?: RequestInit) => {
      if (url === "/api/scenarios") return new Response(JSON.stringify([{ key: "anket", label: "", shortLabel: "Anket", description: "", steps: 3, outcomes: [], problems: [] }]));
      if (url === "/api/scenarios/anket") return new Response(JSON.stringify(DOC));
      if (init?.method === "PUT") return new Response(JSON.stringify({ detail: { message: "Bilinmeyen yer tutucu: {OLMAYAN}" } }), { status: 400 });
      return new Response(JSON.stringify({ spoken: "x", chars: 1, unknown_placeholders: [] }));
    });
    render(<ScenariosPage />);
    fireEvent.change(await screen.findByRole("textbox"), { target: { value: "Merhaba {OLMAYAN}" } });
    fireEvent.click(screen.getByRole("button", { name: "Kaydet" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Bilinmeyen yer tutucu");
  });
});
