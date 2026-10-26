import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SttPage } from "./SttPage";

const MODELS = [
  { profile: "L2", profiles: ["L1", "L2"], provider: "mlx_whisper", model: "whisper-large-v3-turbo", ready: true, warm: true, missing_env: [] },
  { profile: "L3", profiles: ["L3"], provider: "hf_whisper", model: "BuzzASR/turkish", ready: true, warm: false, missing_env: [] },
  { profile: "A1", profiles: ["A1"], provider: "deepgram", model: "nova-3", ready: false, warm: false, missing_env: ["DEEPGRAM_API_KEY"] },
];
const RUN = {
  id: "20261023-120000-abc123", created_at: "2026-10-23T12:00:00+00:00", filename: "t.wav", audio_seconds: 4.2,
  reference: "Merhaba dünya",
  results: [
    { profile: "L2", provider: "mlx_whisper", model: "whisper-large-v3-turbo", status: "ok", text: "Merhaba dünya", seconds: 0.5, rtf: 0.119, wer: 0, ref_words: 2, substitutions: 0, deletions: 0, insertions: 0 },
    { profile: "L3", provider: "hf_whisper", model: "BuzzASR/turkish", status: "cold", error: "L3 profili hazır değil (STT soğuk)." },
  ],
};

let models = MODELS;
let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  models = MODELS;
  fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === "/api/stt/models") return new Response(JSON.stringify(models));
    if (url === "/api/stt/runs") return new Response(JSON.stringify([{ id: RUN.id, created_at: RUN.created_at, filename: "t.wav", audio_seconds: 4.2, reference: RUN.reference, models: ["a", "b"], best_wer: 0 }]));
    if (url === `/api/stt/runs/${RUN.id}`) return new Response(JSON.stringify(RUN));
    if (url === "/api/stt/compare" && init?.method === "POST") return new Response(JSON.stringify(RUN));
    if (url.includes("/warmup") && init?.method === "POST") return new Response(JSON.stringify({ state: "running", components: {} }), { status: 202 });
    if (url.includes("/warmup")) {
      models = MODELS.map((m) => (m.profile === "L3" ? { ...m, warm: true } : m));
      return new Response(JSON.stringify({ state: "ready", components: {} }));
    }
    return new Response("", { status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: () => "blob:x", revokeObjectURL: () => {} }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("STT test ekranı", () => {
  it("modelleri durumlarıyla listeler; yalnızca sıcak ve hazır olanlar başta seçilidir", async () => {
    render(<SttPage />);
    await screen.findByText("BuzzASR/turkish");
    const boxes = screen.getAllByRole("checkbox") as HTMLInputElement[];
    expect(boxes.map((b) => b.checked)).toEqual([true, false, false]);
    expect(boxes[2].disabled).toBe(true); // API anahtarı eksik
    expect(screen.getByText(/Anahtar eksik: DEEPGRAM_API_KEY/)).toBeInTheDocument();
    expect(screen.getByText("Soğuk")).toBeInTheDocument();
  });

  it("Karşılaştır, ses seçilene kadar kapalıdır", async () => {
    render(<SttPage />);
    await screen.findByText("BuzzASR/turkish");
    expect(screen.getByRole("button", { name: "Karşılaştır" })).toBeDisabled();
  });

  it("soğuk modeli Hazırla ile ısıtır (yalnızca STT bileşeni, diğer sıcaklar kalsın diye keep_others=true) ve listeyi yeniler", async () => {
    render(<SttPage />);
    await screen.findByText("BuzzASR/turkish");
    fireEvent.click(screen.getByRole("button", { name: "Hazırla" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/profiles/L3/warmup?keep_others=true&components=stt", { method: "POST" }), { timeout: 3000 });
    await waitFor(() => expect(screen.queryByRole("button", { name: "Hazırla" })).toBeNull(), { timeout: 4000 });
  });

  it("kayıtlı koşuyu açınca sonuçları, WER'i ve soğuk uyarısını gösterir", async () => {
    render(<SttPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Aç" }));
    const results = await screen.findByTestId("stt-results");
    expect(within(results).getByTestId("wer")).toHaveTextContent("0.0%");
    expect(within(results).getByText(/Soğuk, ölçülmedi/)).toBeInTheDocument();
    expect((screen.getByLabelText("Referans metin") as HTMLTextAreaElement).value).toBe("Merhaba dünya");
  });
  it("kanal ve alan ipucu seçenekleri karşılaştırma isteğine eklenir; WAV dosyası kanal seçimi bozulmasın diye çevrilmeden gider (core-013)", async () => {
    render(<SttPage />);
    await screen.findByText("BuzzASR/turkish");
    const file = new File([new Uint8Array([82, 73, 70, 70])], "oturum.wav", { type: "audio/wav" });
    fireEvent.change(screen.getByTestId("stt-file"), { target: { files: [file] } });
    fireEvent.change(screen.getByLabelText("Kanal"), { target: { value: "left" } });
    fireEvent.change(screen.getByLabelText("Alan ipucu"), { target: { value: "sahibinden.com" } });
    const run = screen.getByRole("button", { name: "Karşılaştır" });
    await waitFor(() => expect(run).toBeEnabled());
    fireEvent.click(run);
    await waitFor(() => expect(fetchMock.mock.calls.some(([u]) => u === "/api/stt/compare")).toBe(true));
    const form = fetchMock.mock.calls.find(([u]) => u === "/api/stt/compare")![1].body as FormData;
    expect(form.get("channel")).toBe("left");
    expect(form.get("prompt")).toBe("sahibinden.com");
    expect((form.get("audio") as File).size).toBe(4);      // çevrilmedi: özgün baytlar
  });
});
