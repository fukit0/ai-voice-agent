/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Geliştirmede /api çağrıları FastAPI'ye (8000) gider; build çıktısını FastAPI tek süreçte sunar.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/api": "http://127.0.0.1:8000" } },
  test: { environment: "jsdom", setupFiles: ["./src/setupTests.ts"], include: ["src/**/*.test.{ts,tsx}"] },
});
