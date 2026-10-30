import { useEffect, useMemo, useState } from "react";
import { fetchCall, fetchCalls, fetchCompare } from "../callsApi";
import type { CallDetail, CallUsage, CallList, CallRow, CompareGroup, CompareResult } from "../callsApi";
import "../calls.css";

/** Aramalar (lab-004): kayıtlı test aramalarının listesi/detayı ve profil ya da seçilen aramalar bazında kıyası.
 *  Veri data/voice-sessions oturum kayıtlarıdır; gecikme tanımı `latency_report` ile aynıdır (VAD bitişi → ajanın ilk sesi). */

const OUTCOMES: Record<string, string> = { completed: "Tamamlandı", refused: "Reddetti", abandoned: "Yarıda kaldı", bitmedi: "Bitmedi" };
const outcome = (o: string | null | undefined) => (o ? OUTCOMES[o] ?? o : "—");
const sec = (v: number | null | undefined, d = 2) => (v === null || v === undefined ? "—" : `${v.toFixed(d)} sn`);
const usd = (v: number | null | undefined) => (v === null || v === undefined ? "—" : v === 0 ? "$0" : `$${v < 0.01 ? v.toFixed(5) : v.toFixed(4)}`);
const num = (v: number | null | undefined) => (v === null || v === undefined ? "—" : v.toLocaleString("tr-TR"));
const when = (iso: string | null) => (iso ? iso.slice(5, 16).replace("T", " ") : "—");
const ttsLabel = (c: { tts: string | null; tts_tone: string | null }) => (c.tts ? `${c.tts}${c.tts_tone ? ` · ${c.tts_tone}` : ""}` : "bilinmiyor");

function Delta({ g }: { g: CompareGroup }) {
  if (g.is_baseline) return <span className="calls-muted">taban</span>;
  if (g.delta_p50_s === null) return <>—</>;
  const better = g.delta_p50_s < 0;
  const sign = g.delta_p50_s > 0 ? "+" : "";
  return (
    <span className={better ? "calls-good" : g.delta_p50_s > 0 ? "calls-bad" : ""}>
      {sign}{g.delta_p50_s.toFixed(2)} sn{g.delta_pct !== null ? ` (${sign}${g.delta_pct.toFixed(0)}%)` : ""}
    </span>
  );
}

function CompareTable({ result, onBaseline }: { result: CompareResult; onBaseline: (key: string) => void }) {
  const best = useMemo(() => {
    const vals = result.groups.map((g) => g.first_audio?.p50).filter((v): v is number => v !== undefined && v !== null);
    return vals.length > 1 ? Math.min(...vals) : null;
  }, [result]);
  if (!result.groups.length) return <p className="calls-empty" role="note">Kıyaslanacak arama yok. Sesli Playground'dan arama yapın ya da süzgeci gevşetin.</p>;
  const byCall = result.group === "call";
  return (
    <div className="calls-scroll">
      <table className="calls-table" data-testid="compare-table">
        <thead>
          <tr>
            <th>{byCall ? "Arama" : "Profil"}</th>
            {!byCall && <th>Arama</th>}
            <th>Tur</th>
            <th title="VAD konuşma bitişinden ajanın ilk sesine, medyan">İlk ses p50</th>
            <th>p95</th>
            <th>Fark (p50)</th>
            <th>STT</th><th>LLM</th><th>TTS ilk ses</th>
            <th>Maliyet / arama</th><th>GPU sn</th>
            <th>Cevap / arama</th>
            <th>Sonuç</th>
            <th>TTS</th>
          </tr>
        </thead>
        <tbody>
          {result.groups.map((g) => (
            <tr key={g.key} className={g.is_baseline ? "is-baseline" : ""} data-testid={`cmp-${g.key}`}>
              <td>
                <strong>{g.label}</strong>
                {g.realtime && <span className="calls-tag">realtime</span>}
                {!g.is_baseline && (
                  <button className="calls-link" onClick={() => onBaseline(g.key)} aria-label={`${g.label} tabanı yap`}>taban yap</button>
                )}
              </td>
              {!byCall && (
                <td>
                  {g.sessions}
                  {!g.enough_sessions && <span className="calls-tag warn" title={`Güvenilir karşılaştırma için en az ${result.min_sessions} arama gerekir`}>örnek az</span>}
                </td>
              )}
              <td>{g.turns}</td>
              <td className={best !== null && g.first_audio?.p50 === best ? "calls-best" : ""}>
                {sec(g.first_audio?.p50)}
                {g.first_audio && <span className={g.meets_p50_target ? "calls-tag ok" : "calls-tag bad"}>{g.meets_p50_target ? `< ${result.p50_target_s}` : `≥ ${result.p50_target_s}`}</span>}
              </td>
              <td>{sec(g.first_audio?.p95)}</td>
              <td><Delta g={g} /></td>
              <td>{sec(g.stages.stt)}</td><td>{sec(g.stages.llm)}</td><td>{sec(g.stages.tts_first)}</td>
              <td data-testid="cost-cell">{usd(g.avg_cost_usd)}{(g.usage_calls ?? 0) > 0 && !g.cost_complete && <span className="calls-tag bad" title="Bazı kalemlerin fiyatı ya da token sayısı yok">eksik</span>}</td>
              <td>{g.avg_gpu_s == null ? "—" : g.avg_gpu_s.toFixed(1)}</td>
              <td>{g.avg_answers ?? "—"}</td>
              <td>{Object.entries(g.outcomes).map(([o, n]) => `${outcome(o)} ${n}`).join(", ")}</td>
              <td className="calls-wrap">{g.tts.length ? g.tts.join(", ") : "bilinmiyor"}{g.tones.length ? ` · ${g.tones.join(", ")}` : ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="calls-note">{result.definition} Aşama sütunları tur başına medyandır; realtime kayıtlarda aşama ayrımı yoktur. Hedef: p50 &lt; {result.p50_target_s} sn.</p>
    </div>
  );
}

function UsagePanel({ u }: { u: CallUsage | null | undefined }) {
  if (!u) return <p className="calls-muted" role="note">Bu aramada kaynak ölçümü yok (eval-003'ten önce kaydedilmiş).</p>;
  const i = u.items;
  const c = u.cost;
  return (
    <div data-testid="call-usage">
      <table className="calls-table small">
        <tbody>
          <tr><th>Süre</th><td>{i.duration_s.toFixed(0)} sn (müşteri {i.user_speech_s.toFixed(0)} · ajan {i.agent_speech_s.toFixed(0)} · konuşma payı {i.speech_share === null ? "—" : `%${Math.round(i.speech_share * 100)}`})</td></tr>
          <tr><th>STT</th><td>{i.stt_minutes.toFixed(2)} dk · {i.stt_calls} çağrı{c.by_component.stt !== undefined && <> · {usd(c.by_component.stt)}</>}</td></tr>
          <tr><th>LLM</th><td>{num(i.llm_input_tokens)} giriş / {num(i.llm_output_tokens)} çıkış token · {i.llm_calls} çağrı{c.by_component.llm !== undefined && <> · {usd(c.by_component.llm)}</>}</td></tr>
          <tr><th>TTS</th><td>{num(i.tts_chars)} karakter · {i.tts_audio_s.toFixed(0)} sn ses{c.by_component.tts !== undefined && <> · {usd(c.by_component.tts)}</>}</td></tr>
          <tr><th>Yerel hesaplama</th><td>{i.gpu_s.toFixed(1)} sn (çağrı süresi toplamı; GPU doluluğu değil)</td></tr>
          <tr><th>Toplam maliyet</th><td><strong>{usd(c.total)}</strong> {c.currency}</td></tr>
        </tbody>
      </table>
      {!c.complete && <p className="calls-bad" role="note">Maliyet eksik: {c.unpriced.join(", ")} için fiyat ya da token bilgisi yok; toplam yalnız fiyatlı kalemleri kapsar.</p>}
      {!c.prices_verified && <p className="calls-muted" role="note">Bazı liste fiyatları resmî sayfadan doğrulanmadı (config/pricing.json). {c.note}.</p>}
    </div>
  );
}

function CallDetailPanel({ id, onClose }: { id: string; onClose: () => void }) {
  const [d, setD] = useState<CallDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    const ac = new AbortController();
    setD(null); setErr(null);
    fetchCall(id, ac.signal).then(setD).catch((e) => { if (!ac.signal.aborted) setErr(String(e.message ?? e)); });
    return () => ac.abort();
  }, [id]);
  return (
    <aside className="calls-detail" aria-label="Arama detayı" data-testid="call-detail">
      <div className="calls-detail-head">
        <h3>Arama {id.slice(0, 6)}</h3>
        <button className="calls-x" onClick={onClose} aria-label="Detayı kapat">×</button>
      </div>
      {err && <p role="alert" className="calls-bad">{err}</p>}
      {!d && !err && <p className="calls-muted">Yükleniyor…</p>}
      {d && (
        <>
          <p className="calls-meta">
            {d.profile} · {when(d.started_at)} · {d.scenario ?? "senaryo yok"} · {outcome(d.outcome)} · {d.duration_s !== null ? `${Math.round(d.duration_s)} sn` : "—"}
          </p>
          <p className="calls-meta">TTS: {ttsLabel(d)}{d.tts_speed ? ` · hız ${d.tts_speed}` : ""} · STT: {d.stt ?? "bilinmiyor"} · LLM: {d.llm ?? "bilinmiyor"}</p>
          {d.audio_url ? <audio controls src={d.audio_url} data-testid="call-audio" aria-label="Arama kaydı" /> : <p className="calls-muted" role="note">Ses kaydı yok (silinmiş ya da kaydedilmemiş).</p>}
          <h4>Kaynak ve maliyet</h4>
          <UsagePanel u={d.usage} />
          <h4>Cevaplar</h4>
          {d.answers.length ? (
            <ul className="calls-answers">
              {d.answers.map((a, i) => (
                <li key={`${a.step}-${i}`}>
                  <span>{a.title ?? a.step}</span>
                  <strong>{a.unanswered ? "cevaplanmadı" : String(a.value)}</strong>
                  {a.utterance && <em>“{a.utterance}”</em>}
                </li>
              ))}
            </ul>
          ) : <p className="calls-muted">Cevap yok.</p>}
          <h4>Transkript</h4>
          <ol className="calls-transcript">
            {d.transcript.map((t, i) => (
              <li key={i} className={t.role === "agent" ? "agent" : "user"}>
                <span>{t.role === "agent" ? "Ajan" : "Kullanıcı"}</span> {t.text}
              </li>
            ))}
          </ol>
          <h4>Tur gecikmeleri</h4>
          <div className="calls-scroll">
            <table className="calls-table small">
              <thead><tr><th>Tur</th><th>İlk ses</th><th>STT</th><th>LLM</th><th>TTS ilk</th></tr></thead>
              <tbody>
                {d.turns.map((t) => (
                  <tr key={t.turn}>
                    <td>{t.greeting ? "açılış" : t.turn}</td>
                    <td>{sec(t.first_audio_after_end_s)}</td><td>{sec(t.stt_s)}</td><td>{sec(t.llm_s)}</td><td>{sec(t.tts_first_s)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </aside>
  );
}

export function CallsPage() {
  const [tab, setTab] = useState<"compare" | "list">("compare");
  const [list, setList] = useState<CallList | null>(null);
  const [filters, setFilters] = useState<{ profile: string; scenario: string; outcome: string }>({ profile: "", scenario: "", outcome: "" });
  const [selected, setSelected] = useState<string[]>([]);
  const [mode, setMode] = useState<"profile" | "call">("profile");
  const [baseline, setBaseline] = useState<string | undefined>(undefined);
  const [result, setResult] = useState<CompareResult | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    const ac = new AbortController();
    fetchCalls({ profile: filters.profile, scenario: filters.scenario, outcome: filters.outcome }, ac.signal)
      .then((r) => { setList(r); setErr(null); })
      .catch((e) => { if (!ac.signal.aborted) setErr(String(e.message ?? e)); });
    return () => ac.abort();
  }, [filters]);

  useEffect(() => {
    if (tab !== "compare") return;
    if (mode === "call" && !selected.length) { setResult(null); return; }
    const ac = new AbortController();
    fetchCompare({ group: mode, ids: mode === "call" ? selected : undefined, baseline, ...(mode === "profile" ? filters : {}) }, ac.signal)
      .then((r) => { setResult(r); setErr(null); })
      .catch((e) => { if (!ac.signal.aborted) setErr(String(e.message ?? e)); });
    return () => ac.abort();
  }, [tab, mode, selected, baseline, filters]);

  const toggle = (id: string) => setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : s.length >= 12 ? s : [...s, id]));
  const compareSelected = () => { setMode("call"); setBaseline(undefined); setTab("compare"); };
  const setFilter = (k: keyof typeof filters) => (e: React.ChangeEvent<HTMLSelectElement>) => setFilters((f) => ({ ...f, [k]: e.target.value }));

  const facets = list?.facets;
  const filterBar = (
    <div className="calls-filters" role="group" aria-label="Süzgeçler">
      <label>Profil
        <select value={filters.profile} onChange={setFilter("profile")}>
          <option value="">Hepsi</option>{facets?.profiles.map((p) => <option key={p} value={p}>{p}</option>)}
        </select>
      </label>
      <label>Senaryo
        <select value={filters.scenario} onChange={setFilter("scenario")}>
          <option value="">Hepsi</option>{facets?.scenarios.map((p) => <option key={p} value={p}>{p}</option>)}
        </select>
      </label>
      <label>Sonuç
        <select value={filters.outcome} onChange={setFilter("outcome")}>
          <option value="">Hepsi</option>{facets?.outcomes.map((p) => <option key={p} value={p}>{outcome(p)}</option>)}
        </select>
      </label>
    </div>
  );

  return (
    <section className="calls">
      <h2>Aramalar</h2>
      <p className="calls-muted">Yaptığınız test aramaları: profilleri gecikme ve sonuç bazında kıyaslayın, tek tek dinleyin.</p>
      <div className="calls-tabs" role="tablist">
        <button role="tab" aria-selected={tab === "compare"} onClick={() => setTab("compare")}>Kıyas</button>
        <button role="tab" aria-selected={tab === "list"} onClick={() => setTab("list")}>Aramalar{list ? ` (${list.total})` : ""}</button>
      </div>
      {err && <p role="alert" className="calls-bad">{err}</p>}
      {filterBar}

      {tab === "compare" && (
        <div role="tabpanel">
          <div className="calls-modebar">
            <div className="calls-seg" role="group" aria-label="Kıyas türü">
              <button aria-pressed={mode === "profile"} onClick={() => { setMode("profile"); setBaseline(undefined); }}>Profil bazlı</button>
              <button aria-pressed={mode === "call"} onClick={() => { setMode("call"); setBaseline(undefined); }}>Seçilen aramalar ({selected.length})</button>
            </div>
            {mode === "call" && !selected.length && <span className="calls-muted">“Aramalar” sekmesinden karşılaştırmak istediklerinizi işaretleyin.</span>}
          </div>
          {result ? <CompareTable result={result} onBaseline={setBaseline} /> : mode === "profile" && !err ? <p className="calls-muted">Yükleniyor…</p> : null}
        </div>
      )}

      {tab === "list" && (
        <div role="tabpanel" className={open ? "calls-split" : ""}>
          <div>
            <div className="calls-actions">
              <button className="primary" disabled={!selected.length} onClick={compareSelected}>Seçilenleri karşılaştır ({selected.length})</button>
              {selected.length > 0 && <button onClick={() => setSelected([])}>Seçimi temizle</button>}
            </div>
            {list && !list.calls.length && <p className="calls-empty" role="note">Henüz arama yok. Sesli Playground'da bir arama yapın; kayıtlar burada listelenir.</p>}
            {list && list.calls.length > 0 && (
              <div className="calls-scroll">
                <table className="calls-table" data-testid="call-list">
                  <thead><tr><th><span className="sr-only">Seç</span></th><th>Zaman</th><th>Profil</th><th>Sonuç</th><th>Tur</th><th>İlk ses p50</th><th>TTS</th><th>Ses</th></tr></thead>
                  <tbody>
                    {list.calls.map((c: CallRow) => (
                      <tr key={c.id} className={open === c.id ? "is-open" : ""} data-testid={`call-${c.id}`}>
                        <td><input type="checkbox" checked={selected.includes(c.id)} onChange={() => toggle(c.id)} aria-label={`${c.profile} ${when(c.started_at)} aramasını seç`} /></td>
                        <td><button className="calls-link" onClick={() => setOpen(c.id)} aria-label={`${c.id.slice(0, 6)} detayını aç`}>{when(c.started_at)}</button></td>
                        <td>{c.profile}</td>
                        <td>{outcome(c.outcome)}</td>
                        <td>{c.turns}</td>
                        <td>{sec(c.first_audio_p50_s)}</td>
                        <td className="calls-wrap">{ttsLabel(c)}</td>
                        <td>{c.has_audio ? "var" : "yok"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
          {open && <CallDetailPanel id={open} onClose={() => setOpen(null)} />}
        </div>
      )}
    </section>
  );
}
