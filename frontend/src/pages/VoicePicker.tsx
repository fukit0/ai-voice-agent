import { useEffect, useState } from "react";
import { addLibraryVoice, assignVoices, fetchVoices, type VoiceRow } from "../api";

const TONES: { id: string; label: string }[] = [
  { id: "samimi", label: "Samimi" }, { id: "resmi", label: "Resmî" }, { id: "enerjik", label: "Enerjik" }, { id: "sakin", label: "Sakin" },
];

// ElevenLabs ses seçici: Türkçe sesleri dinle, her ton için ayrı ses ata. Ses değişimi ton farkını model ayarlarından daha çok büyütür.
// Kütüphane sesi kullanılmadan önce hesaba eklenmelidir (ekleme çağrısı gerçek hesapla henüz doğrulanmadı); ticari lisans kontrol edilmelidir.
export function VoicePicker() {
  const [voices, setVoices] = useState<VoiceRow[]>([]);
  const [assigned, setAssigned] = useState<Record<string, string>>({});
  const [search, setSearch] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  const load = async (q = search) => {
    setBusy(true); setMsg(null);
    try {
      const r = await fetchVoices(q);
      setVoices(r.voices); setAssigned(r.assigned);
    } catch (e) { setMsg({ kind: "err", text: String((e as Error).message ?? e) }); }
    finally { setBusy(false); }
  };
  useEffect(() => { void load(""); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const assign = async (tone: string, voiceId: string) => {
    try {
      setAssigned((await assignVoices({ [tone]: voiceId })).assigned);
      setMsg({ kind: "ok", text: voiceId ? "Ses atandı. Bir sonraki ton demosu ve arama bu sesi kullanır." : "Atama kaldırıldı (genel ses)." });
    } catch (e) { setMsg({ kind: "err", text: String((e as Error).message ?? e) }); }
  };

  const add = async (v: VoiceRow) => {
    if (!v.public_owner_id) return;
    try {
      await addLibraryVoice({ public_owner_id: v.public_owner_id, voice_id: v.voice_id, name: v.name });
      setMsg({ kind: "ok", text: `${v.name} hesabınıza eklendi.` });
      await load();
    } catch (e) { setMsg({ kind: "err", text: String((e as Error).message ?? e) }); }
  };

  const nameOf = (id: string) => voices.find((v) => v.voice_id === id)?.name ?? id;

  return (
    <section className="voice-picker" data-testid="voice-picker" aria-label="Ses seçici">
      <h3 className="sub">Ses seçici (ElevenLabs) — ton başına ayrı ses</h3>
      <p className="meta">
        Türkçe sesleri dinleyin ve her ton için bir ses atayın; atanmayan tonlar genel sesi kullanır. Kütüphane seslerini kullanmadan önce
        hesabınıza eklemeniz gerekebilir ve ticari kullanım lisansı ayrıca kontrol edilmelidir.
      </p>
      <ul className="voice-assigned" data-testid="voice-assigned">
        {TONES.map((t) => (
          <li key={t.id}>
            <b>{t.label}:</b> {assigned[t.id] ? nameOf(assigned[t.id]) : "genel ses"}
            {assigned[t.id] && <button type="button" onClick={() => void assign(t.id, "")} aria-label={`${t.label} atamasını kaldır`}>Kaldır</button>}
          </li>
        ))}
      </ul>
      <form className="persona-actions" onSubmit={(e) => { e.preventDefault(); void load(); }}>
        <label htmlFor="vp-search" className="meta">Ara</label>
        <input id="vp-search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="ör. warm, genç, derin" />
        <button type="submit" disabled={busy}>{busy ? "Yükleniyor…" : "Sesleri getir"}</button>
      </form>
      {msg && <p className={msg.kind === "ok" ? "status status-ok" : "error"} role={msg.kind === "ok" ? "status" : "note"}>{msg.text}</p>}
      <div className="tone-grid">
        {voices.map((v) => (
          <article key={v.voice_id} className="tone-card" data-testid={`voice-${v.voice_id}`}>
            <h4>{v.name}</h4>
            <p className="meta">{v.source === "library" ? "Kütüphane" : "Hesabım"}{v.tags.length ? ` · ${v.tags.join(", ")}` : ""}</p>
            {v.description && <p className="meta">{v.description}</p>}
            {v.preview_url && <audio controls preload="none" src={v.preview_url} />}
            {v.source === "library" ? (
              <button type="button" onClick={() => void add(v)}>Hesabıma ekle</button>
            ) : (
              <div className="voice-assign-buttons">
                {TONES.map((t) => (
                  <button key={t.id} type="button" onClick={() => void assign(t.id, v.voice_id)}
                    aria-pressed={assigned[t.id] === v.voice_id}>{t.label} için seç</button>
                ))}
              </div>
            )}
          </article>
        ))}
      </div>
    </section>
  );
}
