import { useEffect, useState } from "react";
import { fetchFreeReply, setFreeReply, type FreeReplySettings as Settings } from "./api";

/** Ayarlar > Konu dışı serbest cevap (ADR 0009 adım 2). Konu dışı/meta sözlere sabit havuz yerine lokal Qwen kısa bir karşılık yazar;
 *  bekleyen soruyu kod okur. Model soğuksa, zaman aşımında ya da denetimden geçmezse havuz cümlesi konuşur. */
export function FreeReplySettings() {
  const [s, setS] = useState<Settings | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [model, setModel] = useState("");
  const [timeout, setTimeoutS] = useState("");

  const apply = (v: Settings) => {
    setS(v);
    setModel(v.model);
    setTimeoutS(String(v.timeout_s));
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
          {s.overridden.length > 0 && (
            <button type="button" onClick={() => save({ enabled: null, model: null, timeout_s: null })}>Varsayılana dön</button>
          )}
        </dd>
      </div>
      <p className="note">
        Soğuk modelde istek atılmaz (Qwen3 30B yüklemesi ~1 dk sürer): önce profil seçicideki Hazırla. Her tur kaydına cevabın kaynağı (qwen / pool) ve
        süresi yazılır. Kategoriler: {s.categories.join(", ")}. İstem {s.prompt.version} · {s.prompt.hash}.
      </p>
      <p className="note">Gerçek Qwen çıktısı bu PoC'de bulutta ölçülmedi; Mac'te <code>scripts/eval_free_reply.py</code> ile ölçülür.</p>
      {err && <p className="note err" role="alert">Değiştirilemedi: {err}</p>}
    </>
  );
}
