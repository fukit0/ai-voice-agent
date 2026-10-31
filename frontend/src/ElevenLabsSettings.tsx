import { useEffect, useState } from "react";
import { fetchElevenModels, setTtsModel, setTtsStreaming, type ElevenModel } from "./api";
import { useProfile } from "./ProfileContext";

/** Ayarlar > Ses (ElevenLabs): aktif profilin ElevenLabs modeli ve akışlı TTS. Seçim kalıcıdır, yeni aramalara uygulanır. */
export function ElevenLabsSettings() {
  const { active, refresh } = useProfile();
  const [models, setModels] = useState<ElevenModel[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const eleven = active?.components.tts?.provider === "elevenlabs";

  useEffect(() => {
    if (!eleven) return;
    const ctrl = new AbortController();
    fetchElevenModels(ctrl.signal)
      .then(setModels)
      .catch((e: Error) => {
        if (!ctrl.signal.aborted) setErr(e.message);
      });
    return () => ctrl.abort();
  }, [eleven]);

  if (!active) return <p className="meta">Profil yüklenmedi.</p>;
  if (!eleven) return <p className="meta">{active.id} profilinde ElevenLabs TTS yok; bu ayarlar yalnızca ElevenLabs'li profillerde (örn. L2-EL, A1, A1S) görünür.</p>;

  const current = active.components.tts?.model ?? "";
  const run = async (fn: () => Promise<void>) => {
    setErr(null);
    try {
      await fn();
      refresh();
    } catch (e) {
      setErr((e as Error).message);
    }
  };

  return (
    <>
      <div className="setting">
        <dt>ElevenLabs modeli<span>Aktif profil ({active.id}) için. Fiyat 1.000 karakter başınadır; TTS toplam maliyetin büyük kısmıdır.</span></dt>
        <dd>
          <select value={current} onChange={(e) => run(() => setTtsModel(active.id, e.target.value))} aria-label="ElevenLabs modeli">
            {models.length === 0 && <option value={current}>{current}</option>}
            {models.map((m) => (
              <option key={m.id} value={m.id}>
                {m.label} · ${m.price_per_1k_usd}/1k karakter{m.id === (active.tts_default_model ?? current) ? " (varsayılan)" : ""}
              </option>
            ))}
          </select>
          {active.tts_default_model && (
            <button type="button" onClick={() => run(() => setTtsModel(active.id, active.tts_default_model as string))}>Varsayılana dön</button>
          )}
        </dd>
      </div>
      <div className="setting">
        <dt>Akışlı TTS<span>Ses cümle bitmeden parça parça çalınır; ilk ses daha erken gelir. İlk parçadan önce hata olursa cümle akışsız üretilir.</span></dt>
        <dd>
          <label>
            <input type="checkbox" checked={!!active.tts_streaming} onChange={(e) => run(() => setTtsStreaming(active.id, e.target.checked))} aria-label="Akışlı TTS" />{" "}
            {active.tts_streaming ? "Açık" : "Kapalı"}
          </label>
        </dd>
      </div>
      {err && <p className="note err" role="alert">Değiştirilemedi: {err}</p>}
    </>
  );
}
