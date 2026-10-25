import { useEffect, useMemo, useRef, useState } from "react";
import {
  fetchScenario, fetchScenarios, previewScenarioText, resetStepText, saveStepText,
  type ScenarioDoc, type ScenarioStep, type ScenarioSummary,
} from "../api";

const KIND_LABEL: Record<string, string> = {
  Choice: "Seçenekli", YesNo: "Evet / Hayır", Score: "Puan", Duration: "Süre", OpenText: "Açık uçlu",
  Statement: "Anons", CheckIn: "Bilgilendirme + soru", CallbackTime: "Randevu zamanı", Terminal: "Kapanış",
};
const SECONDS_PER_CHAR = 38 / 543; // referans ekranda 543 karakter ≈ 38 sn (≈14 karakter/sn)

// Senaryolar ekranı (lab-003): adımlar gruplu listelenir, metin düzenlenir, okunuş örnek değerlerle önizlenir, akış salt okunur görünür.
// Referans: demo firmasının senaryo paneli; akış (dallar) sabittir, yalnızca metinler düzenlenir.
export function ScenariosPage() {
  const [list, setList] = useState<ScenarioSummary[]>([]);
  const [doc, setDoc] = useState<ScenarioDoc | null>(null);
  const [sel, setSel] = useState<string>("");
  const [draft, setDraft] = useState("");
  const [spoken, setSpoken] = useState("");
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const area = useRef<HTMLTextAreaElement>(null);

  const load = (key: string, keepSel = false) =>
    fetchScenario(key).then((d) => {
      setDoc(d);
      if (!keepSel) setSel(d.steps[0].key);
    }).catch((e) => setMsg({ kind: "err", text: String(e.message ?? e) }));

  useEffect(() => {
    fetchScenarios().then((l) => { setList(l); if (l[0]) void load(l[0].key); })
      .catch((e) => setMsg({ kind: "err", text: String(e.message ?? e) }));
  }, []);

  const step: ScenarioStep | undefined = doc?.steps.find((s) => s.key === sel);
  useEffect(() => {
    if (step) { setDraft(step.text); setSpoken(step.spoken); }
  }, [step?.key, step?.text]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => setMsg(null), [sel]); // mesaj yalnızca başka adıma geçince silinir (kayıt sonrası kalır)

  useEffect(() => { // okunuş önizlemesi taslağa göre (örnek değerlerle) güncellenir
    if (!doc || !step || draft === step.text) return;
    const t = setTimeout(() => {
      previewScenarioText(doc.key, draft).then((p) => setSpoken(p.spoken)).catch(() => {});
    }, 250);
    return () => clearTimeout(t);
  }, [draft, doc, step]);

  const groups = useMemo(() => {
    const g: { name: string; steps: ScenarioStep[] }[] = [];
    for (const s of doc?.steps ?? []) {
      if (!g.length || g[g.length - 1].name !== s.group) g.push({ name: s.group, steps: [] });
      g[g.length - 1].steps.push(s);
    }
    return g;
  }, [doc]);

  const insert = (name: string) => {
    const el = area.current;
    const tag = `{${name}}`;
    if (!el) return setDraft((d) => d + tag);
    const [a, b] = [el.selectionStart, el.selectionEnd];
    setDraft(draft.slice(0, a) + tag + draft.slice(b));
    requestAnimationFrame(() => { el.focus(); el.setSelectionRange(a + tag.length, a + tag.length); });
  };

  async function save() {
    if (!doc || !step) return;
    try {
      await saveStepText(doc.key, step.key, draft);
      await load(doc.key, true);
      setMsg({ kind: "ok", text: "Kaydedildi. Değişiklik bir sonraki konuşmada geçerli olur." });
    } catch (e) { setMsg({ kind: "err", text: (e as Error).message }); }
  }
  async function reset() {
    if (!doc || !step) return;
    try {
      await resetStepText(doc.key, step.key);
      await load(doc.key, true);
      setMsg({ kind: "ok", text: "Orijinal metne dönüldü." });
    } catch (e) { setMsg({ kind: "err", text: (e as Error).message }); }
  }

  const dirty = !!step && draft !== step.text;
  const seconds = Math.round(draft.length * SECONDS_PER_CHAR);
  return (
    <section className="screen" data-testid="scenarios-page">
      <h2>Senaryolar</h2>
      <p className="meta">
        lab-003 · plan F7.3 · Asistanın okuduğu metinler. Akış (hangi cevapta nereye gidileceği) sabittir; metinleri düzenleyebilirsiniz.
        Kaynak: demo firmasının örnek senaryosu (birebir kopya).
      </p>
      {list.length > 0 && (
        <div className="tabs" role="tablist">
          {list.map((s) => (
            <button key={s.key} role="tab" aria-selected={doc?.key === s.key} onClick={() => load(s.key)}>
              {s.shortLabel} <span className="chip">{s.steps}</span>
            </button>
          ))}
        </div>
      )}
      {doc && doc.problems.length > 0 && (
        <p className="status status-error" role="alert">Akış sorunları: {doc.problems.join("; ")}</p>
      )}
      {doc && (
        <div className="scn-layout">
          <nav className="scn-list" aria-label="Adımlar">
            <h3 className="sub">{doc.label}</h3>
            {groups.map((g) => (
              <div key={g.name}>
                <div className="scn-group">{g.name}</div>
                {g.steps.map((s) => (
                  <button key={s.key} type="button" className={`scn-step ${s.key === sel ? "active" : ""}`}
                    aria-current={s.key === sel} onClick={() => setSel(s.key)}>
                    <span className="scn-code">{s.code ?? "·"}</span>
                    <span className="scn-title">{s.title}</span>
                    {s.edited && <span className="dot dot-ok" title="Düzenlendi" aria-label="Düzenlendi" />}
                    {s.dtmf && <span className="meta" title="Tuşla yanıtlanabilir">#</span>}
                  </button>
                ))}
              </div>
            ))}
          </nav>
          {step && (
            <article className="scn-detail" data-testid="scenario-detail">
              <h3 className="sub">{step.title}</h3>
              <p className="scn-chips">
                {step.code && <span className="chip">{step.code}</span>}
                <span className="chip">{KIND_LABEL[step.kind] ?? step.kind}</span>
                {step.dtmf && <span className="chip">Tuşla yanıtlanabilir</span>}
                {step.edited && <span className="chip chip-ok">Düzenlendi</span>}
                {!step.applicable && <span className="chip chip-cold">Koşullu (varsayılan akışta yok)</span>}
              </p>
              {step.condition && <p className="meta">{step.condition}</p>}
              <label htmlFor="scn-text"><b>Okunacak metin</b> <span className="meta">{draft.length} karakter · ~{seconds} sn</span></label>
              <textarea id="scn-text" ref={area} rows={6} value={draft} onChange={(e) => setDraft(e.target.value)} />
              <p className="scn-ph">
                <span className="meta">Yer tutucu ekle:</span>{" "}
                {Object.keys(doc.placeholders).map((p) => (
                  <button key={p} type="button" className="chip scn-ph-btn" title={doc.placeholders[p]} onClick={() => insert(p)}>{`{${p}}`}</button>
                ))}
              </p>
              <h4 className="sub">Asistan böyle okuyacak</h4>
              <p className="norm-preview" data-testid="scenario-spoken">{spoken}</p>
              <p className="meta">Örnek değerlerle: müşteri “Ahmet Yılmaz (Bey)”, Q2 puanı 8, randevu “yarın saat on beşte”. Sayılar ve tarihler Türkçe okunuşa çevrilir.</p>
              <p>
                <button type="button" className="primary" disabled={!dirty || !draft.trim()} onClick={save}>Kaydet</button>{" "}
                {(step.edited || dirty) && <button type="button" onClick={reset}>Orijinal metne dön</button>}
              </p>
              {msg && <p className={`status ${msg.kind === "err" ? "status-error" : "status-ok"}`} role={msg.kind === "err" ? "alert" : "status"}>{msg.text}</p>}
              <h4 className="sub">Cevaba göre akış</h4>
              {step.branches.length === 0 ? (
                <p className="meta">Bu adım görüşmeyi bitirir{step.outcome ? <> · sonuç: <b>{doc.outcomes.find((o) => o.key === step.outcome)?.label ?? step.outcome}</b></> : null}.</p>
              ) : (
                <table className="eval-table" data-testid="scenario-flow">
                  <tbody>
                    {step.branches.map((b, i) => (
                      <tr key={i}>
                        <td>{step.choices.find((c) => c.label === b.on)?.dtmf ?? (step.dtmf ? "·" : "")}</td>
                        <td>{b.on || "Cevap sonrası"}</td>
                        <td><button type="button" className="scn-link" onClick={() => setSel(b.to)}>{b.to_title}</button></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              {step.edited && (
                <details>
                  <summary>Orijinal metin</summary>
                  <p className="meta">{step.defaultText}</p>
                </details>
              )}
            </article>
          )}
        </div>
      )}
    </section>
  );
}
