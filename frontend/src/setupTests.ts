import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// vitest globals kapalı olduğu için Testing Library otomatik temizlemez; her testten sonra DOM'u sıfırla.
afterEach(() => cleanup());

// Bazı Node sürümleri/ayarları (ör. NODE_OPTIONS'ta boş --localstorage-file) jsdom'un localStorage'ını bozar:
// getItem bir fonksiyon olmaz. Testler ortama bağlı kalmasın diye bellek içi bir Storage koyarız.
if (typeof globalThis.localStorage?.getItem !== "function") {
  const store = new Map<string, string>();
  const memory: Storage = {
    get length() {
      return store.size;
    },
    clear: () => store.clear(),
    getItem: (k) => (store.has(k) ? (store.get(k) as string) : null),
    key: (i) => Array.from(store.keys())[i] ?? null,
    removeItem: (k) => void store.delete(k),
    setItem: (k, v) => void store.set(k, String(v)),
  };
  Object.defineProperty(globalThis, "localStorage", { value: memory, configurable: true });
}
