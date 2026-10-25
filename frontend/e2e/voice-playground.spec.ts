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

  await page.getByLabel("Senaryo").selectOption("");   // bu test serbest sohbet; senaryo modu aşağıda
  await page.getByRole("button", { name: "Başlat" }).click();
  await expect(page.getByRole("button", { name: "Durdur" })).toBeVisible({ timeout: 15_000 });

  // ajanın selamı: ajan sesi tarayıcıya ulaşır
  await expect(page.getByTestId("voice-lines")).toContainText("Ajan:", { timeout: 15_000 });
  // sahte mikrofon konuşması → STT metni → ajan cevabı
  await expect(page.getByTestId("voice-lines")).toContainText("Siz: ses geldi", { timeout: 30_000 });
  await expect(page.getByTestId("voice-lines")).toContainText("Anladım", { timeout: 30_000 });
  await expect(page.getByTestId("voice-latency")).toContainText("açılış", { timeout: 30_000 });
  await expect(page.getByTestId("voice-latency").getByRole("row")).toHaveCount(3, { timeout: 30_000 }); // başlık + açılış + 1 tur

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

// lab-003: senaryo + telefon filtresi. Sahte LLM değer kuralına göre cevap verir: 'giris' -> dinle (KVKK anonsu),
// ardından 'musaitlik' sorusu. Sahte mikrofon tek konuşma yapar, yani tek cevap doğrulanır.
test("Senaryo modu: aktif düğüm ilerler, çıkarılan cevap listelenir, telefon filtresi konuşma sırasında kapatılır", async ({ page, request }) => {
  await request.post("/api/profiles/V1/warmup?keep_others=true");
  await expect.poll(async () => (await (await request.get("/api/profiles/V1/warmup")).json()).state, { timeout: 10_000 }).not.toBe("running");
  await page.goto("/playground");
  await expect(page.getByLabel("Senaryo")).toHaveValue("anket");
  await page.getByRole("checkbox", { name: /Telefon filtresi/ }).check();
  await page.getByRole("button", { name: "Başlat" }).click();
  await expect(page.getByRole("button", { name: "Durdur" })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId("active-node")).toContainText("Giriş ve KVKK aydınlatma", { timeout: 15_000 });
  await expect(page.getByTestId("voice-lines")).toContainText("benim adım Elif", { timeout: 15_000 });

  await expect(page.getByTestId("voice-answers")).toContainText("dinle", { timeout: 30_000 });
  await expect(page.getByTestId("active-node")).toContainText("Müsaitlik", { timeout: 30_000 });
  const sessions = await (await request.get("/api/voice/sessions")).json();
  expect(sessions[0].stats.utterances).toBeGreaterThanOrEqual(1);
  await page.screenshot({ path: "e2e-artifacts/lab-003-playground.png", fullPage: true });

  await page.getByRole("checkbox", { name: /Telefon filtresi/ }).uncheck();   // konuşma sürerken
  await page.getByRole("button", { name: "Durdur" }).click();
  await expect.poll(async () => (await (await request.get("/api/voice/sessions")).json()).length).toBe(0);
});

// lab-003 / Welcome Call: Playground'da senaryo seçilir, ajan teyit sorusuyla başlar (aranan kişi mi?), dal ilerler.
test("Senaryo modu: Welcome Call seçilir, ajan açılışta aranan kişiyi teyit eder ve cevap sonrası ilerler", async ({ page, request }) => {
  await request.post("/api/profiles/V1/warmup?keep_others=true");
  await expect.poll(async () => (await (await request.get("/api/profiles/V1/warmup")).json()).state, { timeout: 10_000 }).not.toBe("running");
  await page.goto("/playground");
  await page.getByLabel("Senaryo").selectOption("welcome");
  await page.getByRole("button", { name: "Başlat" }).click();
  await expect(page.getByRole("button", { name: "Durdur" })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId("voice-lines")).toContainText("Ahmet Yılmaz", { timeout: 15_000 });
  await expect(page.getByTestId("voice-answers")).toContainText("Evet", { timeout: 30_000 });
  await page.screenshot({ path: "e2e-artifacts/lab-003-welcome-playground.png", fullPage: true });
  await page.getByRole("button", { name: "Durdur" }).click();
  await expect.poll(async () => (await (await request.get("/api/voice/sessions")).json()).length).toBe(0);
});

// core-002: söz kesme gerçek tarayıcıda. Sahte mikrofon dosyası 1. sn'de konuşmaya başlar; ajan o sırada selamlıyor.
// Ölçüm tarayıcıdadır (uzak ses akışının enerjisi): kullanıcı sesinin başladığı andan ajan sesinin kesildiği ana kadar.
test("Söz kesme: ajan konuşurken kullanıcı konuşmaya başlar, ajan sesi tarayıcıda 500 ms içinde kesilir", async ({ page, request }) => {
  await request.post("/api/profiles/V1/warmup?keep_others=true");
  await expect.poll(async () => (await (await request.get("/api/profiles/V1/warmup")).json()).state, { timeout: 10_000 }).not.toBe("running");
  await page.goto("/playground");
  await page.getByLabel("Senaryo").selectOption("");
  await page.getByRole("button", { name: "Başlat" }).click();
  await expect(page.getByText(/söz kesme: 1/)).toBeVisible({ timeout: 20_000 });
  await expect.poll(() => page.evaluate(() => (window as unknown as { __voiceStats: { micOnset: number | null } }).__voiceStats.micOnset),
    { timeout: 10_000 }).not.toBeNull();
  await page.waitForTimeout(1600);   // ölçüm penceresi (1,5 sn) dolsun
  const stats = await page.evaluate(() => (window as unknown as { __voiceStats: { bargeCutMs: number | null } }).__voiceStats);
  console.log(`BROWSER_BARGE_CUT_MS=${stats.bargeCutMs}`);
  expect(stats.bargeCutMs ?? 0).toBeLessThanOrEqual(500);
  await page.getByRole("button", { name: "Durdur" }).click();
});
