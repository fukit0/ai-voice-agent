import { expect, test } from "@playwright/test";

// norm-007: TTS stüdyosunda sayı / fiyat / tarih / telefon normalizasyonu önizlenir (gerçek backend, gerçek SPA).
test("TTS stüdyosu normalize edilmiş metni önizler", async ({ page }) => {
  await page.goto("/tts");
  await page.getByLabel("Cümle seti").fill(
    "Fiyat 1.250.000 TL, ilan 22.10.2026 tarihinde yayınlandı, 0532 123 45 67 numarasını arayın.\nMerhaba, nasılsınız?");
  const preview = page.getByLabel("Normalize önizleme");
  await expect(preview).toContainText("Fiyat bir milyon iki yüz elli bin lira");
  await expect(preview).toContainText("yirmi iki Ekim iki bin yirmi altı");
  await expect(preview).toContainText("sıfır beş yüz otuz iki, yüz yirmi üç, kırk beş, altmış yedi");
  await expect(preview).toContainText("1 cümlede değişiklik");  // 'Merhaba' değişmez
  await page.screenshot({ path: "e2e-artifacts/norm-007-preview.png", fullPage: true });
  await page.getByLabel(/Metni okunur Türkçeye çevir/).uncheck();
  await expect(page.getByLabel("Normalize önizleme")).toHaveCount(0);
});
