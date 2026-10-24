import { useCallback, useEffect, useState } from "react";
import {
  fetchEvalModels, fetchEvalRun, fetchEvalRuns, getWarmup, runLlmEval, startWarmup,
  type EvalModel, type EvalResult, type EvalRun, type EvalRunSummary,
} from "../api";

const modelKey = (m: { provider: string; model: string }) => `${m.provider}:${m.model}`;
const pct = (v: number | null | undefined) => (v == null ? "—" : `${(v * 100).toFixed(0)}%`);
const sec = (v: number | null | undefined) => (v == null ? "—" : `${v.toFixed(2)} sn`);
const GATE = 0.9; // Faz 1 kapısı: cevapların >= %90'ı doğru
const show = (v: unknown) => (v === null || v === undefined ? "—" : JSON.stringify(v));

// LLM fonksiyon çağrısı testi (eval-llm): 30 örnek cevap seçili LLM'lerden geçer; doğru normalize ve doğru dal
// oranı, JSON geçerliliği ve gecikme yan yana görünür. Soğuk model ölçülmez, önce Hazırla (ADR 0001).
export function LlmEvalPage() {
  const [models, setModels] = useState<EvalModel[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [quick, setQuick] = useState(false);
  const [run, setRun] = useState<EvalRun | null>(null);
  const [runs, setRuns] = useState<EvalRunSummary[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [preparing, setPreparing] = useState<Record<string, boolean>>({});

  const loadModels = useCallback(async () => {
    try {
      const list = await fetchEvalModels();
      setModels(list);
      setSelected((prev) => (prev.size ? prev : new Set(list.filter((m) => m.warm && m.ready).map(modelKey))));
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);
  const loadRuns = useCallback(() => fetchEvalRuns().then(setRuns).catch(() => {}), []);
  useEffect(() => {
    void loadModels();
    void loadRuns();
  }, [loadModels, loadRuns]);

  async function prepare(m: EvalModel) {
    const key = modelKey(m);
    setPreparing((p) => ({ ...p, [key]: true }));
    setError(null);
    try {
      let job = await startWarmup(m.profile, true, "llm"); // yalnızca bu LLM; diğer sıcak modeller bellekte kalır
      while (job.state === "running") {
        await new Promise((r) => setTimeout(r, 1000));
        job = await getWarmup(m.profile);
      }
      if (job.state === "failed") setError(job.error ?? `${m.model} hazırlanamadı.`);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setPreparing((p) => ({ ...p, [key]: false }));
      await loadModels();
    }
  }

  async function execute() {
    setBusy(true);
    setError(null);
    try {
      const profiles = models.filter((m) => selected.has(modelKey(m))).map((m) => m.profile);
      setRun(await runLlmEval(profiles, quick ? 5 : undefined));
      void loadRuns();
      void loadModels();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function open(id: string) {
    setError(null);
    try {
      setRun(await fetchEvalRun(id));
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <section className="screen" data-testid="llm-page">
      <h2>LLM testi</h2>
      <p className="meta">
        eval-llm · plan Faz 0 adım 4 · Müşteri cevabını yapılandırma testi: LLM her cevaptan {"{intent, value}"} JSON'u
        çıkarır; değer beklenenle ve flow motorunun seçeceği dal beklenenle karşılaştırılır. Kesin doğrulama: "9" metni sayı sayılmaz.
      </p>

      <h3 className="sub">1 · Modeller</h3>
      <ul className="stt-models">
        {models.map((m) => {
          const key = modelKey(m);
          const state = !m.ready ? `Anahtar eksik: ${m.missing_env.join(", ")}` : m.warm ? "Sıcak" : "Soğuk";
          return (
            <li key={key}>
              <label>
                <input type="checkbox" checked={selected.has(key)} disabled={!m.ready}
                  onChange={(e) => setSelected((s) => { const n = new Set(s); if (e.target.checked) n.add(key); else n.delete(key); return n; })} />
                <b>{m.model || m.provider}</b> <span className="meta">{m.provider} · {m.profiles.join(", ")}</span>
              </label>
              <span className={`chip ${m.warm ? "chip-ok" : preparing[key] ? "chip-busy" : "chip-cold"}`}>
                {preparing[key] ? "Hazırlanıyor…" : state}
              </span>
              {m.ready && !m.warm && (
                <button type="button" disabled={!!preparing[key]} onClick={() => prepare(m)}>Hazırla</button>
              )}
            </li>
          );
        })}
      </ul>

      <p>
        <label><input type="checkbox" checked={quick} onChange={(e) => setQuick(e.target.checked)} /> Hızlı deneme (yalnızca ilk 5 örnek)</label>
      </p>
      <p>
        <button type="button" className="primary" disabled={busy || selected.size === 0} onClick={execute}>
          {busy ? "Çalışıyor…" : quick ? "5 örnekle çalıştır" : "30 örnekle çalıştır"}
        </button>
      </p>
      {error && <p className="status status-error" role="alert">{error}</p>}

      {run && <EvalResults run={run} />}

      <h3 className="sub">Kayıtlı koşular</h3>
      {runs.length === 0 ? <p className="meta">Henüz koşu yok.</p> : (
        <ul className="stt-runs">
          {runs.map((r) => (
            <li key={r.id}>
              <button type="button" onClick={() => open(r.id)}>Aç</button>{" "}
              <span>{new Date(r.created_at).toLocaleString("tr-TR")}</span> · {r.n_samples} örnek · {r.models.join(", ")} ·
              en iyi tam doğru {pct(r.best_full_rate)}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function EvalResults({ run }: { run: EvalRun }) {
  const ok = run.results.filter((r) => r.status === "ok" && r.summary);
  return (
    <div data-testid="llm-results">
      <h3 className="sub">Sonuç · {run.n_samples} örnek</h3>
      {ok.length > 0 && (
        <table className="eval-table">
          <thead>
            <tr><th>Model</th><th>JSON geçerli</th><th>Doğru normalize</th><th>Doğru dal</th><th>Tam doğru</th><th>p50</th><th>p95</th></tr>
          </thead>
          <tbody>
            {ok.map((r) => {
              const s = r.summary!;
              const pass = (s.full_rate ?? 0) >= GATE;
              return (
                <tr key={modelKey(r)}>
                  <td><b>{r.model}</b><br /><span className="meta">{r.profile}</span></td>
                  <td>{pct(s.json_valid_rate)}</td>
                  <td data-testid="normalize-rate">{pct(s.normalize_rate)}</td>
                  <td data-testid="branch-rate">{pct(s.branch_rate)}</td>
                  <td><span className={`chip ${pass ? "chip-ok" : "chip-cold"}`} data-testid="full-rate">{pct(s.full_rate)}</span></td>
                  <td>{sec(s.latency_p50)}</td>
                  <td>{sec(s.latency_p95)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      <p className="meta">Yeşil = tam doğru oranı ≥ %{GATE * 100} (Faz 1 kapısı: cevapların ≥ %90'ı doğru). Normalize oranı yalnızca cevap örneklerinde ({ok[0]?.summary?.n_answers ?? "—"}), diğerleri tüm örneklerde hesaplanır.</p>
      {run.results.map((r) => <ModelDetail key={modelKey(r)} r={r} />)}
    </div>
  );
}

function ModelDetail({ r }: { r: EvalResult }) {
  if (r.status !== "ok" || !r.rows || !r.summary) {
    return <p className="warn">{r.model || r.provider}: {r.status === "cold" ? "Soğuk, ölçülmedi. " : ""}{r.error}</p>;
  }
  const wrong = r.rows.filter((x) => !x.full_ok);
  return (
    <details className="eval-detail">
      <summary>{r.model} · {wrong.length} hatalı örnek · tür bazında: {Object.entries(r.summary.by_type).map(([k, v]) => `${k} ${pct(v.full_rate)}`).join(", ")}</summary>
      {wrong.length === 0 ? <p className="meta">Tüm örnekler doğru.</p> : (
        <table className="eval-table">
          <thead><tr><th>#</th><th>Müşteri</th><th>Beklenen</th><th>Model</th><th>Sorun</th></tr></thead>
          <tbody>
            {wrong.map((x) => (
              <tr key={x.id}>
                <td>{x.id}</td><td>{x.utterance}</td>
                <td>{x.expected.intent} · {show(x.expected.value)} → {x.expected.branch}</td>
                <td>{x.parsed ? `${x.parsed.intent} · ${show(x.parsed.value)}` : <code>{x.raw.slice(0, 60) || "(boş)"}</code>} → {x.got_branch ?? "—"}</td>
                <td>{x.problem ?? (x.value_ok ? "dal/intent farklı" : "değer farklı")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </details>
  );
}
