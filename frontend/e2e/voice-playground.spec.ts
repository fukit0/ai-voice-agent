import { expect, test } from "@playwright/test";

// core-001 kabul: Playground açılır, 'Başlat' ile bağlantı kurulur; kullanıcının sesi ajana ulaşır,
// ajanın sesi tarayıcıda duyulur. Gerçek Chromium + gerçek WebRTC (Opus/DTLS) + sahte mikrofon dosyası;
// STT/LLM/TTS sahtedir (model gerektirmez). Gerçek mikrofon + gerçek modeller Mac'te elle doğrulanır.
test("Başlat → bağlanır, ajan selamlar, sahte mikrofon konuşması ajana ulaşır, ajan sesi duyulur, Durdur kapatır", async ({ page, request }) => {
  await page.goto("/playground");
  await expect(page.getByRole("heading", { level: 2, name: "Playground" })).toBeVisible();

  // ADR 0001: profil soğukken Başlat çalışmaz (409); önce Hazırla
  const cold = await request.post("/api/voice/offer", { data: { sdp: "v=0", type: "offer", profile: "V1" } });
  expect(cold.status()).toBe(409);
  expect((await cold.json()).detail.error).toBe("profile_not_warm");
  await request.post("/api/profiles/V1/warmup?keep_others=true");
  await expect.poll(async () => (await (await request.get("/api/profiles/V1/warmup")).json()).state, { timeout: 10_000 }).not.toBe("running");
  await page.reload();

  await page.getByRole("button", { name: "Başlat" }).click();
  await expect(page.getByRole("button", { name: "Durdur" })).toBeVisible({ timeout: 15_000 });

  // ajanın selamı: ajan sesi tarayıcıya ulaşır
  await expect(page.getByTestId("voice-lines")).toContainText("Ajan:", { timeout: 15_000 });
  // sahte mikrofon konuşması → STT metni → ajan cevabı
  await expect(page.getByTestId("voice-lines")).toContainText("Siz: ses geldi", { timeout: 30_000 });
  await expect(page.getByTestId("voice-lines")).toContainText("Anladım", { timeout: 30_000 });
  await expect(page.getByTestId("voice-latency")).toContainText("ilk sese", { timeout: 30_000 });

  // ajanın sesi gerçekten alındı (WebRTC uzak iz üzerinde enerji ölçüldü)
  await expect.poll(() => page.evaluate(() => (window as unknown as { __voiceStats: { remoteSamples: number } }).__voiceStats.remoteSamples),
    { timeout: 20_000 }).toBeGreaterThan(3);
  const sessions = await (await request.get("/api/voice/sessions")).json();
  expect(sessions).toHaveLength(1);
  expect(sessions[0].turns).toBeGreaterThanOrEqual(1);
  await page.screenshot({ path: "e2e-artifacts/core-001-playground.png", fullPage: true });

  await page.getByRole("button", { name: "Durdur" }).click();
  await expect(page.getByRole("button", { name: "Başlat" })).toBeVisible();
  await expect.poll(async () => (await (await request.get("/api/voice/sessions")).json()).length).toBe(0);
});
