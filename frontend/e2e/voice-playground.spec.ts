import { expect, test } from "@playwright/test";

// core-001 kabul: Playground açılır, 'Başlat' ile bağlantı kurulur; kullanıcının sesi ajana ulaşır,
// ajanın sesi tarayıcıda duyulur. Gerçek Chromium + gerçek WebRTC (Opus/DTLS) + sahte mikrofon dosyası;
// STT/LLM/TTS sahtedir (model gerektirmez). Gerçek mikrofon + gerçek modeller Mac'te elle doğrulanır.
// Fixture'da realtime profil (RT) da hazır sayıldığı için varsayılan profil açıkça V1'e sabitlenir; RT testi kendisi seçer.
test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("sva.profile", "V1"));
});

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

// core-011: realtime profil (sahte sağlayıcı, ağ yok) gerçek Chromium + WebRTC ile. Hibrit yöntem: ajan açılış metnini seslendirir,
// sahte mikrofon konuşması fonksiyon çağrısı olarak bildirilir, akış motoru sonraki adıma geçer, ajan sesi tarayıcıda duyulur.
test("Realtime profil (hibrit): senaryo başlar, cevap fonksiyon çağrısıyla bildirilir, akış ilerler, ajan sesi duyulur, gecikme uçtan uca", async ({ page, request }) => {
  await page.addInitScript(() => localStorage.setItem("sva.profile", "RT"));
  await page.goto("/playground");
  await expect(page.getByLabel("Senaryo")).toHaveValue("anket");
  await page.getByLabel("Senaryo").selectOption("welcome");
  await page.getByRole("button", { name: "Başlat" }).click();
  await expect(page.getByRole("button", { name: "Durdur" })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId("voice-lines")).toContainText("Ahmet Yılmaz", { timeout: 15_000 });
  await expect(page.getByTestId("voice-answers")).toContainText("Evet", { timeout: 30_000 });
  await expect(page.getByTestId("active-node")).not.toContainText("Aranan kişi teyidi", { timeout: 30_000 });
  await expect(page.getByTestId("realtime-note")).toContainText("ayrı STT / LLM / TTS süresi yoktur", { timeout: 30_000 });
  const stats = await page.evaluate(() => (window as unknown as { __voiceStats?: { remotePeak: number } }).__voiceStats);
  expect(stats?.remotePeak ?? 0).toBeGreaterThan(0.02);                       // ajan sesi tarayıcıya ulaştı
  const sessions = await (await request.get("/api/voice/sessions")).json();
  expect(sessions[0].stats.realtime).toBe("fake_realtime");
  expect(sessions[0].stats.tool_calls).toBeGreaterThanOrEqual(1);
  await page.screenshot({ path: "e2e-artifacts/core-011-realtime-playground.png", fullPage: true });
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

// core-013: ses kaydı. Varsayılan kapalıdır; açılınca konuşma stereo WAV olarak saklanır (sol müşteri, sağ ajan),
// Durdur sonrası oynatıcı çıkar, dosya sunucudan inebilir ve silinebilir. Gerçek Chromium + gerçek WebRTC + sahte mikrofon.
test("Ses kaydı: kapalı gelir, açılınca stereo WAV (sol müşteri, sağ ajan) kaydedilir, oynatılır ve silinir", async ({ page, request }) => {
  await request.post("/api/profiles/V1/warmup?keep_others=true");
  await expect.poll(async () => (await (await request.get("/api/profiles/V1/warmup")).json()).state, { timeout: 10_000 }).not.toBe("running");
  await page.goto("/playground");
  await page.getByLabel("Senaryo").selectOption("");
  await expect(page.getByTestId("record-toggle")).not.toBeChecked();
  await page.getByTestId("record-toggle").check();
  await page.getByRole("button", { name: "Başlat" }).click();
  await expect(page.getByTestId("voice-lines")).toContainText("Siz: ses geldi", { timeout: 30_000 });
  await expect(page.getByTestId("voice-lines")).toContainText("Anladım", { timeout: 30_000 });
  await page.getByRole("button", { name: "Durdur" }).click();

  const box = page.getByTestId("recording-box");
  await expect(box).toBeVisible({ timeout: 15_000 });
  const src = await page.getByTestId("recording-audio").getAttribute("src");
  expect(src).toMatch(/^\/api\/voice\/recordings\/[0-9a-f]{12}\.wav$/);
  const res = await request.get(src!);
  expect(res.status()).toBe(200);
  const wav = await res.body();
  expect(wav.subarray(0, 4).toString()).toBe("RIFF");
  expect(wav.readUInt16LE(22)).toBe(2);        // stereo
  expect(wav.readUInt32LE(24)).toBe(16000);
  let left = 0, right = 0;                       // iki kanalda da gerçek ses var (müşteri mikrofonu + ajan)
  for (let i = 44; i + 3 < wav.length; i += 4) {
    left = Math.max(left, Math.abs(wav.readInt16LE(i)));
    right = Math.max(right, Math.abs(wav.readInt16LE(i + 2)));
  }
  expect(left).toBeGreaterThan(500);
  expect(right).toBeGreaterThan(500);

  await box.getByRole("button", { name: "Kaydı sil" }).click();
  await expect(box).toBeHidden();
  expect((await request.get(src!)).status()).toBe(404);
});
