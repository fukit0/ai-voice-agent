import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { buildSet, cancelRun, fetchRun, fetchRuns, fetchSet, startRun } from "../benchmarkApi";
import type { PfMode, Run, RunSummary, SetStatus } from "../benchmarkApi";
import { useProfile } from "../ProfileContext";

/** Kıyas koşusu (eval-001, plan F6.1): seçili profil için kayıtlı persona sesleriyle 20 aramalık seti tek tıkla koşturur.
 *  İki aşama: (1) test setini hazırla (müşteri sesleri bir kez üretilip saklanır), (2) koşu. Sonuçlar Aramalar ekranına düşer. */

const POLL_MS = 1500;
const MODES: { id: PfMode; label: string; hint: string }[] = [
  { id: "both", label: "İkisi de", hint: "40 arama: telefon filtresi kapalı + açık" },
  { id: "off", label: "Kapalı", hint: "20 arama" },
  { id: "on", label: "Açık", hint: "20 arama, dar bant telefon sesi" },
];
const OUTCOMES: Record<string, string> = {
  tamamlandi: "Tamamlandı", katilmak_istemedi: "Katılmak istemedi", geri_arama: "Randevu verildi", musait_degil: "Müsait değil",
  son_3_ay_katilim: "Son 3 ayda katılmış", gorusmeyi_hatirlamiyor: "Hatırlamıyor", aranmak_istemiyor: "Aranmak istemiyor",
  sessiz_cagri: "Sessiz çağrı", sistem_sonlandirdi: "Sistem sonlandırdı",
};
const STATUS: Record<string, { label: string; tone: "ok" | "warn" | "err" | "" }> = {
  pending: { label: "Bekliyor", tone: "" }, running: { label: "Koşuyor", tone: "warn" }, ok: { label: "Tamam", tone: "ok" },
  error: { label: "Hata", tone: "err" }, timeout: { label: "Zaman aşımı", tone: "err" }, max_turns: { label: "Döngü", tone: "err" },
  not_finished: { label: "Bitmedi", tone: "warn" },
};
const sec = (v: number | null | undefined) => (v === null || v === undefined ? "—" : `${v.toFixed(2).replace(".", ",")} sn`);

export function BenchmarkPage() {
  const { active } = useProfile();
  const [set, setSet] = useState<SetStatus | null>(null);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [run, setRun] = useState<Run | null>(null);
  const [mode, setMode] = useState<PfMode>("both");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const alive = useRef(true);

  const refresh = useCallback(async () => {
    try {
      const [s, r] = await Promise.all([fetchSet(), fetchRuns()]);
      if (!alive.current) return;
      setSet(s); setRuns(r);
      const current = r.find((x) => x.status === "running") ?? null;
      if (current) setRun(await fetchRun(current.id));
    } catch (e) { if (alive.current) setError((e as Error).message); }
  }, []);

  useEffect(() => { alive.current = true; refresh(); return () => { alive.current = false; }; }, [refresh]);

  const buildRunning = set?.build.state === "running";
  const runRunning = run?.status === "running";
  useEffect(() => {                                  // üretim ya da koşu sürerken ilerlemeyi yokla
    if (!buildRunning && !runRunning) return;
    const t = setInterval(async () => {
      try {
        if (runRunning && run) setRun(await fetchRun(run.id));
        if (buildRunning || runRunning) setSet(await fetchSet());
        if (runRunning) setRuns(await fetchRuns());
      } catch (e) { setError((e as Error).message); }
    }, POLL_MS);
    return () => clearInterval(t);
  }, [buildRunning, runRunning, run]);

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true); setError(null);
    try { await fn(); await refresh(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  const start = () => act(async () => { if (active) setRun(await fetchRun((await startRun(active.id, mode)).run_id)); });
  const calls = run?.calls ?? [];
  const canRun = !!active && !!set?.ready && !runRunning && !busy && active.mode !== "realtime";
  const sessions = calls.filter((c) => c.session_id).length;

  return (
    <section className="page benchmark">
      <div className="page-head">
        <div>
          <span className="eyebrow">Lab araçları</span>
          <h2>Kıyas koşusu</h2>
          <p className="meta">Seçili profil, kayıtlı 5 test müşterisiyle 4 yolu (tam katılım, ret, geri arama, belirsiz cevap) otomatik arar. Sonuçlar Aramalar ekranına düşer.</p>
        </div>
      </div>
      {error && <p className="note err" role="alert">{error}</p>}

      <div className="panel" aria-labelledby="bm-set">
        <h3 id="bm-set">1. Test seti</h3>
        {!set ? <p className="meta">Yükleniyor…</p> : (
          <>
            <p className="meta">Müşteri sesleri ElevenLabs ile bir kez üretilip saklanır; her profil aynı kayıtları dinler. Yeniden hazırlamak var olanları üretmez, ücretsizdir.</p>
            <div className="table-wrap"><table className="data-table" data-testid="persona-table">
              <thead><tr><th>Test müşterisi</th><th>Ses</th><th>Davranış</th><th>Klip</th></tr></thead>
              <tbody>
                {set.personas.map((p) => (
                  <tr key={p.id}>
                    <td><strong>{p.name}</strong><div className="meta">{p.description}</div></td>
                    <td className="num">{p.voice_id ?? <span className="meta">seçilmedi</span>}</td>
                    <td className="meta">hız {p.speed} · {p.gain_db} dB · {p.noise_snr_db === null ? "gürültüsüz" : `SNR ${p.noise_snr_db} dB`} · {p.reaction_s} sn gecikme</td>
                    <td className="num">{p.clips}/{p.clips_needed}</td>
                  </tr>
                ))}
              </tbody>
            </table></div>
            <p>
              <span className={`pill ${set.ready ? "ok" : "warn"}`}>{set.ready ? "Set hazır" : "Set hazır değil"}</span>{" "}
              {buildRunning && <span className="meta" role="status">Üretiliyor: {set.build.done}/{set.build.total}</span>}
              {set.build.state === "error" && <span className="pill err" role="alert">{set.build.error}</span>}
            </p>
            <button type="button" onClick={() => act(buildSet)} disabled={busy || buildRunning}>{set.ready ? "Eksik klipleri kontrol et" : "Test setini hazırla"}</button>
          </>
        )}
      </div>

      <div className="panel" aria-labelledby="bm-run">
        <h3 id="bm-run">2. Koşu</h3>
        <p className="meta">Profil: <strong>{active ? `${active.id} · ${active.name}` : "seçilmedi"}</strong> (üst çubuktan değiştirilir){active && !active.warm && " · soğuk: önce Hazırla"}</p>
        {active?.mode === "realtime" && <p className="note err" role="note">Realtime profiller bu koşucuda henüz desteklenmiyor; kademeli (L1–L5, A1) profil seçin.</p>}
        <div className="seg" role="radiogroup" aria-label="Telefon filtresi">
          {MODES.map((m) => (
            <button key={m.id} type="button" role="radio" aria-checked={mode === m.id} title={m.hint} onClick={() => setMode(m.id)}>Telefon filtresi: {m.label}</button>
          ))}
        </div>
        <p className="meta">{MODES.find((m) => m.id === mode)?.hint}. Süre profile bağlıdır; yerel modellerde 20 arama onlarca dakika sürebilir.</p>
        <button type="button" className="primary" onClick={start} disabled={!canRun}>Test setini koştur</button>{" "}
        {runRunning && run && <button type="button" onClick={() => act(() => cancelRun(run.id))}>Durdur</button>}

        {run && (
          <>
            <p role="status" data-testid="run-progress">
              <span className={`pill ${run.status === "done" ? "ok" : run.status === "running" ? "warn" : "err"}`}>
                {run.status === "running" ? "Koşuyor" : run.status === "done" ? "Bitti" : run.status === "cancelled" ? "Durduruldu" : "Hata"}
              </span>{" "}
              {run.done}/{run.total} arama · {run.profile}{run.error && ` · ${run.error}`}
            </p>
            <div className="table-wrap"><table className="data-table" data-testid="run-table">
              <thead><tr><th>#</th><th>Müşteri</th><th>Yol</th><th>Telefon</th><th>Durum</th><th>Sonuç</th><th>İlk ses p50</th><th>Cevap</th></tr></thead>
              <tbody>
                {calls.map((c) => {
                  const st = STATUS[c.status] ?? { label: c.status, tone: "" as const };
                  return (
                    <tr key={c.index}>
                      <td className="num">{c.index + 1}</td>
                      <td>{set?.personas.find((p) => p.id === c.persona)?.name ?? c.persona}</td>
                      <td>{set?.paths.find((p) => p.id === c.path)?.name ?? c.path}</td>
                      <td>{c.phone_filter ? "Açık" : "Kapalı"}</td>
                      <td><span className={`pill ${st.tone}`} title={c.error}>{st.label}</span></td>
                      <td>{c.outcome ? OUTCOMES[c.outcome] ?? c.outcome : "—"}</td>
                      <td className="num">{sec(c.first_audio_p50_s)}</td>
                      <td className="num">{c.answers === undefined ? "—" : `${c.answers - (c.unanswered ?? 0)}/${c.answers}`}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table></div>
            {sessions > 0 && <p><Link to="/calls">Aramalar'da gör ({sessions} arama)</Link></p>}
          </>
        )}
        {runs.length > 0 && !run && <p className="meta">Önceki koşular: {runs.length} (en son {runs[0].created_at.slice(5, 16).replace("T", " ")}, {runs[0].profile}, {runs[0].done}/{runs[0].total})</p>}
      </div>
    </section>
  );
}
