import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { VoicePicker } from "./VoicePicker";

const VOICES = [
  { voice_id: "hesapses12345", name: "Egemen", description: "Warm", preview_url: "http://x/e.mp3", source: "account", public_owner_id: null, tags: ["male", "warm"] },
  { voice_id: "libses1234567", name: "Gökçe Deniz", description: "Joyful", preview_url: "http://x/g.mp3", source: "library", public_owner_id: "owner12345678", tags: ["female"] },
];

function mockApi() {
  let assigned: Record<string, string> = {};
  const calls: { url: string; method: string; body?: any }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ url, method, body });
    if (url.startsWith("/api/persona/voices?")) return new Response(JSON.stringify({ voices: VOICES, assigned }));
    if (url === "/api/persona/tones/voices") {
      assigned = { ...assigned, ...body.voices };
      for (const k of Object.keys(assigned)) if (!assigned[k]) delete assigned[k];
      return new Response(JSON.stringify({ assigned }));
    }
    if (url === "/api/persona/voices/add") return new Response(JSON.stringify({ voice_id: "libses1234567" }));
    return new Response("", { status: 404 });
  }));
  return calls;
}
afterEach(() => vi.unstubAllGlobals());

describe("Ses seçici", () => {
  it("sesleri listeler, bir tona atar ve atamayı kaldırır", async () => {
    const calls = mockApi();
    render(<VoicePicker />);
    expect(await screen.findByTestId("voice-hesapses12345")).toHaveTextContent("Egemen");
    expect(screen.getByTestId("voice-assigned")).toHaveTextContent("Enerjik: genel ses");
    fireEvent.click(screen.getByRole("button", { name: "Enerjik için seç" }));
    await waitFor(() => expect(screen.getByTestId("voice-assigned")).toHaveTextContent("Enerjik: Egemen"));
    expect(calls.find((c) => c.method === "PUT")!.body).toEqual({ voices: { enerjik: "hesapses12345" } });
    fireEvent.click(screen.getByRole("button", { name: "Enerjik atamasını kaldır" }));
    await waitFor(() => expect(screen.getByTestId("voice-assigned")).toHaveTextContent("Enerjik: genel ses"));
  });

  it("kütüphane sesi için 'Hesabıma ekle' sunar ve doğru kimliklerle çağırır", async () => {
    const calls = mockApi();
    render(<VoicePicker />);
    const card = await screen.findByTestId("voice-libses1234567");
    expect(card).toHaveTextContent("Kütüphane");
    fireEvent.click(card.querySelector("button")!);
    await waitFor(() => expect(calls.some((c) => c.url === "/api/persona/voices/add")).toBe(true));
    expect(calls.find((c) => c.url === "/api/persona/voices/add")!.body)
      .toEqual({ public_owner_id: "owner12345678", voice_id: "libses1234567", name: "Gökçe Deniz" });
  });

  it("anahtar yoksa hatayı gösterir", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail: { message: "ELEVENLABS_API_KEY tanımlı değil." } }), { status: 400 })));
    render(<VoicePicker />);
    expect(await screen.findByRole("note")).toHaveTextContent("ELEVENLABS_API_KEY");
  });
});
