import { useProfile } from "./ProfileContext";

export function ProfileSelector() {
  const { profiles, active, setActiveId, error } = useProfile();
  if (error) return <span className="status status-error">Profiller yüklenemedi ({error})</span>;
  if (!profiles.length) return <span className="status">Profiller yükleniyor…</span>;
  return (
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
  );
}
