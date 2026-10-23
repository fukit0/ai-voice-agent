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

function mockApi({ healthStatus = 200 } = {}) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (url.startsWith("/api/health"))
        return healthStatus === 200 ? new Response(JSON.stringify(HEALTH)) : new Response("", { status: healthStatus });
      if (url.startsWith("/api/profiles")) return new Response(JSON.stringify(PROFILES));
      return new Response("", { status: 404 });
    }),
  );
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
  it("menüde beş ekranı gösterir", () => {
    mockApi();
    renderAt("/");
    const nav = screen.getByRole("navigation", { name: "Lab ekranları" });
    for (const s of SCREENS) expect(within(nav).getByRole("link", { name: s.label })).toBeInTheDocument();
    expect(SCREENS).toHaveLength(5);
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
    renderAt("/tts");
    const select = await screen.findByRole("combobox", { name: "Profil" });
    const options = within(select).getAllByRole("option").map((o) => o.textContent);
    expect(options).toEqual(["L1 · Hızlı", "L2 · Dengeli", "A1 · API referansı (anahtar eksik)"]);
  });

  it("profil değişince ekran o profilin modellerini gösterir", async () => {
    mockApi();
    renderAt("/tts");
    const card = await screen.findByTestId("active-profile");
    expect(card).toHaveTextContent("ema · ema-lightning");
    fireEvent.change(screen.getByRole("combobox", { name: "Profil" }), { target: { value: "L2" } });
    expect(screen.getByTestId("active-profile")).toHaveTextContent("chatterbox · chatterbox-multilingual");
    expect(localStorage.getItem("sva.profile")).toBe("L2");
  });

  it("anahtarı eksik profilde anlaşılır uyarı gösterir", async () => {
    mockApi();
    renderAt("/stt");
    fireEvent.change(await screen.findByRole("combobox", { name: "Profil" }), { target: { value: "A1" } });
    expect(screen.getByRole("alert")).toHaveTextContent("Eksik API anahtarı: DEEPGRAM_API_KEY");
  });
});
