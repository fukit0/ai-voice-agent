import { useEffect, useRef, useState } from "react";
import {
  addLibraryVoice, assignVoices, fetchModelMatrix, fetchVoices, runTtsLab,
  type ModelRow, type VoiceRow,
} from "../api";

const TONES: { id: string; label: string }[] = [
  { id: "samimi", label: "Samimi" }, { id: "resmi", label: "Resmî" }, { id: "enerjik", label: "Enerjik" }, { id: "sakin", label: "Sakin" },
];
// Atama yuvaları: dört ton + "Genel ses" (kendi sesi olmayan tonlar ve tonsuz çağrılar; L2-EL/A1 profilleri bunu kullanır)
const SLOTS: { id: string; label: string }[] = [...TONES, { id: "default", label: "Genel ses" }];
const GENDER = [["", "Tümü"], ["female", "Kadın"], ["male", "Erkek"], ["neutral", "Nötr"]];
const AGE = [["", "Tümü"], ["young", "Genç"], ["middle_aged", "Orta yaş"], ["old", "Yaşlı"]];
const USE_CASE = [["", "Tüm kullanımlar"], ["conversational", "Sohbet"], ["narrative_story", "Anlatı"], ["social_media", "Sosyal medya"],
  ["entertainment_tv", "Eğlence / TV"], ["advertisement", "Reklam"], ["informative_educational", "Eğitici"], ["characters_animation", "Karakter"]];
const SORTS = [["trending", "Trend"], ["popular", "En çok kullanılan"], ["newest", "En yeni"], ["usage", "Yıllık kullanım"]];
const SCOPES = [["all", "Tümü"], ["account", "Hesabım"], ["library", "Kütüphane"]] as const;
type Scope = (typeof SCOPES)[number][0];

const TR: Record<string, string> = Object.fromEntries([...GENDER, ...AGE, ...USE_CASE].filter(([k]) => k));
const trTag = (t: string) => TR[t] ?? t.replace(/_/g, " ");
const DEFAULT_TEXT = "Merhaba Ahmet Bey, ben Ayşe. sahibinden.com adına arıyorum. Size kısa bir anket yapabilir miyim?";

// Sesin kimliğinden sabit bir degrade üretir; ElevenLabs'deki gibi her sese ayırt edici bir avatar verir.
function avatarStyle(id: string): React.CSSProperties {
  let h = 0;
  for (const c of id) h = (h * 31 + c.charCodeAt(0)) % 360;
  return { background: `linear-gradient(135deg, hsl(${h} 70% 62%), hsl(${(h + 55) % 360} 70% 48%))` };
}

// ElevenLabs tarzı ses kütüphanesi: ara, süz, ekranda dinle, her ton için ses ata; altta kendi metninizle özel önizleme.
// Kütüphane sesi API ile üretimde kullanılmadan önce hesaba eklenmelidir; ticari kullanım lisansı ayrıca kontrol edilmelidir.
export function VoicePicker() {
  const [voices, setVoices] = useState<VoiceRow[]>([]);
  const [assigned, setAssigned] = useState<Record<string, string>>({});
  const [search, setSearch] = useState("");
  const [scope, setScope] = useState<Scope>("all");
  const [gender, setGender] = useState("");
  const [age, setAge] = useState("");
  const [useCase, setUseCase] = useState("");
  const [sort, setSort] = useState("trending");
  const [page, setPage] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const [selected, setSelected] = useState<VoiceRow | null>(null);
  const [menuFor, setMenuFor] = useState<string | null>(null);

  const audioRef = useRef<HTMLAudioElement>(null);
  const [playing, setPlaying] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);

  const [models, setModels] = useState<ModelRow[]>([]);
  const [model, setModel] = useState("eleven_v4_turbo");
  const [text, setText] = useState(DEFAULT_TEXT);
  const [tone, setTone] = useState("");
  const [pBusy, setPBusy] = useState(false);
  const [pInfo, setPInfo] = useState<string | null>(null);

  const reqId = useRef(0);
  const first = useRef(true);

  const load = async (nextPage: number, append: boolean) => {
    const id = ++reqId.current; // gecikmiş eski yanıtlar yeni aramanın üstüne yazmasın
    setBusy(true); setMsg(null);
    try {
      const r = await fetchVoices(search.trim(), scope !== "account", { gender, age, use_case: useCase, sort, page: nextPage });
      if (id !== reqId.current) return;
      const rows = scope === "library" ? r.voices.filter((v) => v.source === "library") : r.voices;
      setVoices((prev) => (append ? [...prev, ...rows] : rows));
      setAssigned(r.assigned); setHasMore(!!r.has_more); setPage(nextPage);
    } catch (e) {
      if (id === reqId.current) setMsg({ kind: "err", text: String((e as Error).message ?? e) });
    } finally { if (id === reqId.current) setBusy(false); }
  };

  // Arama yazdıkça (300 ms bekleyerek) ve süzgeç değiştikçe baştan yükle; ilk açılış gecikmesizdir.
  useEffect(() => {
    const t = setTimeout(() => void load(0, false), first.current ? 0 : 300);
    first.current = false;
    return () => clearTimeout(t);
  }, [search, scope, gender, age, useCase, sort]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { fetchModelMatrix().then((m) => setModels(m.models)).catch(() => {}); }, []);

  const toggle = (key: string, url: string | null) => {
    const a = audioRef.current;
    if (!a || !url) return;
    if (playing === key) { a.pause(); setPlaying(null); return; }
    a.src = url; setPlaying(key); setProgress(0);
    try {
      const p = a.play() as Promise<void> | undefined;
      if (p && typeof p.catch === "function") p.catch(() => setPlaying(null));
    } catch { setPlaying(null); }
  };

  const assign = async (toneId: string, voiceId: string) => {
    try {
      setAssigned((await assignVoices({ [toneId]: voiceId })).assigned);
      setMsg({ kind: "ok", text: voiceId ? "Ses atandı. Bir sonraki ton demosu ve arama bu sesi kullanır." : "Atama kaldırıldı (genel ses)." });
    } catch (e) { setMsg({ kind: "err", text: String((e as Error).message ?? e) }); }
  };

  const add = async (v: VoiceRow) => {
    if (!v.public_owner_id) return;
    try {
      await addLibraryVoice({ public_owner_id: v.public_owner_id, voice_id: v.voice_id, name: v.name });
      setMsg({ kind: "ok", text: `${v.name} hesabınıza eklendi.` });
      await load(0, false);
    } catch (e) { setMsg({ kind: "err", text: String((e as Error).message ?? e) }); }
  };

  const customPreview = async () => {
    if (!selected) return;
    setPBusy(true); setPInfo(null); setMsg(null);
    try {
      const r = await runTtsLab({ text, model, voice_id: selected.voice_id, tone: tone || null, runs: 1 });
      const run = r.runs[0];
      setPInfo(`${selected.name} · ${models.find((m) => m.id === model)?.label ?? model} · ilk ses ${r.median_first_audio_seconds?.toFixed(3) ?? "-"} sn · ${r.chars} karakter · $${r.cost_usd ?? "-"}`);
      toggle("custom", run.url);
    } catch (e) { setMsg({ kind: "err", text: String((e as Error).message ?? e) }); }
    finally { setPBusy(false); }
  };

  const nameOf = (id: string) => voices.find((v) => v.voice_id === id)?.name ?? id;
  const tonesOf = (id: string) => SLOTS.filter((t) => assigned[t.id] === id);
  const chip = (label: string, on: boolean, set: () => void) => (
    <button key={label} type="button" className="vp-pill" aria-pressed={on} onClick={set}>{label}</button>
  );
  const needsAdd = !!selected && selected.source === "library";

  return (
    <section className="voice-picker vp" data-testid="voice-picker" aria-label="Ses seçici">
      <h3 className="sub">Ses kütüphanesi (ElevenLabs) — ton başına ayrı ses</h3>
      <p className="meta">
        Türkçe sesleri arayın, burada dinleyin ve her ton için bir ses atayın; atanmayan tonlar genel sesi kullanır. Kütüphane seslerini üretimde
        kullanmadan önce hesabınıza eklemeniz gerekir ve ticari kullanım lisansı ayrıca kontrol edilmelidir.
      </p>

      <ul className="voice-assigned vp-slots" data-testid="voice-assigned">
        {SLOTS.map((t) => (
          <li key={t.id} className={assigned[t.id] ? "vp-slot vp-slot-on" : "vp-slot"}>
            <b>{t.label}:</b> {assigned[t.id] ? nameOf(assigned[t.id]) : t.id === "default" ? "atanmadı" : "genel ses"}
            {assigned[t.id] && (
              <button type="button" className="vp-x" onClick={() => void assign(t.id, "")} aria-label={`${t.label} atamasını kaldır`}>×</button>
            )}
          </li>
        ))}
      </ul>

      <div className="vp-toolbar">
        <div className="vp-search">
          <span aria-hidden="true">⌕</span>
          <input type="search" aria-label="Ses ara" placeholder="Ses ara: ad, ton, 'sıcak', 'genç'…" value={search}
            onChange={(e) => setSearch(e.target.value)} />
          {search && <button type="button" className="vp-x" aria-label="Aramayı temizle" onClick={() => setSearch("")}>×</button>}
        </div>
        <div className="vp-seg" role="group" aria-label="Kaynak">
          {SCOPES.map(([id, label]) => chip(label, scope === id, () => setScope(id)))}
        </div>
        <label className="vp-sort">Sırala
          <select value={sort} onChange={(e) => setSort(e.target.value)} aria-label="Sırala">
            {SORTS.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
          </select>
        </label>
      </div>
      <div className="vp-filters">
        <div className="vp-seg" role="group" aria-label="Cinsiyet">
          <span className="meta">Cinsiyet</span>{GENDER.map(([id, label]) => chip(label, gender === id, () => setGender(id)))}
        </div>
        <div className="vp-seg" role="group" aria-label="Yaş">
          <span className="meta">Yaş</span>{AGE.map(([id, label]) => chip(label, age === id, () => setAge(id)))}
        </div>
        <label className="vp-sort">Kullanım
          <select value={useCase} onChange={(e) => setUseCase(e.target.value)} aria-label="Kullanım">
            {USE_CASE.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
          </select>
        </label>
      </div>

      {msg && <p className={msg.kind === "ok" ? "status status-ok" : "error"} role={msg.kind === "ok" ? "status" : "note"}>{msg.text}</p>}

      <p className="meta" aria-live="polite">{busy ? "Yükleniyor…" : `${voices.length} ses${hasMore ? "+" : ""}`}</p>
      <ul className="vp-list" aria-busy={busy}>
        {voices.map((v) => {
          const isPlaying = playing === v.voice_id;
          const isSel = selected?.voice_id === v.voice_id;
          const tags = [v.gender, v.age, v.descriptive, v.use_case, v.accent].filter(Boolean) as string[];
          const shown = tags.length ? tags : v.tags;
          return (
            <li key={v.voice_id} className={`vp-row${isSel ? " vp-row-sel" : ""}`} data-testid={`voice-${v.voice_id}`}
              onClick={() => { setSelected(v); setMenuFor(null); }}>
              <button type="button" className="vp-play" style={avatarStyle(v.voice_id)} disabled={!v.preview_url}
                aria-label={`${v.name} ${isPlaying ? "önizlemeyi durdur" : "önizlemeyi çal"}`}
                onClick={(e) => { e.stopPropagation(); setSelected(v); toggle(v.voice_id, v.preview_url); }}>
                {isPlaying ? "❚❚" : "▶"}
              </button>
              <div className="vp-main">
                <div className="vp-name">
                  <b>{v.name}</b>
                  <span className={`vp-badge vp-badge-${v.source}`}>{v.source === "library" ? "Kütüphane" : "Hesabım"}</span>
                  {tonesOf(v.voice_id).map((t) => <span key={t.id} className="vp-badge vp-badge-tone">{t.label}</span>)}
                </div>
                {v.description && <div className="vp-desc">{v.description}</div>}
                <div className="vp-tags">{shown.map((t) => <span key={t} className="vp-tag">{trTag(t)}</span>)}</div>
                {isPlaying && <div className="vp-bar" aria-hidden="true"><i style={{ width: `${Math.round(progress * 100)}%` }} /></div>}
              </div>
              <div className="vp-act" onClick={(e) => e.stopPropagation()}>
                {v.cloned_by_count ? <span className="meta" title="Bu sesi kullanan kişi sayısı">{v.cloned_by_count.toLocaleString("tr-TR")} kullanım</span> : null}
                {v.source === "library" ? (
                  <button type="button" onClick={() => void add(v)}>Hesabıma ekle</button>
                ) : (
                  <button type="button" aria-expanded={menuFor === v.voice_id} onClick={() => setMenuFor(menuFor === v.voice_id ? null : v.voice_id)}>Ton ata</button>
                )}
                {menuFor === v.voice_id && (
                  <div className="vp-menu voice-assign-buttons">
                    {SLOTS.map((t) => (
                      <button key={t.id} type="button" aria-pressed={assigned[t.id] === v.voice_id}
                        onClick={() => void assign(t.id, v.voice_id)}>{t.label} için seç</button>
                    ))}
                  </div>
                )}
              </div>
            </li>
          );
        })}
      </ul>
      {!busy && voices.length === 0 && !msg && <p className="meta" data-testid="voice-empty">Bu aramayla ses bulunamadı.</p>}
      {hasMore && <button type="button" disabled={busy} onClick={() => void load(page + 1, true)}>Daha fazla yükle</button>}

      <audio ref={audioRef} data-testid="vp-audio" onEnded={() => setPlaying(null)}
        onTimeUpdate={(e) => setProgress(e.currentTarget.duration ? e.currentTarget.currentTime / e.currentTarget.duration : 0)} />

      <div className="vp-custom" data-testid="vp-custom">
        <div className="vp-custom-head">
          <b>Özel önizleme</b>
          <span className="meta">{selected ? <>Seçili ses: <b>{selected.name}</b></> : "Önce listeden bir ses seçin."}</span>
        </div>
        <div className="vp-custom-row">
          <input aria-label="Önizleme metni" value={text} maxLength={500} onChange={(e) => setText(e.target.value)} />
          <select aria-label="Önizleme modeli" value={model} onChange={(e) => setModel(e.target.value)}>
            {(models.length ? models : [{ id: model, label: model } as ModelRow]).map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
          </select>
          <select aria-label="Önizleme tonu" value={tone} onChange={(e) => setTone(e.target.value)}>
            <option value="">Ton yok</option>
            {TONES.map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}
          </select>
          <button type="button" className="primary" disabled={playing !== "custom" && (!selected || needsAdd || pBusy || !text.trim())}
            onClick={() => (playing === "custom" ? (audioRef.current?.pause(), setPlaying(null)) : void customPreview())}>
            {pBusy ? "Üretiliyor…" : playing === "custom" ? "Durdur" : "Önizle"}
          </button>
        </div>
        {needsAdd && <p className="meta">Bu bir kütüphane sesi: özel metinle üretmek için önce <b>Hesabıma ekle</b>; yukarıdaki hazır klibi yine dinleyebilirsiniz.</p>}
        {pInfo && <p className="meta" data-testid="vp-info">{pInfo}</p>}
      </div>
    </section>
  );
}
