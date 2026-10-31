import { useState } from "react";
import { Link } from "react-router-dom";
import { setFastPath } from "./api";
import { useProfile } from "./ProfileContext";

/** Ayarlar > Cevap anlama: hızlı yol (kapalı sözlükte LLM'siz). Açık/kapalı aramalar kayda ayrı yazılır ve Aramalar > Kıyas'ta ayrı görünür. */
export function FastPathSettings() {
  const { active, refresh } = useProfile();
  const [err, setErr] = useState<string | null>(null);
  if (!active) return <p className="meta">Profil yüklenmedi.</p>;
  if (active.mode !== "cascade") return <p className="meta">{active.id} realtime profil: cevabı tek model anlar, hızlı yol uygulanmaz.</p>;
  const on = !!active.fast_path;
  const change = async (value: boolean) => {
    setErr(null);
    try {
      await setFastPath(active.id, value);
      refresh();
    } catch (e) {
      setErr((e as Error).message);
    }
  };
  return (
    <>
      <div className="setting">
        <dt>Hızlı yol (LLM'siz)<span>Cevabın tamamı kapalı sözlükle eşleşiyorsa ("evet", "hayır", "tamam olur", "9", "on", "sekiz puan veriyorum") LLM çağrılmaz; kural çözer ve aynı doğrulamalardan geçer. Eşleşmezse LLM devreye girer.</span></dt>
        <dd>
          <label>
            <input type="checkbox" checked={on} onChange={(e) => change(e.target.checked)} aria-label="Hızlı yol" /> {on ? "Açık" : "Kapalı"}
          </label>
          {active.fast_path_default != null && (
            <button type="button" onClick={async () => { setErr(null); try { await setFastPath(active.id, null); refresh(); } catch (e) { setErr((e as Error).message); } }}>Varsayılana dön</button>
          )}
        </dd>
      </div>
      <p className="note">
        Aktif profil: {active.id}. Ayar yeni aramalara ve kıyas koşularına uygulanır. Her arama hangi ayarla yapıldığını kendi kaydına yazar; farkı
        <Link to="/calls"> Aramalar › Kıyas › "Profil + hızlı yol"</Link> görünümünde açık ve kapalı ölçümleri ayrı satırlarda görürsün.
      </p>
      <p className="note">Doğruluk: etiketli 193 örnekte kural yolu 0 yanlış verdi, ama bu örneklerin yalnız 23'ünü (%12) çözdü; gerçek aramalarda kapsam daha yüksek olabilir (ölçülmedi, bkz. kıyas ekranı "LLM'siz tur"). Açıkken profilin LLM doğruluk ölçümü olduğundan iyi görünebilir, çünkü kapalı sözlük cevapları LLM'e hiç gitmez.</p>
      {err && <p className="note err" role="alert">Değiştirilemedi: {err}</p>}
    </>
  );
}
