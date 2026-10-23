import { useProfile } from "./ProfileContext";

const LABELS = { stt: "STT", llm: "LLM", tts: "TTS" } as const;

// Ekranın kullanacağı modelleri ve profilin eksiklerini gösterir.
function fmt(s?: number) {
  return s === undefined ? "" : s < 1 ? `${Math.round(s * 1000)} ms` : `${s.toFixed(1)} sn`;
}

export function ActiveProfile() {
  const { active, job } = useProfile();
  if (!active) return null;
  return (
    <div className="profile-card" data-testid="active-profile">
      <p className="profile-title">
        <strong>
          {active.id} · {active.name}
        </strong>
        {active.purpose ? <span className="meta"> — {active.purpose}</span> : null}
      </p>
      {active.mode === "realtime" && active.realtime ? (
        <p>
          Realtime: {active.realtime.provider} · {active.realtime.model}
        </p>
      ) : (
        <dl className="components">
          {(Object.keys(LABELS) as (keyof typeof LABELS)[]).map((k) => {
            const c = active.components[k];
            const w = job?.components[k];
            return (
              <div key={k}>
                <dt>
                  {LABELS[k]} {c ? <span className={c.warm ? "dot dot-ok" : "dot"} aria-label={c.warm ? "sıcak" : "soğuk"} /> : null}
                </dt>
                <dd>{c ? `${c.provider}${c.model ? ` · ${c.model}` : ""}` : "yok"}</dd>
                {(w?.state === "ready" || w?.state === "degraded") && (
                  <dd className={w.state === "degraded" ? "warn" : "meta"}>
                    sıcak çağrı {fmt(w.warm_seconds)} · ilk yükleme {fmt(w.load_seconds)}
                    {w.final_seconds !== undefined ? ` · hepsi yüklüyken ${fmt(w.final_seconds)}` : ""}
                  </dd>
                )}
                {w?.state === "failed" && <dd className="warn">{w.error}</dd>}
              </div>
            );
          })}
        </dl>
      )}
      {active.missing_env.length > 0 && (
        <p className="warn" role="alert">
          Eksik API anahtarı: {active.missing_env.join(", ")} — .env dosyasına ekleyip backend'i yeniden başlatın.
        </p>
      )}
      {active.issues.map((i) => (
        <p className="warn" key={i}>
          {i}
        </p>
      ))}
      {job?.state === "degraded" && job.error && (
        <p className="warn" data-testid="degraded-warning">
          {job.error}
        </p>
      )}
      {!active.warm && active.mode === "cascade" && job?.state !== "degraded" && (
        <p className="warn" data-testid="cold-warning">
          Profil soğuk: ölçümler production koşullarında olsun diye önce "Hazırla" ile modelleri yükleyin.
        </p>
      )}
      {job?.evicted?.length ? <p className="meta">Bellekten çıkarılan: {job.evicted.join(", ")}</p> : null}
      {active.notes && <p className="meta">{active.notes}</p>}
    </div>
  );
}
