# Kıyas koşusunda ses kaydı (eval-006)

Tarih: 2026-11-03. İlgili: eval-001 (başsız kıyas koşusu), core-013 (canlı arama kaydı, `StereoRecorder`).

## Ne yapıldı
Kıyas ekranında (Lab araçları > Kıyas koşusu) **"Ses kaydını sakla"** onay kutusu (varsayılan kapalı). Açıkken koşudaki her arama
için canlı aramalarla aynı biçimde stereo WAV yazılır (sol kanal müşteri, sağ kanal ajan, 16 kHz, 16 bit), oturum JSON'unun yanına
`<sid>.wav` olarak düşer ve JSON'a `audio` alanı eklenir (canlıdakiyle aynı alanlar + `"synthetic": true`, `"timeline": "virtual"`).
Kayıt Aramalar ekranında mevcut oynatıcıyla otomatik görünür (`has_audio`), indirilebilir ve silinebilir; kıyas sonuç satırında
"Aramalar'da dinle" bağlantısı çıkar.

- API: `POST /api/evalrun/runs` gövdesine `record_audio` (varsayılan `false`); koşu kaydına (`data/eval-runs/<id>.json`) işlenir,
  her aramada `has_audio` döner. Kapalıyken arayüz alanı hiç göndermez (istek gövdesi eskisiyle aynı).
- Kod: `backend/app/voice/recording.py` (`StereoRecorder(timeline="virtual")`), `backend/app/evalrun.py` (`run_call(record_audio=...)`).

## Kararlar ve sebepleri
1. **Sanal zaman çizelgesi, duvar saati değil.** Başsız koşu gerçek zamandan hızlıdır: ajan sesi "anında çalınmış" sayılır,
   müşteri klibi tek seferde beslenir. Canlı kaydın duvar saati hizalaması burada iki kanalı üst üste bindirirdi. Sanal kipte kayıt
   olay sırasıyla ilerleyen bir saat tutar: ajan push'ları bir blok oluşturur; müşteri klibi gelince blok kapanır, klip ajan sesinin
   bitişinden sonra yerleşir; sonraki ajan bloğu klibin (cevap sonrası 1,6 sn sessizlik dahil) bitişinden başlar. Kanallar çakışmaz.
2. **Canlı davranış değişmedi.** Varsayılan `timeline="wall"`; canlı kod yolu (rtc.py) hiç değişmedi, mevcut kayıt testleri aynen geçer.
3. **Ajan bloğu tek parça yeniden örneklenir** (48 kHz -> 16 kHz): küçük push parçalarını ayrı ayrı indirmek sınırlarda tıklama yapardı.
4. **Varsayılan kapalı.** Disk maliyeti ve kıyas ölçümünün asıl çıktısının sayılar olması; ses yalnız "neden böyle oldu" incelemesi için.
5. **Hata koşuyu bozmaz.** WAV yazılamazsa arama yine `ok` ve ölçümler döner; yalnız `has_audio: false`.
6. **Sınır:** `MAX_SECONDS` (30 dk) sanal saate de uygulanır; aşılırsa kayıt durur, `truncated: true`.

## Boyut
16 kHz x 2 kanal x 2 bayt = 64 KB/sn: **~7,5 MB / 2 dk arama**; 20 aramalık koşu **~150 MB**, "ikisi de" (40 arama) ~300 MB.
Silme Aramalar ekranından tek tek yapılır; toplu temizlik yok (production'da saklama süresi politikası gerekir).

## KVKK notu
Müşteri tarafı **sentetik persona sesidir** (ElevenLabs ile bir kez üretilmiş test klipleri); gerçek kişi sesi ve kişisel veri yoktur.
Bu yüzden canlı kayıttaki gizlilik gerekçesiyle aynı sıkılık gerekmez; yine de varsayılan kapalı tutuldu (aynı arayüz alışkanlığı).

## Sınırlama (bunu bil)
Kayıt **sıralıdır**: söz kesme, üst üste konuşma, gerçek tepki süresi ve ağ gecikmesi kayıtta yoktur. Ajanın sesi ile müşterinin
sesi arasındaki boşluk ölçülen gecikmeyi değil sanal yerleşimi yansıtır (gecikme sayıları oturum JSON'undaki `first_audio_after_end_s`
alanındadır). Kayıt **gerçek telefon kaydı gibi dinlenmemeli**; içerik/ton/akış incelemesi içindir.

## Doğrulama
`backend/tests/test_voice.py` (sanal zaman çizelgesi: sıra, çakışma yok, sınır, canlı kip regresyonu) ve
`backend/tests/test_evalrun.py` (kapalıyken WAV yok, açıkken sentetik stereo WAV + Aramalar'da `has_audio` + indirme, kayıt hatası
koşuyu bozmaz, API alanı), `frontend/src/pages/BenchmarkPage.test.tsx` (onay kutusu varsayılan kapalı, istek gövdesi, dinle bağlantısı).
Sahte modellerle doğrulandı; gerçek profil + gerçek klip setiyle Mac'te dinleyerek doğrulanmadı.
