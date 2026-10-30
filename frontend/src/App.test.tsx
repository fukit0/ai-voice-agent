import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ProfileStatus } from "./api";
import { App, ROUTER_FUTURE } from "./App";
import { SCREENS } from "./screens";

const HEALTH = { status: "ok", service: "lab-backend", version: "0.1.0", python: "3.11", uptime_seconds: 1 };

const profile = (over: Partial<ProfileStatus>): ProfileStatus => ({
  id: "L1",
  name: "Hızlı",
  purpose: "",
  mode: "cascade",
  notes: "",
  components: {
    stt: { provider: "mlx_whisper", model: "whisper-turbo" },
    llm: { provider: "ollama", model: "gemma4:e4b" },
    tts: { provider: "ema", model: "ema-lightning" },
  },
  realtime: null,
  missing_env: [],
  issues: [],
  ready: true,
  warm: false,
  warmup: null,
  ...over,
});

const PROFILES: ProfileStatus[] = [
  profile({}),
  profile({
    id: "L2",
    name: "Dengeli",
    components: {
      stt: { provider: "mlx_whisper", model: "whisper-turbo" },
      llm: { provider: "ollama", model: "qwen3" },
      tts: { provider: "chatterbox", model: "chatterbox-multilingual" },
    },
  }),
  profile({
    id: "A1",
    name: "API referansı",
    components: {
      stt: { provider: "deepgram", model: "nova-3" },
      llm: { provider: "anthropic", model: "claude-haiku-5-5" },
      tts: { provider: "elevenlabs", model: "eleven_flash_v2_5" },
    },
    missing_env: ["DEEPGRAM_API_KEY"],
    ready: false,
  }),
];

const READY_JOB = {
  profile: "L1",
  state: "ready",
  seconds: 3.2,
  evicted: ["chatterbox:"],
  error: null,
  components: {
    stt: { state: "ready", load_seconds: 2.1, warm_seconds: 0.31 },
    llm: { state: "ready", load_seconds: 0.9, warm_seconds: 0.12 },
    tts: { state: "ready", load_seconds: 0.2, warm_seconds: 0.05 },
  },
};

function mockApi({ healthStatus = 200 } = {}) {
  let warmed = false;
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.startsWith("/api/health"))
      return healthStatus === 200 ? new Response(JSON.stringify(HEALTH)) : new Response("", { status: healthStatus });
    if (url.includes("/warmup") && init?.method === "POST")
      return new Response(JSON.stringify({ ...READY_JOB, state: "running", components: { stt: { state: "loading" } } }), { status: 202 });
    if (url.includes("/warmup")) {
      warmed = true;
      return new Response(JSON.stringify(READY_JOB));
    }
    if (url.startsWith("/api/tts") || url.startsWith("/api/stt") || url.startsWith("/api/eval")) return new Response("[]");
    if (url.startsWith("/api/profiles"))
      return new Response(
        JSON.stringify(PROFILES.map((p) => (warmed && p.id === "L1" ? { ...p, warm: true, warmup: READY_JOB } : p))),
      );
    return new Response("", { status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]} future={ROUTER_FUTURE}>
      <App />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  try {
    localStorage.clear();
  } catch {
    /* yok */
  }
});
afterEach(() => vi.unstubAllGlobals());

describe("Lab iskeleti", () => {
  it("menüde on ekranı gruplu gösterir", () => {
    mockApi();
    renderAt("/");
    const nav = screen.getByRole("navigation", { name: "Lab ekranları" });
    for (const s of SCREENS) expect(within(nav).getByRole("link", { name: s.label })).toBeInTheDocument();
    expect(SCREENS).toHaveLength(10);
    for (const g of ["Genel", "Arama", "Kayıtlar & Raporlar", "Yapılandırma", "Lab araçları"]) expect(within(nav).getByText(g)).toBeInTheDocument();
  });

  it("kök yolu ilk ekrana yönlendirir", () => {
    mockApi();
    renderAt("/");
    expect(screen.getByRole("heading", { level: 2, name: SCREENS[0].label })).toBeInTheDocument();
  });

  it("backend sağlıklıysa bağlı durumunu gösterir", async () => {
    mockApi();
    renderAt("/stt");
    expect(await screen.findByText(/Backend bağlı · v0.1.0/)).toBeInTheDocument();
  });

  it("backend yoksa hata durumunu gösterir", async () => {
    mockApi({ healthStatus: 502 });
    renderAt("/stt");
    expect(await screen.findByText(/Backend yok \(HTTP 502\)/)).toBeInTheDocument();
  });
});

describe("Profil seçimi (core-003)", () => {
  it("profilleri listeler ve eksik anahtarı işaretler", async () => {
    mockApi();
    renderAt("/playground");
    const select = await screen.findByRole("combobox", { name: "Profil" });
    const options = within(select).getAllByRole("option").map((o) => o.textContent);
    expect(options).toEqual(["L1 · Hızlı", "L2 · Dengeli", "A1 · API referansı (anahtar eksik)"]);
  });

  it("profil değişince ekran o profilin modellerini gösterir", async () => {
    mockApi();
    renderAt("/playground");
    const card = await screen.findByTestId("active-profile");
    expect(card).toHaveTextContent("ema · ema-lightning");
    fireEvent.change(screen.getByRole("combobox", { name: "Profil" }), { target: { value: "L2" } });
    expect(screen.getByTestId("active-profile")).toHaveTextContent("chatterbox · chatterbox-multilingual");
    expect(localStorage.getItem("sva.profile")).toBe("L2");
  });

  it("anahtarı eksik profilde anlaşılır uyarı gösterir", async () => {
    mockApi();
    renderAt("/playground"); // ActiveProfile kartını gösteren (henüz placeholder) bir ekran; /stt artık kendi sayfası
    fireEvent.change(await screen.findByRole("combobox", { name: "Profil" }), { target: { value: "A1" } });
    expect(screen.getByRole("alert")).toHaveTextContent("Eksik API anahtarı: DEEPGRAM_API_KEY");
  });
});

describe("Hazırla (lab-006, ADR 0001)", () => {
  it("soğuk profilde uyarı ve Hazırla düğmesi gösterir", async () => {
    mockApi();
    renderAt("/playground");
    expect(await screen.findByTestId("warm-state")).toHaveTextContent("Soğuk");
    expect(screen.getByTestId("cold-warning")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Hazırla" })).toBeEnabled();
  });

  it("Hazırla profili ısıtır, süreleri gösterir ve sıcak durumuna geçer", async () => {
    const fetchMock = mockApi();
    renderAt("/playground");
    fireEvent.click(await screen.findByRole("button", { name: "Hazırla" }));
    expect(await screen.findByText(/Hazırlanıyor · STT/)).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/api/profiles/L1/warmup?keep_others=false", { method: "POST" });
    expect(await screen.findByText("Sıcak", {}, { timeout: 3000 })).toBeInTheDocument();
    expect(screen.queryByTestId("cold-warning")).not.toBeInTheDocument();
    expect(screen.getByText(/sıcak çağrı 310 ms · ilk yükleme 2.1 sn/)).toBeInTheDocument();
  });

  it("bellek çekişmesinde uyarı gösterir", async () => {
    const degraded = {
      ...READY_JOB,
      state: "degraded",
      error: "Bu bilgisayarda profilin tüm modelleri aynı anda sıcak tutulamıyor; TTS hepsi yüklüyken yavaşlıyor (bellek çekişmesi).",
      components: { ...READY_JOB.components, tts: { state: "degraded", load_seconds: 140, warm_seconds: 2, final_seconds: 33 } },
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) =>
        url.startsWith("/api/profiles")
          ? new Response(JSON.stringify(PROFILES.map((p) => (p.id === "L1" ? { ...p, warmup: degraded } : p))))
          : new Response(JSON.stringify(HEALTH)),
      ),
    );
    renderAt("/playground");
    expect(await screen.findByText("Bellek yetmiyor")).toBeInTheDocument();
    expect(screen.getByTestId("degraded-warning")).toHaveTextContent("bellek çekişmesi");
    expect(screen.getByText(/hepsi yüklüyken 33.0 sn/)).toBeInTheDocument();
  });

  it("eksik anahtarlı profilde Hazırla devre dışı", async () => {
    mockApi();
    renderAt("/playground");
    fireEvent.change(await screen.findByRole("combobox", { name: "Profil" }), { target: { value: "A1" } });
    expect(screen.getByRole("button", { name: "Hazırla" })).toBeDisabled();
  });
});
