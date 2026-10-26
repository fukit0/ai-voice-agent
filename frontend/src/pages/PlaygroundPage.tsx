import { useEffect, useRef, useState } from "react";
import { ActiveProfile } from "../ActiveProfile";
import { fetchScenarios, type ScenarioSummary } from "../api";
import { useProfile } from "../ProfileContext";
import { startVoice, type VoiceEvent, type VoiceHandle } from "../voice";

type Line = { role: "user" | "agent"; text: string };
type Turn = Extract<VoiceEvent, { type: "turn" }>;
type Node = Extract<VoiceEvent, { type: "node" }>;
type Answer = Extract<VoiceEvent, { type: "answer" }>;
const STATE_LABEL: Record<string, string> = {
  connecting: "Bağlanıyor…", idle: "Hazır", listening: "Dinliyor", thinking: "Düşünüyor", speaking: "Konuşuyor", closed: "Kapandı",
};
const KIND_LABEL: Record<string, string> = {
  Choice: "Seçenekli", YesNo: "Evet / Hayır", Score: "Puan", Duration: "Süre", OpenText: "Açık uçlu",
  Statement: "Anons", CheckIn: "Bilgilendirme + soru", CallbackTime: "Randevu zamanı", Terminal: "Kapanış",
};
const sec = (v?: number | null) => (v === undefined || v === null ? "—" : `${v.toFixed(2)} sn`);
const show = (v: unknown) => (v === null || v === undefined ? "cevap yok" : typeof v === "boolean" ? (v ? "Evet" : "Hayır") : String(v));

// Konuşma playground'u (lab-003): profil + senaryo seçilir, mikrofonla konuşulur; aktif düğüm, çıkarılan cevaplar,
// tur başına STT / LLM / TTS gecikmesi canlı akar. Telefon filtresi konuşma sırasında açılıp kapatılabilir.
export function PlaygroundPage() {
  const { active } = useProfile();
  const [scenarios, setScenarios] = useState<ScenarioSummary[]>([]);
  const [scenario, setScenario] = useState<string>("");
  const [phone, setPhone] = useState(false);
  const [record, setRecord] = useState(false);                         // core-013: varsayılan kapalı (gizlilik)
  const [recording, setRecording] = useState<string | null>(null);     // kaydedilen oturumun kimliği (durdurunca)
  const [state, setState] = useState<string>("idle");
  const [lines, setLines] = useState<Line[]>([]);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [node, setNode] = useState<Node | null>(null);
  const [visited, setVisited] = useState<string[]>([]);
  const [answers, setAnswers] = useState<Answer[]>([]);
  const [outcome, setOutcome] = useState<{ label: string } | null>(null);
  const [levels, setLevels] = useState<[number, number]>([0, 0]);
  const [barges, setBarges] = useState(0);
  const [bargeMs, setBargeMs] = useState<number | null>(null);
  const [held, setHeld] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const handle = useRef<VoiceHandle | null>(null);
  const running = state !== "idle" && state !== "closed";
  const connecting = state === "connecting";

  useEffect(() => {
    fetchScenarios().then((l) => {
      if (!Array.isArray(l)) return;
      setScenarios(l);
      setScenario((cur) => cur || l[0]?.key || "");
    }).catch(() => {});
  }, []);

  const onEvent = (e: VoiceEvent) => {
    if (e.type === "state") setState(e.state);
    else if (e.type === "transcript") setLines((l) => [...l, { role: e.role, text: e.text }]);
    else if (e.type === "turn") setTurns((t) => [...t, e]);
    else if (e.type === "barge_in") { setBarges((n) => n + 1); if (e.cut_ms !== undefined) setBargeMs(e.cut_ms); }
    else if (e.type === "hold") setHeld(e.on ? (e.text ?? "") : null);
    else if (e.type === "node") { setNode(e); setVisited((v) => [...v, e.key]); }
    else if (e.type === "answer") setAnswers((a) => [...a, e]);
    else if (e.type === "outcome") setOutcome({ label: e.label });
    else if (e.type === "error") setError(e.message);
  };

  async function start() {
    if (!active) return;
    setError(null); setRecording(null); setLines([]); setTurns([]); setBarges(0); setBargeMs(null); setHeld(null); setNode(null); setVisited([]); setAnswers([]); setOutcome(null);
    setState("connecting");
    try {
      handle.current = await startVoice(active.id, { onEvent, onLevels: (m, a) => setLevels([m, a]) },
        { scenario: scenario || undefined, phoneFilter: phone, record });
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
    await h?.close();                       // sunucu WAV'ı kapanışta yazar; close() bitince dosya hazırdır
    if (h && record) setRecording(h.sessionId);
  }

  async function deleteRecording() {
    if (!recording) return;
    await fetch(`/api/voice/recordings/${recording}`, { method: "DELETE" }).catch(() => {});
    setRecording(null);
  }

  function togglePhone(on: boolean) {
    setPhone(on);
    handle.current?.setPhoneFilter(on);
  }

  useEffect(() => () => { void handle.current?.close(); }, []);

  const total = scenarios.find((s) => s.key === scenario)?.steps;
  return (
    <section className="screen" data-testid="playground-page">
      <h2>Playground</h2>
      <p className="meta">lab-003 · plan F7.3 · Mikrofonla ajanla konuşun. Yankıyı önlemek için kulaklık kullanın; ajan konuşurken araya girebilirsiniz.</p>
      <ActiveProfile />
      <div className="voice-options">
        <label>Senaryo{" "}
          <select value={scenario} disabled={running} onChange={(e) => setScenario(e.target.value)} aria-label="Senaryo">
            <option value="">Serbest sohbet (senaryosuz)</option>
            {scenarios.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
          </select>
        </label>
        <label className="voice-check">
          <input type="checkbox" checked={phone} onChange={(e) => togglePhone(e.target.checked)} /> Telefon filtresi (dar bant 300–3400 Hz)
        </label>
        <label className="voice-check" title="Sol kanal müşteri (ham mikrofon), sağ kanal ajan. Dosya bu bilgisayarda data/voice-sessions/ altına yazılır.">
          <input type="checkbox" checked={record} disabled={running} onChange={(e) => setRecord(e.target.checked)}
                 data-testid="record-toggle" /> Konuşmayı kaydet (ses)
        </label>
      </div>
      {recording && (
        <p className="voice-recording" data-testid="recording-box">
          Kayıt hazır: <audio controls src={`/api/voice/recordings/${recording}.wav`} data-testid="recording-audio" />{" "}
          <a href={`/api/voice/recordings/${recording}.wav`} download>İndir</a>{" "}
          <button type="button" onClick={deleteRecording}>Kaydı sil</button>
          <span className="meta"> · sol kanal: siz, sağ kanal: ajan · konum: data/voice-sessions/{recording}.wav</span>
        </p>
      )}
      <p className="voice-controls">
        {running ? (
          <button type="button" className="primary" onClick={stop}>Durdur</button>
        ) : (
          <button type="button" className="primary" disabled={!active || connecting} onClick={start}>Başlat</button>
        )}
        <span className={`chip ${state === "speaking" ? "chip-busy" : state === "listening" ? "chip-ok" : ""}`} data-testid="voice-state">
          {STATE_LABEL[state] ?? state}
        </span>
        {barges > 0 && <span className="meta">söz kesme: {barges}{bargeMs !== null ? ` · son: ${bargeMs} ms` : ""}</span>}
        {held !== null && <span className="chip chip-busy" data-testid="voice-hold" title={held}>Cümle bitmemiş gibi, devamını bekliyor…</span>}
      </p>
      {running && (
        <div className="voice-meters" aria-hidden="true">
          <label>Mikrofon <meter min={0} max={1} value={levels[0]} /></label>
          <label>Ajan <meter min={0} max={1} value={levels[1]} /></label>
        </div>
      )}
      {error && <p className="status status-error" role="alert">{error}</p>}
      {outcome && <p className="status status-ok" role="status" data-testid="voice-outcome">Görüşme bitti · sonuç: <b>{outcome.label}</b></p>}

      <div className="voice-grid">
        <div>
          <h3 className="sub">Konuşma</h3>
          {lines.length === 0 ? <p className="meta">Henüz konuşma yok.</p> : (
            <ol className="voice-lines" data-testid="voice-lines">
              {lines.map((l, i) => <li key={i} className={`voice-${l.role}`}><b>{l.role === "agent" ? "Ajan" : "Siz"}:</b> {l.text}</li>)}
            </ol>
          )}
        </div>
        {scenario && (
          <div>
            <h3 className="sub">Aktif düğüm</h3>
            {node ? (
              <p data-testid="active-node">
                {node.code && <span className="chip">{node.code}</span>} <b>{node.title}</b>{" "}
                <span className="chip">{KIND_LABEL[node.kind] ?? node.kind}</span>
                <br /><span className="meta">{node.group} · adım {visited.length}{total ? ` / ${total}` : ""}</span>
              </p>
            ) : <p className="meta">Konuşma başlayınca görünür.</p>}
            <h3 className="sub">Çıkarılan cevaplar</h3>
            {answers.length === 0 ? <p className="meta">Henüz cevap yok.</p> : (
              <table className="eval-table" data-testid="voice-answers">
                <tbody>
                  {answers.map((a, i) => (
                    <tr key={i}>
                      <td>{a.code ?? a.title}</td>
                      <td><b>{show(a.value)}</b></td>
                      <td className="meta">{a.unanswered ? "anlaşılamadı" : `“${a.utterance}”`}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}
      </div>

      <h3 className="sub">Tur gecikmeleri</h3>
      {turns.length === 0 ? <p className="meta">Henüz tur yok.</p> : turns.some((t) => t.realtime) ? (
        <>
          <p className="meta" data-testid="realtime-note">
            Realtime profil: ses doğrudan modele gider; ayrı STT / LLM / TTS süresi yoktur. Ölçülen tek şey, konuşma bitişinden
            ajanın ilk sesine geçen uçtan uca süredir (kırılım: cevabı fonksiyon çağrısıyla bildirme + metni seslendirme).
          </p>
          <table className="eval-table" data-testid="voice-latency">
            <thead><tr><th>Tur</th><th>Cevabı bildirme</th><th>Metni seslendirme</th><th>Konuşma bitişinden ilk sese (uçtan uca)</th></tr></thead>
            <tbody>
              {turns.map((t, i) => (
                <tr key={t.turn}>
                  <td>{t.greeting ? "açılış" : i}</td>
                  <td>{t.no_tool_call ? "fonksiyon çağrılmadı" : sec(t.answer_s)}</td>
                  <td>{sec(t.speak_s)}</td>
                  <td>{t.greeting ? "—" : sec(t.first_audio_after_end_s)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      ) : (
        <table className="eval-table" data-testid="voice-latency">
          <thead><tr><th>Tur</th><th>STT</th><th>LLM</th><th>TTS (ilk cümle)</th><th>Konuşma bitişinden ilk sese</th><th>Bitiş bekleme</th></tr></thead>
          <tbody>
            {turns.map((t, i) => (
              <tr key={t.turn}>
                <td>{t.greeting ? "açılış" : i}</td><td>{sec(t.stt_s)}</td><td>{sec(t.llm_s)}</td><td>{sec(t.tts_first_s)}</td>
                <td>{t.greeting ? "—" : sec(t.first_audio_after_end_s)}</td>
                <td>{t.endpoint_wait_ms !== undefined ? `${t.endpoint_wait_ms / 1000} sn` : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
