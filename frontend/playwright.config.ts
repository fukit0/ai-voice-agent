import { defineConfig } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

// E2E: build edilmiş arayüzü FastAPI tek süreçte sunarken test eder.
// Önce: npm run build. Tarayıcı: npx playwright install chromium (veya PW_CHROMIUM yolu).
// İki sunucu: 8765 gerçek profiller (smoke/norm/eval), 8766 sahte sağlayıcılı profil (core-001 ses hattı).
const port = Number(process.env.LAB_PORT ?? 8765);
const voicePort = port + 1;
const py = process.env.LAB_PYTHON ?? ".venv/bin/python";

// Chromium'un sahte mikrofonu: 48 kHz mono WAV; 1 sn sessizlik + 2 sn konuşma benzeri sinyal + 6 sn sessizlik, döngüde.
function fakeMicWav(): string {
  const rate = 48000;
  const n = rate * 9;
  const pcm = Buffer.alloc(n * 2);
  let seed = 7;
  for (let i = rate; i < rate * 3; i++) {
    seed = (seed * 1103515245 + 12345) & 0x7fffffff;
    const noise = (seed / 0x7fffffff - 0.5) * 0.4;
    const tone = 0.35 * Math.sin((2 * Math.PI * 180 * i) / rate) * (0.6 + 0.4 * Math.sin((2 * Math.PI * 4 * i) / rate));
    pcm.writeInt16LE(Math.round((tone + noise) * 32767), i * 2);
  }
  const h = Buffer.alloc(44);
  h.write("RIFF", 0); h.writeUInt32LE(36 + pcm.length, 4); h.write("WAVEfmt ", 8);
  h.writeUInt32LE(16, 16); h.writeUInt16LE(1, 20); h.writeUInt16LE(1, 22); h.writeUInt32LE(rate, 24);
  h.writeUInt32LE(rate * 2, 28); h.writeUInt16LE(2, 32); h.writeUInt16LE(16, 34); h.write("data", 36); h.writeUInt32LE(pcm.length, 40);
  const dir = join(process.cwd(), "e2e-artifacts");
  mkdirSync(dir, { recursive: true });
  const file = join(dir, "fake-mic.wav");
  writeFileSync(file, Buffer.concat([h, pcm]));
  return file;
}

const executablePath = process.env.PW_CHROMIUM || undefined;
export default defineConfig({
  testDir: "./e2e",
  projects: [
    {
      name: "lab",
      testIgnore: /voice-.*\.spec\.ts/,
      use: { baseURL: `http://127.0.0.1:${port}`, launchOptions: { executablePath } },
    },
    {
      name: "voice",
      testMatch: /voice-.*\.spec\.ts/,
      use: {
        baseURL: `http://127.0.0.1:${voicePort}`,
        permissions: ["microphone"],
        launchOptions: {
          executablePath,
          args: [
            "--use-fake-ui-for-media-stream",
            "--use-fake-device-for-media-stream",
            `--use-file-for-fake-audio-capture=${fakeMicWav()}`,
            "--autoplay-policy=no-user-gesture-required",
          ],
        },
      },
    },
  ],
  webServer: [
    {
      command: `cd .. && ${py} -m uvicorn backend.app.main:app --port ${port}`,
      url: `http://127.0.0.1:${port}/api/health`,
      reuseExistingServer: false,
      timeout: 30_000,
    },
    {
      command: `cd .. && SVA_FAKE_PROVIDERS=1 SVA_PROFILES=frontend/e2e/fixtures/voice-profiles.yaml SVA_DATA_DIR=/tmp/sva-voice-e2e ${py} -m uvicorn backend.app.main:app --port ${voicePort}`,
      url: `http://127.0.0.1:${voicePort}/api/health`,
      reuseExistingServer: false,
      timeout: 30_000,
    },
  ],
});
