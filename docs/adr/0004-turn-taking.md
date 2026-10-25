# ADR 0004 — Söz sırası ve söz kesme: enerji tabanlı VAD + muhafazakâr "Smart Turn" katmanları

Durum: kabul edildi (core-002, 2026-10-25)

## Karar
Öğrenilmiş bir Smart Turn modeli eklemeden, üç katmanla başlıyoruz (backend/app/voice/session.py, vad.py):
1. **Bitiş sessizliği düğüme göre:** kısa cevap düğümlerinde 600 ms, açık uçlu (OpenText) düğümlerde 1200 ms. Düşünerek konuşulan cevaplarda duraksama turu bitirmez.
2. **Tamamlanmamış cümle bekletme:** STT metni bağlaç/dolgu ile ("evet ama", "çünkü", "şey", "ya da") ya da virgül/üç nokta ile bitiyorsa ajan hemen cevap vermez; 1,5 sn devam bekler. Devam gelirse iki konuşma **birleştirilip yeniden çözülür** (tek tur, tek transkript satırı); gelmezse süre dolunca yarım cümleye cevap verilir.
3. **Söz kesme (barge-in):** ajan konuşurken 160 ms kesintisiz yüksek ses (eşik: gürültü tabanı + 6 dB) → ajan çıkış kuyruğu hemen boşaltılır, dinlemeye geçilir. Daha kısa sesler (öksürük, tık) söz kesme sayılmaz.

## Gerekçe
- Plan "Smart Turn" diyor; öğrenilmiş model (Pipecat Smart Turn, LiveKit turn detector) Türkçe için doğrulanmadı ve ek bağımlılık/gecikme getirir. Önce ölçülebilir, açıklanabilir kurallarla başlayıp ölçüm sonrası model eklemek daha güvenli.
- Metin tabanlı bekletme ses modelinden bağımsızdır ve her STT sağlayıcısıyla çalışır; bedeli yalnızca yarım cümlede en fazla HOLD_S ek gecikmedir.
- BARGE_FRAMES 10 -> 8: 200 ms iken istemci ölçümü ≈380 ms'ydi; gerçek tarayıcının jitter tamponu için pay bırakmak üzere 160 ms'ye indirildi (≈335 ms).

## Ölçüm (bulut, sahte ses; gerçek insan konuşması ve gerçek hoparlör değil)
- aiortc istemcisi (Opus/DTLS): kullanıcı sesi başladığından ajan sesinin istemcide kesildiğine ≈330–345 ms (sunucu algılama ≈140 ms).
- Gerçek Chromium (uzak ses akışı enerjisi): 340 ms (3 koşu). Sınır 500 ms.

## Sınırlar (demoda bilinmeli)
- Enerji tabanlı VAD gürültülü ortamda ya da hoparlörden gelen ajan sesinin mikrofona karışmasında (yankı) yanlış söz kesme yapabilir; kulaklık kullanın. Tarayıcı yankı engelleme açık ama garanti değildir.
- Bekletme listesi muhafazakârdır; "hem de", "bir de" gibi birçok doğal yarım cümleyi yakalamaz. Gerçek STT çıktısında noktalama/büyük harf farkı olabilir, listede yalnızca küçük harfli kelimeler eşleşir.
- İki katman birlikte: yarım cümlede cevap gecikmesi ≈ bitiş sessizliği (0,6–1,2 sn) + 1,5 sn bekleme. p50 < 1,2 sn hedefi bu turlar için geçerli değildir (yalnızca tamamlanmış cümleler için ölçülür).
- Gerçek insan sesi, gerçek STT ve gerçek hoparlörle söz kesme ve sessiz-hat davranışı Mac'te elle doğrulanmalıdır.
