import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { VoicePicker } from "./VoicePicker";

const VOICES = [
  { voice_id: "hesapses12345", name: "Egemen", description: "Warm", preview_url: "http://x/e.mp3", source: "account", public_owner_id: null,
    tags: ["male", "warm"], gender: "male", age: "middle_aged", descriptive: "warm", use_case: "conversational" },
  { voice_id: "libses1234567", name: "Gökçe Deniz", description: "Joyful", preview_url: "http://x/g.mp3", source: "library", public_owner_id: "owner12345678",
    tags: ["female"], gender: "female", age: "young", use_case: "social_media", cloned_by_count: 4200 },
];
const MATRIX = { source: "s", price_note: "n", models: [
  { id: "eleven_flash_v2_5", label: "Flash v2.5", price_per_1k_usd: 0.04, latency_note: "", tags: false, tone_levers: "", notes: "" },
  { id: "eleven_v4_turbo", label: "v4 Turbo", price_per_1k_usd: 0.04, latency_note: "", tags: true, tone_levers: "", notes: "" },
] };

function mockApi(opts: { hasMore?: boolean } = {}) {
  let assigned: Record<string, string> = {};
  const calls: { url: string; method: string; body?: any }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ url, method, body });
    if (url.startsWith("/api/persona/voices?")) {
      const page = Number(new URL(url, "http://h").searchParams.get("page") ?? 0);
      const rows = page === 0 ? VOICES : [{ ...VOICES[1], voice_id: "libses7654321", name: "Sayfa İki" }];
      return new Response(JSON.stringify({ voices: rows, assigned, has_more: !!opts.hasMore && page === 0, page }));
    }
    if (url === "/api/persona/model-matrix") return new Response(JSON.stringify(MATRIX));
    if (url === "/api/persona/tones/voices") {
      assigned = { ...assigned, ...body.voices };
      for (const k of Object.keys(assigned)) if (!assigned[k]) delete assigned[k];
      return new Response(JSON.stringify({ assigned }));
    }
    if (url === "/api/persona/voices/add") return new Response(JSON.stringify({ voice_id: "libses1234567" }));
    if (url === "/api/persona/tts-lab") {
      return new Response(JSON.stringify({
        model: body.model, voice_id: body.voice_id, tone: body.tone, seed: 1234, chars: 21, sent_text: body.text, applied: {},
        price_per_1k_usd: 0.04, cost_usd: 0.00084, median_first_audio_seconds: 0.287,
        runs: [{ id: "lab-1", url: "/api/persona/tone-demo/lab-1.wav", first_audio_seconds: 0.287, total_seconds: 0.9, audio_seconds: 3, acoustics: {} }],
      }));
    }
    return new Response("", { status: 404 });
  }));
  return calls;
}
const voiceCalls = (calls: { url: string }[]) => calls.filter((c) => c.url.startsWith("/api/persona/voices?")).map((c) => c.url);
const lastVoiceCall = (calls: { url: string }[]) => { const u = voiceCalls(calls); return u[u.length - 1]; };

let play: ReturnType<typeof vi.fn>;
beforeEach(() => {
  play = vi.fn(() => Promise.resolve());
  vi.spyOn(HTMLMediaElement.prototype, "play").mockImplementation(play as any);
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
});
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("Ses kütüphanesi", () => {
  it("sesleri listeler, bir tona atar ve atamayı kaldırır", async () => {
    const calls = mockApi();
    render(<VoicePicker />);
    const row = await screen.findByTestId("voice-hesapses12345");
    expect(row).toHaveTextContent("Egemen");
    expect(row).toHaveTextContent("Erkek"); // etiketler Türkçeleştirilir
    expect(screen.getByTestId("voice-assigned")).toHaveTextContent("Enerjik: genel ses");
    fireEvent.click(within(row).getByRole("button", { name: "Ton ata" }));
    fireEvent.click(screen.getByRole("button", { name: "Enerjik için seç" }));
    await waitFor(() => expect(screen.getByTestId("voice-assigned")).toHaveTextContent("Enerjik: Egemen"));
    expect(calls.find((c) => c.method === "PUT")!.body).toEqual({ voices: { enerjik: "hesapses12345" } });
    expect(screen.getByTestId("voice-hesapses12345")).toHaveTextContent("Enerjik"); // satırda atanan ton rozeti
    fireEvent.click(screen.getByRole("button", { name: "Enerjik atamasını kaldır" }));
    await waitFor(() => expect(screen.getByTestId("voice-assigned")).toHaveTextContent("Enerjik: genel ses"));
  });

  it("kütüphane sesi için 'Hesabıma ekle' sunar ve doğru kimliklerle çağırır", async () => {
    const calls = mockApi();
    render(<VoicePicker />);
    const card = await screen.findByTestId("voice-libses1234567");
    expect(card).toHaveTextContent("Kütüphane");
    expect(card).toHaveTextContent("4.200 kullanım");
    fireEvent.click(within(card).getByRole("button", { name: "Hesabıma ekle" }));
    await waitFor(() => expect(calls.some((c) => c.url === "/api/persona/voices/add")).toBe(true));
    expect(calls.find((c) => c.url === "/api/persona/voices/add")!.body)
      .toEqual({ public_owner_id: "owner12345678", voice_id: "libses1234567", name: "Gökçe Deniz" });
  });

  it("yazdıkça arar (bekleyerek) ve süzgeçleri sunucuya iletir", async () => {
    const calls = mockApi();
    render(<VoicePicker />);
    await screen.findByTestId("voice-hesapses12345");
    fireEvent.change(screen.getByRole("searchbox", { name: "Ses ara" }), { target: { value: "sıcak" } });
    await waitFor(() => expect(voiceCalls(calls).some((u) => u.includes("search=s%C4%B1cak"))).toBe(true));
    fireEvent.click(within(screen.getByRole("group", { name: "Cinsiyet" })).getByRole("button", { name: "Kadın" }));
    fireEvent.change(screen.getByRole("combobox", { name: "Sırala" }), { target: { value: "popular" } });
    await waitFor(() => {
      const last = lastVoiceCall(calls);
      expect(last).toContain("gender=female");
      expect(last).toContain("sort=popular");
      expect(last).toContain("search=");
    });
    fireEvent.click(within(screen.getByRole("group", { name: "Kaynak" })).getByRole("button", { name: "Hesabım" }));
    await waitFor(() => expect(lastVoiceCall(calls)).toContain("library=false"));
  });

  it("'Daha fazla yükle' sonraki sayfayı listeye ekler", async () => {
    const calls = mockApi({ hasMore: true });
    render(<VoicePicker />);
    await screen.findByTestId("voice-hesapses12345");
    fireEvent.click(screen.getByRole("button", { name: "Daha fazla yükle" }));
    expect(await screen.findByTestId("voice-libses7654321")).toHaveTextContent("Sayfa İki");
    expect(screen.getByTestId("voice-hesapses12345")).toBeInTheDocument(); // ilk sayfa korunur
    expect(lastVoiceCall(calls)).toContain("page=1");
  });

  it("dinleme klibini ekranda çalar ve durdurur", async () => {
    mockApi();
    render(<VoicePicker />);
    await screen.findByTestId("voice-hesapses12345");
    fireEvent.click(screen.getByRole("button", { name: "Egemen önizlemeyi çal" }));
    expect(play).toHaveBeenCalledTimes(1);
    expect((screen.getByTestId("vp-audio") as HTMLAudioElement).src).toBe("http://x/e.mp3");
    fireEvent.click(await screen.findByRole("button", { name: "Egemen önizlemeyi durdur" }));
    expect(await screen.findByRole("button", { name: "Egemen önizlemeyi çal" })).toBeInTheDocument();
  });

  it("özel önizleme: seçili ses + model + tonla üretir, gecikmeyi gösterir ve çalar", async () => {
    const calls = mockApi();
    render(<VoicePicker />);
    const card = await screen.findByTestId("voice-hesapses12345");
    const go = screen.getByRole("button", { name: "Önizle" });
    expect(go).toBeDisabled(); // ses seçilmeden önizleme yok
    fireEvent.click(card);
    await screen.findByRole("option", { name: "Flash v2.5" });
    fireEvent.change(screen.getByLabelText("Önizleme modeli"), { target: { value: "eleven_flash_v2_5" } });
    fireEvent.change(screen.getByLabelText("Önizleme tonu"), { target: { value: "sakin" } });
    fireEvent.change(screen.getByLabelText("Önizleme metni"), { target: { value: "Merhaba dünya" } });
    expect(go).toBeEnabled();
    fireEvent.click(go);
    expect(await screen.findByTestId("vp-info")).toHaveTextContent("ilk ses 0.287 sn");
    expect(screen.getByTestId("vp-info")).toHaveTextContent("Egemen");
    expect(calls.find((c) => c.url === "/api/persona/tts-lab")!.body)
      .toMatchObject({ text: "Merhaba dünya", model: "eleven_flash_v2_5", voice_id: "hesapses12345", tone: "sakin", runs: 1 });
    expect(play).toHaveBeenCalled();
    expect((screen.getByTestId("vp-audio") as HTMLAudioElement).src).toContain("/api/persona/tone-demo/lab-1.wav");
  });

  it("kütüphane sesi seçiliyken özel önizleme kapalıdır ve ekleme önerir", async () => {
    mockApi();
    render(<VoicePicker />);
    fireEvent.click(await screen.findByTestId("voice-libses1234567"));
    expect(screen.getByRole("button", { name: "Önizle" })).toBeDisabled();
    expect(screen.getByTestId("vp-custom")).toHaveTextContent("önce Hesabıma ekle");
  });

  it("anahtar yoksa hatayı gösterir", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail: { message: "ELEVENLABS_API_KEY tanımlı değil." } }), { status: 400 })));
    render(<VoicePicker />);
    expect(await screen.findByRole("note")).toHaveTextContent("ELEVENLABS_API_KEY");
  });
});
