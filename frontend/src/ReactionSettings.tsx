import { useEffect, useState } from "react";
import { fetchReactions, setReactions, type ReactionSettings as Settings } from "./api";

/** Ayarlar > Cevaba bağlı tepkiler (hum-001 aç/kapa; docs/cevaba-bagli-tepki-ayari.md). Açıkken cevabın türüne göre havuzdan kısa tepki
 *  ("Ne güzel, bunu duymak iyi geldi."); kapalıyken hum-001 öncesi gibi persona onay sözleri sırayla. Havuz ve oran Persona ekranında saklı kalır. */
export function ReactionSettings() {
  const [s, setS] = useState<Settings | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    fetchReactions().then(setS).catch((e: Error) => setErr(e.message));
  }, []);

  const save = async (v: boolean | null) => {
    setErr(null);
    try {
      setS(await setReactions(v));
    } catch (e) {
      setErr((e as Error).message);
    }
  };

  if (!s) return err ? <p className="note err" role="alert">Yüklenemedi: {err}</p> : <p className="meta">Yükleniyor…</p>;
  const pools = Object.values(s.pool_sizes).reduce((a, b) => a + b, 0);
  return (
    <>
      <div className="setting">
        <dt>Cevaba bağlı tepkiler<span>Açık: her cevaptan sonra cevabın türüne göre (puan düşük/orta/yüksek, evet/hayır, diğer) kısa bir tepki, örneğin "Ne güzel, bunu duymak iyi geldi."; aynı aramada tekrar etmez, tepki oranı %{Math.round(s.reaction_rate * 100)}. Kapalı: eski sabit onay, persona onay sözleri sırayla ({s.acknowledgements.join(" · ") || "liste boş: onay söylenmez"}), oran uygulanmaz. Realtime profillerde uygulanmaz.</span></dt>
        <dd>
          <label>
            <input type="checkbox" checked={s.enabled} onChange={(e) => save(e.target.checked)} aria-label="Cevaba bağlı tepkiler" /> {s.enabled ? "Açık" : "Kapalı"}
          </label>
          {s.overridden && <button type="button" onClick={() => save(null)}>Varsayılana dön</button>}
        </dd>
      </div>
      <p className="note">
        Tepki havuzu ({pools} cümle) ve oranı Persona ekranında düzenlenir; kapatınca silinmez, açınca aynen geri gelir. Müşterinin söylediğine bağlı
        kısa yanıt ve empati (şikayet, cevapla birlikte sorulan soru) bu ayardan bağımsızdır. Açık arama başladığı ayarla sürer; her arama kaydı
        ayarın değerini, her tur kaydı tepkinin kaynağını (havuz / sabit onay / bağlam / atlandı) yazar.
      </p>
      {err && <p className="note err" role="alert">Değiştirilemedi: {err}</p>}
    </>
  );
}
