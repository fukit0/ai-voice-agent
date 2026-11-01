import { useState } from "react";
import { Icon } from "./icons";

// Oturum kimliğini panoya kopyalar. Pano API'si yoksa (http, eski tarayıcı) gizli textarea ile dener.
export function CopyIdButton({ id, label = "Oturum kimliğini kopyala" }: { id: string; label?: string }) {
  const [done, setDone] = useState(false);
  async function copy(e: React.MouseEvent) {
    e.stopPropagation();
    try {
      if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(id);
      else {
        const t = document.createElement("textarea");
        t.value = id; document.body.appendChild(t); t.select(); document.execCommand("copy"); t.remove();
      }
      setDone(true); setTimeout(() => setDone(false), 1500);
    } catch { /* pano reddedildi: sessizce geç */ }
  }
  return (
    <button type="button" className="copy-id" onClick={copy} title={done ? "Kopyalandı" : `${label}: ${id}`} aria-label={label}>
      <Icon name={done ? "check" : "copy"} size={15} />
    </button>
  );
}
