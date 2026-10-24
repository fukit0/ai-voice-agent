# ADR 0002 — Ses taşıma katmanı: aiortc ile doğrudan WebRTC (Pipecat yerine)

Durum: kabul edildi (core-001, 2026-10-24)

## Bağlam
PoC Planı F1.1, tarayıcıdan mikrofonla konuşmayı "yerel WebRTC" ile ve Pipecat iskeleti üzerinde öngörüyor.
Elimizde zaten sağlayıcı soyutlaması (STT/LLM/TTS arayüzleri), ısıtma kapısı (ADR 0001) ve profil sistemi var.

## Karar
Pipecat'i eklemek yerine **aiortc** ile WebRTC'yi doğrudan kuruyoruz: Opus ses, DTLS-SRTP, olaylar için `events` RTCDataChannel.
Hat: mikrofon → 16 kHz mono → enerji tabanlı konuşma bitişi (Endpointer) → STT → LLM → cümle cümle (trnorm + TTS) → 48 kHz, 20 ms çerçeveli ajan izi.
Söz kesme: ajan konuşurken kullanıcı sesi `BARGE_FRAMES` boyunca eşiği aşarsa ajan çıkışı hemen boşaltılır.

## Gerekçe
- Mevcut sağlayıcı arayüzlerimiz ve adil kıyas düzeneğimiz (eval-llm, STT/TTS stüdyoları) Pipecat servis modeline yeniden yazılmak zorunda kalmazdı.
- aiortc, Pipecat'in SmallWebRTC taşımasının da altında yatan kütüphanedir; ileride Pipecat'e geçiş taşıma katmanını kaybettirmez.
- Bağımlılık ağırlığı ve bulutta modelsiz test edilebilirlik: tüm hat sahte sağlayıcılarla (`SVA_FAKE_PROVIDERS=1`) gerçek WebRTC üzerinden CI'da koşuyor.

## Sapma ve sınırlar (Plana göre)
- Plandan sapma: Pipecat yok. Üretimde (telefon/SIP, çok oturum) Pipecat veya LiveKit değerlendirmesi core-0xx kapsamında yeniden açılır.
- VAD enerji tabanlı (PoC). Gürültülü ortamda hatalı başlangıç/bitiş verebilir; Silero VAD sonraki adımdır.
- Yankı engelleme tarayıcıdadır (echoCancellation); hoparlörle kullanımda kendi sesini duyup söz kesebilir: demoda kulaklık kullanın.
- Tek Mac'te en çok 3 eşzamanlı oturum; ölçüm profilinin sıcak olması şart (409 `profile_not_warm`).
- Gerçek mikrofon + gerçek modellerle gecikme (Faz 1 kapısı p50 < 1,2 sn) bu ADR ile ölçülmüş sayılmaz; Mac'te elle ölçülür.
