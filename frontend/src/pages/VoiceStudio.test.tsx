import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PersonaPage } from "./PersonaPage";
import { VoiceStudio } from "./VoiceStudio";

const MATRIX = { source: "s", price_note: "n", models: [
  { id: "eleven_v4_turbo", label: "v4 Turbo", price_per_1k_usd: 0.04, latency_note: "", tags: true, tone_levers: "", notes: "" },
] };
const PERSONA = {
  name: "Elif", tone: "samimi", address: "bey_hanim", max_sentences: 2, max_words_per_sentence: 14, speed: 1,
  acknowledgements: ["Anladım."], avoid_phrases: [], extra_rules: "",
};
const VIEW = {
  persona: PERSONA, defaults: PERSONA, options: { tone: ["samimi"], address: ["bey_hanim"] }, prompt: "p", greeting: "Merhaba",
  preview_ack: [], prompt_stats: { utterances: 0, sentences: 0, avg_words_per_sentence: null, max_words: 0, over_limit: [], over_limit_rate: 0, avoid_hits: [] },
};

function mockApi() {
  const urls: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    urls.push(url);
    if (url.startsWith("/api/persona/voices?")) return new Response(JSON.stringify({ voices: [], assigned: {}, has_more: false, page: 0 }));
    if (url === "/api/persona/model-matrix") return new Response(JSON.stringify(MATRIX));
    if (url === "/api/persona/tones") return new Response(JSON.stringify({ tones: [], demo_text: "Merhaba Ahmet Bey." }));
    if (url === "/api/persona") return new Response(JSON.stringify(VIEW));
    if (url === "/api/persona/preview") return new Response(JSON.stringify({ problems: [], ...VIEW }));
    return new Response("", { status: 404 });
  }));
  return urls;
}

function Host() {
  const [open, setOpen] = useState(true);
  return (<><button onClick={() => setOpen(true)}>aç</button><VoiceStudio open={open} onClose={() => setOpen(false)} /></>);
}

beforeEach(() => {
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
});
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); document.body.style.overflow = ""; });

describe("Ses stüdyosu (popup)", () => {
  it("üç sekme sunar; yalnız açılan sekme yüklenir ve sekme durumu korunur", async () => {
    const urls = mockApi();
    render(<Host />);
    const dialog = screen.getByRole("dialog", { name: "Ses stüdyosu" });
    expect(within(dialog).getAllByRole("tab").map((t) => t.querySelector("b")!.textContent)).toEqual(["Ses kütüphanesi", "Laboratuvar", "Ton demosu"]);
    expect(await screen.findByRole("searchbox", { name: "Ses ara" })).toBeVisible();
    expect(urls.includes("/api/persona/tones")).toBe(false); // ton demosu sekmesi henüz açılmadı

    fireEvent.change(screen.getByRole("searchbox", { name: "Ses ara" }), { target: { value: "sıcak" } });
    fireEvent.click(screen.getByRole("tab", { name: /Ton demosu/ }));
    await waitFor(() => expect(urls.includes("/api/persona/tones")).toBe(true));
    expect(screen.getByRole("tab", { name: /Ton demosu/ })).toHaveAttribute("aria-selected", "true");
    expect(screen.queryByRole("searchbox", { name: "Ses ara" })).toBeNull(); // gizli sekme erişilebilirlik ağacında yok

    fireEvent.click(screen.getByRole("tab", { name: /Ses kütüphanesi/ }));
    expect(screen.getByRole("searchbox", { name: "Ses ara" })).toHaveValue("sıcak"); // arama metni silinmedi
  });

  it("ok tuşlarıyla sekme değiştirir", async () => {
    mockApi();
    render(<Host />);
    const first = screen.getByRole("tab", { name: /Ses kütüphanesi/ });
    fireEvent.keyDown(first, { key: "ArrowRight" });
    expect(screen.getByRole("tab", { name: /Laboratuvar/ })).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(screen.getByRole("tab", { name: /Laboratuvar/ }), { key: "ArrowLeft" });
    expect(screen.getByRole("tab", { name: /Ses kütüphanesi/ })).toHaveAttribute("aria-selected", "true");
  });

  it("Escape, ×, arka plana tıklama kapatır; sayfa kaydırması açılınca kilitlenir", async () => {
    mockApi();
    render(<Host />);
    expect(document.body.style.overflow).toBe("hidden");
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull()); // hidden: erişilebilirlik ağacından çıkar
    expect(document.body.style.overflow).toBe("");
    fireEvent.click(screen.getByRole("button", { name: "aç" }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Pencereyi kapat" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    fireEvent.click(screen.getByRole("button", { name: "aç" }));
    const overlay = (await screen.findByTestId("voice-studio")).parentElement!;
    fireEvent.mouseDown(overlay);
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });
});

describe("Persona ekranında stüdyo kartı", () => {
  it("stüdyo kapalıyken ElevenLabs çağrısı yapmaz; kart düğmesi pencereyi açar, kapatınca durum korunur", async () => {
    const urls = mockApi();
    render(<PersonaPage />);
    await screen.findByLabelText("Ajanın adı");
    expect(screen.getByTestId("studio-card")).toHaveTextContent("Ses stüdyosu");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(urls.some((u) => u.startsWith("/api/persona/voices?"))).toBe(false);
    expect(screen.queryByTestId("voice-picker")).toBeNull(); // uzun sayfa artık yok

    fireEvent.click(screen.getByRole("button", { name: "Ses stüdyosunu aç" }));
    expect(await screen.findByRole("dialog", { name: "Ses stüdyosu" })).toBeVisible();
    await screen.findByRole("searchbox", { name: "Ses ara" });
    expect(urls.some((u) => u.startsWith("/api/persona/voices?"))).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "Pencereyi kapat" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    const before = urls.filter((u) => u.startsWith("/api/persona/voices?")).length;
    fireEvent.click(screen.getByRole("button", { name: "Ses stüdyosunu aç" }));
    expect(await screen.findByRole("dialog")).toBeVisible();
    expect(urls.filter((u) => u.startsWith("/api/persona/voices?")).length).toBe(before); // yeniden yükleme yok
  });
});
