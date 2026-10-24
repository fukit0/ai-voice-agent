import { expect, test } from "@playwright/test";

// lab-003 / Senaryolar: gerçek backend + SPA. Demo firmasının örnek anket senaryosu (33 adım) yüklenir,
// metin düzenlenip kaydedilir, okunuş normalize edilir, akış bağlantısı adıma geçer, orijinale dönülür.
test("Senaryolar: örnek anket yüklenir, metin düzenlenir ve geri alınır, akış gezilir", async ({ page, request }) => {
  await page.goto("/scenarios");
  await expect(page.getByRole("heading", { level: 2, name: "Senaryolar" })).toBeVisible();
  const nav = page.getByRole("navigation", { name: "Adımlar" });
  await expect(nav.getByRole("button")).toHaveCount(33);
  await expect(page.getByRole("heading", { level: 3, name: "Giriş ve KVKK aydınlatma" })).toBeVisible();
  await expect(page.getByTestId("scenario-spoken")).toContainText("benim adım Elif");

  // akış: "Hayır, dinlemek istemedi" -> Müsaitlik
  await page.getByTestId("scenario-flow").getByRole("button", { name: "Müsaitlik" }).click();
  await expect(page.getByRole("heading", { level: 3, name: "Müsaitlik" })).toBeVisible();

  const box = page.getByRole("textbox");
  await box.fill("Şimdi {MT_HITAP} ile görüşmeniz için 3 dakikanız var mı?");
  await expect(page.getByTestId("scenario-spoken")).toContainText("Mehmet Bey ile görüşmeniz için üç dakikanız var mı?");
  await page.getByRole("button", { name: "Kaydet" }).click();
  await expect(page.getByText("Kaydedildi")).toBeVisible();
  const doc = await (await request.get("/api/scenarios/anket")).json();
  expect(doc.steps.find((s: { key: string }) => s.key === "musaitlik").edited).toBe(true);
  await page.screenshot({ path: "e2e-artifacts/lab-003-scenarios.png", fullPage: true });

  await page.getByRole("button", { name: "Orijinal metne dön" }).click();
  await expect(page.getByText("Orijinal metne dönüldü")).toBeVisible();
  await expect(box).toHaveValue("Görüşme yapmak için müsait misiniz?");
});
