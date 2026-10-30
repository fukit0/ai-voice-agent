import { useEffect, useRef, useState } from "react";
import "../studio.css"; // pencere ve Persona kartı stilleri (genel styles.css'e dokunmadan)
import { ToneDemo } from "./ToneDemo";
import { TtsLab } from "./TtsLab";
import { VoicePicker } from "./VoicePicker";

const TABS = [
  { id: "library", label: "Ses kütüphanesi", hint: "Ara, dinle, tona ata" },
  { id: "lab", label: "Laboratuvar", hint: "Model · gecikme · maliyet" },
  { id: "tones", label: "Ton demosu", hint: "Aynı cümle, dört ton" },
] as const;
type TabId = (typeof TABS)[number]["id"];

// Ses stüdyosu: ElevenLabs ayarlarının tamamı (ses kütüphanesi, TTS laboratuvarı, ton demosu) tek bir açılır pencerede, sekmeli.
// Persona ekranı kısa kalır; pencere açılınca ilgili sekme yüklenir, kapatılınca çalan ses durur ama sekme durumları (arama, seçili ses) korunur.
export function VoiceStudio({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [tab, setTab] = useState<TabId>("library");
  const [visited, setVisited] = useState<Set<TabId>>(new Set(["library"]));
  const rootRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const opener = useRef<Element | null>(null);

  const show = (id: TabId) => { setTab(id); setVisited((v) => new Set(v).add(id)); };

  useEffect(() => {
    if (open) {
      opener.current = document.activeElement;
      closeRef.current?.focus();
      const prev = document.body.style.overflow;
      document.body.style.overflow = "hidden"; // arka sayfa kaymasın
      const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
      document.addEventListener("keydown", onKey);
      return () => { document.body.style.overflow = prev; document.removeEventListener("keydown", onKey); };
    }
    rootRef.current?.querySelectorAll("audio").forEach((a) => { try { a.pause(); } catch { /* jsdom */ } });
    (opener.current as HTMLElement | null)?.focus?.();
  }, [open, onClose]);

  const onTabKey = (e: React.KeyboardEvent, i: number) => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    e.preventDefault();
    show(TABS[(i + (e.key === "ArrowRight" ? 1 : TABS.length - 1)) % TABS.length].id);
  };

  return (
    <div ref={rootRef} className="studio" hidden={!open} onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="studio-box" role="dialog" aria-modal="true" aria-label="Ses stüdyosu" data-testid="voice-studio">
        <header className="studio-head">
          <div>
            <h2>Ses stüdyosu</h2>
            <span className="meta">ElevenLabs · ses, ton, model</span>
          </div>
          <button ref={closeRef} type="button" className="studio-close" aria-label="Pencereyi kapat" onClick={onClose}>×</button>
        </header>
        <div className="studio-tabs" role="tablist" aria-label="Ses stüdyosu bölümleri">
          {TABS.map((t, i) => (
            <button key={t.id} type="button" role="tab" id={`studio-tab-${t.id}`} aria-selected={tab === t.id} aria-controls={`studio-panel-${t.id}`}
              tabIndex={tab === t.id ? 0 : -1} onClick={() => show(t.id)} onKeyDown={(e) => onTabKey(e, i)}>
              <b>{t.label}</b><span>{t.hint}</span>
            </button>
          ))}
        </div>
        <div className="studio-body">
          <div role="tabpanel" id="studio-panel-library" aria-labelledby="studio-tab-library" hidden={tab !== "library"}>
            {visited.has("library") && <VoicePicker />}
          </div>
          <div role="tabpanel" id="studio-panel-lab" aria-labelledby="studio-tab-lab" hidden={tab !== "lab"}>
            {visited.has("lab") && <TtsLab />}
          </div>
          <div role="tabpanel" id="studio-panel-tones" aria-labelledby="studio-tab-tones" hidden={tab !== "tones"}>
            {visited.has("tones") && <ToneDemo />}
          </div>
        </div>
      </div>
    </div>
  );
}
