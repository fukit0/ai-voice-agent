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
- Eşikler SENTETİK işaretlerle ayarlandı (kapı gümbürtüsü ilk denemede kesti; üçüncü özellik o bulgudan sonra eklendi): gerçek kayıtlarla (`scripts/eval_barge_gate.py --dir`) doğrulanmadı, aşırı uyum riski var.
- 'Hmm' gibi sesli geri bildirimler perdeli olduğu için hâlâ keser; çözüm kısa STT doğrulaması (b).
- Fısıltı ve 'ş/s' gibi perdesiz başlangıçlar kesmeyi en çok ~sesli ünlüye kadar geciktirir (sentetikte 300 ms içinde).
- Realtime: OpenAI profilinde karar yereldir (süzgeç geçerli); Gemini'de sunucu kendi VAD'iyle keser, süzgeç etkisizdir (arayüzde uyarı notu).
- Eski testlerin "konuşma" işareti beyaz gürültüydü; artık kesmediği için konuşma benzeri sese çevrildi (bilinçli beklenti değişikliği).

## Kanıt
`backend/tests/test_barge_gate.py`; `evidence/core-016-sentetik-*.json` (süzgeçli ve süzgeçsiz). Gerçek ölçüm: `python scripts/eval_barge_gate.py --dir <etiketli klasör>`.
