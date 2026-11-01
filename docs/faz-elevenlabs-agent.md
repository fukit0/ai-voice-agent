# Faz 3 — ElevenLabs Agent referansı (ayrı faz, henüz başlamadı)

Karar (2026-11-01, kullanıcı): ElevenLabs'ta oluşturulan agent'a senaryo verilip aramayı agent'ın yönlendirmesi ayrı bir faz olarak ele alınır. Faz 1 (lokal ajan + kıyas matrisi) ve Faz 2 (yönetim paneli, projeksiyon) kapsamını bölmez; core-027/core-012 işleri bu fazdan bağımsız sürer.

## Neden ayrı faz
- Mimari fark: bizim hatta akışı kod (FlowDriver) belirler, LLM yalnız cevabı ayrıştırır (ADR 0003/0005 hibrit). ElevenLabs Agent'ta akışı LLM prompta bakarak yönetir (A2/A3 gibi tek modelli yaklaşım, hibritin tersi). Doğallık/esneklik artar; adım atlama, yanlış dal ve cevabı yanlış kaydetme riski artar. Demoda açıkça söylenir: "iki farklı mimariyi aynı ölçütlerle kıyasladık".
- Ölçüm düzenine ayrı bir bağdaştırıcı gerekir (STT/LLM/TTS bileşen süreleri agent içinde gizli; yalnız uçtan uca ölçülebilir). Bu yüzden Faz 1 matrisini bozmadan ayrı ilerler.

## Nasıl kurulur (konuşmadan not; ElevenLabs dokümanı: https://elevenlabs.io/docs/eleven-agents/customization/personalization.md)
1. Senaryo: sistem promptuna persona, numaralı adım sırası, dallanma kuralları (katılmak istemiyorum, geri ara, bir daha aramayın/DNC) ve soru metinleri. İlk mesaj = açılış cümlesi.
2. Kişiye özel değer: prompt/ilk mesajda `{{musteri_adi}}` vb.; değerler konuşma başında `conversation_initiation_client_data.dynamic_variables` ile gider. `system__` önekli değişkenler gönderilemez. Prompt override (`conversation_config_override`) önce agent'ın Security ayarında açılmalı; doküman değişkenleri öneriyor (override eski yöntem).
3. Dallanma: prompt yetmezse workflow özelliği (DOĞRULANMADI: dokümandan okunmadı, ekranda bakılacak).
4. Cevap toplama (agent cevabı kendiliğinden yapılandırılmış vermez): (a) webhook aracı `kaydet_cevap(adim, deger)` -> bizim backend'e POST, prompta "her cevaptan sonra çağır" (öneri: ölçüm düzenimize oturur, canlı); (b) konuşma sonrası analiz (veri toplama + değerlendirme ölçütleri; kolay ama canlı değil).
5. Arama: tarayıcıdan test konuşmasıyla dene; gerçek telefonda agent'a numara bağla (Twilio/SIP), giden arama isteğinde `dynamic_variables` gönder. İstekte `conversation_initiation_client_data` varsa giriş webhook'u tetiklenmez, yoksa tetiklenir.

## Planlanan iş (öneri, onay bekliyor)
- Agent'ı kıyasa profil olarak ekle (öneri adı A4): aynı 5 persona x 4 yol (eval-001), doğruluk, gecikme ve maliyet aynı tabloda.
- Girdi gerekir: agent kimliği, araç (webhook) tanımı var mı, API anahtarı kapsamı. Henüz alınmadı.

## Doğrulanmadı / riskler
- Türkçe kalite, gecikme ve maliyet bu agent için ölçülmedi. Workflow ve araç ekran adları doğrulanmadı.
- ElevenLabs agent maliyeti (dakika fiyatı + LLM) kurumsal teklife bağlı; maliyet tablosuna henüz girmedi.
