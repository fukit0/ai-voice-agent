// Lab ekranlarının tek kaynağı: menü, yönlendirme ve testler buradan okur.
// featureId, feature_list.json'daki kayıtla eşleşir. `group` yan menüdeki başlığı, `icon` simgesini belirler (ui-001).
export type NavGroup = "Genel" | "Arama" | "Kayıtlar & Raporlar" | "Yapılandırma" | "Lab araçları";
export const NAV_GROUPS: NavGroup[] = ["Genel", "Arama", "Kayıtlar & Raporlar", "Yapılandırma", "Lab araçları"];

export type Screen = {
  path: string;
  label: string;
  featureId: string;
  planRef: string;
  summary: string;
  group: NavGroup;
  icon: string;
};

export const SCREENS: Screen[] = [
  {
    path: "/overview",
    label: "Genel Bakış",
    featureId: "ui-001",
    planRef: "F7.4",
    group: "Genel",
    icon: "grid",
    summary: "Kayıtlı aramalardan özet: görüşme sayısı, tamamlanma, süre, tepki süresi, söz kesme ve sonuç dağılımı.",
  },
  {
    path: "/playground",
    label: "Playground",
    featureId: "lab-003",
    planRef: "F7.3",
    group: "Arama",
    icon: "phone",
    summary:
      "Mikrofonla ajanla konuşma: profil ve senaryo seçimi, telefon filtresi, canlı transkript, tur başına STT / LLM / TTS gecikmesi.",
  },
  {
    path: "/calls",
    label: "Aramalar",
    featureId: "lab-004",
    planRef: "F7.4",
    group: "Kayıtlar & Raporlar",
    icon: "headphones",
    summary: "Test aramalarının listesi ve detayı: transkript, ses kaydı, çıkarılan cevaplar, gecikmeler.",
  },
  {
    path: "/matrix",
    label: "Kıyas matrisi",
    featureId: "lab-005",
    planRef: "F7.5",
    group: "Kayıtlar & Raporlar",
    icon: "target",
    summary: "Profil koşuları ve dinleme puanlarından otomatik dolan ağırlıklı kıyas matrisi.",
  },
  {
    path: "/scenarios",
    label: "Senaryolar",
    featureId: "lab-003",
    planRef: "F7.3",
    group: "Yapılandırma",
    icon: "flow",
    summary:
      "Anket senaryosunun adımları, okunacak metinler ve cevaba göre akış; metin düzenlenir, okunuşu örnek değerlerle önizlenir.",
  },
  {
    path: "/persona",
    label: "Persona",
    featureId: "core-005",
    planRef: "F1.5",
    group: "Yapılandırma",
    icon: "wave",
    summary:
      "Ajanın adı, tonu, hitap tarzı, cümle uzunluğu sınırı ve doğal onay sözleri girilir; oluşan istem canlı görünür, kayıtlı aramalarda cümle başına kelime sayısı raporlanır.",
  },
  {
    path: "/settings",
    label: "Ayarlar",
    featureId: "ui-001",
    planRef: "F7",
    group: "Yapılandırma",
    icon: "gear",
    summary: "Etkin profil, model bileşenleri, ortam anahtarları, konuşma davranışı varsayılanları ve tema.",
  },
  {
    path: "/tts",
    label: "TTS stüdyosu",
    featureId: "lab-001",
    planRef: "F7.1",
    group: "Lab araçları",
    icon: "speaker",
    summary:
      "Cümle seti girilir, TTS modelleriyle ses üretilir, ilk ses süresi ve RTF loglanır. Dinleyici modu klipleri gizli kimlik ve rastgele sırayla çalar, puanları toplar.",
  },
  {
    path: "/stt",
    label: "STT test",
    featureId: "lab-002",
    planRef: "F7.2",
    group: "Lab araçları",
    icon: "mic",
    summary:
      "Ses yüklenir veya kaydedilir; STT modellerinin çıktısı yan yana, referans metne göre WER ve süreyle görünür.",
  },
  {
    path: "/llm",
    label: "LLM testi",
    featureId: "eval-llm",
    planRef: "Faz 0 adım 4",
    group: "Lab araçları",
    icon: "check",
    summary:
      "30 örnek müşteri cevabı seçili LLM'lerden geçer; doğru normalize (değer) ve doğru dal oranı, JSON geçerliliği ve gecikme yan yana görünür.",
  },
];
