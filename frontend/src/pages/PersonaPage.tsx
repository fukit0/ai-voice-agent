import { useEffect, useState } from "react";
import {
  fetchPersona, fetchPersonaReport, previewPersona, resetPersona, savePersona,
  type PersonaFields, type PersonaReport, type PersonaView,
} from "../api";
import { ToneDemo } from "./ToneDemo";

const TONE_LABEL: Record<string, string> = {
  samimi: "Samimi (sıcak, rahat)", resmi: "Resmî (ölçülü, kibar)", enerjik: "Enerjik (canlı, neşeli)", sakin: "Sakin (yumuşak, telaşsız)",
};
const ADDRESS_LABEL: Record<string, string> = {
  bey_hanim: "Ad + Bey/Hanım (Ahmet Bey)", ad: "Yalnız ad (Ahmet)", siz: "Ad kullanma, 'siz' de",
};
const lines = (s: string) => s.split("\n").map((x) => x.trim()).filter(Boolean);

// Persona ekranı (core-005): ajanın adı, tonu, hitabı, cümle uzunluğu ve doğal onay sözleri buradan girilir.
// Değişiklik anında oluşan istemi, açılış cümlesini ve onay sözü örneklerini gösterir; Playground'daki bir sonraki arama bu persona ile açılır.
export function PersonaPage() {
  const [view, setView] = useState<PersonaView | null>(null);
  const [form, setForm] = useState<PersonaFields | null>(null);
  const [acks, setAcks] = useState("");
  const [avoid, setAvoid] = useState("");
  const [problems, setProblems] = useState<string[]>([]);
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const [report, setReport] = useState<PersonaReport | null>(null);

  const apply = (v: PersonaView) => {
    setView(v); setForm(v.persona); setAcks(v.persona.acknowledgements.join("\n")); setAvoid(v.persona.avoid_phrases.join("\n"));
    setProblems([]);
  };
  useEffect(() => {
    fetchPersona().then(apply).catch((e) => setMsg({ kind: "err", text: String(e.message ?? e) }));
  }, []);

  const current = (): PersonaFields | null =>
    form ? { ...form, acknowledgements: lines(acks), avoid_phrases: lines(avoid) } : null;

  useEffect(() => { // yazdıkça istem önizlemesi (kaydetmeden)
    const cur = current();
    if (!cur || !view) return;
    const t = setTimeout(() => {
      previewPersona(cur).then((p) => {
        setProblems(p.problems);
        if (!p.problems.length) setView((v) => (v ? { ...v, prompt: p.prompt!, greeting: p.greeting!, prompt_stats: p.prompt_stats!, preview_ack: p.preview_ack! } : v));
      }).catch(() => {});
    }, 250);
    return () => clearTimeout(t);
  }, [form, acks, avoid]); // eslint-disable-line react-hooks/exhaustive-deps

  const set = <K extends keyof PersonaFields>(k: K, v: PersonaFields[K]) => setForm((f) => (f ? { ...f, [k]: v } : f));

  const save = async () => {
    const cur = current();
    if (!cur) return;
    try {
      apply(await savePersona(cur));
      setMsg({ kind: "ok", text: "Kaydedildi. Bir sonraki arama bu persona ile açılır." });
    } catch (e) { setMsg({ kind: "err", text: String((e as Error).message ?? e) }); }
  };
  const reset = async () => {
    apply(await resetPersona());
    setMsg({ kind: "ok", text: "Varsayılan persona geri yüklendi." });
  };

  const dirty = view && form && JSON.stringify(current()) !== JSON.stringify(view.persona);

  return (
    <section className="screen" data-testid="persona-page">
      <h2>Persona</h2>
      <p className="meta">
        Ajanın kim olduğunu ve nasıl konuştuğunu belirleyin. Ad senaryo metinlerindeki {"{ASISTAN}"} olur; onay sözleri kademeli hatta
        her cevaptan sonra söylenir; istem serbest sohbette kullanılır. Gerçek aramalarda cümle uzunluğu aşağıdaki raporla denetlenir.
      </p>
      <p className="meta" data-testid="persona-voice-note">
        <b>Not:</b> Ton hem <b>söz üslubunu</b> hem de <b>sesin söyleyişini</b> etkiler; ama ne kadar etkileyeceği TTS sağlayıcısına bağlıdır.
        EMA tek ses olduğu için yalnız hız değişir; Chatterbox ifade gücünü, ElevenLabs kararlılık/hızı (v3 ve v4 modellerinde ses etiketlerini) kullanır.
        Aşağıdaki <b>ton demosu</b> aynı cümleyi dört tonda yan yana dinletir.
      </p>
      {msg && <p className={msg.kind === "ok" ? "status status-ok" : "error"} role="status">{msg.text}</p>}
      {form && view && (
        <div className="persona-layout">
          <form className="persona-form" onSubmit={(e) => { e.preventDefault(); void save(); }} aria-label="Persona girişi">
            <label htmlFor="p-name"><b>Ajanın adı</b></label>
            <input id="p-name" value={form.name} onChange={(e) => set("name", e.target.value)} />
            <label htmlFor="p-tone"><b>Ton (söz üslubu)</b> <span className="meta">söz üslubu + söyleyiş</span></label>
            <select id="p-tone" value={form.tone} onChange={(e) => set("tone", e.target.value)}>
              {view.options.tone.map((t) => <option key={t} value={t}>{TONE_LABEL[t] ?? t}</option>)}
            </select>
            <label htmlFor="p-address"><b>Hitap tarzı</b></label>
            <select id="p-address" value={form.address} onChange={(e) => set("address", e.target.value)}>
              {view.options.address.map((t) => <option key={t} value={t}>{ADDRESS_LABEL[t] ?? t}</option>)}
            </select>
            <div className="persona-row">
              <div>
                <label htmlFor="p-sent"><b>En çok cümle</b></label>
                <input id="p-sent" type="number" min={1} max={5} value={form.max_sentences}
                  onChange={(e) => set("max_sentences", Number(e.target.value))} />
              </div>
              <div>
                <label htmlFor="p-words"><b>Cümle başına en çok kelime</b></label>
                <input id="p-words" type="number" min={5} max={40} value={form.max_words_per_sentence}
                  onChange={(e) => set("max_words_per_sentence", Number(e.target.value))} />
              </div>
            </div>
            <label htmlFor="p-speed"><b>Konuşma hızı</b> <span className="meta">1,0 = normal · {form.speed.toFixed(2)}</span></label>
            <input id="p-speed" type="range" min={0.7} max={1.3} step={0.05} value={form.speed}
              onChange={(e) => set("speed", Number(e.target.value))} />
            <p className="meta">Hız EMA'da uygulanır (ElevenLabs'te 0,7–1,2); Chatterbox yok sayar. Bir sonraki arama bu hızla açılır.</p>
            <label htmlFor="p-acks"><b>Doğal onay sözleri</b> <span className="meta">her satıra bir tane</span></label>
            <textarea id="p-acks" rows={4} value={acks} onChange={(e) => setAcks(e.target.value)} />
            <label htmlFor="p-avoid"><b>Kullanılmayacak kalıplar</b> <span className="meta">her satıra bir tane</span></label>
            <textarea id="p-avoid" rows={3} value={avoid} onChange={(e) => setAvoid(e.target.value)} />
            <label htmlFor="p-extra"><b>Ek kurallar</b> <span className="meta">{form.extra_rules.length}/600</span></label>
            <textarea id="p-extra" rows={3} value={form.extra_rules} onChange={(e) => set("extra_rules", e.target.value)} />
            {problems.length > 0 && <ul className="error persona-problems" role="alert">{problems.map((p) => <li key={p}>{p}</li>)}</ul>}
            <div className="persona-actions">
              <button type="submit" disabled={!dirty || problems.length > 0}>Kaydet</button>
              <button type="button" onClick={() => void reset()}>Varsayılana dön</button>
            </div>
          </form>

          <aside className="persona-preview" aria-label="Önizleme">
            <h3 className="sub">Açılış cümlesi</h3>
            <p className="norm-preview" data-testid="persona-greeting">{view.greeting}</p>
            <p className="meta">
              Cümle başına ortalama {view.prompt_stats.avg_words_per_sentence ?? "-"} kelime
              (sınır {form.max_words_per_sentence}); sınırı aşan {view.prompt_stats.over_limit.length} cümle.
            </p>
            <h3 className="sub">Onay sözleri (sırayla)</h3>
            <p>{view.preview_ack.length ? view.preview_ack.join("  ·  ") : "Onay sözü yok."}</p>
            <h3 className="sub">Oluşan istem</h3>
            <pre className="persona-prompt" data-testid="persona-prompt">{view.prompt}</pre>
          </aside>
        </div>
      )}

      <ToneDemo />

      <h3 className="sub">Cümle uzunluğu raporu (kayıtlı aramalar)</h3>
      <p className="meta">Playground'da yapılan aramaların ajan cümleleri; sınır ve yasak kalıplara göre. Gerçek arama yoksa boş görünür.</p>
      <button type="button" onClick={() => fetchPersonaReport().then(setReport).catch((e) => setMsg({ kind: "err", text: String(e.message ?? e) }))}>
        Raporu getir
      </button>
      {report && (report.sessions.length === 0 ? <p className="meta" data-testid="persona-report-empty">Kayıtlı arama yok.</p> : (
        <div data-testid="persona-report">
          <p>
            <b>{report.total?.avg_words_per_sentence}</b> kelime/cümle (ort.), en uzun {report.total?.max_words}; sınırı aşan oran %
            {Math.round((report.total?.over_limit_rate ?? 0) * 100)}; yasak kalıp: {report.total?.avoid_hits.join(", ") || "yok"}.
          </p>
          <table className="eval-table">
            <thead><tr><th>Arama</th><th>Profil</th><th>Cümle</th><th>Ort. kelime</th><th>Sınırı aşan</th></tr></thead>
            <tbody>
              {report.sessions.map((s) => (
                <tr key={s.id}><td>{s.id}</td><td>{s.profile}</td><td>{s.sentences}</td>
                  <td>{s.avg_words_per_sentence}</td><td>{s.over_limit.length}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </section>
  );
}
