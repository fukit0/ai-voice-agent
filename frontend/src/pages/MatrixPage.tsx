import { useCallback, useEffect, useRef, useState } from "react";
import { fetchDecisionReport, fetchMatrix, saveDecision } from "../matrixApi";
import type { CriterionId, DecisionStatus, Matrix, MatrixRow, Metric, Weights } from "../matrixApi";

/** Kıyas matrisi (lab-005, plan F7.5). Puanlar ve toplam backend'de hesaplanır (GET /api/matrix) — tek doğruluk kaynağı.
 *  Ekran: ağırlık kaydırıcıları → yeniden hesap (kısa gecikmeli); "Yenile" ve pencereye dönüş → yeni koşu/arama/puan görünür.
 *  Veri olmayan kriter "ölçülmedi" gösterilir, sayı uydurulmaz; profilde bileşen yoksa "uygulanamaz" (ağırlık paydasından çıkar). */

const STORE = "sva.matrix.weights";
const IDS: CriterionId[] = ["latency", "naturalness", "accuracy", "wer", "resources"];
const tr = (v: number, d = 1) => v.toFixed(d).replace(".", ",");

function loadWeights(): Weights | undefined {
  try {
    const raw = JSON.parse(localStorage.getItem(STORE) ?? "null");
    if (raw && IDS.every((k) => typeof raw[k] === "number" && raw[k] >= 0)) return raw;
  } catch { /* tarayıcı depolaması yok */ }
  return undefined;
}

function show(id: CriterionId, m: Metric) {
  if (id === "latency") return `${tr(m.value, 2)} sn`;
  if (id === "naturalness") return `${tr(m.value, 2)}/5`;
  if (id === "wer") return `WER %${tr(m.value * 100)}`;
  if (id === "resources") return `$${tr(m.value, 3)}/arama`;
  return `%${tr(m.value * 100, 0)} doğru`;
}

function Cell({ id, m, na }: { id: CriterionId; m: MatrixRow["metrics"][CriterionId]; na?: string }) {
  if (!m && na) return <td className="num mx-na" title={na}>uygulanamaz</td>;
  if (!m) return <td className="num mx-missing" title="Bileşen var ama bu profil için kayıt yok">ölçülmedi</td>;
  return (
    <td className="num">
      <strong>{tr(m.score, 0)}</strong> <span className="meta">{show(id, m)}</span>
      {m.n !== null && <span className="meta mx-n"> · n={m.n}</span>}
      {m.note && <span className="pill warn mx-note">{m.note}</span>}
    </td>
  );
}

function License({ r }: { r: MatrixRow }) {
  if (r.eliminated) {
    const bad = r.license.filter((l) => l.commercial_ok === false).map((l) => l.model).join(", ");
    return <span className="pill err" title={bad}>Elendi · ticari kullanım yok</span>;
  }
  if (r.license_unknown.length) return <span className="pill warn" title={r.license_unknown.join(", ")}>Lisans belirsiz</span>;
  const verified = r.license.every((l) => l.verified);
  return <span className={`pill ${verified ? "ok" : ""}`}>{verified ? "Ticari OK" : "Ticari OK · doğrulanmadı"}</span>;
}

const STATUS_LABEL: Record<DecisionStatus, string> = { aday: "Aday", secildi: "Seçildi", elendi: "Elendi" };

function DecisionRow({ r, onSaved }: { r: MatrixRow; onSaved: () => void }) {
  const d = r.decision ?? { status: "aday" as DecisionStatus, reason: "", decided_at: null, snapshot: null };
  const [status, setStatus] = useState<DecisionStatus>(d.status);
  const [reason, setReason] = useState(d.reason);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { setStatus(d.status); setReason(d.reason); }, [d.status, d.reason]);
  const dirty = status !== d.status || reason.trim() !== d.reason;
  const save = async () => {
    setBusy(true); setErr(null);
    try { await saveDecision(r.profile, status, reason); onSaved(); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  return (
    <div className="mx-decision" data-testid={`decision-${r.profile}`}>
      <strong>{r.profile}</strong> <span className="meta">{r.name}</span>
      <select value={status} onChange={(e) => setStatus(e.target.value as DecisionStatus)} aria-label={`${r.profile} kararı`}>
        {(Object.keys(STATUS_LABEL) as DecisionStatus[]).map((k) => <option key={k} value={k}>{STATUS_LABEL[k]}</option>)}
      </select>
      <textarea value={reason} rows={2} placeholder={status === "aday" ? "Karar yok" : "Neden? (gerekçe zorunlu, demoda profil bazında anlatılır)"}
        onChange={(e) => setReason(e.target.value)} aria-label={`${r.profile} gerekçesi`} disabled={status === "aday"} />
      <button type="button" onClick={save} disabled={!dirty || busy} aria-label={`${r.profile} kararını kaydet`}>Kaydet</button>
      {d.decided_at && <span className="meta">{d.decided_at.slice(0, 16).replace("T", " ")} UTC{d.snapshot ? ` · o günkü toplam ${d.snapshot.total === null ? "—" : tr(d.snapshot.total)}` : ""}</span>}
      {err && <p className="note err" role="alert">{err}</p>}
    </div>
  );
}

function DecisionPanel({ rows, onSaved }: { rows: MatrixRow[]; onSaved: () => void }) {
  const [report, setReport] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const show = async () => { try { setReport(await fetchDecisionReport()); setErr(null); } catch (e) { setErr((e as Error).message); } };
  return (
    <div className="panel" aria-labelledby="mx-d">
      <h3 id="mx-d">Profil kararları</h3>
      <p className="meta">Kıyas koşusundan sonra her profil için Seçildi / Elendi kararı ve gerekçesi buraya yazılır; karar anındaki toplam puan da kaydedilir. Demoda profil bazında anlatılır.</p>
      {rows.map((r) => <DecisionRow key={r.profile} r={r} onSaved={onSaved} />)}
      <button type="button" onClick={show}>Demo özetini göster</button>
      {err && <p className="note err" role="alert">{err}</p>}
      {report && <pre className="mx-report" data-testid="decision-report">{report}</pre>}
    </div>
  );
}

export function MatrixPage() {
  const [weights, setWeights] = useState<Weights | undefined>(loadWeights);
  const [data, setData] = useState<Matrix | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const seq = useRef(0);

  const load = useCallback((w: Weights | undefined) => {
    const mine = ++seq.current;                       // eski yanıt yenisinin üstüne yazmasın
    setLoading(true);
    fetchMatrix(w).then((m) => {
      if (mine !== seq.current) return;
      setData(m); setError(null);
    }).catch((e: Error) => { if (mine === seq.current) setError(e.message); })
      .finally(() => { if (mine === seq.current) setLoading(false); });
  }, []);

  useEffect(() => {                                    // ağırlık değişince kısa gecikmeyle yeniden hesapla
    const t = setTimeout(() => load(weights), data ? 250 : 0);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [weights, load]);

  useEffect(() => {                                    // başka ekranda koşu yapıp dönünce güncel olsun
    const refresh = () => load(weights);
    window.addEventListener("focus", refresh);
    return () => window.removeEventListener("focus", refresh);
  }, [weights, load]);

  const current: Weights | undefined = weights ?? data?.weights;
  const setW = (id: CriterionId, v: number) => {
    const next = { ...(current as Weights), [id]: v };
    setWeights(next);
    try { localStorage.setItem(STORE, JSON.stringify(next)); } catch { /* depolama yok */ }
  };
  const reset = () => {
    setWeights(undefined);
    try { localStorage.removeItem(STORE); } catch { /* depolama yok */ }
  };
  const sum = current ? IDS.reduce((a, k) => a + current[k], 0) : 0;
  const anyData = data?.rows.some((r) => IDS.some((k) => r.metrics[k]));
  const ordered = data ? [...data.rows].sort((a, b) => (a.rank ?? 1e9) - (b.rank ?? 1e9) || a.profile.localeCompare(b.profile)) : [];

  return (
    <section className="page matrix">
      <div className="page-head">
        <div>
          <span className="eyebrow">Kayıtlar &amp; Raporlar</span>
          <h2>Kıyas matrisi</h2>
          <p className="meta">Profiller; gecikme, doğallık, doğruluk ve STT hatasına göre ağırlıklı puanlanır. Değerler Lab kayıtlarından otomatik dolar.</p>
        </div>
        <div className="head-actions">
          <button type="button" className="primary" onClick={() => load(weights)} disabled={loading}>{loading ? "Yenileniyor…" : "Yenile"}</button>
        </div>
      </div>

      {error && <p className="note err" role="alert">Matris alınamadı: {error}</p>}

      <div className="panel" aria-labelledby="mx-w">
        <h3 id="mx-w">Ağırlıklar</h3>
        <p className="meta">Kaydırınca puanlar yeniden hesaplanır. Toplam her zaman %100'e normalize edilir.</p>
        <div className="mx-weights">
          {(data?.criteria ?? []).map((c) => (
            <label key={c.id} className="mx-weight" title={`${c.source} · ${c.rule}`}>
              <span>{c.label}</span>
              <input type="range" min={0} max={100} step={5} value={current?.[c.id] ?? 0} aria-label={`${c.label} ağırlığı`}
                onChange={(e) => setW(c.id, Number(e.target.value))} />
              <output>{sum > 0 && current ? `%${tr(current[c.id] / sum * 100, 0)}` : "—"}</output>
            </label>
          ))}
        </div>
        <button type="button" onClick={reset}>Varsayılana dön</button>
      </div>

      {data && !anyData && (
        <div className="empty" data-testid="matrix-empty">
          <strong>Henüz ölçüm yok</strong>
          Profiller için arama yapın, STT/LLM testi koşun ya da TTS dinleme puanı verin; sonuçlar burada otomatik görünür.
        </div>
      )}

      {data && (
        <div className="panel">
          <div className="table-wrap mx-table-wrap">
            <table className="data-table mx-table" data-testid="matrix-table">
              <thead>
                <tr>
                  <th>#</th><th>Profil</th>
                  {data.criteria.map((c) => <th key={c.id} title={c.rule}>{c.label}</th>)}
                  <th>Kapsam</th><th>Toplam</th><th>Lisans</th>
                </tr>
              </thead>
              <tbody>
                {ordered.map((r) => (
                  <tr key={r.profile} className={r.eliminated ? "mx-out" : ""} data-testid={`row-${r.profile}`}>
                    <td className="num">{r.rank ?? "—"}</td>
                    <td><strong>{r.profile}</strong> <span className="meta">{r.name}</span>
                      <div className="meta">{r.components.map((c) => `${c.kind}: ${(c.model || c.provider).split("/").pop()}`).join(" · ")}</div></td>
                    {IDS.map((id) => <Cell key={id} id={id} m={r.metrics[id]} na={r.not_applicable?.[id]} />)}
                    <td className="num" title={`Eksik: ${r.missing.join(", ") || "yok"}`}>%{tr(r.coverage * 100, 0)}</td>
                    <td className="num mx-total">{r.total === null
                      ? <span className="meta" title={`Kapsam en az %${tr(data.min_coverage * 100, 0)} olmalı`}>{r.eliminated ? "elendi" : "yetersiz veri"}</span>
                      : <strong>{tr(r.total)}</strong>}</td>
                    <td><License r={r} />{r.decision && r.decision.status !== "aday" && (
                      <div><span className={`pill ${r.decision.status === "elendi" ? "err" : "ok"}`} title={r.decision.reason}>{STATUS_LABEL[r.decision.status]}</span></div>)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <ul className="note-list">
            {data.notes.map((n) => <li key={n} className="meta">{n}</li>)}
            <li className="meta">Güncelleme: {data.generated_at.slice(11, 19)} UTC · sıralama için kapsam en az %{tr(data.min_coverage * 100, 0)} olmalı.</li>
          </ul>
        </div>
      )}

      {data && <DecisionPanel rows={ordered} onSaved={() => load(weights)} />}
    </section>
  );
}
