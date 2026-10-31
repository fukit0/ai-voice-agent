import { useEffect, useState } from "react";
import { fetchElevenModels, setTtsModel, type ElevenModel } from "./api";
import { useProfile } from "./ProfileContext";

export function ProfileSelector() {
  const { profiles, active, setActiveId, error, refresh } = useProfile();
  const [models, setModels] = useState<ElevenModel[]>([]);
  const [modelError, setModelError] = useState<string | null>(null);
  const eleven = active?.components.tts?.provider === "elevenlabs";

  useEffect(() => {
    if (!eleven) return;
    const ctrl = new AbortController();
    fetchElevenModels(ctrl.signal)
      .then(setModels)
      .catch((err: Error) => {
        if (!ctrl.signal.aborted) setModelError(err.message);
      });
    return () => ctrl.abort();
  }, [eleven]);

  if (error) return <span className="status status-error">Profiller yüklenemedi ({error})</span>;
  if (!profiles.length) return <span className="status">Profiller yükleniyor…</span>;

  const current = active?.components.tts?.model ?? "";
  const changed = !!active?.tts_default_model;
  const onModel = async (model: string) => {
    if (!active) return;
    setModelError(null);
    try {
      await setTtsModel(active.id, model);
      refresh();
    } catch (err) {
      setModelError((err as Error).message);
    }
  };

  return (
    <>
      <label className="profile-select">
        Profil
        <select value={active?.id ?? ""} onChange={(e) => setActiveId(e.target.value)} aria-label="Profil">
          {profiles.map((p) => (
            <option key={p.id} value={p.id}>
              {p.id} · {p.name}
              {p.missing_env.length ? " (anahtar eksik)" : ""}
            </option>
          ))}
        </select>
      </label>
      {eleven && models.length > 0 && (
        <label className="profile-select">
          ElevenLabs modeli
          <select value={current} onChange={(e) => onModel(e.target.value)} aria-label="ElevenLabs modeli">
            {models.map((m) => (
              <option key={m.id} value={m.id}>
                {m.label} · ${m.price_per_1k_usd}/1k karakter{m.id === (active?.tts_default_model ?? current) ? " (varsayılan)" : ""}
              </option>
            ))}
          </select>
          {changed && (
            <button type="button" onClick={() => onModel(active!.tts_default_model!)} title="Profilin varsayılan modeline dön">
              Varsayılana dön
            </button>
          )}
        </label>
      )}
      {modelError && <span className="status status-error">Model değiştirilemedi ({modelError})</span>}
    </>
  );
}
