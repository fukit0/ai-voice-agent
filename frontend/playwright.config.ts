import { defineConfig } from "@playwright/test";

// E2E: build edilmiş arayüzü FastAPI tek süreçte sunarken test eder.
// Önce: npm run build. Tarayıcı: npx playwright install chromium (veya PW_CHROMIUM yolu).
const port = Number(process.env.LAB_PORT ?? 8765);
export default defineConfig({
  testDir: "./e2e",
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    launchOptions: process.env.PW_CHROMIUM ? { executablePath: process.env.PW_CHROMIUM } : {},
  },
  webServer: {
    command: `cd .. && ${process.env.LAB_PYTHON ?? ".venv/bin/python"} -m uvicorn backend.app.main:app --port ${port}`,
    url: `http://127.0.0.1:${port}/api/health`,
    reuseExistingServer: false,
    timeout: 30_000,
  },
});
