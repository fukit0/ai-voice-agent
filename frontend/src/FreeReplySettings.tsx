import { useEffect, useState } from "react";
import { fetchFreeReply, setFreeReply, type FreeReplySettings as Settings, type FreeReplyStatsGroup } from "./api";

const THINKING_KEYS = ["thinking", "thinking_model", "thinking_timeout_s"];
const sec = (v: number | null) => (v == null ? "–" : `${v.toFixed(2)} sn`);
const pct = (v: number | null) => (v == null ? "–" : `%${Math.round(v * 100)}`);

/** Thinking açık/kapalı kıyası: son N serbest cevap turu (oturum kayıtlarından). Süre yalnız LLM'e istek giden turlardan. */
function ThinkingStats({ stats }: { stats: NonNullable<Settings["stats"]> }) {
  const row = (label: string, g: FreeReplyStatsGroup) => (
    <tr key={label}>
      <td>{label}</td><td>{g.turns}</td><td>{sec(g.mean_s)}</td><td>{sec(g.p50_s)}</td><td>{sec(g.p95_s)}</td><td>{pct(g.fallback_rate)}</td>
      <td>{Object.entries(g.fallback_reasons).map(([k, n]) => `${k} ${n}`).join(", ") || "–"}</td>
    </tr>
  );
  return (
    <table className="calls-table small" aria-label="Thinking kıyası">
      <thead><tr><th>Thinking</th><th>Tur</th><th>Ort.</th><th>p50</th><th>p95</th><th>Havuza düşüş</th><th>Sebep</th></tr></thead>
      <tbody>{row("Kapalı", stats.off)}{row("Açık", stats.on)}{stats.haiku && stats.haiku.turns > 0 && row("Haiku (düşünme yok)", stats.haiku)}</tbody>
    </table>
  );
}


/** off-004 (docs/serbest-cevap-genis-kapsam.md): kullanıcının yazdığı tam sistem istemi. Boş = varsayılan. Sabit çerçeve ve bilinen
 *  gerçekler her istemin sonuna eklenir; çıktı denetimi istemden bağımsızdır ve buradan kapatılamaz. */
function PromptEditor({ s, save }: { s: Settings; save: (p: Parameters<typeof setFreeReply>[0]) => Promise<void> }) {
  const saved = s.system_prompt ?? s.default_system_prompt ?? "";
  const [text, setText] = useState(saved);
  const [fallback, setFallback] = useState(s.fallback_text ?? "");
  const [preview, setPreview] = useState(false);
  useEffect(() => setText(s.system_prompt ?? s.default_system_prompt ?? ""), [s.system_prompt, s.default_system_prompt]);
  useEffect(() => setFallback(s.fallback_text ?? ""), [s.fallback_text]);
  const max = s.system_prompt_max ?? 4000;
  const fmax = s.fallback_text_max ?? 200;
  const tooLong = text.length > max;
  const dirty = text !== saved;
  const custom = !!s.prompt.custom;
  const never = (s.never_llm ?? ["identity", "hold", "support"]).join(", ");
  return (
    <>
      <div className="setting">
        <dt>Geniş kapsam (havuz yalnız yedek)<span>Açıkken LLM, anket cevabı olmayan HER turda konuşur: konu dışı, meta (kim arıyor, numara, kayıt, süre, amaç), sohbet ve akışın soruya cevap olarak anlayamadığı söz ("tam anlayamadım" yerine). LLM şu turlarda ÇALIŞMAZ: cevap, ret, DNC, geri arama, hızlı yol, realtime profiller ve sabit metinli {never}. Arka uçlar: {(s.wide_scope_backends ?? ["haiku"]).join(", ")} (Qwen ölçümü uydurma gösterdiği için config'te kapalı).</span></dt>
        <dd>
          <label>
            <input type="checkbox" checked={s.use_pool_fallback_only !== false} onChange={(e) => save({ use_pool_fallback_only: e.target.checked })}
              aria-label="Geniş kapsam" /> {s.use_pool_fallback_only !== false ? "Açık" : "Kapalı (eski kategori listesi)"}
          </label>
        </dd>
      </div>
      <div className="setting prompt-setting">
        <dt>Sistem istemi{custom ? <span className="pill warn">Özel istem</span> : <span className="pill ok">Varsayılan</span>}
          <span>Model bu metni aynen alır. {"{ASISTAN}"}, {"{MAX}"}, {"{WORDS}"} yer tutucuları doldurulur. Müşteri sözü her zaman ayrı ve etiket içinde VERİ olarak gider. Boş kaydederseniz varsayılana döner. Güvenlik denetimi (iade/indirim/ücret vaadi, istem sızıntısı, web adresi, uydurma telefon/adres, ad uydurma, yabancı dil, aşırı uzunluk) istemden bağımsızdır ve kapatılamaz: denetimden geçmeyen cümle söylenmez.</span></dt>
        <dd className="prompt-dd">
          <textarea value={text} onChange={(e) => setText(e.target.value)} aria-label="Sistem istemi" rows={14} spellCheck={false}
            style={{ width: "100%", fontFamily: "var(--mono, monospace)", fontSize: 13 }} />
          <div className="prompt-actions">
            <span className={tooLong ? "pill err" : "meta"} aria-label="Karakter sayısı">{text.length} / {max}</span>
            <button type="button" disabled={!dirty || tooLong} onClick={() => save({ system_prompt: text.trim() ? text : null })}>Kaydet</button>
            <button type="button" disabled={!dirty} onClick={() => setText(saved)}>Geri al</button>
            <button type="button" disabled={!custom} onClick={() => save({ system_prompt: null })}>Varsayılana sıfırla</button>
            <button type="button" onClick={() => setPreview((v) => !v)} aria-expanded={preview}>{preview ? "Önizlemeyi gizle" : "Etkin istemi göster"}</button>
          </div>
          {preview && (
            <pre className="note" aria-label="Etkin istem" style={{ whiteSpace: "pre-wrap" }}>{s.effective_system_prompt}</pre>
          )}
          <p className="meta">Sabit çerçeve (değiştirilemez): {s.frame}</p>
        </dd>
      </div>
      <div className="setting">
        <dt>LLM yedek cümlesi<span>LLM hata verirse, zaman aşımına düşerse, anahtar yoksa ya da cümlesi denetimden geçmezse söylenir; ardından anket sorusu okunur. Kayıt/numara/amaç/süre gibi bilgi sorularında bunun yerine gözden geçirilmiş sabit cevap konuşur. En fazla {fmax} karakter.</span></dt>
        <dd>
          <input value={fallback} onChange={(e) => setFallback(e.target.value)} aria-label="LLM yedek cümlesi" size={48} maxLength={fmax} />
          <button type="button" disabled={fallback === (s.fallback_text ?? "")} onClick={() => save({ fallback_text: fallback.trim() || null })}>Kaydet</button>
        </dd>
      </div>
    </>
  );
}

const HAIKU_KEYS = ["backend", "haiku_model", "haiku_timeout_s"];
const BACKEND_LABEL: Record<string, string> = {
  auto: "Otomatik (profilin LLM'ine göre)",
  haiku: "Claude Haiku (API)",
  qwen: "Lokal Qwen (Ollama)",
};

/** Ayarlar > Konu dışı serbest cevap (ADR 0009 adım 2). Konu dışı/meta sözlere sabit havuz yerine lokal Qwen kısa bir karşılık yazar;
 *  bekleyen soruyu kod okur. Model soğuksa, zaman aşımında ya da denetimden geçmezse havuz cümlesi konuşur. */
export function FreeReplySettings() {
  const [s, setS] = useState<Settings | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [model, setModel] = useState("");
  const [timeout, setTimeoutS] = useState("");
  const [thinkModel, setThinkModel] = useState("");
  const [thinkTimeout, setThinkTimeout] = useState("");
  const [haikuModel, setHaikuModel] = useState("");
  const [haikuTimeout, setHaikuTimeout] = useState("");

  const apply = (v: Settings) => {
    setHaikuModel(v.haiku_model ?? "");
    setHaikuTimeout(v.haiku_timeout_s == null ? "" : String(v.haiku_timeout_s));
    setS(v);
    setModel(v.model);
    setTimeoutS(String(v.timeout_s));
    setThinkModel(v.thinking_model ?? "");
    setThinkTimeout(v.thinking_timeout_s == null ? "" : String(v.thinking_timeout_s));
  };
  useEffect(() => {
    fetchFreeReply().then(apply).catch((e: Error) => setErr(e.message));
  }, []);

  const save = async (patch: Parameters<typeof setFreeReply>[0]) => {
    setErr(null);
    try {
      apply(await setFreeReply(patch));
    } catch (e) {
      setErr((e as Error).message);
    }
  };

  if (!s) return err ? <p className="note err" role="alert">Yüklenemedi: {err}</p> : <p className="meta">Yükleniyor…</p>;
  const st = s.status;
  const pill = !st ? null : !st.reachable
    ? <span className="pill err">Ollama'ya ulaşılamıyor → havuz</span>
    : st.warm ? <span className="pill ok">Sıcak</span> : <span className="pill warn">Soğuk → havuz (Hazırla ile yükleyin)</span>;
  const [lo, hi] = s.timeout_range;
  const t = Number(timeout.replace(",", "."));
  const timeoutOk = Number.isFinite(t) && t >= lo && t <= hi;
  const hasThinking = s.thinking !== undefined;          // eski backend: thinking satırı gösterilmez
  const [tlo, thi] = s.thinking_timeout_range ?? [1, 30];
  const tt = Number(thinkTimeout.replace(",", "."));
  const thinkTimeoutOk = Number.isFinite(tt) && tt >= tlo && tt <= thi;
  const ts = s.thinking_status;
  const thinkPill = !s.thinking || !ts ? null : !ts.reachable
    ? <span className="pill err">Ollama'ya ulaşılamıyor → havuz</span>
    : ts.warm ? <span className="pill ok">Sıcak</span> : <span className="pill warn">Thinking modeli soğuk → havuz</span>;
  const hasBackend = s.backend !== undefined;            // eski backend: arka uç satırları gösterilmez
  const [hlo, hhi] = s.haiku_timeout_range ?? [0.3, 5];
  const ht = Number(haikuTimeout.replace(",", "."));
  const haikuTimeoutOk = Number.isFinite(ht) && ht >= hlo && ht <= hhi;
  const hs = s.haiku_status;
  const keyPill = !hs ? null : hs.key_present
    ? <span className="pill ok">Anahtar var</span>
    : <span className="pill warn">ANTHROPIC_API_KEY yok → havuz</span>;
  return (
    <>
      <div className="setting">
        <dt>Serbest cevap<span>Anket cevabı olmayan turlarda LLM müşterinin söylediğine anlamlı, kısa bir cevap verir; anket sorusunu kod ayrıca okur ve müşterinin cevabı LLM cümlesinden asla kaydedilmez. Cevap, ret, DNC, geri arama ve hızlı yol turlarında çağrılmaz. Realtime profillerde (A2/A3) uygulanmaz.</span></dt>
        <dd>
          <label>
            <input type="checkbox" checked={s.enabled} onChange={(e) => save({ enabled: e.target.checked })} aria-label="Serbest cevap" /> {s.enabled ? "Açık" : "Kapalı"}
          </label>
        </dd>
      </div>
      {s.default_system_prompt !== undefined && <PromptEditor s={s} save={save} />}
      {hasBackend && (
        <>
          <div className="setting">
            <dt>Arka uç<span>Otomatik: aramanın profilindeki LLM Anthropic ise (A1, A1S) Claude Haiku, Ollama ise (L1–L5) lokal Qwen. Haiku ve Qwen aynı istemi, aynı denetimi ve aynı havuza düşüşü kullanır.</span></dt>
            <dd>
              <select value={s.backend} onChange={(e) => save({ backend: e.target.value as NonNullable<Settings["backend"]> })} aria-label="Serbest cevap arka ucu">
                {(s.backends ?? ["auto", "haiku", "qwen"]).map((b) => <option key={b} value={b}>{BACKEND_LABEL[b] ?? b}</option>)}
              </select>
            </dd>
          </div>
          <div className="setting">
            <dt>Haiku modeli<span>Boş bırakılırsa profilin LLM modeli kullanılır (A1S: {s.haiku_default_model ?? "claude-haiku-5-5"}). Düşünme her zaman kapalı; token sınırı {s.haiku_max_tokens ?? "–"} (config). Soğuk model yok; anahtar yoksa istek atılmadan havuz konuşur.</span></dt>
            <dd>
              <input value={haikuModel} onChange={(e) => setHaikuModel(e.target.value)} aria-label="Haiku modeli" size={28}
                placeholder={`profilden (${s.haiku_default_model ?? "claude-haiku-5-5"})`} />
              <button type="button" disabled={haikuModel.trim() === (s.haiku_model ?? "")}
                onClick={() => save({ haiku_model: haikuModel.trim() || null })}>Kaydet</button>
              {keyPill}
            </dd>
          </div>
          <div className="setting">
            <dt>Haiku zaman aşımı (sn)<span>Bu sürede cevap gelmezse havuz cümlesi konuşur. Varsayılan 2,5 sn ölçüme dayanır (2026-11-03 Haiku serbest cevap ölçümü: p95 1,96 sn, en yavaş 2,06 sn; 2,0 sn sınırında 102 turdan 4'ü zaman aşımına düştü). Aralık {hlo}–{hhi} sn.</span></dt>
            <dd>
              <input value={haikuTimeout} onChange={(e) => setHaikuTimeout(e.target.value)} aria-label="Haiku zaman aşımı" size={5} inputMode="decimal" />
              <button type="button" disabled={!haikuTimeoutOk || ht === s.haiku_timeout_s} onClick={() => save({ haiku_timeout_s: ht })}>Kaydet</button>
              {s.overridden.some((k) => HAIKU_KEYS.includes(k)) && (
                <button type="button" onClick={() => save({ backend: null, haiku_model: null, haiku_timeout_s: null })}>Arka ucu varsayılana dön</button>
              )}
            </dd>
          </div>
        </>
      )}
      <div className="setting">
        <dt>Qwen modeli<span>Ollama model adı; L2 ayrıştırıcısıyla aynı model bellekte tek kopya kalır. Yalnız Qwen arka ucunda kullanılır.</span></dt>
        <dd>
          <input value={model} onChange={(e) => setModel(e.target.value)} aria-label="Serbest cevap modeli" size={36} />
          <button type="button" disabled={!model.trim() || model === s.model} onClick={() => save({ model: model.trim() })}>Kaydet</button>
          {pill}
        </dd>
      </div>
      <div className="setting">
        <dt>Qwen zaman aşımı (sn)<span>Bu sürede cevap gelmezse havuz cümlesi konuşur. Aralık {lo}–{hi} sn.</span></dt>
        <dd>
          <input value={timeout} onChange={(e) => setTimeoutS(e.target.value)} aria-label="Serbest cevap zaman aşımı" size={5} inputMode="decimal" />
          <button type="button" disabled={!timeoutOk || t === s.timeout_s} onClick={() => save({ timeout_s: t })}>Kaydet</button>
          {s.overridden.some((k) => !THINKING_KEYS.includes(k) && !HAIKU_KEYS.includes(k)) && (
            <button type="button" onClick={() => save({ enabled: null, model: null, timeout_s: null })}>Varsayılana dön</button>
          )}
        </dd>
      </div>
      {hasThinking && (
        <>
          <div className="setting">
            <dt>Qwen thinking (yalnız ölçüm, yavaşlatır)<span>Açıkken serbest cevap ayrı thinking modeliyle ve düşünme açık (think) istenir; düşünme metni ayıklanır, yalnız son cevap denetlenip söylenir. Serbest cevap kapalıysa ya da arka uç Haiku ise etkisizdir. Amaç gecikme farkını ölçmek.</span></dt>
            <dd>
              <label>
                <input type="checkbox" checked={!!s.thinking} onChange={(e) => save({ thinking: e.target.checked })} aria-label="Qwen thinking" /> {s.thinking ? "Açık" : "Kapalı"}
              </label>
              {s.thinking && <span className="pill warn">Gecikme belirgin artar: canlı demoda kapalı tutun</span>}
            </dd>
          </div>
          <div className="setting">
            <dt>Thinking modeli<span>Mac'te <code>ollama list</code> ile var olduğunu doğrulayın; bellekte değilse (soğuk) havuz konuşur. Token sınırı {s.thinking_max_tokens ?? "–"} (config).</span></dt>
            <dd>
              <input value={thinkModel} onChange={(e) => setThinkModel(e.target.value)} aria-label="Thinking modeli" size={36} />
              <button type="button" disabled={!thinkModel.trim() || thinkModel === s.thinking_model} onClick={() => save({ thinking_model: thinkModel.trim() })}>Kaydet</button>
              {thinkPill}
            </dd>
          </div>
          <div className="setting">
            <dt>Thinking zaman aşımı (sn)<span>Yalnız thinking açıkken geçerli (ölçüm için uzun). Aralık {tlo}–{thi} sn.</span></dt>
            <dd>
              <input value={thinkTimeout} onChange={(e) => setThinkTimeout(e.target.value)} aria-label="Thinking zaman aşımı" size={5} inputMode="decimal" />
              <button type="button" disabled={!thinkTimeoutOk || tt === s.thinking_timeout_s} onClick={() => save({ thinking_timeout_s: tt })}>Kaydet</button>
              {s.overridden.some((k) => THINKING_KEYS.includes(k)) && (
                <button type="button" onClick={() => save({ thinking: null, thinking_model: null, thinking_timeout_s: null })}>Thinking varsayılana dön</button>
              )}
            </dd>
          </div>
          {s.stats && (
            <div className="note">
              Son {s.stats.turns} serbest cevap turu (en çok {s.stats.last}; süre uçtan uca, yalnız LLM'e istek giden turlar)
              {s.stats.haiku?.cost_usd_total != null && ` · Haiku tahmini maliyet ${s.stats.haiku.cost_usd_total.toFixed(4)} USD`}:
              <ThinkingStats stats={s.stats} />
            </div>
          )}
        </>
      )}
      <p className="note">
        Qwen: soğuk modelde istek atılmaz (Qwen3 30B yüklemesi ~1 dk sürer): önce profil seçicideki Hazırla. Her tur kaydına cevabın kaynağı (qwen / haiku / pool),
        süresi ve Haiku'da token ile tahmini maliyet yazılır. Kategoriler: {s.categories.join(", ")}. İstem {s.prompt.version} · {s.prompt.hash}{s.prompt.custom ? " (özel)" : ""}.
      </p>
      <p className="note">Mac'te ölçüm: <code>scripts/eval_free_reply.py --runs 3</code> (Qwen) ve <code>--backend haiku</code> (Haiku). Haiku serbest cevabı gerçek API ile henüz ölçülmedi.</p>
      {err && <p className="note err" role="alert">Değiştirilemedi: {err}</p>}
    </>
  );
}
