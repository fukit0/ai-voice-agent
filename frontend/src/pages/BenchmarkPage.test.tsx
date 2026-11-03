import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App, ROUTER_FUTURE } from "../App";

// eval-001: Kıyas koşusu ekranı — test seti hazırlama, tek tıkla koşu, ilerleme, sonuçların Aramalar'a bağlanması.

const PROFILE = (over: Record<string, unknown> = {}) => ({
  id: "L1", name: "Hızlı", purpose: "", mode: "cascade", notes: "",
  components: { stt: { provider: "mlx_whisper", model: "t" }, llm: { provider: "ollama", model: "g" }, tts: { provider: "ema", model: "e" } },
  realtime: null, missing_env: [], issues: [], ready: true, warm: true, warmup: null, ...over,
});
const PERSONAS = ["ayse_sakin", "mehmet_hizli"].map((id, i) => ({
  id, name: i ? "Mehmet (aceleci)" : "Ayşe (sakin)", description: "d", gender: "female", age: "young", speed: 1, gain_db: 0, noise_snr_db: null,
  reaction_s: 0.4, voice_id: "v" + i, clips: 26, clips_needed: 26,
}));
const PATHS = [{ id: "ret", name: "Ankete katılmayı reddeder", description: "" }, { id: "geri_arama", name: "Müsait değil, geri arama ister", description: "" }];
const SET = (ready: boolean, build: Record<string, unknown> = {}) => ({
  personas: PERSONAS, paths: PATHS, texts: 26, calls: 20, ready, build: { state: "idle", done: 0, total: 0, error: null, ...build },
});
const CALLS = (status: string) => [
  { index: 0, persona: "ayse_sakin", path: "ret", phone_filter: false, status, session_id: "a1", outcome: "katilmak_istemedi", answers: 4, unanswered: 0, turns: 5, first_audio_p50_s: 1.31 },
  { index: 1, persona: "mehmet_hizli", path: "geri_arama", phone_filter: true, status: "pending" },
];
const RUN = (status: string, done: number) => ({ id: "20261030-120000-abcdef", profile: "L1", phone_filter: "both", created_at: "2026-10-30T12:00:00+00:00",
  finished_at: null, status, total: 2, done, error: null, calls: CALLS(done ? "ok" : "running") });

type Handler = (url: string, init?: RequestInit) => unknown;
function mock(handler: Handler, profile = PROFILE()) {
  const f = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.startsWith("/api/health")) return new Response(JSON.stringify({ status: "ok", version: "0.1.0" }));
    if (url.startsWith("/api/profiles")) return new Response(JSON.stringify([profile]));
    const out = handler(url, init);
    if (out instanceof Response) return out;
    return new Response(JSON.stringify(out ?? {}));
  });
  vi.stubGlobal("fetch", f);
  return f;
}
const open = () => render(<MemoryRouter initialEntries={["/benchmark"]} future={ROUTER_FUTURE}><App /></MemoryRouter>);
beforeEach(() => { try { localStorage.clear(); } catch { /* yok */ } });
afterEach(() => vi.unstubAllGlobals());

describe("Kıyas koşusu", () => {
  it("set hazır değilken koşuyu kapatır ve seti hazırlatır", async () => {
    const f = mock((url, init) => {
      if (url === "/api/evalrun/set/build") return { started: true };
      if (url === "/api/evalrun/set") return SET(false);
      if (url === "/api/evalrun/runs" && !init?.method) return [];
    });
    open();
    expect(await screen.findByText("Set hazır değil")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Test setini koştur" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Test setini hazırla" }));
    await waitFor(() => expect(f.mock.calls.some(([u, i]) => u === "/api/evalrun/set/build" && i?.method === "POST")).toBe(true));
    expect(within(screen.getByTestId("persona-table")).getAllByRole("row")).toHaveLength(3);
  });

  it("tek tıkla koşturur, ilerlemeyi gösterir ve sonuçları Aramalar'a bağlar", async () => {
    let polls = 0;
    const f = mock((url, init) => {
      if (url === "/api/evalrun/set") return SET(true);
      if (url === "/api/evalrun/runs" && init?.method === "POST") return new Response(JSON.stringify({ run_id: RUN("running", 0).id, total: 2 }), { status: 202 });
      if (url === "/api/evalrun/runs") return [];
      if (url.startsWith("/api/evalrun/runs/")) return ++polls < 3 ? RUN("running", 1) : RUN("done", 2);
    });
    open();
    const go = await screen.findByRole("button", { name: "Test setini koştur" });
    await waitFor(() => expect(go).toBeEnabled());
    fireEvent.click(go);
    await waitFor(() => expect(f.mock.calls.some(([u, i]) => u === "/api/evalrun/runs" && i?.method === "POST")).toBe(true));
    const post = f.mock.calls.find(([u, i]) => u === "/api/evalrun/runs" && i?.method === "POST")!;
    expect(JSON.parse(post[1]!.body as string)).toEqual({ profile: "L1", phone_filter: "both" });
    expect(await screen.findByTestId("run-table")).toBeInTheDocument();
    expect(screen.getByText("Katılmak istemedi")).toBeInTheDocument();
    expect(screen.getByText("1,31 sn")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId("run-progress")).toHaveTextContent("Bitti"), { timeout: 6000 });
    expect(screen.getByTestId("run-progress")).toHaveTextContent("2/2 arama");
    expect(screen.getByRole("link", { name: /Aramalar'da gör/ })).toHaveAttribute("href", "/calls");
  });

  it("telefon filtresi seçimi isteğe yansır", async () => {
    const f = mock((url, init) => {
      if (url === "/api/evalrun/set") return SET(true);
      if (url === "/api/evalrun/runs" && init?.method === "POST") return new Response(JSON.stringify({ run_id: RUN("running", 0).id, total: 20 }), { status: 202 });
      if (url === "/api/evalrun/runs") return [];
      if (url.startsWith("/api/evalrun/runs/")) return RUN("done", 2);
    });
    open();
    fireEvent.click(await screen.findByRole("radio", { name: /Telefon filtresi: Kapalı/ }));
    const go = screen.getByRole("button", { name: "Test setini koştur" });
    await waitFor(() => expect(go).toBeEnabled());
    fireEvent.click(go);
    await waitFor(() => expect(f.mock.calls.some(([u, i]) => u === "/api/evalrun/runs" && i?.method === "POST")).toBe(true));
    const post = f.mock.calls.find(([u, i]) => u === "/api/evalrun/runs" && i?.method === "POST")!;
    expect(JSON.parse(post[1]!.body as string).phone_filter).toBe("off");
  });

  it("realtime profilde koşuyu kapatır ve nedenini söyler", async () => {
    mock((url) => (url === "/api/evalrun/set" ? SET(true) : url === "/api/evalrun/runs" ? [] : undefined), PROFILE({ id: "A2", name: "Realtime", mode: "realtime" }));
    open();
    expect(await screen.findByText(/Realtime profiller bu koşucuda henüz desteklenmiyor/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Test setini koştur" })).toBeDisabled();
  });

  it("sunucu hatasını (soğuk profil) gösterir", async () => {
    mock((url, init) => {
      if (url === "/api/evalrun/set") return SET(true);
      if (url === "/api/evalrun/runs" && init?.method === "POST") return new Response(JSON.stringify({ detail: { message: "L1 profili hazır değil (LLM soğuk)." } }), { status: 409 });
      if (url === "/api/evalrun/runs") return [];
    });
    open();
    const go = await screen.findByRole("button", { name: "Test setini koştur" });
    await waitFor(() => expect(go).toBeEnabled());
    fireEvent.click(go);
    expect(await screen.findByRole("alert")).toHaveTextContent("LLM soğuk");
  });
});

describe("Kıyas koşusu: ses kaydı (eval-006)", () => {
  const handler = (calls: Record<string, unknown>[]) => (url: string, init?: RequestInit) => {
    if (url === "/api/evalrun/set") return SET(true);
    if (url === "/api/evalrun/runs" && init?.method === "POST") return new Response(JSON.stringify({ run_id: RUN("running", 0).id, total: 2 }), { status: 202 });
    if (url === "/api/evalrun/runs") return [];
    if (url.startsWith("/api/evalrun/runs/")) return { ...RUN("done", 2), record_audio: true, calls };
  };

  it("onay kutusu varsayılan kapalı; kapalıyken istek gövdesinde record_audio yok", async () => {
    const f = mock(handler(CALLS("ok")));
    open();
    const box = await screen.findByRole("checkbox", { name: /Ses kaydını sakla/ });
    expect(box).not.toBeChecked();
    expect(screen.getByTestId("record-hint")).toHaveTextContent("~7,5 MB / 2 dk");
    expect(screen.getByTestId("record-hint")).toHaveTextContent("~150 MB");
    expect(screen.getByTestId("record-hint")).toHaveTextContent("sentetik persona");
    const go = screen.getByRole("button", { name: "Test setini koştur" });
    await waitFor(() => expect(go).toBeEnabled());
    fireEvent.click(go);
    await waitFor(() => expect(f.mock.calls.some(([u, i]) => u === "/api/evalrun/runs" && i?.method === "POST")).toBe(true));
    const post = f.mock.calls.find(([u, i]) => u === "/api/evalrun/runs" && i?.method === "POST")!;
    expect(JSON.parse(post[1]!.body as string)).not.toHaveProperty("record_audio");
  });

  it("işaretlenince record_audio: true gönderir ve kaydı olan satırda Aramalar'da dinle bağlantısı çıkar", async () => {
    const rows = [{ ...CALLS("ok")[0], has_audio: true }, { ...CALLS("ok")[1], status: "ok", session_id: "b2", has_audio: false }];
    const f = mock(handler(rows));
    open();
    fireEvent.click(await screen.findByRole("checkbox", { name: /Ses kaydını sakla/ }));
    expect(screen.getByRole("checkbox", { name: /Ses kaydını sakla/ })).toBeChecked();
    const go = screen.getByRole("button", { name: "Test setini koştur" });
    await waitFor(() => expect(go).toBeEnabled());
    fireEvent.click(go);
    await waitFor(() => expect(f.mock.calls.some(([u, i]) => u === "/api/evalrun/runs" && i?.method === "POST")).toBe(true));
    const post = f.mock.calls.find(([u, i]) => u === "/api/evalrun/runs" && i?.method === "POST")!;
    expect(JSON.parse(post[1]!.body as string)).toEqual({ profile: "L1", phone_filter: "both", record_audio: true });
    const links = await screen.findAllByRole("link", { name: "Aramalar'da dinle" });
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveAttribute("href", "/calls");
  });
});
