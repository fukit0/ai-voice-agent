import { describe, expect, it } from "vitest";
import { sttRunToText, sttTxtName } from "./sttExport";

const BASE = { id: "20261102-120000-abc123", created_at: "2026-11-02T12:00:00+00:00", filename: "gorusme.wav", audio_seconds: 12.5, reference: "" };

describe("sttRunToText", () => {
  it("müşteri/ajan ayrı koşuyu etiketli satırlar olarak yazar, sessiz kanalı belirtir", () => {
    const txt = sttRunToText({ ...BASE, channel: "both", results: [{
      profile: "L2", provider: "mlx_whisper", model: "whisper-turbo", status: "ok",
      speakers: {
        customer: { text: "", silent: true, level_dbfs: -120 },
        agent: { text: "Merhaba, ben Ayşe", silent: false, level_dbfs: -20 },
      },
    }] });
    expect(txt).toContain("Dosya: gorusme.wav");
    expect(txt).toContain("Kanal: Müşteri + Ajan ayrı");
    expect(txt).toContain("Müşteri (kanal sessiz, yazıya çevrilmedi):");
    expect(txt).toContain("Ajan:\nMerhaba, ben Ayşe");
    expect(txt).toContain("konuşma sırası gösterilmez");
  });

  it("tek metinli koşuda WER ve süreyi, hatalı modelde nedeni yazar", () => {
    const txt = sttRunToText({ ...BASE, reference: "merhaba dünya", results: [
      { profile: "L2", provider: "mlx_whisper", model: "m", status: "ok", text: "merhaba dünya", wer: 0, seconds: 0.5, rtf: 0.04 },
      { profile: "L3", provider: "hf_whisper", model: "b", status: "cold", error: "L3 hazır değil" },
    ] });
    expect(txt).toContain("Referans metin:\nmerhaba dünya");
    expect(txt).toContain("WER 0.0% · 0.50 sn · RTF 0.040");
    expect(txt).toContain("Sonuç yok: model soğuk, ölçülmedi. L3 hazır değil");
  });

  it("dosya adı uzantısız + -transkript.txt", () => {
    expect(sttTxtName({ ...BASE, results: [] })).toBe("gorusme-transkript.txt");
    expect(sttTxtName({ ...BASE, filename: null, results: [] })).toBe("kayit-transkript.txt");
  });
});
