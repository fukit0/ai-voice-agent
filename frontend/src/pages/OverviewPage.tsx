import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { fetchCalls } from "../callsApi";
import type { CallRow } from "../callsApi";
import { Icon } from "../icons";

/** Genel Bakış (ui-001): kayıtlı aramalardan (data/voice-sessions, /api/calls) hesaplanan özet. Hiçbir sayı uydurulmaz;
 *  veri yoksa boş durum gösterilir. Tepki süresi tanımı latency_report ile aynıdır: VAD konuşma bitişi → ajanın ilk sesi. */

const P50_TARGET_S = 1.2;
type Range = "today" | "7d" | "30d" | "all";
const RANGES: { id: Range; label: string; days: number | null }[] = [
  { id: "today", label: "Bugün", days: 1 },
  { id: "7d", label: "7 gün", days: 7 },
  { id: "30d", label: "30 gün", days: 30 },
  { id: "all", label: "Tümü", days: null },
];

const OUTCOMES: Record<string, { label: string; tone: "ok" | "warn" | "err" | "" }> = {
  completed: { label: "Tamamlandı", tone: "ok" },
  refused: { label: "Reddetti", tone: "err" },
  abandoned: { label: "Yarıda kaldı", tone: "warn" },
  bitmedi: { label: "Bitmedi", tone: "warn" },
};
const outcomeInfo = (o: string | null) => (o ? OUTCOMES[o] ?? { label: o, tone: "" as const } : { label: "—", tone: "" as const });

export const median = (xs: number[]) => {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
};
const mean = (xs: number[]) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null);
const tr = (v: number, d = 1) => v.toFixed(d).replace(".", ",");
export const mmss = (s: number | null) => (s === null ? "—" : `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(Math.round(s % 60)).padStart(2, "0")}`);
const when = (iso: string | null) => (iso ? iso.slice(5, 16).replace("T", " ") : "—");
const present = (v: number | null | undefined): v is number => v !== null && v !== undefined;

function inRange(c: CallRow, days: number | null, now: number) {
  if (days === null) return true;
  if (!c.started_at) return false;
  const t = Date.parse(c.started_at);
  return Number.isFinite(t) && now - t <= days * 86_400_000;
}

function DailyChart({ calls }: { calls: CallRow[] }) {
  const byDay = useMemo(() => {
    const m = new Map<string, number>();
    for (const c of calls) if (c.started_at) m.set(c.started_at.slice(0, 10), (m.get(c.started_at.slice(0, 10)) ?? 0) + 1);
    return [...m.entries()].sort(([a], [b]) => a.localeCompare(b)).slice(-30);
  }, [calls]);
  if (!byDay.length) return <p className="meta">Tarihli arama yok.</p>;
  const W = 600, H = 180, padL = 26, padB = 22, padT = 8;
  const max = Math.max(1, ...byDay.map(([, n]) => n));
  const bw = (W - padL) / byDay.length;
  const y = (n: number) => padT + (H - padB - padT) * (1 - n / max);
  const every = Math.ceil(byDay.length / 7);
  return (
    <svg className="chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Günlük arama sayısı">
      {[0, 0.5, 1].map((f) => (
        <g key={f}>
          <line className="gridline" x1={padL} x2={W} y1={y(max * f)} y2={y(max * f)} />
          <text x={0} y={y(max * f) + 4}>{Math.round(max * f)}</text>
        </g>
      ))}
      {byDay.map(([d, n], i) => (
        <g key={d}>
          <rect className="bar" x={padL + i * bw + bw * 0.15} width={bw * 0.7} y={y(n)} height={H - padB - y(n)} rx={3}><title>{d}: {n} arama</title></rect>
          {i % every === 0 && <text x={padL + i * bw} y={H - 6}>{d.slice(8, 10)}.{d.slice(5, 7)}</text>}
        </g>
      ))}
    </svg>
  );
}

function Kpi({ icon, label, value, unit, sub, tone }: { icon: string; label: string; value: string; unit?: string; sub?: string; tone?: "good" | "bad" }) {
  return (
    <div className={`kpi${tone ? ` ${tone}` : ""}`}>
      <p className="kpi-label"><Icon name={icon} size={16} /> {label}</p>
      <p className="kpi-value">{value}{unit && <small>{unit}</small>}</p>
      {sub && <p className="kpi-sub">{sub}</p>}
    </div>
  );
}

export function OverviewPage() {
  const [all, setAll] = useState<CallRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [range, setRange] = useState<Range>("all");

  useEffect(() => {
    const ac = new AbortController();
    fetchCalls({}, ac.signal).then((r) => setAll(r.calls), (e) => { if (!ac.signal.aborted) setError(String(e.message ?? e)); });
    return () => ac.abort();
  }, []);

  const calls = useMemo(() => {
    const now = Date.now();
    const days = RANGES.find((r) => r.id === range)?.days ?? null;
    return (all ?? []).filter((c) => inRange(c, days, now));
  }, [all, range]);

  const m = useMemo(() => {
    const done = calls.filter((c) => c.outcome === "completed").length;
    const durs = calls.map((c) => c.duration_s).filter(present);
    const stage = (k: "stt_p50_s" | "llm_p50_s" | "tts_first_p50_s") => median(calls.map((c) => c[k]).filter(present));
    const outcomes = new Map<string, number>();
    for (const c of calls) outcomes.set(c.outcome ?? "—", (outcomes.get(c.outcome ?? "—") ?? 0) + 1);
    const profiles = new Map<string, CallRow[]>();
    for (const c of calls) profiles.set(c.profile, [...(profiles.get(c.profile) ?? []), c]);
    return {
      done, p50: median(calls.map((c) => c.first_audio_p50_s).filter(present)), avgDur: mean(durs), totalDur: durs.reduce((a, b) => a + b, 0),
      answers: calls.reduce((a, c) => a + c.answers, 0), unanswered: calls.reduce((a, c) => a + c.unanswered, 0),
      barge: calls.reduce((a, c) => a + c.barge_ins, 0), rejected: calls.reduce((a, c) => a + c.stt_rejected, 0),
      turns: calls.reduce((a, c) => a + c.turns, 0), stt: stage("stt_p50_s"), llm: stage("llm_p50_s"), tts: stage("tts_first_p50_s"),
      outcomes: [...outcomes.entries()].sort((a, b) => b[1] - a[1]),
      profiles: [...profiles.entries()].map(([id, cs]) => ({ id, n: cs.length, p50: median(cs.map((c) => c.first_audio_p50_s).filter(present)) })),
    };
  }, [calls]);

  const recent = useMemo(() => [...calls].sort((a, b) => (b.started_at ?? "").localeCompare(a.started_at ?? "")).slice(0, 8), [calls]);
  const stageMax = Math.max(0.01, m.stt ?? 0, m.llm ?? 0, m.tts ?? 0);

  return (
    <section className="page overview">
      <div className="page-head">
        <div>
          <span className="eyebrow">Raporlama</span>
          <h2>Genel Bakış</h2>
          <p className="meta">Test aramalarının sonuçları: tamamlanma, süre, tepki süresi, söz kesme ve cevaplanan sorular.</p>
        </div>
        <div className="seg" role="group" aria-label="Tarih aralığı">
          {RANGES.map((r) => (
            <button key={r.id} type="button" aria-pressed={range === r.id} onClick={() => setRange(r.id)}>{r.label}</button>
          ))}
        </div>
      </div>

      {error && <p className="note" role="alert">Aramalar yüklenemedi: {error}</p>}
      {all === null && !error && <p className="meta" role="status">Yükleniyor…</p>}

      {all !== null && calls.length === 0 && (
        <div className="empty" data-testid="overview-empty">
          <strong>{all.length ? "Bu aralıkta arama yok" : "Henüz arama kaydı yok"}</strong>
          {all.length ? "Aralığı genişletin ya da yeni bir arama yapın." : "Playground'dan mikrofonla bir arama yapın; sonuçlar burada görünür."}
          <div><Link to="/playground" className="cta"><Icon name="phone" size={16} /> Yeni Arama</Link></div>
        </div>
      )}

      {calls.length > 0 && (
        <>
          <div className="kpis" data-testid="kpis">
            <Kpi icon="phone" label="Görüşme" value={String(calls.length)} unit="arama" sub={`${m.turns} tur · ${m.answers} cevaplanan soru`} />
            <Kpi icon="check" label="Tamamlanan" value={String(m.done)} sub={`%${tr((m.done / calls.length) * 100)} tamamlanma`} />
            <Kpi icon="headphones" label="Ortalama süre" value={mmss(m.avgDur)} sub={`toplam ${tr(m.totalDur / 60)} dk`} />
            <Kpi icon="target" label="Tepki süresi" value={m.p50 === null ? "—" : tr(m.p50, 2)} unit={m.p50 === null ? undefined : "sn"}
              tone={m.p50 === null ? undefined : m.p50 <= P50_TARGET_S ? "good" : "bad"}
              sub={`medyan · hedef ≤ ${tr(P50_TARGET_S)} sn (konuşma bitişi → ilk ses)`} />
            <Kpi icon="wave" label="Söz kesme" value={String(m.barge)} unit="kez" sub={`${m.rejected} anlaşılmayan ses elendi`} />
            <Kpi icon="mic" label="Cevapsız soru" value={String(m.unanswered)}
              sub={m.answers + m.unanswered ? `%${tr((m.unanswered / (m.answers + m.unanswered)) * 100)} oranında` : undefined} />
          </div>

          <div className="grid-2">
            <div className="panel">
              <h3>Günlük arama akışı</h3>
              <p className="meta">Her gün yapılan arama sayısı</p>
              <DailyChart calls={calls} />
            </div>
            <div className="panel">
              <h3>Görüşme sonuçları</h3>
              <p className="meta">Görüşmenin nasıl sonuçlandığı</p>
              <div className="bars">
                {m.outcomes.map(([k, n]) => {
                  const info = outcomeInfo(k === "—" ? null : k);
                  return (
                    <div className="bar-row" key={k}>
                      <span>{info.label}</span>
                      <span className="bar-track"><span className={`bar-fill tone-${info.tone || "accent"}`} style={{ width: `${(n / calls.length) * 100}%`, display: "block" }} /></span>
                      <span className="bar-num">{n} · %{tr((n / calls.length) * 100, 0)}</span>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>

          <div className="grid-2">
            <div className="panel">
              <h3>Gecikme dağılımı</h3>
              <p className="meta">Aşama başına medyan süre (tüm turlar)</p>
              <div className="bars">
                {([["STT", m.stt, "blue"], ["LLM", m.llm, "accent"], ["TTS ilk ses", m.tts, "ok"]] as const).map(([name, v, tone]) => (
                  <div className="bar-row" key={name}>
                    <span>{name}</span>
                    <span className="bar-track"><span className={`bar-fill tone-${tone}`} style={{ width: `${((v ?? 0) / stageMax) * 100}%`, display: "block" }} /></span>
                    <span className="bar-num">{v === null ? "—" : `${tr(v, 2)} sn`}</span>
                  </div>
                ))}
              </div>
            </div>
            <div className="panel">
              <h3>Profillere göre</h3>
              <p className="meta">Aynı koşulda kaç arama yapıldı, tepki süresi nasıl</p>
              <div className="table-wrap">
                <table className="data-table">
                  <thead><tr><th>Profil</th><th>Arama</th><th>İlk ses p50</th></tr></thead>
                  <tbody>
                    {m.profiles.map((p) => (
                      <tr key={p.id}>
                        <td>{p.id}</td><td className="num">{p.n}</td>
                        <td className="num">{p.p50 === null ? "—" : <span className={`pill ${p.p50 <= P50_TARGET_S ? "ok" : "err"}`}>{tr(p.p50, 2)} sn</span>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="note">Profilleri ayrıntılı kıyaslamak için <Link to="/calls">Aramalar → Kıyas</Link>.</p>
            </div>
          </div>

          <div className="panel">
            <h3>Son görüşmeler</h3>
            <p className="meta">Ayrıntı, döküm ve ses kaydı için Aramalar ekranı</p>
            <div className="table-wrap">
              <table className="data-table" data-testid="recent-calls">
                <thead><tr><th>Zaman</th><th>Profil</th><th>Senaryo</th><th>Sonuç</th><th>Süre</th><th>İlk ses p50</th><th>Tur</th><th>Cevap</th></tr></thead>
                <tbody>
                  {recent.map((c) => {
                    const o = outcomeInfo(c.outcome);
                    return (
                      <tr key={c.id}>
                        <td>{when(c.started_at)}</td>
                        <td><Link to="/calls">{c.profile}</Link></td>
                        <td>{c.scenario ?? "—"}</td>
                        <td><span className={`pill ${o.tone}`}>{o.label}</span></td>
                        <td className="num">{mmss(c.duration_s)}</td>
                        <td className="num">{c.first_audio_p50_s === null ? "—" : `${tr(c.first_audio_p50_s, 2)} sn`}</td>
                        <td className="num">{c.turns}</td>
                        <td className="num">{c.answers}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <p className="note"><Link to="/calls">Tüm aramalar →</Link></p>
          </div>
        </>
      )}
    </section>
  );
}
