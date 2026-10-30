import { useEffect, useMemo, useState } from "react";
import { fetchModelMatrix, fetchVoices, runTtsLab, type LabResult, type ModelMatrix, type VoiceRow } from "../api";

const TONES = [{ id: "", label: "Ton yok" }, { id: "samimi", label: "Samimi" }, { id: "resmi", label: "Resmî" },
  { id: "enerjik", label: "Enerjik" }, { id: "sakin", label: "Sakin" }];
const median = (xs: number[]) => (xs.length ? [...xs].sort((a, b) => a - b)[Math.floor(xs.length / 2)] : null);
const fmt = (v: number | null | undefined, d = 2) => (v === null || v === undefined ? "-" : v.toFixed(d));

type Row = LabResult & { id: string; label: string; voiceName: string; total: number };

// TTS laboratuvarı: kendi metninizi model + ses + ton seçerek üretin; ilk ses süresini (canlı hat için asıl ölçü) ve maliyeti görün.
// Kıyas matrisi: resmî fiyat/gecikme notları + sizin ölçtüğünüz medyan süreler yan yana. Gecikme sizin ağınızdan ölçülür.
export function TtsLab() {
  const [matrix, setMatrix] = useState<ModelMatrix | null>(null);
  const [voices, setVoices] = useState<VoiceRow[]>([]);
  const [text, setText] = useState("Merhaba Ahmet Bey, ben Ayşe. sahibinden.com adına arıyorum. Size kısa bir anket yapabilir miyim?");
  const [model, setModel] = useState("eleven_flash_v2_5");
  const [voice, setVoice] = useState("");
  const [tone, setTone] = useState("enerjik");
  const [runs, setRuns] = useState(3);
  const [calls, setCalls] = useState(10000);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [rows, setRows] = useState<Row[]>([]);

  useEffect(() => {
    fetchModelMatrix().then(setMatrix).catch(() => {});
    fetchVoices("", false).then((r) => setVoices(r.voices)).catch(() => {});
  }, []);

  const labelOf = (id: string) => matrix?.models.find((m) => m.id === id)?.label ?? id;
  const voiceName = (id: string) => (id ? voices.find((v) => v.voice_id === id)?.name ?? id : "ton/genel ses");

  const run = async (m: string) => {
    const r = await runTtsLab({ text, model: m, voice_id: voice || null, tone: tone || null, runs });
    const total = median(r.runs.map((x) => x.total_seconds)) ?? 0;
    setRows((prev) => [{ ...r, id: `${r.runs[0].id}`, label: labelOf(m), voiceName: voiceName(voice || r.voice_id), total }, ...prev]);
  };
  const runOne = async (m: string) => {
    setBusy(m); setErr(null);
    try { await run(m); } catch (e) { setErr(String((e as Error).message ?? e)); } finally { setBusy(null); }
  };
  const runAll = async () => {
    setErr(null);
    for (const m of matrix?.models ?? []) {
      setBusy(m.id);
      try { await run(m.id); } catch (e) { setErr(`${m.label}: ${String((e as Error).message ?? e)}`); }
    }
    setBusy(null);
  };

  // matris: her model için son ölçüm (aynı ses + ton + metin ile yapılanlar karşılaştırılabilir)
  const latest = useMemo(() => {
    const out: Record<string, Row> = {};
    for (const r of [...rows].reverse()) out[r.model] = r;
    return out;
  }, [rows]);

  return (
    <section className="tts-lab" data-testid="tts-lab" aria-label="TTS laboratuvarı">
      <h3 className="sub">TTS laboratuvarı — model, ses, ton; gecikme ve maliyet</h3>
      <p className="meta">
        Metni yazın, model/ses/ton seçin. <b>İlk ses süresi</b> canlı hatta müşterinin beklediği süredir (akışlı ölçülür); toplam süre tüm klibin bitişidir.
        Ölçüm bu bilgisayarın ağından yapılır; birkaç tekrarın medyanına bakın.
      </p>
      <label htmlFor="lab-text"><b>Metin</b> <span className="meta">{text.length}/500</span></label>
      <textarea id="lab-text" rows={3} maxLength={500} value={text} onChange={(e) => setText(e.target.value)} />
      <div className="persona-row">
        <div>
          <label htmlFor="lab-model"><b>Model</b></label>
          <select id="lab-model" value={model} onChange={(e) => setModel(e.target.value)}>
            {(matrix?.models ?? []).map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
          </select>
        </div>
        <div>
          <label htmlFor="lab-voice"><b>Ses</b></label>
          <select id="lab-voice" value={voice} onChange={(e) => setVoice(e.target.value)}>
            <option value="">Ton/genel ses (atanan)</option>
            {voices.map((v) => <option key={v.voice_id} value={v.voice_id}>{v.name}</option>)}
          </select>
        </div>
        <div>
          <label htmlFor="lab-tone"><b>Ton</b></label>
          <select id="lab-tone" value={tone} onChange={(e) => setTone(e.target.value)}>
            {TONES.map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}
          </select>
        </div>
        <div>
          <label htmlFor="lab-runs"><b>Tekrar</b></label>
          <input id="lab-runs" type="number" min={1} max={3} value={runs} onChange={(e) => setRuns(Math.min(3, Math.max(1, Number(e.target.value) || 1)))} />
        </div>
      </div>
      <div className="persona-actions">
        <button type="button" disabled={!!busy || !text.trim() || !matrix} onClick={() => void runOne(model)}>
          {busy === model ? "Üretiliyor…" : "Bu modelle dene"}
        </button>
        <button type="button" disabled={!!busy || !text.trim() || !matrix} onClick={() => void runAll()}>
          {busy ? "Sırayla deniyor…" : "Tüm modelleri sırayla dene"}
        </button>
      </div>
      {err && <p className="error" role="note">{err}</p>}

      {matrix && (
        <>
          <h4>Kıyas matrisi</h4>
          <label htmlFor="lab-calls" className="meta">Aylık çağrı sayısı (maliyet tahmini için)</label>
          <input id="lab-calls" type="number" min={1} value={calls} onChange={(e) => setCalls(Math.max(1, Number(e.target.value) || 1))} />
          <div className="table-scroll">
            <table className="eval-table" data-testid="lab-matrix">
              <thead>
                <tr><th>Model</th><th>Fiyat ($/1K kar.)</th><th>Resmî gecikme notu</th><th>Ölçülen ilk ses (sn)</th><th>Ölçülen toplam (sn)</th>
                  <th>Ses etiketi</th><th>Ton kaldıracı</th><th>Bu metin ($)</th><th>Aylık ({calls.toLocaleString("tr-TR")} çağrı, $)</th></tr>
              </thead>
              <tbody>
                {matrix.models.map((m) => {
                  const r = latest[m.id];
                  const chars = r?.chars ?? text.length;
                  const per = (chars * m.price_per_1k_usd) / 1000;
                  return (
                    <tr key={m.id} data-testid={`matrix-${m.id}`}>
                      <td><b>{m.label}</b></td><td>{m.price_per_1k_usd.toFixed(2)}</td><td>{m.latency_note}</td>
                      <td>{fmt(r?.median_first_audio_seconds, 3)}</td><td>{fmt(r?.total, 2)}</td>
                      <td>{m.tags ? "var" : "yok"}</td><td>{m.tone_levers}</td>
                      <td>{per.toFixed(5)}</td><td>{(per * calls).toFixed(2)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="meta">{matrix.price_note} Kaynak: {matrix.source}.</p>
        </>
      )}

      {rows.length > 0 && (
        <div data-testid="lab-results">
          <h4>Denemeler (en yeni üstte)</h4>
          <div className="tone-grid">
            {rows.map((r) => (
              <article key={r.id} className="tone-card" data-testid={`lab-${r.model}`}>
                <h4>{r.label}</h4>
                <p className="meta">{r.voiceName} · {r.tone ?? "ton yok"} · {r.chars} karakter · ${r.cost_usd ?? "-"}</p>
                <audio controls src={r.runs[0].url} />
                <ul className="tone-metrics">
                  <li>ilk ses (medyan): <b>{fmt(r.median_first_audio_seconds, 3)} sn</b></li>
                  <li>toplam (medyan): <b>{fmt(r.total, 2)} sn</b> · ses {fmt(r.runs[0].audio_seconds, 1)} sn</li>
                  <li>tekrarlar: {r.runs.map((x) => fmt(x.first_audio_seconds, 3)).join(" / ")}</li>
                </ul>
                <p className="meta">{Object.entries(r.applied).map(([k, v]) => `${k}: ${v}`).join(" · ") || "ayar yok"}{r.sent_text !== text ? " · gönderilen metin etiket içerir" : ""}</p>
              </article>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
