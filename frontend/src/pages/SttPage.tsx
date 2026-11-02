import { useCallback, useEffect, useRef, useState } from "react";
import {
  compareStt, fetchSttModels, fetchSttRun, fetchSttRuns, getWarmup, startWarmup, sttAudioUrl,
  type SttChannel, type SttModel, type SttResult, type SttRun, type SttRunSummary,
} from "../api";
import { toWav } from "../wav";

const modelKey = (m: { provider: string; model: string }) => `${m.provider}:${m.model}`;
const pct = (v: number | null | undefined) => (v == null ? "—" : `${(v * 100).toFixed(1)}%`);

// STT test ekranı (lab-002, plan F7.2): aynı ses seçilen STT modellerinden geçer; transkript, süre, RTF ve
// referans metin varsa WER yan yana görünür. Soğuk model ölçülmez, önce Hazırla (ADR 0001).
export function SttPage() {
  const [models, setModels] = useState<SttModel[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [audio, setAudio] = useState<{ blob: Blob; name: string; url: string; converted: boolean } | null>(null);
  const [reference, setReference] = useState("");
  const [channel, setChannel] = useState<SttChannel>("mix");
  const [prompt, setPrompt] = useState("");
  const [run, setRun] = useState<SttRun | null>(null);
  const [runs, setRuns] = useState<SttRunSummary[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [preparing, setPreparing] = useState<Record<string, boolean>>({});
  const [recording, setRecording] = useState(false);
  const recorder = useRef<MediaRecorder | null>(null);

  const loadModels = useCallback(async () => {
    try {
      const list = await fetchSttModels();
      setModels(list);
      setSelected((prev) => (prev.size ? prev : new Set(list.filter((m) => m.warm && m.ready).map(modelKey))));
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);
  const loadRuns = useCallback(() => fetchSttRuns().then(setRuns).catch(() => {}), []);
  useEffect(() => {
    void loadModels();
    void loadRuns();
  }, [loadModels, loadRuns]);

  const setAudioBlob = (blob: Blob, name: string, converted = true) => {
    if (audio) URL.revokeObjectURL(audio.url);
    setAudio({ blob, name, url: URL.createObjectURL(blob), converted });
    setRun(null);
  };

  async function onFile(file: File | undefined) {
    if (!file) return;
    setError(null);
    try {
      // WAV olduğu gibi gönderilir: stereo ses kaydında (sol müşteri, sağ ajan) kanal seçimi sunucuda yapılır;
      // toWav() kanalları ortalayıp tek kanala indirir ve seçimi imkânsız kılar. Diğer biçimler (m4a, webm) WAV'a çevrilir.
      const isWav = /\.wav$/i.test(file.name) || /^audio\/(x-)?wav$/.test(file.type);
      setAudioBlob(isWav ? file : await toWav(file, true), file.name.replace(/\.[^.]+$/, "") + ".wav", !isWav);
    } catch {
      setError("Ses dosyası çözülemedi. WAV, MP3, M4A veya OGG deneyin.");
    }
  }

  async function toggleRecord() {
    if (recording) {
      recorder.current?.stop();
      return;
    }
    setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const chunks: Blob[] = [];
      const rec = new MediaRecorder(stream);
      rec.ondataavailable = (e) => chunks.push(e.data);
      rec.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        setRecording(false);
        try {
          setAudioBlob(await toWav(new Blob(chunks, { type: rec.mimeType })), "kayit.wav");
        } catch {
          setError("Kayıt çözülemedi.");
        }
      };
      recorder.current = rec;
      rec.start();
      setRecording(true);
    } catch {
      setError("Mikrofona erişilemedi. Tarayıcı iznini kontrol edin veya bir ses dosyası yükleyin.");
    }
  }

  async function prepare(m: SttModel) {
    const key = modelKey(m);
    setPreparing((p) => ({ ...p, [key]: true }));
    setError(null);
    try {
      let job = await startWarmup(m.profile, true, "stt"); // yalnızca bu STT modeli; diğer sıcak modeller bellekte kalır
      while (job.state === "running") {
        await new Promise((r) => setTimeout(r, 1000));
        job = await getWarmup(m.profile);
      }
      if (job.state === "failed") setError(job.error ?? `${m.model} hazırlanamadı.`);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setPreparing((p) => ({ ...p, [key]: false }));
      await loadModels();
    }
  }

  async function execute() {
    if (!audio) return;
    setBusy(true);
    setError(null);
    try {
      const profiles = models.filter((m) => selected.has(modelKey(m))).map((m) => m.profile);
      try {
        setRun(await compareStt(audio.blob, audio.name, profiles, reference, channel, prompt));
      } catch (first) {
        // Sunucu dosyayı çözemediyse (WAV adlı başka biçim, m4a/opus) tarayıcıda WAV'a çevirip bir kez daha dene; stereo korunur.
        if (audio.converted || !/Ses çözülemedi/.test((first as Error).message)) throw first;
        const wav = await toWav(audio.blob, true);
        setAudioBlob(wav, audio.name, true);
        setRun(await compareStt(wav, audio.name, profiles, reference, channel, prompt));
      }
      void loadRuns();
      void loadModels();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function open(id: string) {
    setError(null);
    try {
      const r = await fetchSttRun(id);
      setRun(r);
      setReference(r.reference);
      if (audio) URL.revokeObjectURL(audio.url);
      setAudio(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  const canRun = !!audio && selected.size > 0 && !busy;
  return (
    <section className="screen" data-testid="stt-page">
      <h2>STT test</h2>
      <p className="meta">lab-002 · plan F7.2 · Aynı sesi birden çok STT modelinden geçirin, WER ve süreyi karşılaştırın.</p>

      <h3 className="sub">1 · Modeller</h3>
      <ul className="stt-models">
        {models.map((m) => {
          const key = modelKey(m);
          const state = !m.ready ? `Anahtar eksik: ${m.missing_env.join(", ")}` : m.warm ? "Sıcak" : "Soğuk";
          return (
            <li key={key}>
              <label>
                <input type="checkbox" checked={selected.has(key)} disabled={!m.ready}
                  onChange={(e) => setSelected((s) => { const n = new Set(s); if (e.target.checked) n.add(key); else n.delete(key); return n; })} />
                <b>{m.model || m.provider}</b> <span className="meta">{m.provider} · {m.profiles.join(", ")}</span>
              </label>
              <span className={`chip ${m.warm ? "chip-ok" : preparing[key] ? "chip-busy" : "chip-cold"}`}>
                {preparing[key] ? "Hazırlanıyor…" : state}
              </span>
              {m.ready && !m.warm && (
                <button type="button" disabled={!!preparing[key]} onClick={() => prepare(m)}>Hazırla</button>
              )}
            </li>
          );
        })}
      </ul>

      <h3 className="sub">2 · Ses</h3>
      <div className="stt-audio">
        <label className="file">
          Ses dosyası yükle
          <input type="file" accept="audio/*" onChange={(e) => onFile(e.target.files?.[0])} data-testid="stt-file" />
        </label>
        <button type="button" onClick={toggleRecord}>{recording ? "Kaydı durdur" : "Mikrofondan kaydet"}</button>
        {audio && <span className="meta">{audio.name}</span>}
      </div>
      {(audio || run) && <audio controls src={audio?.url ?? (run ? sttAudioUrl(run.id) : undefined)} />}

      <h3 className="sub">3 · Referans metin (WER için, isteğe bağlı)</h3>
      <textarea rows={3} value={reference} onChange={(e) => setReference(e.target.value)} disabled={channel === "both"}
        placeholder={channel === "both" ? "Müşteri + Ajan ayrı modunda WER hesaplanmaz" : "Seste söylenenin doğru yazılışı"}
        aria-label="Referans metin" />

      <h3 className="sub">4 · Seçenekler (isteğe bağlı)</h3>
      <div className="voice-options">
        <label>Kanal{" "}
          <select value={channel} onChange={(e) => setChannel(e.target.value as SttChannel)} aria-label="Kanal"
                  title="Playground'da kaydedilen stereo ses: sol kanal müşteri, sağ kanal ajan. 'Müşteri + Ajan ayrı': iki kanalı ayrı ayrı yazıya çevirir (referans metin gerekmez). Müşteri hatalarını ölçmek için Sol'u seçin.">
            <option value="mix">Karışık (varsayılan)</option>
            <option value="both">Müşteri + Ajan ayrı (referanssız)</option>
            <option value="left">Sol (müşteri)</option>
            <option value="right">Sağ (ajan)</option>
          </select>
        </label>
        <label>Alan ipucu{" "}
          <input type="text" value={prompt} onChange={(e) => setPrompt(e.target.value)} aria-label="Alan ipucu" size={48}
                 placeholder="örn. sahibinden.com, çağrı merkezi, müşteri temsilcisi, bir ile on arasında puan"
                 title="Yalnızca MLX Whisper: aynı model ipuçsuz ve ipuçlu yan yana koşar (kısa seslerde ipucunu aynen yazma riski vardır)." />
        </label>
      </div>
      <p>
        <button type="button" className="primary" disabled={!canRun} onClick={execute}>
          {busy ? "Çalışıyor…" : "Karşılaştır"}
        </button>
      </p>
      {error && <p className="status status-error" role="alert">{error}</p>}

      {run && <Results run={run} />}

      <h3 className="sub">Kayıtlı koşular</h3>
      {runs.length === 0 ? <p className="meta">Henüz koşu yok.</p> : (
        <ul className="stt-runs">
          {runs.map((r) => (
            <li key={r.id}>
              <button type="button" onClick={() => open(r.id)}>Aç</button>{" "}
              <span>{new Date(r.created_at).toLocaleString("tr-TR")}</span> · {r.filename ?? "kayıt"} ·{" "}
              {r.audio_seconds} sn · {r.models.length} model · en iyi WER {pct(r.best_wer)}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function Results({ run }: { run: SttRun }) {
  return (
    <div className="stt-results" data-testid="stt-results">
      {run.results.map((r: SttResult) => (
        <article key={`${r.provider}:${r.model}`} className="stt-card">
          <h4>{r.model || r.provider}</h4>
          <p className="meta">{r.provider} · {r.profile}</p>
          {r.status === "ok" && r.speakers ? (
            <div data-testid="stt-speakers">
              {(["customer", "agent"] as const).map((k) => {
                const sp = r.speakers![k];
                return (
                  <div key={k} className="stt-speaker">
                    <p className="meta"><b>{k === "customer" ? "Müşteri (sol kanal)" : "Ajan (sağ kanal)"}</b>
                      {sp.silent ? " · kanal sessiz, yazıya çevrilmedi" : ` · ${sp.seconds?.toFixed(2)} sn · RTF ${sp.rtf?.toFixed(3)}`}</p>
                    <p className="stt-text">{sp.text || "(konuşma yok)"}</p>
                  </div>
                );
              })}
              <p className="meta">Kanallar ayrı yazıldığı için konuşma sırası gösterilmez.</p>
            </div>
          ) : r.status === "ok" ? (
            <>
              <p className="stt-text">{r.text || "(boş transkript)"}</p>
              <dl className="stt-stats">
                <div><dt>WER</dt><dd data-testid="wer">{pct(r.wer)}</dd></div>
                <div><dt>Süre</dt><dd>{r.seconds?.toFixed(2)} sn</dd></div>
                <div><dt>RTF</dt><dd>{r.rtf?.toFixed(3)}</dd></div>
              </dl>
              {r.ref_words ? (
                <p className="meta">{r.ref_words} kelime · {r.substitutions} yanlış, {r.deletions} eksik, {r.insertions} fazla</p>
              ) : null}
            </>
          ) : (
            <p className="warn">{r.status === "cold" ? "Soğuk, ölçülmedi. " : ""}{r.error}</p>
          )}
        </article>
      ))}
    </div>
  );
}
