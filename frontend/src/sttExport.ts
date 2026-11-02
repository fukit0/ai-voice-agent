import type { SttRun } from "./api";

const CHANNEL_LABEL: Record<string, string> = {
  mix: "Karışık", left: "Sol (müşteri)", right: "Sağ (ajan)", both: "Müşteri + Ajan ayrı",
};

// STT koşusunu indirilebilir düz metne çevirir (UTF-8). Model başına bir bölüm; ayrı kanal modunda Müşteri/Ajan satırları.
export function sttRunToText(run: SttRun & { channel?: string; language?: string }): string {
  const lines: string[] = [
    "STT transkripti",
    `Dosya: ${run.filename ?? "kayıt"}`,
    `Tarih: ${new Date(run.created_at).toLocaleString("tr-TR")}`,
    `Süre: ${run.audio_seconds} sn · Kanal: ${CHANNEL_LABEL[run.channel ?? "mix"] ?? run.channel}`,
    `Koşu: ${run.id}`,
  ];
  if (run.reference) lines.push("", "Referans metin:", run.reference);
  for (const r of run.results) {
    lines.push("", "=".repeat(48), `${r.model || r.provider} (${r.provider} · ${r.profile})`);
    if (r.status !== "ok") {
      lines.push(`Sonuç yok: ${r.status === "cold" ? "model soğuk, ölçülmedi. " : ""}${r.error ?? ""}`.trim());
      continue;
    }
    if (r.speakers) {
      for (const [key, label] of [["customer", "Müşteri"], ["agent", "Ajan"]] as const) {
        const sp = r.speakers[key];
        lines.push("", `${label}${sp.silent ? " (kanal sessiz, yazıya çevrilmedi)" : ""}:`, sp.text || "(konuşma yok)");
      }
      lines.push("", "Not: kanallar ayrı yazıldı; konuşma sırası gösterilmez.");
    } else {
      lines.push("", r.text || "(boş transkript)");
      const stats = [r.wer != null ? `WER ${(r.wer * 100).toFixed(1)}%` : "", r.seconds != null ? `${r.seconds.toFixed(2)} sn` : "",
        r.rtf != null ? `RTF ${r.rtf.toFixed(3)}` : ""].filter(Boolean);
      if (stats.length) lines.push("", stats.join(" · "));
    }
  }
  return lines.join("\n") + "\n";
}

export function downloadText(filename: string, text: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: "text/plain;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export const sttTxtName = (run: SttRun) => `${(run.filename ?? "kayit").replace(/\.[^.]+$/, "")}-transkript.txt`;
