// Lab ekranlarının tek kaynağı: menü, yönlendirme ve testler buradan okur.
// featureId, feature_list.json'daki kayıtla eşleşir.
export type Screen = {
  path: string;
  label: string;
  featureId: string;
  planRef: string;
  summary: string;
};

export const SCREENS: Screen[] = [
  {
    path: "/tts",
    label: "TTS stüdyosu",
    featureId: "lab-001",
    planRef: "F7.1",
    summary:
      "Cümle seti girilir, TTS modelleriyle ses üretilir, ilk ses süresi ve RTF loglanır. Dinleyici modu klipleri gizli kimlik ve rastgele sırayla çalar, puanları toplar.",
  },
  {
    path: "/stt",
    label: "STT test",
    featureId: "lab-002",
    planRef: "F7.2",
    summary:
      "Ses yüklenir veya kaydedilir; STT modellerinin çıktısı yan yana, referans metne göre WER ve süreyle görünür.",
  },
  {
    path: "/llm",
    label: "LLM testi",
    featureId: "eval-llm",
    planRef: "Faz 0 adım 4",
    summary:
      "30 örnek müşteri cevabı seçili LLM'lerden geçer; doğru normalize (değer) ve doğru dal oranı, JSON geçerliliği ve gecikme yan yana görünür.",
  },
  {
    path: "/scenarios",
    label: "Senaryolar",
    featureId: "lab-003",
    planRef: "F7.3",
    summary:
      "Anket senaryosunun adımları, okunacak metinler ve cevaba göre akış; metin düzenlenir, okunuşu örnek değerlerle önizlenir.",
  },
  {
    path: "/playground",
    label: "Playground",
    featureId: "lab-003",
    planRef: "F7.3",
    summary:
      "Mikrofonla ajanla konuşma: profil ve senaryo seçimi, telefon filtresi, canlı transkript, tur başına STT / LLM / TTS gecikmesi.",
  },
  {
    path: "/calls",
    label: "Aramalar",
    featureId: "lab-004",
    planRef: "F7.4",
    summary: "Test aramalarının listesi ve detayı: transkript, ses kaydı, çıkarılan cevaplar, gecikmeler.",
  },
  {
    path: "/matrix",
    label: "Kıyas matrisi",
    featureId: "lab-005",
    planRef: "F7.5",
    summary: "Profil koşuları ve dinleme puanlarından otomatik dolan ağırlıklı kıyas matrisi.",
  },
];
