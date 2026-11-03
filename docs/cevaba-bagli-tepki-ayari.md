# Cevaba bağlı tepkiler: aç/kapa ayarı (hum-001)

Tarih: 2026-11-03

## Ne yapıldı
- **Ayarlar > Cevaba bağlı tepkiler** paneli: onay kutusu (Açık/Kapalı), açıklama ve "Varsayılana dön". Varsayılan **AÇIK**, yani mevcut hum-001 davranışı sürer.
- **Kapalı** olunca hum-001 öncesi davranışa döner (commit `f2b40d4` öncesi `flow.py`: `persona_mod.ack(...)`). Her kabul edilen cevaptan sonra persona `acknowledgements` sözleri sırayla söylenir ("Anladım.", "Teşekkür ederim.", ...). `reaction_rate` bu durumda uygulanmaz, çünkü eskiden de uygulanmıyordu.
- Tepki havuzu ve oranı (persona) **silinmez**, sadece kullanılmaz. Ayar tekrar açılınca aynen geri gelir.
- Kalıcılık `data/reactions.json` dosyasında. Dosyaya yalnızca varsayılandan farklı bir değer yazılır. Yazma atomiktir (`.new` + replace). Dosya bozuksa varsayılan geçerli olur.
- API: `GET /api/reactions` ve `PUT /api/reactions {"enabled": true|false|null}`. `null` varsayılana döndürür.
- Ayar yeni aramalara uygulanır. Arama başında `reaction_setting.apply_to(flow)` çağrılır ve değer o anda FlowDriver'a kopyalanır. Açık bir arama başladığı ayarla sürer (free-reply ve model seçimiyle aynı desen).
- Kayıtlar:
  - Arama kaydına `config.reactions = {"enabled": bool}` yazılır. Persona yoksa (realtime) değer `null` olur.
  - Tur kaydına `reaction = {"source", "bucket"}` yazılır. `source` şu değerlerden biridir: `pool` (hum-001), `ack` (açık ama kova boş), `fixed_ack` (ayar kapalı), `context` (off-001), `skipped` (oran gereği atlandı).

## Karar: off-001 bağlam tepkileri ayardan bağımsız
Müşteri cevapla birlikte bir soru sorduğunda verilen kısa yanıt ve şikayete gösterilen empati (off-001) kapalıyken de çalışır. Bunlar müşterinin *söylediğine* verilen işlevsel yanıtlardır. Ayar yalnızca *değere* bağlı hum-001 kova tepkisini kapatır. Kapatılırlarsa "numaramı nereden buldunuz" sorusu cevapsız kalırdı.

## Kapsam dışı
- Realtime hatta tepki katmanı zaten yoktur.
- `evalrun` ve `offtopic_eval` simülasyonları bu ayarı okumaz. FlowDriver'ın varsayılanı açık olduğu için ölçümler hum-001 davranışıyla yapılmaya devam eder.

## Doğrulama
- Backend: 919 test geçti, 1 atlandı (önceden 907). Yeni testler `backend/tests/test_reaction_setting.py` dosyasında (12 test) ve şunları kapsıyor:
  - kapalıyken havuz tepkisi yok, sabit onaylar sırayla söyleniyor ve oran uygulanmıyor,
  - açıkken davranış değişmiyor,
  - off-001 bağlam tepkisi korunuyor,
  - kalıcılık ve bozuk dosya,
  - API GET/PUT ve 422 hatası,
  - arama başında değerin kopyalanması,
  - arama ve tur kaydı.
- Frontend: tsc temiz, 123 test geçti (önceden 121). Yeni testler `frontend/src/ReactionSettings.test.tsx` dosyasında.
- **Doğrulanmadı:** bulutta Mac'in localhost'una erişilemiyor. Gerçek sesli arama ile TTS'in sabit onayı ya da tepkiyi seslendirmesi denenmedi.

## Demoda anlatırken
Bu ayar "insansı tepki ne kadar fark yaratıyor" karşılaştırması içindir: aynı anket bir kez Açık, bir kez Kapalı yapılır. Kapalıyken bile empati ve araya giren sorulara verilen yanıtlar sürer. Bu nedenle Kapalı mod saf "robot" değildir, hum-001 öncesi hâlidir.
