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
      <tbody>{row("Kapalı", stats.off)}{row("Açık", stats.on)}</tbody>
    </table>
  );
}

/** Ayarlar > Konu dışı serbest cevap (ADR 0009 adım 2). Konu dışı/meta sözlere sabit havuz yerine lokal Qwen kısa bir karşılık yazar;
 *  bekleyen soruyu kod okur. Model soğuksa, zaman aşımında ya da denetimden geçmezse havuz cümlesi konuşur. */
export function FreeReplySettings() {
  const [s, setS] = useState<Settings | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [model, setModel] = useState("");
  const [timeout, setTimeoutS] = useState("");
  const [thinkModel, setThinkModel] = useState("");
  const [thinkTimeout, setThinkTimeout] = useState("");

  const apply = (v: Settings) => {
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
  return (
    <>
      <div className="setting">
        <dt>Serbest cevap (lokal Qwen)<span>Yalnız konu dışı ve karşı soru turlarında ("sende kaç puan vereyim", "bunu neden soruyorsunuz", "hava nasıl"). Cevap, ret, DNC, geri arama ve hızlı yol turlarında çağrılmaz. Realtime profillerde uygulanmaz.</span></dt>
        <dd>
          <label>
            <input type="checkbox" checked={s.enabled} onChange={(e) => save({ enabled: e.target.checked })} aria-label="Serbest cevap" /> {s.enabled ? "Açık" : "Kapalı"}
          </label>
        </dd>
      </div>
      <div className="setting">
        <dt>Model<span>Ollama model adı; L2 ayrıştırıcısıyla aynı model bellekte tek kopya kalır.</span></dt>
        <dd>
          <input value={model} onChange={(e) => setModel(e.target.value)} aria-label="Serbest cevap modeli" size={36} />
          <button type="button" disabled={!model.trim() || model === s.model} onClick={() => save({ model: model.trim() })}>Kaydet</button>
          {pill}
        </dd>
      </div>
      <div className="setting">
        <dt>Zaman aşımı (sn)<span>Bu sürede cevap gelmezse havuz cümlesi konuşur. Aralık {lo}–{hi} sn.</span></dt>
        <dd>
          <input value={timeout} onChange={(e) => setTimeoutS(e.target.value)} aria-label="Serbest cevap zaman aşımı" size={5} inputMode="decimal" />
          <button type="button" disabled={!timeoutOk || t === s.timeout_s} onClick={() => save({ timeout_s: t })}>Kaydet</button>
          {s.overridden.some((k) => !THINKING_KEYS.includes(k)) && (
            <button type="button" onClick={() => save({ enabled: null, model: null, timeout_s: null })}>Varsayılana dön</button>
          )}
        </dd>
      </div>
      {hasThinking && (
        <>
          <div className="setting">
            <dt>Qwen thinking (yalnız ölçüm, yavaşlatır)<span>Açıkken serbest cevap ayrı thinking modeliyle ve düşünme açık (think) istenir; düşünme metni ayıklanır, yalnız son cevap denetlenip söylenir. Serbest cevap kapalıysa etkisizdir (Qwen çağrılmaz). Amaç gecikme farkını ölçmek.</span></dt>
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
              Son {s.stats.turns} serbest cevap turu (en çok {s.stats.last}; süre uçtan uca, yalnız Qwen'e istek giden turlar):
              <ThinkingStats stats={s.stats} />
            </div>
          )}
        </>
      )}
      <p className="note">
        Soğuk modelde istek atılmaz (Qwen3 30B yüklemesi ~1 dk sürer): önce profil seçicideki Hazırla. Her tur kaydına cevabın kaynağı (qwen / pool) ve
        süresi yazılır. Kategoriler: {s.categories.join(", ")}. İstem {s.prompt.version} · {s.prompt.hash}.
      </p>
      <p className="note">Gerçek Qwen çıktısı bu PoC'de bulutta ölçülmedi; Mac'te <code>scripts/eval_free_reply.py</code> ile ölçülür.</p>
      {err && <p className="note err" role="alert">Değiştirilemedi: {err}</p>}
    </>
  );
}
