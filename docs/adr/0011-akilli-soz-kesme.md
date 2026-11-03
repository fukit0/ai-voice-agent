# ADR 0011: Akıllı söz kesme (öksürük, nefes, klavye ajanı kesmesin)

Durum: Kabul (PoC), gerçek kayıtla doğrulama bekliyor. Tarih: 2026-10-30. Özellik: core-016.

## Sorun
Söz kesme yalnız seviye + süreye bakıyordu (core-015): eşiği 160 ms aşan her ses ajanı susturuyordu. Öksürük, boğaz temizleme, kapı sesi, nefes ajanı kesiyordu (kullanıcı geri bildirimi 2026-10-27).

## Seçenekler
- (a) Silero VAD: öğrenilmiş model, en sağlam. Bu ortamda model/ONNX gerçek mikrofonla doğrulanamadı, yeni bağımlılık ve model dosyası getirir.
- (b) Aday seste ajan sesini kısıp kısa STT ile doğrulama: en doğrusu ama gecikme ekler ve 500 ms bütçesini zorlar.
- (c) Spektral/perde sezgisi: bağımlılıksız, çok hızlı, zayıf kalabilir.

## Karar
(c) güçlendirilmiş hâliyle: 20 ms çerçevede ses perdesi periyodikliği (80-400 Hz), sıfır geçiş oranı ve ≥400 Hz enerji payı. Kesme için kesintisiz yüksek ses koşusunda en az 3 sesli çerçeve gerekir (`voiced_min`, 0 = kapalı). 1,2 sn perdesiz yüksek ses yine keser (süzgeç arayanı sonsuza dek susturamaz). Karar `voice/vad.BargeTracker` içinde; `session.py` ve `realtime.py` aynı sınıfı kullanır. Silero ya da kısa STT doğrulaması aynı arayüze takılabilir (Faz 1).

Gerekçe: PoC'de tekrarlanabilir, testli, bağımlılıksız ve gecikmeyi artırmıyor (sentetik konuşmada medyan kesme 160 ms, değişmedi).

## Sınırlar (demoda saklanmaz)
- GERÇEK KAYIT SONUCU (2026-10-30, 33 dosya, tek konuşmacı/mikrofon, sınıf başına n=5): ilk sürüm BAŞARISIZ (öksürük 5/5, boğaz 2/5, nefes 1/5 yanlış kesme; konuşma 1/5 kesti). Neden: ≥400 Hz payı ALT sınırdı ama gerçek konuşmada bu pay düşüktür (0,08-0,26); öksürük çerçeveleri kısmen perdeli (özilinti 0,58-0,68).
  Yeniden ayar (PEAK_MIN 0,75, HF ÜST sınır 0,30): nefes 0/5, kapı 0/5, klavye 0/5, öksürük 1/5, hmm 1/3, boğaz 4/5, konuşma 3/5 (eski süzgeçsiz davranışla AYNI; kalan 2 konuşma kaydı seviye eşiğinin altında). Süzgeçsiz: nefes 2, öksürük 5, kapı 3, hmm 1, boğaz 5, konuşma 3.
  Test hâlâ `passed:false` (boğaz, hmm, öksürük 1). Eşikler bu 33 kayda göre ayarlandı -> aşırı uyum riski; yeni konuşmacı/mikrofonla yeniden ölçülmeli.
- Konuşma kayıtları sessiz (tepe −26…−32 dB); canlı eşik −27 dBFS iken (söz kesme seviyesi −21) süzgeçsiz bile neredeyse hiç kesmez: asıl sınırlayıcı süzgeç değil SEVİYE ayarıdır.
- Boğaz temizleme ve 'hmm' perde/spektrum özellikleriyle ayrılamıyor: kısa STT/Silero doğrulaması (seçenek a/b) gerekir.
- 'Hmm' gibi sesli geri bildirimler perdeli olduğu için hâlâ keser; çözüm kısa STT doğrulaması (b).
- Fısıltı ve 'ş/s' gibi perdesiz başlangıçlar kesmeyi en çok ~sesli ünlüye kadar geciktirir (sentetikte 300 ms içinde).
- Realtime: OpenAI profilinde karar yereldir (süzgeç geçerli); Gemini'de sunucu kendi VAD'iyle keser, süzgeç etkisizdir (arayüzde uyarı notu).
- Eski testlerin "konuşma" işareti beyaz gürültüydü; artık kesmediği için konuşma benzeri sese çevrildi (bilinçli beklenti değişikliği).

## Kanıt
`backend/tests/test_barge_gate.py`; `evidence/core-016-sentetik-*.json` (süzgeçli ve süzgeçsiz). Gerçek ölçüm: `python scripts/eval_barge_gate.py --dir <etiketli klasör>`.

## Güncelleme 2026-11-03: güçlü perdede ≥400 Hz üst sınırı kalktı
Canlı aramalarda (a75c42b14e09, 981040abd23b) müşteri bağırarak konuştu. Perde 0,93–1,00 olduğu hâlde ≥400 Hz payı 0,5–0,9 çıktı.
HF_MAX=0,30 bu çerçeveleri "sesli değil" saydı. Söz kesme hiç olmadı ya da söylem başından 4,1 sn sonra oldu.
Karar: perde ≥ `PEAK_STRONG` (0,90) ise HF_MAX uygulanmaz. Ayar `Endpointer.configure(peak_strong=)` ile değişir, 0 = eski kural.
Gerçek 33 kayıtta sonuç değişmedi (0,85 bir öksürük ekliyordu). Yan etki: ajan TTS çerçevelerinin sesli oranı 0,33'ten 0,69'a çıktı.
Bu yüzden yankı söz kesme seviyesini aşarsa kendini kesme riski artar. Benzetimde yankı ajan sesinin −8 dB altına çıkınca 112 sn'de 1 kesme oldu; ölçülen yankı ≈ −22 dB.
Açık kalan: kısa kelimeler ("sekiz") 160 ms kesintisiz koşuyu dolduramıyor. Boşluk toleransı denendi, hmm/öksürük yanlış kesmesi eklediği için reddedildi.
Ayrıntı: `docs/soz-kesme-analizi-a75c42b14e09-981040abd23b.md`.
