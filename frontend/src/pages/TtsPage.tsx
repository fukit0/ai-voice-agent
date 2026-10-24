import { useCallback, useEffect, useState } from "react";
import {
  blindAudioUrl, createTtsSession, fetchTtsModels, fetchTtsSession, fetchTtsSessions, fetchTtsSummary, getWarmup,
  previewNormalize, rateClip, startListening, startWarmup, ttsClipUrl, ttsRatingsCsvUrl,
  type BlindRating, type BlindView, type NormalizePreview, type TtsModel, type TtsSession, type TtsSessionSummary,
  type TtsSummaryRow,
} from "../api";

const DEFAULT_SENTENCES = [
  "Merhaba, ben Sahibinden'den arıyorum. Size birkaç kısa soru sormak istiyorum, uygun musunuz?",
  "İlanınızla ilgili deneyiminizi bire ile beş arasında bir puanla değerlendirir misiniz?",
  "Anladım, geri bildiriminiz için çok teşekkür ederim.",
  "Ödeme sürecinde yaşadığınız bir sorun oldu mu?",
  "23.10.2026 tarihinde yayınlanan ilanınız için 1.500 TL ödeme yaptınız.",
  "Telefon numaranız 0532 123 45 67, doğru mu?",
  "Müşteri hizmetlerimizle ilgili önerileriniz varsa memnuniyetle dinlerim.",
  "Biraz daha açar mısınız? Tam olarak anlayamadım.",
  "Rahatsız ettiysem özür dilerim, daha sonra tekrar arayabilirim.",
  "Görüşmek üzere, iyi günler dilerim.",
].join("\n");

const modelKey = (m: { provider: string; model: string }) => `${m.provider}:${m.model}`;
const sec = (v?: number) => (v == null ? "—" : `${v.toFixed(2)} sn`);

const LABELS: Record<"naturalness" | "humanlike" | "mispronunciation", [string, string]> = {
  naturalness: ["Doğallık", "1 yapay · 5 çok doğal"],
  humanlike: ["İnsan gibilik", "1 robotik · 5 gerçek insan gibi"],
  mispronunciation: ["Telaffuz hatası", "0 hata yok · 5 çok hatalı"],
};

// TTS stüdyosu (lab-001, plan F7.1). Yönetici: cümle seti × modeller → klipler (ilk ses süresi, RTF, aynı ses seviyesi).
// Dinleyici modu: model adları gizli, klipler rastgele sırada; puanlar kaydedilir ve CSV olarak indirilir.
export function TtsPage() {
  const [mode, setMode] = useState<"studio" | "listen">("studio");
  const [sessions, setSessions] = useState<TtsSessionSummary[]>([]);
  const loadSessions = useCallback(() => fetchTtsSessions().then(setSessions).catch(() => {}), []);
  useEffect(() => { void loadSessions(); }, [loadSessions]);

  return (
    <section aria-labelledby="tts-title">
      <h2 id="tts-title">TTS stüdyosu</h2>
      <span className="chip">lab-001</span>
      <div className="tabs" role="tablist">
        <button role="tab" aria-selected={mode === "studio"} onClick={() => setMode("studio")}>Stüdyo</button>
        <button role="tab" aria-selected={mode === "listen"} onClick={() => { setMode("listen"); void loadSessions(); }}>
          Dinleyici modu
        </button>
      </div>
      {mode === "studio" ? <Studio onCreated={loadSessions} sessions={sessions} /> : <Listener sessions={sessions} />}
    </section>
  );
}

function Studio({ sessions, onCreated }: { sessions: TtsSessionSummary[]; onCreated: () => void }) {
  const [models, setModels] = useState<TtsModel[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [text, setText] = useState(DEFAULT_SENTENCES);
  const [phone, setPhone] = useState(false);
  const [normalizeText, setNormalizeText] = useState(true);
  const [preview, setPreview] = useState<NormalizePreview[]>([]);
  const [session, setSession] = useState<TtsSession | null>(null);
  const [summary, setSummary] = useState<TtsSummaryRow[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [preparing, setPreparing] = useState<Record<string, boolean>>({});

  const loadModels = useCallback(async () => {
    try {
      const list = await fetchTtsModels();
      setModels(list);
      setSelected((prev) => (prev.size ? prev : new Set(list.filter((m) => m.warm && m.ready).map(modelKey))));
    } catch (e) { setError((e as Error).message); }
  }, []);
  useEffect(() => { void loadModels(); }, [loadModels]);

  const sentences = text.split("\n").map((s) => s.trim()).filter(Boolean);
  const chosen = models.filter((m) => selected.has(modelKey(m)));

  // norm-007: TTS'e gidecek hali, yazarken kısa gecikmeyle önizlenir (yalnızca değişen cümleler gösterilir).
  const sentenceKey = sentences.join("\n");
  useEffect(() => {
    if (!normalizeText || !sentences.length) { setPreview([]); return; }
    let cancelled = false;
    const timer = setTimeout(() => {
      previewNormalize(sentences.slice(0, 30)).then((p) => { if (!cancelled && Array.isArray(p)) setPreview(p); }).catch(() => {});
    }, 300);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [sentenceKey, normalizeText]); // eslint-disable-line react-hooks/exhaustive-deps
  const changed = preview.filter((p) => p.changes.length > 0);

  async function prepare(m: TtsModel) {
    const key = modelKey(m);
    setPreparing((p) => ({ ...p, [key]: true }));
    setError(null);
    try {
      // Stüdyoya özgü model (Chatterbox) tek başına yüklenir: diğer modeller bellekten çıkarılır (ADR 0001).
      // Yalnızca TTS bileşeni ısıtılır (LLM / STT anahtarları stüdyo için gerekmez). Tek bileşenli stüdyo
      // profilinde (Chatterbox) keep_others=false: diğer modeller bellekten çıkar, model tek başına yüklenir.
      let job = m.studio_only ? await startWarmup(m.profile, false) : await startWarmup(m.profile, true, "tts");
      while (job.state === "running") {
        await new Promise((r) => setTimeout(r, 1000));
        job = await getWarmup(m.profile);
      }
      if (job.state === "failed") setError(job.error ?? `${m.model || m.provider} hazırlanamadı.`);
    } catch (e) { setError((e as Error).message); }
    finally { setPreparing((p) => ({ ...p, [key]: false })); await loadModels(); }
  }

  async function poll(id: string) {
    let s = await fetchTtsSession(id);
    setSession(s);
    while (s.state === "running") {
      await new Promise((r) => setTimeout(r, 1000));
      s = await fetchTtsSession(id);
      setSession(s);
    }
    return s;
  }

  async function generate() {
    setBusy(true); setError(null); setSummary([]);
    try {
      const started = await createTtsSession(sentences, chosen.map((m) => m.profile), phone, normalizeText);
      const done = await poll(started.id);
      if (done.state === "failed") setError(done.error ?? "Üretim başarısız.");
      onCreated();
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  async function open(id: string) {
    setError(null);
    try {
      setSession(await fetchTtsSession(id));
      setSummary(await fetchTtsSummary(id));
    } catch (e) { setError((e as Error).message); }
  }

  const label = (profile: string) => {
    const m = models.find((x) => x.profiles.includes(profile)) ?? models.find((x) => x.profile === profile);
    return m ? `${m.provider}${m.model ? " · " + m.model : ""}` : profile;
  };

  return (
    <div>
      <h3 className="sub">1 · Modeller</h3>
      <ul className="stt-models">
        {models.map((m) => {
          const key = modelKey(m);
          return (
            <li key={key}>
              <label>
                <input type="checkbox" disabled={!m.ready} checked={selected.has(key)}
                  onChange={(e) => setSelected((prev) => { const n = new Set(prev); if (e.target.checked) n.add(key); else n.delete(key); return n; })} />
                {" "}{m.provider}{m.model ? ` · ${m.model}` : ""}
              </label>
              <span className="meta">{m.studio_only ? "yalnızca stüdyo" : m.profiles.join(", ")}</span>
              <span className={`chip ${!m.ready ? "chip-cold" : m.warm ? "chip-ok" : ""}`}>
                {!m.ready ? `Eksik: ${m.missing_env.join(", ") || "sağlayıcı"}` : m.warm ? "Sıcak" : "Soğuk"}
              </span>
              {m.ready && !m.warm && (
                <button type="button" disabled={!!preparing[key]} onClick={() => prepare(m)}
                  title={m.studio_only ? "Diğer modelleri bellekten çıkarır; model tek başına yüklenir." : undefined}>
                  {preparing[key] ? "Hazırlanıyor…" : "Hazırla"}
                </button>
              )}
            </li>
          );
        })}
      </ul>

      <h3 className="sub">2 · Cümle seti ({sentences.length} cümle, satır başına bir cümle)</h3>
      <textarea rows={8} value={text} onChange={(e) => setText(e.target.value)} aria-label="Cümle seti" />
      <label className="check">
        <input type="checkbox" checked={phone} onChange={(e) => setPhone(e.target.checked)} />
        {" "}Telefon turu (300–3400 Hz, 8 kHz)
      </label>
      <label className="check">
        <input type="checkbox" checked={normalizeText} onChange={(e) => setNormalizeText(e.target.checked)} />
        {" "}Metni okunur Türkçeye çevir (sayı, fiyat, tarih, telefon)
      </label>
      {normalizeText && (
        <div className="norm-preview" aria-label="Normalize önizleme">
          {changed.length === 0 ? (
            <p className="meta">Cümlelerde çevrilecek sayı, fiyat, tarih veya telefon yok.</p>
          ) : (
            <>
              <p className="meta">TTS'e giden hali ({changed.length} cümlede değişiklik):</p>
              <ul>
                {changed.map((p) => (
                  <li key={p.text}><span className="meta">{p.text}</span><br /><strong>{p.spoken}</strong></li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}

      <p>
        <button type="button" className="primary" disabled={busy || !sentences.length || !chosen.length} onClick={generate}>
          {busy ? "Üretiliyor…" : `Ses üret (${sentences.length} × ${chosen.length})`}
        </button>
        {busy && session && <span className="meta"> {session.done}/{session.total} klip</span>}
      </p>
      {error && <p role="alert" className="error">{error}</p>}

      {session && (
        <div>
          <h3 className="sub">Sonuç <span className="meta">{session.id} · klipler −20 dBFS RMS'e normalize{session.phone ? " · telefon turu" : ""}</span></h3>
          <table className="tts-table">
            <thead>
              <tr><th>Cümle</th><th>Model</th><th>İlk ses</th><th>RTF</th><th>Süre</th><th>Dinle</th></tr>
            </thead>
            <tbody>
              {session.clips.map((c) => (
                <tr key={c.id}>
                  <td title={session.spoken?.[c.sentence_idx]}>
                    {c.sentence_idx + 1}. {session.sentences[c.sentence_idx].slice(0, 48)}
                    {session.text_normalized && session.spoken && session.spoken[c.sentence_idx] !== session.sentences[c.sentence_idx] &&
                      <span className="meta"> · okunuşu: {session.spoken[c.sentence_idx].slice(0, 60)}</span>}
                  </td>
                  <td>{label(c.profile)}</td>
                  {c.status === "ok" ? (
                    <>
                      <td title={c.first_audio_measured ? "ölçülen ilk ses" : "akış yok: üretimin tamamı"}>{sec(c.first_audio_seconds)}{c.first_audio_measured ? "" : "*"}</td>
                      <td>{c.rtf?.toFixed(2)}</td>
                      <td>{sec(c.audio_seconds)}</td>
                      <td><audio controls preload="none" src={ttsClipUrl(session.id, c.id)} /></td>
                    </>
                  ) : (
                    <td colSpan={4} className={c.status === "failed" ? "error" : "meta"}>
                      {c.status === "cold" ? "Soğuk — önce Hazırla. " : ""}{c.error}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
          <p className="meta">* Bu sağlayıcıda akış ölçülmüyor; ilk ses süresi olarak üretimin tamamı yazıldı.</p>
          {summary.length > 0 && (
            <>
              <h3 className="sub">Puan özeti</h3>
              <table className="tts-table">
                <thead><tr><th>Model</th><th>Puan sayısı</th><th>Doğallık</th><th>İnsan gibilik</th><th>Telaffuz hatası</th></tr></thead>
                <tbody>{summary.map((r) => (
                  <tr key={r.profile}><td>{label(r.profile)}</td><td>{r.ratings}</td><td>{r.naturalness}</td><td>{r.humanlike}</td><td>{r.mispronunciation}</td></tr>
                ))}</tbody>
              </table>
            </>
          )}
          <p><a href={ttsRatingsCsvUrl(session.id)} download>Puanları CSV olarak indir</a></p>
        </div>
      )}

      {sessions.length > 0 && (
        <>
          <h3 className="sub">Kayıtlı oturumlar</h3>
          <ul className="stt-runs">
            {sessions.map((s) => (
              <li key={s.id}>
                <span>{s.id} · {s.sentences} cümle · {s.models.join(", ")} · {s.clips} klip{s.phone ? " · telefon" : ""}</span>{" "}
                <button type="button" onClick={() => open(s.id)}>Aç</button>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

function Listener({ sessions }: { sessions: TtsSessionSummary[] }) {
  const [sid, setSid] = useState("");
  const [name, setName] = useState("");
  const [view, setView] = useState<BlindView | null>(null);
  const [index, setIndex] = useState(0);
  const [scores, setScores] = useState<BlindRating>({ naturalness: 3, humanlike: 3, mispronunciation: 0, comment: "" });
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { if (!sid && sessions.length) setSid(sessions[0].id); }, [sessions, sid]);

  async function begin() {
    setError(null);
    try {
      const v = await startListening(sid, name.trim());
      setView(v);
      const first = v.items.findIndex((it) => !it.rating);
      setIndex(first === -1 ? 0 : first);
    } catch (e) { setError((e as Error).message); }
  }

  const item = view?.items[index];
  useEffect(() => {
    setScores(item?.rating ?? { naturalness: 3, humanlike: 3, mispronunciation: 0, comment: "" });
  }, [item?.token]); // eslint-disable-line react-hooks/exhaustive-deps

  async function save() {
    if (!view || !item) return;
    setError(null);
    try {
      await rateClip(view.session, view.listener, item.token, scores);
      const items = view.items.map((it, i) => (i === index ? { ...it, rating: scores } : it));
      setView({ ...view, items, rated: items.filter((it) => it.rating).length });
      if (index < items.length - 1) setIndex(index + 1);
    } catch (e) { setError((e as Error).message); }
  }

  if (!view) {
    return (
      <div>
        <p className="meta">Model adları gizlidir; klipler her dinleyici için farklı rastgele sırada çalar.</p>
        <label>Oturum{" "}
          <select value={sid} onChange={(e) => setSid(e.target.value)} aria-label="Oturum">
            {sessions.map((s) => <option key={s.id} value={s.id}>{s.id} · {s.clips} klip</option>)}
          </select>
        </label>{" "}
        <label>Dinleyici adı{" "}
          <input value={name} onChange={(e) => setName(e.target.value)} aria-label="Dinleyici adı" maxLength={40} />
        </label>{" "}
        <button type="button" className="primary" disabled={!sid || !name.trim()} onClick={begin}>Dinlemeye başla</button>
        {!sessions.length && <p className="meta">Önce Stüdyo sekmesinden ses üretin.</p>}
        {error && <p role="alert" className="error">{error}</p>}
      </div>
    );
  }

  const done = view.rated === view.items.length;
  return (
    <div>
      <p className="meta">{view.listener} · {view.rated}/{view.items.length} puanlandı</p>
      {item && (
        <div className="stt-card">
          <h4>Klip {item.position} / {view.items.length}</h4>
          <p className="stt-text">“{item.sentence}”</p>
          <audio key={item.token} controls autoPlay src={blindAudioUrl(view.session, item.token, view.listener)} />
          {(Object.keys(LABELS) as (keyof typeof LABELS)[]).map((f) => (
            <label key={f} className="rate">
              <span>{LABELS[f][0]} <span className="meta">({LABELS[f][1]})</span></span>
              <input type="range" min={f === "mispronunciation" ? 0 : 1} max={5} step={1} value={scores[f]}
                aria-label={LABELS[f][0]} onChange={(e) => setScores({ ...scores, [f]: Number(e.target.value) })} />
              <strong>{scores[f]}</strong>
            </label>
          ))}
          <input value={scores.comment ?? ""} placeholder="Not (isteğe bağlı)" aria-label="Not"
            onChange={(e) => setScores({ ...scores, comment: e.target.value })} />
          <p>
            <button type="button" disabled={index === 0} onClick={() => setIndex(index - 1)}>Önceki</button>{" "}
            <button type="button" className="primary" onClick={save}>{index < view.items.length - 1 ? "Kaydet ve sonraki" : "Kaydet"}</button>
          </p>
        </div>
      )}
      {done && <p role="status" className="chip chip-ok">Tüm klipler puanlandı, teşekkürler.</p>}
      {error && <p role="alert" className="error">{error}</p>}
    </div>
  );
}
