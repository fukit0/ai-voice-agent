import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LlmEvalPage } from "./LlmEvalPage";

const MODELS = [
  { profile: "L2", profiles: ["L2"], provider: "ollama", model: "qwen3:30b", ready: true, warm: true, missing_env: [] },
  { profile: "L4", profiles: ["L4"], provider: "ollama", model: "gpt-oss:20b", ready: true, warm: false, missing_env: [] },
  { profile: "A1", profiles: ["A1"], provider: "anthropic", model: "claude-haiku-5-5", ready: false, warm: false, missing_env: ["ANTHROPIC_API_KEY"] },
];
const SUMMARY = {
  n: 30, n_answers: 24, json_valid_rate: 1, schema_valid_rate: 0.9, intent_rate: 0.97, normalize_rate: 0.875,
  branch_rate: 0.93, full_rate: 0.9, latency_p50: 0.31, latency_p95: 0.8,
  by_type: { rating: { n: 7, full_rate: 0.86, branch_rate: 0.86 }, number: { n: 7, full_rate: 0.71, branch_rate: 0.86 } },
};
const BAD_ROW = {
  id: "s20", node: "satis_fiyati", utterance: "iki buçuk milyon", seconds: 0.4, raw: '{"intent":"answer","value":2000000}',
  expected: { intent: "answer", value: 2500000, branch: "yuksek_fiyat" },
  parsed: { intent: "answer", value: 2000000 }, got_branch: "yuksek_fiyat", problem: null,
  json_valid: true, schema_valid: true, intent_ok: true, value_ok: false, branch_ok: true, full_ok: false,
};
const RUN = {
  id: "20261024-120000-abc123", created_at: "2026-10-24T12:00:00+00:00", n_samples: 30,
  results: [
    { profile: "L2", provider: "ollama", model: "qwen3:30b", status: "ok", summary: SUMMARY, rows: [BAD_ROW] },
    { profile: "L4", provider: "ollama", model: "gpt-oss:20b", status: "cold", error: "L4 profili hazır değil (LLM soğuk)." },
  ],
};

let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => {
  fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === "/api/eval/llm/models") return new Response(JSON.stringify(MODELS));
    if (url === "/api/eval/llm/runs") return new Response(JSON.stringify([{ id: RUN.id, created_at: RUN.created_at, n_samples: 30, models: ["ollama:qwen3:30b"], best_full_rate: 0.9 }]));
    if (url === `/api/eval/llm/runs/${RUN.id}`) return new Response(JSON.stringify(RUN));
    if (url === "/api/eval/llm/run" && init?.method === "POST") return new Response(JSON.stringify(RUN));
    return new Response("", { status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("LLM testi ekranı", () => {
  it("sıcak modeli seçili getirir, anahtarı eksik modeli kilitler", async () => {
    render(<LlmEvalPage />);
    const warm = await screen.findByRole("checkbox", { name: /qwen3:30b/ });
    expect(warm).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /gpt-oss:20b/ })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: /claude-haiku/ })).toBeDisabled();
    expect(screen.getByText(/Anahtar eksik: ANTHROPIC_API_KEY/)).toBeInTheDocument();
  });

  it("seçili profillerle koşuyu başlatır ve oranları, hatalı örneği ve soğuk modeli gösterir", async () => {
    render(<LlmEvalPage />);
    await screen.findByRole("checkbox", { name: /qwen3:30b/ });
    fireEvent.click(screen.getByRole("button", { name: "30 örnekle çalıştır" }));
    const results = await screen.findByTestId("llm-results");
    const call = fetchMock.mock.calls.find((c) => c[0] === "/api/eval/llm/run")!;
    expect(JSON.parse(call[1].body)).toEqual({ profiles: ["L2"] });
    expect(within(results).getByTestId("normalize-rate")).toHaveTextContent("88%");
    expect(within(results).getByTestId("branch-rate")).toHaveTextContent("93%");
    expect(within(results).getByTestId("full-rate")).toHaveTextContent("90%");
    expect(within(results).getByTestId("full-rate")).toHaveClass("chip-ok"); // >= %90 kapısı
    expect(within(results).getByText("iki buçuk milyon")).toBeInTheDocument();
    expect(within(results).getByText(/Soğuk, ölçülmedi/)).toBeInTheDocument();
  });

  it("hızlı deneme yalnızca 5 örnek ister", async () => {
    render(<LlmEvalPage />);
    await screen.findByRole("checkbox", { name: /qwen3:30b/ });
    fireEvent.click(screen.getByRole("checkbox", { name: /Hızlı deneme/ }));
    fireEvent.click(screen.getByRole("button", { name: "5 örnekle çalıştır" }));
    await waitFor(() => expect(fetchMock.mock.calls.some((c) => c[0] === "/api/eval/llm/run")).toBe(true));
    const call = fetchMock.mock.calls.find((c) => c[0] === "/api/eval/llm/run")!;
    expect(JSON.parse(call[1].body)).toEqual({ profiles: ["L2"], limit: 5 });
  });

  it("kayıtlı koşuyu yeniden açar", async () => {
    render(<LlmEvalPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Aç" }));
    expect(await screen.findByTestId("llm-results")).toBeInTheDocument();
  });
});
