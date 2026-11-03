import { expect, it } from "vitest";
import { FREE_REPLY_REASONS, freeReplyReason } from "./callsApi";

// off-003 (docs/serbest-cevap-haiku.md): serbest cevabın havuza neden düştüğü Aramalar ekranında okunur olmalı.
it("havuz sebebi arka uç ve kategoriyle okunur", () => {
  expect(freeReplyReason({ reply_source: "pool", free_reply_fallback: "category", free_reply_backend: "qwen", free_reply_category: "topic_change" }))
    .toBe(`${FREE_REPLY_REASONS.category} [qwen, topic_change]`);
  expect(freeReplyReason({ reply_source: "pool", free_reply_fallback: "audit", free_reply_backend: "haiku", free_reply_category: "weather",
    free_reply_fails: ["realworld_claim"] })).toBe("denetimden geçmedi: realworld_claim [haiku, weather]");
});

it("LLM konuştuysa sebep yok; eski kayıtta arka uç qwen sayılır; bilinmeyen sebep aynen yazılır", () => {
  expect(freeReplyReason({ reply_source: "haiku" })).toBeNull();
  expect(freeReplyReason({ reply_source: "pool", free_reply_fallback: "no_key" })).toBe("ANTHROPIC_API_KEY yok [qwen (eski kayıt)]");
  expect(freeReplyReason({ reply_source: "pool", free_reply_fallback: "yeni_sebep", free_reply_backend: "haiku" })).toBe("yeni_sebep [haiku]");
});
