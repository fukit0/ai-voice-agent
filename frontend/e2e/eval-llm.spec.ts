import { expect, test } from "@playwright/test";

// eval-llm: LLM testi ekranı gerçek backend + gerçek SPA ile açılır; veri seti 30 örnek, modeller profillerden gelir.
// Gerçek modellerle koşu Mac'te yapılır (bulutta Ollama yok): burada yalnızca ekran ve uç noktalar doğrulanır.
test("LLM testi ekranı profillerdeki LLM'leri listeler ve veri seti 30 örnektir", async ({ page, request }) => {
  const samples = await (await request.get("/api/eval/llm/samples")).json();
  expect(samples.samples).toHaveLength(30);
  expect(Object.keys(samples.nodes)).toEqual(["memnuniyet", "ilan_verdi_mi", "kanal", "satis_fiyati"]);

  await page.goto("/llm");
  await expect(page.getByRole("heading", { level: 2, name: "LLM testi" })).toBeVisible();
  await expect(page.getByRole("checkbox", { name: /qwen3:30b/ })).toBeVisible();
  await expect(page.getByRole("checkbox", { name: /claude-haiku-5-5/ })).toBeDisabled(); // anahtar yok
  await expect(page.getByRole("button", { name: "30 örnekle çalıştır" })).toBeDisabled(); // soğuk: hiçbiri seçili değil
  await page.screenshot({ path: "e2e-artifacts/eval-llm-page.png", fullPage: true });
});

test("soğuk model ölçülmez: API 'cold' döner, 0% sahte sonuç üretmez", async ({ request }) => {
  const res = await request.post("/api/eval/llm/run", { data: { profiles: ["L2"], limit: 3 } });
  expect(res.ok()).toBeTruthy();
  const run = await res.json();
  expect(run.results[0].status).not.toBe("ok");
  expect(run.results[0].rows).toBeUndefined();
});
