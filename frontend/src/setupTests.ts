import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// vitest globals kapalı olduğu için Testing Library otomatik temizlemez; her testten sonra DOM'u sıfırla.
afterEach(() => cleanup());
