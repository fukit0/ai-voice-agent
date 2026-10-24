import { useEffect, useRef, useState } from "react";
import { ActiveProfile } from "../ActiveProfile";
import { useProfile } from "../ProfileContext";
import { startVoice, type VoiceEvent, type VoiceHandle } from "../voice";

type Line = { role: "user" | "agent"; text: string };
type Turn = Extract<VoiceEvent, { type: "turn" }>;
const STATE_LABEL: Record<string, string> = {
  connecting: "Bağlanıyor…", idle: "Hazır", listening: "Dinliyor", thinking: "Düşünüyor", speaking: "Konuşuyor", closed: "Kapandı",
};
const sec = (v?: number) => (v === undefined ? "—" : `${v.toFixed(2)} sn`);

// Konuşma playground'u, core-001 kapsamı: mikrofon izni, Başlat/Durdur, canlı durum ve transkript, tur gecikmesi.
// Senaryo seçimi, çıkarılan cevaplar ve telefon filtresi lab-003'te eklenir.
export function PlaygroundPage() {
  const { active } = useProfile();
  const [state, setState] = useState<string>("idle");
  const [lines, setLines] = useState<Line[]>([]);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [levels, setLevels] = useState<[number, number]>([0, 0]);
  const [barges, setBarges] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const handle = useRef<VoiceHandle | null>(null);
  const running = state !== "idle" && state !== "closed";
  const connecting = state === "connecting";

  const onEvent = (e: VoiceEvent) => {
    if (e.type === "state") setState(e.state);
    else if (e.type === "transcript") setLines((l) => [...l, { role: e.role, text: e.text }]);
    else if (e.type === "turn") setTurns((t) => (e.greeting ? t : [...t, e]));
    else if (e.type === "barge_in") setBarges((n) => n + 1);
    else if (e.type === "error") setError(e.message);
  };

  async function start() {
    if (!active) return;
    setError(null);
    setLines([]);
    setTurns([]);
    setBarges(0);
    setState("connecting");
    try {
      handle.current = await startVoice(active.id, { onEvent, onLevels: (m, a) => setLevels([m, a]) });
    } catch (e) {
      setError((e as Error).message);
      setState("idle");
    }
  }

  async function stop() {
    const h = handle.current;
    handle.current = null;
    setLevels([0, 0]);
    setState("idle");
    await h?.close();
  }

  useEffect(() => () => { void handle.current?.close(); }, []);

  const last = turns[turns.length - 1];
  return (
    <section className="screen" data-testid="playground-page">
      <h2>Playground</h2>
      <p className="meta">core-001 · plan F1.1 · Mikrofonla ajanla konuşun. Yankıyı önlemek için kulaklık kullanın; ajan konuşurken araya girebilirsiniz.</p>
      <ActiveProfile />
      <p className="voice-controls">
        {running ? (
          <button type="button" className="primary" onClick={stop}>Durdur</button>
        ) : (
          <button type="button" className="primary" disabled={!active || connecting} onClick={start}>Başlat</button>
        )}
        <span className={`chip ${state === "speaking" ? "chip-busy" : state === "listening" ? "chip-ok" : ""}`} data-testid="voice-state">
          {STATE_LABEL[state] ?? state}
        </span>
        {barges > 0 && <span className="meta">söz kesme: {barges}</span>}
      </p>
      {running && (
        <div className="voice-meters" aria-hidden="true">
          <label>Mikrofon <meter min={0} max={1} value={levels[0]} /></label>
          <label>Ajan <meter min={0} max={1} value={levels[1]} /></label>
        </div>
      )}
      {error && <p className="status status-error" role="alert">{error}</p>}
      <h3 className="sub">Konuşma</h3>
      {lines.length === 0 ? <p className="meta">Henüz konuşma yok.</p> : (
        <ol className="voice-lines" data-testid="voice-lines">
          {lines.map((l, i) => <li key={i} className={`voice-${l.role}`}><b>{l.role === "agent" ? "Ajan" : "Siz"}:</b> {l.text}</li>)}
        </ol>
      )}
      {last && (
        <p className="meta" data-testid="voice-latency">
          Son tur · STT {sec(last.stt_s)} · LLM {sec(last.llm_s)} · TTS (ilk cümle) {sec(last.tts_first_s)} ·
          konuşma bitişinden ilk sese {sec(last.first_audio_after_end_s)} (+ {(last.endpoint_wait_ms ?? 0) / 1000} sn bitiş bekleme)
        </p>
      )}
    </section>
  );
}
