import type { ReactNode } from "react";
import { ElevenLabsSettings } from "../ElevenLabsSettings";
import { FastPathSettings } from "../FastPathSettings";
import { useProfile } from "../ProfileContext";
import { useTheme } from "../theme";

/** Ayarlar (ui-001): yapılandırma ÖZETİ. Düzenlenebilir olan tek şey tema (yalnız bu tarayıcıda).
 *  Konuşma davranışı değerleri backend/app/voice/vad.py sabitlerinin kopyasıdır ve burada salt okunurdur: Playground'da canlı
 *  değiştirilir (core-015), kalıcı bir ayar deposu PoC kapsamında yoktur (bkz. docs/demo-soru-cevap.md). */

const SPEECH_DEFAULTS: { name: string; desc: string; value: string }[] = [
  { name: "Söz kesme süresi", desc: "Eşiğin üstünde kesintisiz geçmesi gereken süre; kısa onaylar ('hı hı') kesmesin.", value: "160 ms (8 çerçeve)" },
  { name: "Söz kesme marjı", desc: "Normal dinleme eşiğinin üstüne eklenir; hat yankısı kesmeyi tetiklemesin.", value: "+6 dB" },
  { name: "Otomatik dinleme eşiği", desc: "Gürültü tabanı + 12 dB, en az −45 dBFS. Playground'da elle değiştirilebilir.", value: "−45 dBFS (alt sınır)" },
  { name: "Konuşma bitiş sessizliği", desc: "Müşteri sustuktan sonra cevabın bittiği sayılana kadar beklenen süre.", value: "600 ms (açık uçlu sorularda daha uzun)" },
  { name: "Tepki süresi hedefi", desc: "Konuşma bitişinden ajanın ilk sesine, medyan.", value: "≤ 1,2 sn" },
  { name: "Akıllı söz kesme (core-016)", desc: "Öksürük/klavye gibi sesleri ayıran süzgeç. Gerçek kayıtlarda henüz doğrulanmadı: boğaz temizleme ve 'hmm' hâlâ keser.", value: "Deneysel · doğrulanmadı" },
];

function Row({ name, desc, children }: { name: string; desc?: string; children: ReactNode }) {
  return (
    <div className="setting">
      <dt>{name}{desc && <span>{desc}</span>}</dt>
      <dd>{children}</dd>
    </div>
  );
}

export function SettingsPage() {
  const { active } = useProfile();
  const [theme, setTheme] = useTheme();
  const comps = active ? (["stt", "llm", "tts"] as const).map((k) => [k.toUpperCase(), active.components[k]] as const) : [];

  return (
    <section className="page settings">
      <div className="page-head">
        <div>
          <span className="eyebrow">Yapılandırma</span>
          <h2>Ayarlar</h2>
          <p className="meta">Etkin profil, ortam anahtarları ve konuşma davranışı varsayılanları. Profil seçimi üst çubuktadır; ElevenLabs modeli ve akışlı TTS bu sayfadadır.</p>
        </div>
      </div>
      <div className="settings-wrap">
        <nav className="settings-nav" aria-label="Ayar bölümleri">
          <a href="#profil">Profil</a>
          <a href="#ses">Ses (ElevenLabs)</a>
          <a href="#anlama">Cevap anlama</a>
          <a href="#konusma">Konuşma</a>
          <a href="#gorunum">Görünüm</a>
        </nav>
        <div className="settings-sections">
          <div className="panel" id="profil">
            <h3>Etkin profil</h3>
            <p className="meta">Aramalar ve ölçümler bu profilin modelleriyle yapılır</p>
            {!active ? <p className="meta">Profil yüklenmedi.</p> : (
              <dl>
                <Row name="Profil">{active.id} · {active.name}</Row>
                <Row name="Amaç">{active.purpose || "—"}</Row>
                <Row name="Mod" desc="cascade: STT → LLM → TTS; realtime: tek model.">{active.mode === "realtime" ? "Realtime" : "Cascade"}</Row>
                {active.mode === "realtime" && active.realtime
                  ? <Row name="Realtime model">{active.realtime.provider} · {active.realtime.model}</Row>
                  : comps.map(([k, c]) => <Row key={k} name={k}>{c ? `${c.provider}${c.model ? ` · ${c.model}` : ""}` : "yok"}</Row>)}
                <Row name="Durum" desc="Soğuk profilde ilk çağrı modelleri yükler; ölçümden önce Hazırla'ya basın.">
                  <span className={`pill ${active.warm ? "ok" : "warn"}`}>{active.warm ? "Sıcak" : "Soğuk"}</span>
                </Row>
                <Row name="Ortam anahtarları">
                  {active.missing_env.length
                    ? <span className="pill err" role="alert">Eksik: {active.missing_env.join(", ")}</span>
                    : <span className="pill ok">Tamam</span>}
                </Row>
              </dl>
            )}
            <p className="note">Anahtarlar sunucudaki <code>.env</code> dosyasından okunur; tarayıcıdan girilmez ya da gösterilmez.</p>
          </div>

          <div className="panel" id="ses">
            <h3>Ses (ElevenLabs)</h3>
            <p className="meta">Aktif profilin TTS modeli ve akış ayarı. Seçim kalıcıdır, yeni aramalara uygulanır.</p>
            <dl><ElevenLabsSettings /></dl>
          </div>

          <div className="panel" id="anlama">
            <h3>Cevap anlama (hızlı yol)</h3>
            <p className="meta">Aktif profil için; seçim kalıcıdır, yeni aramalara uygulanır.</p>
            <dl><FastPathSettings /></dl>
          </div>

          <div className="panel" id="konusma">
            <h3>Konuşma davranışı</h3>
            <p className="meta">Varsayılan değerler (salt okunur)</p>
            <dl>
              {SPEECH_DEFAULTS.map((s) => <Row key={s.name} name={s.name} desc={s.desc}>{s.value}</Row>)}
            </dl>
            <p className="note">Eşik ve söz kesme ayarları Playground'da canlı değiştirilir. Kalıcı ayar deposu bu PoC'de yoktur; değerler kod sabitleridir.</p>
          </div>

          <div className="panel" id="gorunum">
            <h3>Görünüm</h3>
            <p className="meta">Yalnız bu tarayıcıda saklanır</p>
            <dl>
              <Row name="Tema" desc="Koyu tema varsayılandır.">
                <div className="seg" role="radiogroup" aria-label="Tema">
                  <button type="button" role="radio" aria-checked={theme === "dark"} onClick={() => setTheme("dark")}>Koyu</button>
                  <button type="button" role="radio" aria-checked={theme === "light"} onClick={() => setTheme("light")}>Açık</button>
                </div>
              </Row>
            </dl>
          </div>
        </div>
      </div>
    </section>
  );
}
