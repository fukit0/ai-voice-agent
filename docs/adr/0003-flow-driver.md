# ADR 0003 — Anket akışı: deterministik motor + LLM yalnızca cevabı yapılandırır

Durum: kabul edildi (lab-003, 2026-10-24)

## Karar
Konuşmayı `FlowDriver` (backend/app/voice/flow.py) yönetir. Akış (dallar) `config/scenarios/*.json` içindedir ve sabittir; metinler düzenlenebilir (data/scenario-overrides). Her soru adımında LLM'e eval-llm ile aynı JSON sözleşmesi verilir: `{"intent","value"}`; sonraki adımı LLM değil `scenario.next_step` seçer.
Statement adımları ardışık okunur, soruda durulur. Açık uçlu (OpenText) cevaplar LLM çağrılmadan metin olarak kaydedilir (gecikme kazancı).

## Gerekçe
- Plan: "akışı deterministik flow motoru yönetir, LLM yalnızca düğüm içinde konuşur ve cevabı yapılandırır". Denetlenebilir, aynı girdi aynı dal.
- Sağlayıcıdan bağımsız (tüm profillerde `LLMProvider.complete`), eval-llm ölçümleri doğrudan geçerli (L2 %97, A1 %97, L5 %100).
- Kesin tip doğrulama: '9' metni sayı sayılmaz; geçersiz çıktı "anlaşılamadı" gibi işlenir.

## Davranış kuralları
- Anlaşılmayan cevap en fazla 2 kez farklı biçimde tekrar sorulur (2.'de ipucu eklenir). Sonra: Puan/Süre/Açık uçlu için "cevap yok" dalı; Evet-Hayır/Seçenekli için kibar kapanış, sonuç `sistem_sonlandirdi`.
- `repeat` tekrar hakkı harcamaz. `refuse` -> ret kapanışı, `dnc` -> aranma yasağı kapanışı, `callback` -> randevu adımı. `off_topic`: kısa not + soruya dönüş.
- Q2 puanı sonraki metinlerde ({Q2}) sözle, randevu zamanı ({RANDEVU}) müşterinin söylediği ifadeyle doldurulur.

## Sınırlar (demoda bilinmeli)
- Sessiz hat (kapanis_sessiz) ve ses katmanı olayları (müşteri hiç konuşmuyor) henüz bağlı değil.
- Cevap çıkarma gürültülü STT çıktısıyla ölçülmedi; gerçek modellerle uçtan uca anket tamamlanma oranı ölçülmedi.
- Telefon filtresi yalnızca bant sınırlama (≈300–3400 Hz) ve 8 kHz'e denk bant; G.711/AMR codec sıkıştırması ve paket kaybı yok.
- `off_topic` için soruya gerçek yanıt (ör. "neden soruyorsunuz") üretilmez; yalnızca nazik geri dönüş.
