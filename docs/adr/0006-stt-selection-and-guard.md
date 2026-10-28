# ADR 0006 — STT seçimi ve STT geçidi (sttguard) eşikleri

Tarih: 2026-10-28 · Özellik: core-020 · Durum: karar verildi, ölçüm 56 klip (tek konuşmacı, Mac mikrofonu)

## Veri
`evidence/core-020-stt-eval.json`: 56 kısa klip (on, evet/hayır, rakam, kod karışımı, kısa cümle, 4 öksürük, 5 gürültü), 3 STT.

| STT (profil) | WER | Tam eşleşme | Gürültü/öksürük yazıya dökülme | Geçit doğru ret | Geçit yanlış ret | p50 sn |
|---|---|---|---|---|---|---|
| Deepgram nova-3 (A1) | 0,29 | 0,79 | 0,11 | 0,82 | 0,00 | 1,06 |
| Whisper large-v3-turbo MLX (L2) | 0,62 | 0,40 | 1,00 | 0,35 | 0,00 | 0,52 |
| BuzzASR/turkish HF (L3) | 2,01 | 0,79 | 1,00 | 0,26 | 0,00 | 1,34 |

Geçit sonuçları `repetition_loop` kuralı eklendikten sonraki yeniden hesaptır (kural ölçümden çıkan bulgudur).

## Karar
1. **Kalite referansı: Deepgram.** Öksürük/gürültüyü neredeyse hiç yazıya dökmüyor (`confidence=0` ile boş dönüyor) ve geçit
   onu %82 yakalıyor, doğru cevapları reddetmiyor. Bulut STT olduğu için gerçek müşteri sesi için KVKK/yer kararı ayrıca gerekir (plan: demo API'leri).
2. **Yerel hat (L2/L3): Whisper tabanlı STT öksürükte metin uydurur** ("İzlediğiniz için teşekkür ederim", "System 12", "Köhömm", "Hıhıhı…").
   Yalnızca eşik/sezgisel geçitle çözülmez: halüsinasyon metinlerinde logprob yüksek, `no_speech_prob` ≈ 1e-10. Geçit bunların
   %26–35'ini yakalıyor. L3 (BuzzASR) tekrar döngüsüne giriyor; WER 2,01 bu yüzden.
3. **Geçit eşikleri değişmedi** (güven 0,5; logprob −1,0; sıkıştırma 2,4): taramada yanlış ret ≤%5 koşuluyla daha iyi bir ayar
   bulunmadı (Deepgram için 0,4 aynı sonuç). **Yeni kural:** tekrar döngüsü (`repetition_loop`: aynı ≤4 karakterlik parça ≥8 kez ardışık ya da 30+ karakterlik "kelime").
4. **Yerel hatta öksürük için asıl çözüm geçit değil, giriş tarafı:** ses seviyesi/süre ile yalnızca sese bakan söz kesme ve uç nokta öksürüğü konuşma sanıyor. Silero VAD gibi konuşma-olasılığı modeli core-016'da denenecek.

## Sınırlar (demoda saklanmaz)
- Plain **large-v3 ölçülmedi** (L2 large-v3-turbo). Tek konuşmacı, sessiz oda; telefon filtresi/8 kHz ve gerçek müşteri sesi yok.
- Tam eşleşme "on" / "10" gibi yazım farklarını da hata sayar; rakam sözle yazma (norm-007) sonrası yeniden ölçülmeli.
- Geçit yanlış ret oranı 0 çıkması 37 cevap klibiyle sınırlı; üretimde daha çok veriyle izlenmeli.
