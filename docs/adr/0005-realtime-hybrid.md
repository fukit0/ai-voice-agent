# ADR 0005 — Realtime profiller (A2/A3): hibrit yöntem

Tarih: 2026-10-25 · Özellik: core-011 · Durum: uygulandı, canlı doğrulama bekliyor (blocked)

## Karar
A2 (OpenAI Realtime) ve A3 (Gemini Live) profilleri **hibrit** çalışır: ses doğrudan modele gider, ama akışı modele değil
bizim flow motoru (`FlowDriver`) yürütür.
- Soruyu model seslendirir, ama metni biz verdik ("AYNEN SÖYLE: «…»"); model kendi cümlesini eklemez.
- Müşteri konuşunca model yalnızca `report_answer(intent, value_json)` fonksiyonunu çağırır; `FlowDriver.handle_structured`
  aynı sıkı tip denetimiyle (`check_value`) doğrular ve sonraki adımı seçer. Bozuk, yanlış tipli ya da hiç gelmeyen çağrı
  "anlaşılamadı" sayılır ve normal tekrar-sorma yolu işler.
- Söz kesme, telefon filtresi, çıkış kuyruğu, senaryo ve kayıt biçimi cascade profillerle aynı koddur.

## Neden (reddedilen yöntem)
"Tüm senaryoyu talimat olarak verip modele bırakmak" akışı belirsiz yapar (model adım atlayabilir, metni değiştirebilir),
sonuçlar profiller arasında kıyaslanamaz ve cevap doğruluğu ölçülemez. Hibritte tek değişken sesin kendisidir.

## Sağlayıcı ayrıntıları
- OpenAI: `create_response=false`; konuşma bitince `response.create` (yalnızca metin çıktısı, `tool_choice=report_answer`),
  sonra `function_call_output` + ikinci `response.create` (ses, `tool_choice=none`). **Bedel: tur başına iki model gidiş-dönüşü**;
  tek turda hem anlayıp hem konuşan "saf" realtime kullanımından yavaştır. Bu bilinçli bir takas (deterministik akış).
- Gemini: sunucu VAD'ı cevap turunu kendisi başlatır (talimat: yalnızca fonksiyon çağır); metin `realtimeInput.text` ile
  seslendirilir (`clientContent` üretimi keser). Giriş 16 kHz, çıkış 24 kHz.
- Gecikme tanımı: yerel VAD'ın konuşma bitişi → ajanın ilk sesi (cascade ile aynı tanım); kırılım: cevabı bildirme + seslendirme.
  Ayrı STT/LLM/TTS süresi yoktur; arayüz bunu açıkça belirtir.

## Doğrulananlar (bulut, sahte sağlayıcı)
`test_realtime.py` (22 test): protokol mesajları (OpenAI/Gemini), fonksiyon çağrısı → akış, yanlış tip / çağrı yok → tekrar sorma,
söz kesme, telefon filtresi, Welcome Call'ın baştan sona tamamlanması, API hataları; Chromium e2e: ajan sesi tarayıcıya ulaşır.

## Doğrulanmayanlar (demoda "çalışıyor" denmez)
1. Gerçek OpenAI/Gemini ile oturum (anahtar geçerliliği, model adının erişilebilirliği: `gpt-realtime-2.1-mini`,
   `gemini-3.8-live` adları plandan alındı, doğrulanmadı). Bağdaştırıcılar belgelere göre yazıldı (Gemini WebSocket alanları
   belgeyle karşılaştırıldı; OpenAI fonksiyon çağrısı olayları bilgiye dayalı).
2. Fonksiyon çağrısı güvenilirliği ve "AYNEN SÖYLE" sadakati, Türkçe ses kalitesi (A3 Türkçe desteği belgede doğrulanamamıştı).
3. A2/A3 gecikmesinin L2 ile 5 test aramasında karşılaştırılması (kıyas matrisi girdisi).
Komut (anahtarı ve ağı olan makinede): `.venv/bin/python scripts/realtime_smoke.py` → `evidence/core-011-live-smoke.json` ve
`data/realtime-smoke/*.wav`.
## Bilinen sınırlar
Serbest soruya cevap yok (CheckIn'de olduğu gibi); gerçek mikrofon + hoparlör yankısı denenmedi; sağlayıcı VAD'ı ile yerel VAD
birlikte çalıştığından konuşma bitişi iki kez tanımlıdır (ölçüm yerel VAD'a göre).
