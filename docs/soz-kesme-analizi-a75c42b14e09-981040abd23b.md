# Söz kesme analizi: oturum a75c42b14e09 ve 981040abd23b (A1S, canlı arama, 2026-11-03)

Durum: kök neden kanıtlandı ve düzeltildi (birinci neden). İkinci neden (kısa kelimeler) ölçüldü, düzeltilmedi.
İlgili: core-002 (söz kesme), core-016 (akıllı söz kesme süzgeci, blocked), ADR 0011.

## Kullanıcı şikâyeti
Ajan soruyu okurken müşteri bağırarak "Yedi puan vermek istiyorum ya da sekiz olsun. Alo, söz kesme, çalış." ve "sekiz" dedi.
Söz kesme çalışmadı, ajan okumaya devam etti.

## Kanıt kaynakları ve yöntem
- `data/voice-sessions/<id>.json` (vad ayarları, istatistik, transkript) ve `<id>.wav` (sol = ham mikrofon = VAD girişi, sağ = tarayıcıya giden ajan sesi).
- `logs/provider-calls.jsonl`: söz kesme sırasında düşürülen konuşmalar STT'ye hiç gitmiyor (akış iptal edilir), metinleri günlükte **yok**.
  Bu yüzden düşürülen bölümlerin hangi kelimeler olduğu kanıtlanamaz; yalnız akustik olarak (seviye, perde, F0) tanımlanır.
- Yeniden oynatma: `python scripts/replay_barge_session.py data/voice-sessions/<id>.wav [--peak-strong 0] [--detail a:b]`.
  Sol kanal üretimdeki `Endpointer` + `BargeTracker`'dan çerçeve çerçeve geçer; kapı ajan sesi çalarken açık.
- Kayıt anındaki kod bugünküyle aynı: `vad.py`/`speechlike.py` en son 2026-10-31'de değişti; `session.py`'nin oturumlardan sonraki tek farkı serbest cevap alanları (4742bbe).

| Oturum | Eşik (elle) | Söz kesme seviyesi | barge_frames | voiced_min | Kayıtlı barge_ins / barge_blocked | Yeniden oynatma (eski kural) |
|---|---|---|---|---|---|---|
| a75c42b14e09 | −32 dBFS | −26 dBFS | 8 (160 ms) | 3 | 4 / 1 | 6 / 3 |
| 981040abd23b | −30 dBFS | −24 dBFS | 8 (160 ms) | 3 | 4 / 3 | 5 / 3 |

Yeniden oynatma yaklaşık: ajanın durumu kayıtta yok, sağ kanaldan çıkarılıyor. Fazla barge'lar ajanın gerçek kesmeyle zaten sustuğu
anlarda (sağ kanal −120 dBFS) çıkıyor. 981040'ta blocked sayısı birebir tuttu.

## Müşteri sesinin yankı değil müşteri olduğu (ölçüm)
- Sol/sağ normalleştirilmiş çapraz ilinti (0–400 ms gecikme, 0,3–0,5 sn pencereler): 0,05–0,35 (doğrusal yankı olsaydı ≈1'e yakın olurdu).
- F0: sol kanalda 90–145 Hz (erkek sesi). Ajan (Selin, kadın TTS) 205–372 Hz.
- Yalnız ajanın konuştuğu çerçevelerde mikrofondaki kalıntı yankı: a75c p50 −46,2 / p99 −33,4 / en yüksek −30,0 dBFS. 981040 p50 −63,0 / p99 −38,2 / en yüksek −31,9 dBFS.
  İkisi de söz kesme seviyesinin (−26 / −24) altında. Tarayıcıda `echoCancellation` açık.

## Elenen nedenler (kodla karşılaştırma)
- Mikrofon kapısı yok: `rtc._read` ajan konuşurken de her çerçeveyi `session.feed`'e veriyor.
- Durum koşulu: söz kesme `thinking` ve `speaking` durumunda açık (`session._on_frame`). Ajan sesi çalarken durum `speaking`.
- Akışlı STT beklemesi yok: söz kesme kararı yalnız seviye ve perdeye bakıyor, STT kısmi sonucunu beklemiyor.
- Seviye eşiği tek başına neden değil: kaçan bölümlerde müşteri −5…−22 dBFS, söz kesme seviyesinin 2–20 dB üstünde.

## Tur tablosu (ajan konuşurken müşteri sesi)
"Koşu" = söz kesme seviyesini kesintisiz aşan 20 ms çerçeve sayısı. Söz kesme için 8 gerekir. "Sesli" = koşu içindeki perdeli çerçeve sayısı (≥3 gerekir).
"Eski" = 2026-11-03 öncesi kural, "Yeni" = bu değişiklik. Süreler araçtan (ilk yüksek çerçeveden karara).

### a75c42b14e09 (seviye −26 dBFS)
| t (sn) | Ne (transkript) | Tepe dBFS | Perde / ≥400 Hz payı | Eski | Yeni |
|---|---|---|---|---|---|
| 35,5–36,9 | "Dinlemek istemiyorum" (KVKK okunurken) | −7,4 | – | kesti, 160 ms | aynı |
| 81,2–82,7 | "Evet hatırlıyorum" | −11,4 | 0,93–0,97 / 0,63–0,84 | ilk koşu 8 çerçeve, 0 sesli: **blocked**; 82,64'te kesti (ilk sesten **660 ms**, 500 ms sınırı aşıldı) | 81,98→82,12, 160 ms |
| 91,3–92,6 | "Dilek soruyu sorabilir miyim" | −9,9 | – | kesti, 160 ms | aynı |
| 114,1–115,3 | "Bayağı iyiydi ya" | −9,6 | – | kesti, 400 ms | 160 ms |
| 125,2–127,3 | (düşürüldü, metin yok; yüksek sesli erkek sesi) | **−7,6** | 0,90–0,99 / 0,30–0,76 | 14 çerçeve koşu, 2 sesli: **blocked, ajan devam etti** | 125,38→125,52, 160 ms |
| 132,5–132,7; 152,6–152,9; 163,5–163,7 | (düşürüldü; iki kısa ünlü, ~250 ms; "sekiz" kalıbına uyuyor ama kanıtlanamaz) | −11,8…−13,8 | sesli | en uzun koşu 4–5 çerçeve: kesmedi | **değişmedi: kesmiyor** (ikinci neden) |
| 140,2–140,7 | "Merhaba, nasılsınız?" | −14,0 | – | kesti, 240 ms | aynı |

### 981040abd23b (seviye −24 dBFS)
| t (sn) | Ne (transkript) | Tepe dBFS | Perde / ≥400 Hz payı | Eski | Yeni |
|---|---|---|---|---|---|
| 39,1–40,1 | "Devam edebilir miyiz?" | −6,9 | 0,92 / 0,28 | kesti, 380 ms | 220 ms |
| 45,9–47,1 | "Devam edebilir miyiz diyorum" | −11,3 | 0,95 / 0,35 | kesti, 260 ms | 160 ms |
| 103,6–103,9 | (düşürüldü; F0 137 Hz, perde 0,89, sesli) | −9,4 | 0,89 / 0,56 | **blocked** | 103,62→103,76, 160 ms (içerik bilinmiyor) |
| 106,0–106,6 | "On vermek istiyorum" | −11,5 | – | kesti, 200 ms | (yeni kuralda ajan 103,6'da zaten susmuştu) |
| 112,2–114,7 | (düşürüldü; perde medyan 0,57: büyük olasılıkla konuşma değil) | −5,5 | 0,57 / 0,10 | blocked | **blocked (değişmedi)** |
| 131,9–133,7 | (düşürüldü; kısa sesli parçalar) | −16,1 | sesli | koşular ≤6 çerçeve: kesmedi | değişmedi |
| **135,84–140,6** | **"Yedi puan vermek istiyorum ya da sekiz olsun. Alo, söz kesme, çalış."** (5,48 sn) | −13,2 | 0,93–1,00 / **0,50–0,92** | 138,08–139,12 arası 53 çerçevelik koşu, perde ≈0,99, ≥400 Hz payı ≈0,77, **0 sesli: blocked** (1,2 sn zorla kesmeye 7 çerçeve kala). Kesme ancak 139,98'de, söylem başladıktan **4,14 sn** sonra. | 138,08→138,22, 160 ms. Söylem başından **2,38 sn** sonra. Kalan gecikme ikinci nedenden. |

## Kök neden 1 (kanıtlandı, düzeltildi): bağırınca ≥400 Hz üst sınırı konuşmayı "sesli değil" sayıyor
`speechlike.is_voiced` üç koşul arıyordu: perde ≥ 0,75, sıfır geçiş 0,02–0,30 ve **≥400 Hz enerji payı ≤ 0,30 (HF_MAX)**.
HF_MAX, 2026-10-30'da 33 kayıtla ayarlandı. O kayıtlarda konuşma sessizdi (tepe −26…−32 dBFS), ≥400 Hz payı 0,08–0,26 ölçülmüştü.
Bağırarak ya da yüksek sesle konuşulunca açık ünlülerin F1'i yükselir (erkek seste F0 ≈100 Hz iken baskın enerji 600–800 Hz'e kayar).
Kaçan bölümlerde çerçeveler çok belirgin perdeli (0,93–1,00) ama ≥400 Hz payı 0,5–0,9. Süzgeç bu yüzden müşterinin en yüksek sesli konuşmasını öksürük gibi eledi.
Kısacası "bağırınca kesildi" değil, tersine **bağırınca kesilmedi**: kesmeler yalnız ≥400 Hz payı düşük çerçevelerin (ör. 139,94: 0,04) geldiği anlarda oldu.

### Düzeltme
- `speechlike.PEAK_STRONG = 0.90`: perde ≥ 0,90 ise HF_MAX uygulanmaz. Sıfır geçiş sınırları geçerli kalır.
- Ayar çalışırken değiştirilebilir: `Endpointer.peak_strong`, `configure(peak_strong=…)` (0 = kapalı/eski kural, aksi hâlde 0,75–1,0 aralığına kırpılır).
  Veri kanalı / teklif `vad` komutu `{"peak_strong": x}` (session.py ve realtime.py `set_vad`). Değer `settings()` ile oturum JSON'una yazılır.
- Neden 0,90: ADR 0011'e göre gerçek öksürük çerçevelerinin perdesi 0,58–0,68. Taramada (gerçek 33 kayıt):

| peak_strong | nefes | öksürük | kapı | hmm | klavye | konuşma | boğaz |
|---|---|---|---|---|---|---|---|
| kapalı (eski) | 0/5 | 1/5 | 0/5 | 1/3 | 0/5 | 3/5 | 4/5 |
| 0,97 / 0,95 / 0,93 / **0,90** | 0/5 | 1/5 | 0/5 | 1/3 | 0/5 | 3/5 | 4/5 |
| 0,85 | 0/5 | **2/5** | 0/5 | 1/3 | 0/5 | 3/5 | 4/5 |

0,90 eski davranışla birebir aynı. 0,85 bir öksürük yanlış kesmesi ekliyor; bu yüzden seçilmedi.

### Önce / sonra (yeniden oynatma)
| | Eski kural | Yeni kural |
|---|---|---|
| a75c 125,4 (yüksek sesli, düşürülmüş söylem) | blocked, ajan devam etti | 160 ms'de kesti |
| a75c "Evet hatırlıyorum" | ilk sesten 660 ms | 160 ms |
| a75c "Bayağı iyiydi ya" | 400 ms | 160 ms |
| 981040 "Yedi puan … çalış." | söylem başından 4,14 sn | 2,38 sn |
| 981040 103,6 (içerik bilinmiyor) | blocked | 160 ms'de kesti |
| Toplam blocked (a75c / 981040) | 3 / 3 | 1 / 1 |

## Kök neden 2 (ölçüldü, DÜZELTİLMEDİ): kısa kelimeler 160 ms kesintisiz koşuyu dolduramıyor
Söz kesme, seviyeyi kesintisiz aşan 8 çerçeve (160 ms) istiyor. "Sekiz" gibi iki heceli kısa kelimede iki ünlü 60–100 ms sürüyor.
Arada /k/ kapanması seviyeyi eşiğin altına düşürüyor; en uzun koşu 4–5 çerçevede kalıyor.
"Yedi puan…" söyleminin ilk 2,2 saniyesi de bu yüzden kaçtı: koşular 2, 2, 7, 3 çerçeve, eşik −24 dBFS.
Denenen ve **reddedilen** düzeltme: koşunun 1–2 çerçevelik düşüşte sıfırlanmaması (boşluk toleransı).
Gerçek kayıtlarda G=1 hmm yanlış kesmesini 1/3'ten 2/3'e çıkardı. G=2 (peak_strong ile) öksürüğü 1/5'ten 2/5'e çıkardı.
Doğru çözüm ADR 0011 seçenek (a)/(b): Silero VAD ya da kısa STT doğrulaması. Pratik geçici önlem: kullanıcı eşiği daha düşük ayarlarsa (ör. −35) söz kesme seviyesi de düşer.

## Yanlış tetikleme riski (ölçüm)
- Gerçek 33 kayıt (`evidence/core-016-gercek-20261103-120407.json`): sonuç 2026-10-30 ile **aynı**. `passed:false` önceden de böyleydi (boğaz 4/5, hmm 1/3, öksürük 1/5, konuşma 3/5). Bu değişiklik ne iyileştirdi ne kötüleştirdi.
- Sentetik (`evidence/core-016-sentetik-20261103-120408.json`): konuşma 9/9 kesiyor (medyan 160 ms); öksürük, boğaz, klavye, kapı, nefes 30/30 kesmiyor.
- Ajan yankısı: ajan sesinin kendi çerçevelerinin "sesli" oranı eski kuralda 0,33, yenide 0,69 (TTS ünlüleri de yüksek ≥400 Hz payı taşıyor).
  Yankı söz kesme seviyesini aşarsa yeni kural kendini kesmeye daha yatkın. a75c ajan sesiyle yankı benzetimi (112 sn ajan konuşması):

| Kalıntı yankı (ajan sesine göre) | Eski: kendini kesme | Yeni: kendini kesme |
|---|---|---|
| −20 / −16 / −12 dB | 0 / 0 / 0 | 0 / 0 / 0 |
| −8 dB (medyan −32 dBFS) | 0 | 1 |
| −4 dB (medyan −28 dBFS) | 25 | 57 |

Bu iki oturumda ölçülen yankı ajan sesinin ≈ −22 dB altında (p50 −46 dBFS), yani güvenli bölgede.
Yankı engelleme kapalı hoparlörlü telefonda risk artar. Seviye eşiği hâlâ asıl korumadır.

## Yapılan değişiklik (dosyalar)
- `backend/app/voice/speechlike.py`: `PEAK_STRONG` ve `is_voiced(..., peak_strong=)`.
- `backend/app/voice/vad.py`: `Endpointer.peak_strong`, `configure`/`settings` alanı, `BargeTracker` bu ayarı kullanıyor.
- `backend/app/voice/session.py`, `backend/app/voice/realtime.py`: `set_vad` `peak_strong` iletiyor.
- `backend/tests/test_barge_loud_voice.py` (11 yeni test): F1 ≈700 Hz baskın sentetik "bağıran" ses.
  Özellik profili kayıtla aynı (perde ≥0,93, ≥400 Hz payı >0,30). Eski kuralda kesmiyor, yeni kuralda ≤200 ms'de kesiyor.
  Öksürük, nefes, kapı, klavye ve boğaz sesleri iki seviyede de sesli sayılmıyor. Ayar kırpılıyor.
- `scripts/replay_barge_session.py`: offline yeniden oynatma aracı.
- `docs/adr/0011-akilli-soz-kesme.md`: güncelleme notu.
- Testler: backend 964 geçti, 1 atlandı (953 + 11). Bir tam koşuda `test_streaming_stt::test_session_uses_live_transcript...` zamanlama nedeniyle bir kez düştü; tek başına ve ikinci tam koşuda geçti, değişiklikle ilgisi yok. Frontend tsc temiz, vitest 127.

## Doğrulanmayanlar
- Yeni kural canlı aramada denenmedi; kanıt offline yeniden oynatma + sentetik/kayıtlı ölçüm.
- Düşürülen bölümlerin metni yok (STT'ye gitmedi). "Sekiz" dendiği yerler akustik kalıptan tahmin, kanıt değil. Önerilen: söz kesme/blocked olaylarını zaman damgasıyla oturum JSON'una yazmak.
- Yeniden oynatmada ajan durumu yaklaşık; olay sayıları kayıtlı istatistikten ±1–2 farklı.
- Gerçek telefon hattı, hoparlör yankısı (AEC kapalı), kadın sesi / başka mikrofon: eşikler tek konuşmacı (erkek) ve iki oturumla ölçüldü, aşırı uyum riski var.
- Realtime profiller aynı `BargeTracker`'ı kullanıyor; canlı denenmedi. Gemini'de sunucu VAD'i keser, bu değişiklik etkisiz.
- Kök neden 2 (kısa kelimeler) ile boğaz temizleme ve hmm yanlış kesmeleri açık (core-016 blocked kalmalı).

## Demoda anlatırken
"Bağırınca kesmiyordu" hatası, gürültü süzgecinin sessiz konuşmaya göre ayarlanmış olmasından çıktı ve düzeltildi.
Ama kısa tek kelimelik araya girmeler ("sekiz") hâlâ ajanı kesmeyebilir. Bunu "ilk deneme" diye geçiştirme: sınırlama bilinçli, çözümü Silero/kısa STT doğrulaması.

## Ek bulgu (2026-11-03 10:30 UTC): "uzun bir cümle kuruyorum, yine kesmiyordu"
Kullanıcı oturum kimliği vermedi. a75c42b14e09 ve 981040abd23b'den sonra iki A1S oturumu var:
- 2f419d1e94fe: 08:47 UTC, 211 sn, elle eşik −40 → söz kesme seviyesi −34 dBFS.
- 603cd918e947: 08:53–09:39 UTC, otomatik eşik. Anket ~468 sn'de bitti, sonrası açık kalan hatta ofis konuşması (incelenmedi).

İkisi de cd820c2'den (09:09) **önce** başladı. JSON'larının `vad` alanında `peak_strong` yok, yani eski kodla çalıştılar.
Mac'te 09:39:53'ten sonra kaydedilmiş oturum **yok**. Kullanıcının mesajı 10:23'te geldi. Düzeltmeden sonra denediyse arka uç yeniden başlatılmamış ya da oturum kaydedilmemiş olabilir.
Doğrulama yolu: yeni oturum JSON'unda `"peak_strong": 0.9` görünmeli.

Yöntem: söylemler üretimdeki `Endpointer` ile çıkarıldı, ≥0,8 sn olanlar incelendi. Karşılaştırma: `replay_barge_session.py --peak-strong 0` (eski) ve varsayılan (cd820c2).

| Oturum / t (sn) | Ne | Ölçüm | Eski kural | cd820c2 |
|---|---|---|---|---|
| 2f419 **96,4–100,6** | Müşteri ~4,2 sn konuştu (üç parça, metin yok: düşürüldü). Ajan "Kusura bakmayın, tekrar soruyorum…" okuyordu | −11…−20 dBFS, F0 110–128 Hz, perde 0,99–1,00, ≥400 Hz payı 0,40–0,83, yankı ilintisi ≤0,16 | 96,44 ve 98,30: blocked (0–1 sesli çerçeve). 99,38'de 60 çerçeve dolunca **zorla kesme, 1,2 sn**. Kayıtlı `barge_cut_ms` içindeki **1181 ms** bu olay | 96,58'de kesti, **160 ms** |
| 2f419 81,3–82,2 | kısa söylem | perdeli, ≥400 Hz payı yüksek | blocked, sonra 620 ms | 160 ms |
| 603c 93,4 / 228,7 | kısa söylemler | aynı profil | blocked (kesmedi) | 220 / 180 ms |
| 603c 348,2–350,7 | 2,6 sn söylem | aynı profil | blocked, sonra 400 ms | 160 ms |
| 603c 443,7–445,8 | 2,1 sn söylem | aynı profil | blocked, sonra 640 ms | 220 ms |
| 2f419 137,0–138,9 | ajan konuşurken düşük ses | F0 70–76 Hz, perde 0,5–0,7, ≥400 Hz payı ≈0, −32…−42 dBFS | kesmedi | kesmedi (doğru: uğultu/mikrofon gürültüsü, konuşma değil) |

Toplam (603c yalnız anket bölümü, ≤470 sn):

| | Eski: barge / blocked / >500 ms | cd820c2: barge / blocked / >500 ms |
|---|---|---|
| 2f419d1e94fe | 10 / 3 / 1 (1200 ms) | 10 / 0 / 0, medyan 160 ms |
| 603cd918e947 | 12 / 10 / 0, medyan 200 ms | 14 / 1 / 0, medyan 160 ms |

Sonuç: "uzun cümlede kesmiyor" şikâyeti **aynı kök nedenden** (kök neden 1) çıkıyor ve cd820c2 bunu kapatıyor.
Uzun söylemde eski kural, 1,2 sn zorla kesme dolana kadar bekliyordu. Söylem parçalı olunca her parça engellenip hiç kesilmeyebiliyordu.
Elenen nedenler: yankı yok (ilinti ≤0,16, müşteri F0 erkek, ajan kadın), mikrofon kapısı yok, durum `speaking`, seviye eşiği aşılıyor (söylem çerçevelerinin %79–98'i seviye üstünde).
Yeni kod değişikliği yapılmadı. Yanlış tetikleme ölçümü (33 kayıt + sentetik) cd820c2'deki gibi geçerli.
Doğrulanmayan: düzeltmenin canlı aramada çalıştığı (düzeltme sonrası kayıtlı oturum yok); düşürülen söylemlerin metni.
