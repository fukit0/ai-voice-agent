import { expect, test } from "@playwright/test";

const SCREENS = ["Genel Bakış", "Playground", "Aramalar", "Kıyas matrisi", "Senaryolar", "Persona", "Ayarlar", "TTS stüdyosu", "STT test", "LLM testi"];

test("Lab açılır, backend bağlı ve on ekran arasında gezinilir", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Voice Agent Lab" })).toBeVisible();
  await expect(page.getByTestId("backend-status")).toHaveText(/Backend bağlı/);

  const nav = page.getByRole("navigation", { name: "Lab ekranları" });
  for (const name of SCREENS) {
    await nav.getByRole("link", { name }).click();
    await expect(page.getByRole("heading", { level: 2, name })).toBeVisible();
  }
  await page.screenshot({ path: process.env.E2E_SCREENSHOT ?? "e2e-artifacts/lab-home.png", fullPage: true });
});
