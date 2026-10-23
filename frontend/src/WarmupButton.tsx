import { useProfile } from "./ProfileContext";

const COMP_LABEL: Record<string, string> = { stt: "STT", llm: "LLM", tts: "TTS" };

// "Hazırla": seçili profilin modellerini yükler ve ısıtır (ADR 0001). Sıcak olmayan profilde ölçüm yapılmaz.
export function WarmupButton() {
  const { active, job, prepare, prepareError } = useProfile();
  if (!active || active.mode !== "cascade") return null;
  const running = job?.state === "running";
  const current = running
    ? Object.entries(job.components).find(([, c]) => c.state === "loading" || c.state === "measuring")
    : undefined;
  const label = running
    ? `Hazırlanıyor${current ? ` · ${COMP_LABEL[current[0]] ?? current[0]}` : ""}…`
    : active.warm
      ? "Sıcak"
      : "Soğuk";
  return (
    <div className="warmup">
      <span className={`chip ${running ? "chip-busy" : active.warm ? "chip-ok" : "chip-cold"}`} data-testid="warm-state">
        {label}
      </span>
      <button type="button" onClick={prepare} disabled={running || !active.ready}
        title={active.ready ? "Modelleri yükle ve ısıt" : "Profilde eksik anahtar veya model var"}>
        {active.warm ? "Yeniden hazırla" : "Hazırla"}
      </button>
      {prepareError && <span className="status status-error">{prepareError}</span>}
    </div>
  );
}
