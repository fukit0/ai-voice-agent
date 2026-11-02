# STT yavaşlık analizi — oturum 888090ca1304 (2026-11-02)

Kaynak: `data/voice-sessions/888090ca1304.json`, `logs/provider-calls.jsonl` (08:54–09:00 UTC), `voice/session.py::_transcribe_live`, `voice/sttguard.py`.
Profil **A1S** (Deepgram nova-3 akış + toplu yedek). 25 konuşma, 5 yedek.

## Tur bazında
| Tur | Ses (sn) | stt_s | Akış | Toplu yedek | Neden |
|---|---|---|---|---|---|
| 3 | 15,0 | 2,10 | 0,17 | 1,92 | guard:low_confidence |
| 7 | 1,58 | 2,45 | 1,50 (zaman aşımı) | 0,95 | Finalize 1,5 sn'de gelmedi |
| 9 | 1,30 | 1,54 | 0,40 | 1,13 | guard:low_confidence |
| 37 | 2,30 | 2,24 | 0,39 | 1,85 | low_confidence; toplu da reddedildi (conf 0,17) |
| (kayıtsız, ~08:56:03) | 2,50 | ~1,97 | 0,24 | 1,72 | empty; tur kaydı yok |
| 5 | 1,50 | 0,97 | 0,97 | — | yedeksiz, yavaş Finalize |
| Diğer 19 tur | 0,96–15,0 | 0,16–0,33 (medyan ~0,21) | | | — |

## Kanıtlı kök nedenler
1. **Yavaşlık akışta değil, toplu yedekte.** Yedekte konuşmanın tamamı REST ile yeniden çözülüyor (0,95–1,92 sn). Yedeksiz turlar 15 sn seste bile 0,23 sn.
2. **Yedeğin %60'ı düşük güven geçidi** (MIN_CONFIDENCE 0,5). Ortamda ikinci konuşan var ("Dur oğlum…", "Bak anlayamadı ya"); tur 37'de yedek de reddedildi, 1,85 sn boşa gitti.
3. **Bir tur Finalize zaman aşımı** (1,5 sn), ardından yedek: toplam 2,45 sn.

Elenenler: ses uzunluğu (15 sn → 0,23 sn), soğuk bağlantı (ilk akış turu 0,17 sn; prewarm 0,89 sn), Mac'te eşzamanlı Whisper/TTS çağrısı (pencerede yalnız bu oturumun çağrıları var).

## Doğrulanmadı
- Toplu yedeğin 1,72/1,85 sn sürmesi (geçmiş p50 0,98, p90 1,49): bağlantı havuzu mu, Deepgram mı, ağ mı ayrıştırılamadı.
- Finalize zaman aşımının nedeni (ağ / Deepgram). 2026-11-01'de 275 zaman aşımı vardı, bugün 25'te 1: fark açıklanamadı.
- Mac sistem yükü ve WebSocket açılış süresi kaydedilmiyor.
- VAD bekleme (600/1200 ms) stt_s'e dahil değil ama algılanan beklemeye ekleniyor. Tur 3'te 15 sn üst sınıra kadar konuşma kapanmadı.

## Öneriler (çarşamba öncesi, öncelik sırasıyla)
1. **Demo ortamı:** sessiz oda, kulaklık, tek konuşan.
2. **Düşük güvende toplu yedeği atlama seçeneği:** 0,3 altında doğrudan "anlaşılmadı" (tur 37 türü 1,8 sn kazanç). Tur 3/9 yedekle kurtuldu; eşik kayıtlı WAV'larla ölçülmeden açılmamalı.
3. `stream_finish_timeout_s` 1,5 → ~0,8 (profil ayarı, kod değil). Bugün başarılı akış en fazla 0,97 sn; 11-01 p90 1,40, önce ölçülmeli.
4. Gözlemlenebilirlik: tur kaydına `stt_stream_s` / `stt_batch_s` / ws açılış süresi; "empty" yedeğinde de tur kaydı yazılsın.
5. Demoda: "STT tipik 0,2 sn; güvensiz turda tüm ses yeniden çözülür, 1,5–2,5 sn."
