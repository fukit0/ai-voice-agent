import { useEffect, useRef, useState } from "react";
import { fetchProfiles, fetchTones, runToneDemo, type ProfileStatus, type ToneDemoResult } from "../api";

// ElevenLabs'te ton desteği model ailesine göre değişir (ADR 0010). Ses etiketi ([excited] vb.) yalnız v3/v4 ailesinde belgelenmiş.
const EL_MODELS: { id: string; label: string }[] = [
  { id: "", label: "Profildeki model" },
  { id: "eleven_flash_v2_5", label: "Flash v2.5 (hızlı; ton: kararlılık + hız)" },
  { id: "eleven_multilingual_v2", label: "Multilingual v2 (kararlılık + stil + hız)" },
  { id: "eleven_v4_turbo", label: "v4 Turbo (ses etiketleri; canlı hat adayı)" },
  { id: "eleven_v3", label: "v3 (ses etiketleri; yüksek gecikme)" },
];
const ACOUSTIC_LABEL: Record<string, string> = {
  words_per_sec: "kelime/sn", pitch_median_hz: "perde (Hz)", pitch_std_semitones: "perde oynaklığı (yarım ton)", loudness_std_db: "şiddet dalgalanması (dB)",
};

// Aynı cümleyi seçili profilin sesiyle dört tonda üretir; parametreleri ve akustik farkı yan yana gösterir.
export function ToneDemo() {
  const [profiles, setProfiles] = useState<ProfileStatus[]>([]);
  const [profile, setProfile] = useState("");
  const [model, setModel] = useState("eleven_v4_turbo");   // dinleme sonucu (ADR 0010): ton farkı v4'te duyuluyor, Flash'ta belirgin değil
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [res, setRes] = useState<ToneDemoResult | null>(null);
  const players = useRef<Record<string, HTMLAudioElement | null>>({});

  useEffect(() => {
    fetchProfiles().then((ps) => {
      const ok = ps.filter((p) => p.components.tts);
      setProfiles(ok);
      setProfile((cur) => cur || ok[0]?.id || "");
    }).catch(() => {});
    fetchTones().then((t) => setText(t.demo_text)).catch(() => {});
  }, []);

  const chosen = profiles.find((p) => p.id === profile);
  const isEleven = chosen?.components.tts?.provider === "elevenlabs";

  const run = async () => {
    setBusy(true); setErr(null);
    try { setRes(await runToneDemo({ profile, text, model: isEleven && model ? model : null })); }
    catch (e) { setErr(String((e as Error).message ?? e)); }
    finally { setBusy(false); }
  };

  const playAll = async () => {
    for (const c of res?.clips ?? []) {
      const a = players.current[c.id];
      if (!a) continue;
      a.currentTime = 0;
      await new Promise<void>((done) => { a.onended = () => done(); a.onerror = () => done(); void a.play().catch(() => done()); });
    }
  };

  return (
    <section className="tone-demo" data-testid="tone-demo" aria-label="Ton demosu">
      <h3 className="sub">Ton demosu — aynı cümle, dört ton</h3>
      <p className="meta">
        Seçili profilin TTS'iyle aynı cümleyi her tonda üretir. Ses sabit tohumla (seed) üretilir; fark rastgelelikten değil tondan gelir.
        EMA'da yalnız hız değişir (tek ses); Chatterbox'ta ifade gücü, ElevenLabs'te kararlılık/hız ve v3/v4 modellerinde ses etiketi.
      </p>
      <div className="persona-row">
        <div>
          <label htmlFor="td-profile"><b>Profil (TTS)</b></label>
          <select id="td-profile" value={profile} onChange={(e) => setProfile(e.target.value)}>
            {profiles.map((p) => <option key={p.id} value={p.id}>{p.id} — {p.components.tts?.provider}</option>)}
          </select>
        </div>
        {isEleven && (
          <div>
            <label htmlFor="td-model"><b>ElevenLabs modeli</b></label>
            <select id="td-model" value={model} onChange={(e) => setModel(e.target.value)}>
              {EL_MODELS.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
            </select>
          </div>
        )}
      </div>
      <label htmlFor="td-text"><b>Cümle</b> <span className="meta">{text.length}/300</span></label>
      <textarea id="td-text" rows={2} value={text} maxLength={300} onChange={(e) => setText(e.target.value)} />
      <div className="persona-actions">
        <button type="button" onClick={() => void run()} disabled={busy || !profile || !text.trim()}>
          {busy ? "Üretiliyor…" : "Dört tonu üret"}
        </button>
        {res && <button type="button" onClick={() => void playAll()}>Sırayla çal</button>}
      </div>
      {err && <p className="error" role="alert">{err}</p>}
      {res && (
        <div data-testid="tone-results">
          <p className="meta">
            {res.provider} / {res.model ?? "-"} · tohum {res.seed ?? "yok"}
            {!res.takes_tone && " · bu sağlayıcı ton parametresi almıyor (klipler aynı)"}
            {res.provider === "elevenlabs" && !res.tag_model && " · bu modelde ses etiketi yok; ton yalnız kararlılık/hız ile verilir"}
          </p>
          <div className="tone-grid">
            {res.clips.map((c) => (
              <article key={c.id} className="tone-card" data-testid={`tone-${c.tone}`}>
                <h4>{c.label}</h4>
                <audio ref={(el) => { players.current[c.id] = el; }} controls src={c.url} />
                <p className="meta">
                  {Object.entries(c.applied).map(([k, v]) => `${k}: ${v}`).join(" · ") || "parametre yok"}
                </p>
                <ul className="tone-metrics">
                  {Object.entries(ACOUSTIC_LABEL).map(([k, label]) => {
                    const v = (c.acoustics as Record<string, number | undefined>)[k];
                    return v === undefined ? null : <li key={k}>{label}: <b>{v}</b></li>;
                  })}
                </ul>
              </article>
            ))}
          </div>
          <p className="meta">Sayılar yaklaşıktır ve dinlemenin yerini tutmaz; amaç tonlar arasındaki yönü görmektir.</p>
        </div>
      )}
    </section>
  );
}
