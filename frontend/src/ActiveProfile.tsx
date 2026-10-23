import { useProfile } from "./ProfileContext";

const LABELS = { stt: "STT", llm: "LLM", tts: "TTS" } as const;

// Ekranın kullanacağı modelleri ve profilin eksiklerini gösterir.
export function ActiveProfile() {
  const { active } = useProfile();
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
            return (
              <div key={k}>
                <dt>{LABELS[k]}</dt>
                <dd>{c ? `${c.provider}${c.model ? ` · ${c.model}` : ""}` : "yok"}</dd>
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
      {active.notes && <p className="meta">{active.notes}</p>}
    </div>
  );
}
