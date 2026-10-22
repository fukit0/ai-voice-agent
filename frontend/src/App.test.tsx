import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App, ROUTER_FUTURE } from "./App";
import { SCREENS } from "./screens";


function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]} future={ROUTER_FUTURE}>
      <App />
    </MemoryRouter>,
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("Lab iskeleti", () => {
  it("menüde beş ekranı gösterir", () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})));
    renderAt("/");
    const nav = screen.getByRole("navigation", { name: "Lab ekranları" });
    for (const s of SCREENS) {
      expect(nav).toContainElement(screen.getByRole("link", { name: s.label }));
    }
    expect(SCREENS).toHaveLength(5);
  });

  it("kök yolu ilk ekrana yönlendirir", () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})));
    renderAt("/");
    expect(screen.getByRole("heading", { level: 2, name: SCREENS[0].label })).toBeInTheDocument();
  });

  it("backend sağlıklıysa bağlı durumunu gösterir", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ status: "ok", service: "lab-backend", version: "0.1.0", python: "3.11", uptime_seconds: 1 }))),
    );
    renderAt("/stt");
    expect(await screen.findByText(/Backend bağlı · v0.1.0/)).toBeInTheDocument();
  });

  it("backend yoksa hata durumunu gösterir", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("", { status: 502 })));
    renderAt("/stt");
    expect(await screen.findByText(/Backend yok \(HTTP 502\)/)).toBeInTheDocument();
  });
});
