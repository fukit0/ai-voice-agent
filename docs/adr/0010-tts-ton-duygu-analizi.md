# ADR 0010 - TTS ton/duygu kontrolü analizi (Chatterbox, ElevenLabs) — uygulandı; ElevenLabs doğrulaması ve ses kalibrasyonu açık

Tarih: 2026-10-30. İlgili: core-005 (Persona), Demo S1/S28, scn-010 (ses seçimi, Faz 2).

## Gözlem (kullanıcı, gerçek dinleme)
- Persona'da ton değişince Chatterbox'ta hiçbir fark yok; ElevenLabs'te "samimi" seçince ses daha resmî duyuldu.

## Kök neden (koddan, doğrulandı)
- Persona'daki "ton" TTS'e HİÇ iletilmiyor; yalnızca LLM istemine (serbest sohbet) giriyor. TTS'e giden tek persona alanı konuşma hızı (`speed`).
- Chatterbox çağrısı `generate(text, language_id)`: `exaggeration`, `cfg_weight`, `audio_prompt_path` verilmiyor, kütüphane varsayılanları (0,5 / 0,5) ve varsayılan ses kullanılıyor.
- ElevenLabs çağrısı yalnızca `speed != 1` ise `voice_settings.speed` gönderiyor; `stability`, `style`, `similarity_boost` verilmiyor (sesin kayıtlı ayarları geçerli) ve `seed` yok.
- ElevenLabs'te "daha resmî" algısı büyük olasılıkla **üretim rastgeleliğidir** (belgeye göre çıktı deterministik değil, `seed` en iyi çaba ile tutarlılık sağlar). Aynı cümle iki kez üretilse farklı duyulabilir; ton seçimi bunun nedeni değil. Kanıt: ton alanı hiçbir TTS parametresine bağlı değil. Doğrulama: aynı cümleyi aynı seed ile iki kez üretip aynı olduğunu dinleyin.

## Chatterbox: ton/duygu nasıl girilir (kaynak: resemble-ai/chatterbox, mtl_tts.py)
- `exaggeration` (varsayılan 0,5): duygu şiddeti. Yüksek değer daha ifadeli ve **daha hızlı** konuşturur. Aralık kodda zorlanmıyor; pratik 0,25–1,0.
- `cfg_weight` (varsayılan 0,5): tempo/ifade dengesi. Düşük (≈0,3) daha yavaş ve düşünceli; ifadeli konuşmada `exaggeration` ≈0,7+ ile birlikte `cfg_weight` ≈0,3 önerilir. Referans klip dil/aksan aktarımını azaltmak için `cfg_weight=0`.
- `temperature` (0,8): çeşitlilik/rastgelelik; düşük = daha tutarlı.
- `audio_prompt_path` (referans klip, ~10 sn): **ses tınısını ve konuşma stilini klonlar**; ton farkı için en güçlü araç. Samimi ve resmî iki ayrı referans kayıt, ayar sayılarından daha belirgin fark verir. Referans dili `language_id` ile aynı olmalı (aksan). Kişi sesi yalnız yazılı izinle (S1).
- `[laugh]`, `[chuckle]` gibi paralinguistik etiketler yalnız Turbo/Nano modellerinde; çok dilli (Türkçe) modelde yok.
- Türkçe `language_id="tr"` destekleniyor (23 dil). Sınır: Chatterbox bu Mac'te canlı hatta kullanılamıyor (ADR 0001), yalnızca stüdyo.

## ElevenLabs: ton/duygu nasıl girilir
- `voice_settings.stability` (0–1, varsayılan 0,5): düşük değer **daha geniş duygu aralığı**, yüksek değer daha düz/tutarlı (resmî). Resmî ton = yüksek, samimi = düşük.
- `voice_settings.style` (varsayılan 0): stil abartısı; sıfırdan büyük değer ek hesap ve **gecikme** getirir. Flash v2.5'te etkisi belgede doğrulanmadı, dinleyerek test edilmeli.
- `voice_settings.similarity_boost` (0–1, 0,75) ve `use_speaker_boost` (açık = gecikme artar): ses benzerliği, ton değil.
- `voice_settings.speed` (0,7–1,2): bağlı.
- `seed` (0–4294967295): A/B karşılaştırmada rastgeleliği sabitlemek için şart.
- Metin ipuçları: ünlem, üç nokta (duraklama), BÜYÜK HARF (vurgu) tonu etkiler; tasvir cümleleri ("dedi heyecanla") **sesli okunur**.
- Eleven v3/v4 **ses etiketleri** (`[whispers]`, `[sighs]`, `[laughs]`): en doğrudan duygu kontrolü, ama v3 gerçek zamanlı ajan için önerilmiyor; Flash v2.5 (≈75 ms, 32 dil, Türkçe var) gerçek zamanlı için doğru model ve belgede etiket/duygu desteği tanımlı değil.
- `previous_text`/`next_text`: parçalar arası süreklilik (cümle cümle TTS'te kullanışlı).

## Öneri (ilk analiz; 2026-10-30'da uygulandı, aşağıdaki "Uygulama" bölümüne bakın)
1. Ton → TTS parametre eşlemesi `config/tone-voice.json`'da tutulur, ekrandan düzenlenebilir: ElevenLabs samimi {stability 0,35; style 0,3}, resmî {stability 0,7; style 0}; Chatterbox samimi {exaggeration 0,6; cfg_weight 0,4}, resmî {0,3; 0,5}. **Sayılar başlangıç tahminidir, dinleyerek kalibre edilir.**
2. TTS stüdyosunda sabit `seed` ile aynı cümleyi samimi/resmî iki ton için yan yana üretme (kör dinleme).
3. Chatterbox'ta en belirgin fark için referans klip seçimi (samimi/resmî) ayrı bir seçenek.
4. EMA'da ton değişmez (tek ses, duygu yok); yalnız hız.
5. Canlı hatta ElevenLabs Flash v2.5 ile `style` gecikmesi ölçülür; kabul edilmezse yalnız `stability`.

## Sınırlar
- ElevenLabs `style`'ın Flash v2.5'te işe yarayıp yaramadığı ve v3 etiketlerinin Türkçe kalitesi doğrulanmadı.
- Duygu/ton algısı öznel; kör dinleme ile ölçülmeli.

Kaynaklar: resemble-ai/chatterbox README ve mtl_tts.py; elevenlabs.io/docs (voice settings default, convert API, models, prompting).

## Uygulama (2026-10-30)
- **Tek kaynak:** `config/tone-voice.json` (varsayılan) + `data/tone-voice.json` (ekran/API ile düzenleme, derin birleştirilir). Anahtar: sağlayıcı > model (veya `default`) > ton. `backend/app/tone_voice.py` çözer ve doğrular (aralık dışı sayı, bilinmeyen alan/ton reddedilir).
- **Dört ton:** samimi, resmî, enerjik, sakin (persona.TONES; LLM istemi için de tarif var). Persona'daki ton artık `VoiceSession(tts_tone=...)` ile her cümlenin TTS çağrısına gider; yalnız `tone` parametresini tanıyan sağlayıcıya iletilir (eski sağlayıcı ve test sahteleri bozulmaz).
- **EMA:** yalnız hız (enerjik 1,15; sakin 0,88; resmî 0,95). Tek ses olduğu için başka ton aracı yok.
- **Chatterbox:** `exaggeration` / `cfg_weight` / `temperature` (enerjik 0,9 / 0,3 / 0,9; resmî ve sakin düşük ifade). İsteğe bağlı `audio_prompt_path` ve `seed` seçenek olarak okunur. Yalnız stüdyo (ADR 0001).
- **ElevenLabs:** model ailesine göre. Flash v2.5 ve varsayılan: `stability` + `speed`. Multilingual v2: ek olarak `style`. v3 / v4 / v4 Turbo: **ses etiketi** (`[excited]`, `[calm]`, `[warmly]`, `[serious]`) metnin başına eklenir. Ton başına ayrı ses: `ELEVENLABS_VOICE_ID_ENERJIK` vb. tanımlıysa o ses kullanılır. `seed` seçeneği desteklenir. `multilingual_v2` modeline `language_code` gönderilmez (model kabul etmiyor).
- **Ton demosu:** Persona ekranı altında "Ton demosu": aynı cümle, sabit tohum, dört ton, yan yana ses + uygulanan parametreler + yaklaşık akustik özet (hız, perde, perde oynaklığı, şiddet dalgalanması). ElevenLabs profilinde model seçilebilir (Flash / Multilingual v2 / v4 Turbo / v3).
- **Doğrulama betiği (Mac'te çalıştırılır):** `scripts/verify_elevenlabs_tones.py` her model x ton için klip üretir ve `evidence/elevenlabs-tones-*/report.json` yazar. Buluttan ElevenLabs'e erişilemediği için bu doğrulama BENİM tarafımdan yapılmadı.

## Hangi ElevenLabs modeli ton yapabilir (araştırma, 2026-10-30; belgeye dayalı, Türkçe davranışı DOĞRULANMADI)
- **Flash v2.5:** en hızlı (~75 ms), Türkçe var. Belgede ses etiketi desteği yok. Ton için elde yalnız `stability` (düşük = daha geniş duygu), `speed` ve ses seçimi var; `style` etkisi doğrulanmadı ve gecikme ekler. **Beklenti: ince fark, "şaşırtıcı" olmayabilir.**
- **Multilingual v2:** `style` etkili, gecikme yüksek (canlı hat için uygun değil); stüdyoda/demoda ton farkı Flash'tan belirgin olabilir.
- **v4 Turbo / v4:** ses etiketleri (`[excited]`, `[calm]`…) desteklenir; Turbo gerçek zamanlıya yakın (~100 ms çıkarım). **Ton için en güçlü aday; canlı hatta da kullanılabilir olması hedeflenen yol.** Türkçe etiket kalitesi dinlenerek doğrulanmalı.
- **v3:** etiketler var ama gecikme yüksek, gerçek zamanlı ajan için önerilmiyor; demo için kayıttan çalma olarak kullanılabilir.
- **Sesin kendisi:** farklı tonlar için Voice Library'den ayrı Türkçe sesler (örn. enerjik/sakin) veya Voice Design ile üretilen sesler `voice_settings`'ten daha belirgin fark verir; bu uygulamada ton başına `ELEVENLABS_VOICE_ID_<TON>` ile bağlanır.
- **Karar yolu:** önce `verify_elevenlabs_tones.py`, sonra dinleme. Fark Flash'ta duyulmuyorsa v4 Turbo'ya geçilir (gecikme ayrıca ölçülür) ve gerekirse ton başına ayrı ses tanımlanır.

## Sınırlar (güncel)
- ElevenLabs'e buluttan erişim yok; model karşılaştırması ve sayıların kalibrasyonu kullanıcı Mac'inde yapılmalı. `config/tone-voice.json` sayıları başlangıç tahminidir.
- Ses etiketlerinin Türkçede nasıl okunduğu (sesli okunma riski dahil) doğrulanmadı.
- Chatterbox ton testi bulutta torch olmadığı için atlandı (1 test skip); Mac'te çalıştırılmalı.
- Akustik özet (otokorelasyonlu perde) yaklaşıktır; dinlemenin yerini tutmaz.

## Dinleme sonucu (kullanıcı, 2026-10-30) ve karar
- **Gözlem (kullanıcı, gerçek dinleme):** ton farkı yalnız **v4** modelinde hissediliyor; Flash v2.5'te belirgin değil. Belge araştırmasındaki beklentiyle (ses etiketi yalnız v3/v4 ailesinde) uyumlu. Sayısal akustik rapor (report.json) henüz paylaşılmadı; tespit dinlemeye dayanıyor.
- **Karar (demo):** ton gösterimi için ElevenLabs modeli **v4 (Turbo)**; Flash v2.5 ton demosunda kullanılmaz (hızlı ama ton farkı ince). Canlı hatta v4 Turbo gecikmesi ÖLÇÜLMEDİ; ölçülmeden canlı hat varsayılanı değiştirilmez.
- **Sonraki adım (öneri, onay bekliyor):** ElevenLabs ses seçici (Türkçe ses listesi + dinleme + ton başına ses atama). Ton farkını model dışında sesin kendisi de büyütür (scn-010'u öne çeker). Kütüphane sesinin hesaba eklenmesi gerekip gerekmediği ve ticari lisans kullanımı doğrulanmadı.

## ElevenLabs doğrulama ölçümü (2026-10-30, kullanıcı Mac'inde, `scripts/verify_elevenlabs_tones.py`, seed 1234)
Kanıt: `evidence/elevenlabs-tones-20261030-113531/` (16 WAV + report.json). 4 model x 4 ton, hata yok; v4 Turbo ve v3 ses etiketiyle, Türkçe cümleyle üretildi.

| Model | Etiket | Tonlar arası fark: hız (kel/sn) | perde oynaklığı (yarım ton) | şiddet dalgalanması (dB) | Üretim süresi (tam klip, REST) |
|---|---|---|---|---|---|
| Flash v2.5 | yok | 0,43 | 1,30 | 1,46 | 0,6 sn (ilk çağrı 3,0 soğuk) |
| Multilingual v2 | yok | 0,54 | 1,61 | 0,50 | 0,9-1,0 sn |
| v4 Turbo | var | 0,13 | 0,31 | 0,37 | 1,4-1,5 sn |
| v3 | var | 0,33 | 0,37 | 0,58 | 3,1-4,4 sn |

- **Okuma (dürüst):** hız ve perde gibi kaba ölçüler Flash ve Multilingual v2'de tonlar arasında DAHA büyük fark gösteriyor (bu fark ağırlıkla bizim `speed`/`stability` ayarlarımızdan geliyor). v4 Turbo'da bu ölçüler az değişiyor, ama kullanıcı dinlemesinde fark **en çok v4'te** hissedildi. Çelişki yok: ses etiketi hız/perde yerine söyleyiş, vurgu ve duygu rengini değiştiriyor; kaba ölçüler bunu yakalamıyor. Bu yüzden karar ölçüme değil DİNLEMEYE bırakıldı, ölçü yalnız yardımcı.
- **Gecikme:** süreler tam klibin REST üretim süresidir (ilk ses baytı değil). v4 Turbo ~1,4 sn, Flash ~0,6 sn, v3 3-4 sn. Canlı hat için akış (streaming) ve ilk ses süresi ayrıca ölçülmeli; v3 canlı hat için uygun değil, v4 Turbo sınırda, tek cümlelik demo klibinde sorun değil.
- **Karar:** demo ton gösterimi v4 Turbo; canlı hat modeli akışlı gecikme ölçümü sonrası seçilir.
- **Kalan bilinmeyenler:** Türkçede etiketlerin sesli okunup okunmadığı (kullanıcı dinlemesinde bildirilmedi, açıkça doğrulanmadı), akışlı ilk ses süresi, kalibrasyonun ayar sayıları.

## Ses seçici (2026-10-30, uygulandı; gerçek hesapla DOĞRULANMADI)
- **Neden:** dinleme sonucu ton farkı model ayarından çok modele ve sese bağlı; ayrı ses atamak en güçlü kaldıraç. ElevenLabs arayüzündeki gibi ses listesi kullanıcı isteğiyle eklendi.
- **Ne yapar:** Persona ekranında "Ses seçici": hesaptaki sesler + Türkçe kütüphane sesleri (dinleme klibi, etiketler), her ton için ayrı ses atama/kaldırma, kütüphane sesini "Hesabıma ekle". API: `GET /api/persona/voices`, `PUT /api/persona/tones/voices`, `POST /api/persona/voices/add`. API anahtarı yalnız arka uçta kalır.
- **Öncelik:** `ELEVENLABS_VOICE_ID_<TON>` ortam değişkeni > ekrandan atanan ton sesi (`data/tone-voice.json` > `voices`) > genel `ELEVENLABS_VOICE_ID`. Parametre sıfırlama atanan sesleri silmez.
- **Güvenlik:** ses/sahip kimlikleri URL yoluna girdiği için yalnız harf/rakam kabul edilir (422 aksi halde).
- **Doğrulanmayanlar (saklanmaz):** ElevenLabs liste/kütüphane yanıt alanları ve `voices/add` çağrısı belgeye göre yazıldı, sahte HTTP ile test edildi, gerçek hesapla denenmedi; kütüphane sesinin kullanımdan önce hesaba eklenmesi gerekip gerekmediği; kütüphane seslerinin ticari kullanım lisansı (üretim öncesi hukuk/ürün onayı); ses sahibi sesi kütüphaneden çekebilir.

### Ses seçici yeniden tasarımı (2026-10-30, ElevenLabs ses kütüphanesi deneyimi)
- **Neden:** kullanıcı ElevenLabs'teki ses kütüphanesi deneyimini beğendi; ilk sürüm düz kart listesiydi (arama için buton, dinleme için tarayıcı oynatıcısı). Demoda ses seçmek hızlı ve gösterişli olmalı: ara, süz, **aynı ekranda dinle**, ata.
- **Ne değişti:** (1) **Arama** yazdıkça çalışır (300 ms bekleme; eski yanıt yeni aramanın üstüne yazmaz). (2) **Süzgeçler:** kaynak (Tümü/Hesabım/Kütüphane), cinsiyet, yaş, kullanım alanı; **sıralama** (trend, en çok kullanılan, en yeni, yıllık kullanım); "Daha fazla yükle" ile sayfalama. (3) **Satır içi dinleme:** her satırda avatar-oynat düğmesi, tek paylaşılan ses öğesi (aynı anda tek klip), ilerleme çubuğu. (4) **Etiketler** Türkçeleştirilir, atanan ton rozeti satırda görünür, "Ton ata" açılır menüsü. (5) **Özel önizleme çubuğu** (ekranın altında yapışkan): kendi metniniz + model (varsayılan v4 Turbo) + ton ile seçili sesi üretir; ilk ses süresi, karakter ve maliyet gösterilir. Çağrı mevcut `POST /api/persona/tts-lab` ucunu kullanır (yeni uç nokta yok).
- **Arka uç:** `GET /api/persona/voices` artık `gender`, `age`, `use_case`, `sort` (`trending|popular|newest|usage`), `page` alır; satırlar yapısal alanlar (`gender, age, accent, descriptive, use_case, category, cloned_by_count`) ve `has_more` döner; eski `tags` alanı korunur. Geçersiz `sort` 400 verir. Süzgeçler kütüphane aramasında ElevenLabs'e iletilir, hesap seslerinde sunucuda uygulanır.
- **Karar/sınır (saklanmaz):** (a) Sayfalama yalnız **kütüphane** sesleri içindir; hesap sesleri (en çok 100) yalnız ilk sayfada gelir. (b) **Kütüphane sesi özel metinle üretilemez, önce "Hesabıma ekle" gerekir**: ekran bunu önizleme düğmesini kapatıp söyler; hazır klip yine dinlenir. Bu, ElevenLabs'in kütüphane seslerini API ile ancak hesaba eklenince kullanıma açmasına dayanır ve gerçek hesapla **doğrulanmadı**. (c) Süzgeç parametre adları (`use_cases`, `sort=cloned_by_count|created_date|usage_character_count_1y`) ve yanıt alanları belgeye göre yazıldı, sahte HTTP ile test edildi; gerçek yanıt farklıysa ilk denemede ayarlanır. (d) Arama kelimesi ElevenLabs'in aramasına gider, Türkçe sorgu kalitesi bilinmiyor; İngilizce etiketler ("warm", "cheerful") de dene.
- **Doğrulama:** 434 arka uç + 61 ön yüz test; `tsc` temiz; bulut Chromium'da açık/koyu/telefon genişliğinde ekran görüntüsü (sahte API yanıtlarıyla). Gerçek ElevenLabs hesabıyla ekran **denenmedi**.

### Persona ekranı sadeleştirme: Ses stüdyosu penceresi (2026-10-30)
- **Neden:** ses kütüphanesi + TTS laboratuvarı + ton demosu Persona formunun altına alt alta eklenince sayfa çok uzadı ("karmaşık, kalabalık, sonsuz scroll"); kullanıcı ElevenLabs ayarlarının bir popup'a alınmasını ve ElevenLabs'teki deneyime benzemesini istedi.
- **Karar:** Persona ekranında yalnız persona formu, önizleme, kısa bir **"Ses stüdyosu"** kartı ve cümle uzunluğu raporu kalır. Kart, sekmeli bir **açılır pencere** (`VoiceStudio`) açar: **Ses kütüphanesi** (arama, süzgeç, satır içi dinleme, ton ata, özel önizleme) · **Laboratuvar** (model/ses/ton, gecikme, maliyet, kıyas matrisi) · **Ton demosu**. Mevcut üç panel değişmeden pencerenin sekmeleri olarak kullanıldı; yeni API yok. Pencere stilleri ayrı `frontend/src/studio.css` dosyasında (genel `styles.css`'e dokunmadan).
- **Davranış:** pencere ilk açılışta yüklenir (kapalıyken ElevenLabs çağrısı yapılmaz); sekmeler tembel yüklenir; kapatınca çalan ses durur ama arama metni, süzgeç, seçili ses ve lab sonuçları korunur (pencere gizlenir, silinmez). Escape, × ve arka plana tıklama kapatır; açıkken arka sayfa kaymaz; odak açan düğmeye döner; sekmeler ok tuşlarıyla gezilir; telefonda tam ekran.
- **Karar/sınır (saklanmaz):** (a) Pencere oturum boyunca bellekte kalır, sayfa yenilenince sıfırlanır (atanan sesler sunucuda kalıcıdır). (b) Odak tuzağı (Tab'ın pencere dışına çıkmasını engelleme) yapılmadı; `aria-modal` ve Escape var. (c) Ekran gerçek hesapla denenmedi (sahte API ile açık/koyu/telefon ekran görüntüsü alındı).

### L2-EL profili ve Persona'dan atanan sesin profillere doğrudan etkisi (2026-10-30)
- **İstek:** "L2 profilinin TTS'ini EMA yerine ElevenLabs ile denemek; L2 + ElevenLabs profili ekle; Persona'dan ElevenLabs için ses ve ton seçtiğimde profillere direk etki etsin."
- **Yeni profil `L2-EL` ("Dengeli + ElevenLabs", `config/profiles.yaml`):** STT ve LLM L2 ile birebir aynı (`mlx-community/whisper-large-v3-turbo`, `qwen3:30b-a3b-instruct-2507-q4_K_M`), TTS `elevenlabs` / `eleven_v4_turbo` (demo modeli kararı, bu belgenin dinleme bölümü). Sağlayıcı önbelleği `provider+model+ayar` anahtarlı olduğu için L2 ile L2-EL arasında geçişte STT/LLM bellekte kalır, yalnız TTS değişir (EMA'nın belleği boşalır). L2 değişmedi; EMA ile karşılaştırma için ikisi yan yana durur.
- **Etki zinciri (yeniden başlatma gerekmez):** Persona'daki ton → `tts_tone` → `ElevenLabsTTS.synthesize` her cümlede `tone_voice.resolve_voice(ton)` ve ton parametrelerini okur; atanan sesler `data/tone-voice.json` içinde olduğundan, Persona'da ses/ton değişince **bir sonraki cümle** yeni ayarı kullanır. Aynı zincir A1 profilini de etkiler.
- **Ses önceliği (güncel):** açık `voice` > `ELEVENLABS_VOICE_ID_<TON>` ortam değişkeni > o tona ekrandan atanan ses > ekrandan atanan **Genel ses** > `ELEVENLABS_VOICE_ID`. **Karar:** ekrandaki Genel ses `.env`'deki genel sesten önce gelir, çünkü kullanıcı Persona'da ses seçince eski `.env` değerine takılmadan etki istedi; ton başına ortam değişkeni önceki davranışıyla en üstte kaldı.
- **Genel ses yuvası (yeni):** `voices` haritasına `"default"` anahtarı eklendi (Ses stüdyosu'nda "Genel ses"). Neden: kendi sesi atanmamış bir tonda ElevenLabs profili çökmesin; tek bir ses seçip dört tonu ayar farkıyla denemek de mümkün olsun (Flash+ses senaryosu).
- **Hazırlık denetimi değişti:** `ELEVENLABS_VOICE_ID` artık zorunlu ortam değişkeni değil; yalnız `ELEVENLABS_API_KEY` zorunlu. Her ton için bir ses çözülemiyorsa profil durumu "hazır değil" olur ve eksik tonları adıyla söyler (`ElevenLabsTTS.readiness_issues`). Ses hiç yoksa sentez `ProviderError` ile Türkçe, yönlendiren mesaj verir (önceden ham `KeyError`). `POST /tts-lab` bu durumu 400 `no_voice` olarak döner.
- **Testler:** `test_profiles.py` içindeki iki beklenti BİLİNÇLİ güncellendi (profil listesine `L2-EL`, A1'in eksik ortam değişkenleri kümesinden `ELEVENLABS_VOICE_ID` çıktı); zayıflatma değil, tasarım değişikliği: aynı denetim `readiness_issues` testleriyle korunuyor. Yeni testler: Genel ses önceliği ve doğrulama, mevcut TTS örneğinde atamanın anında etkisi, ses yokken hata/hazırlık, L2-EL listeleme. Ayrıca profil yükleyicisinden gerçek `L2-EL` TTS'i kurup sahte HTTP ile enerjik→kendi sesi+`[excited]`, sakin→Genel ses+`[calm]` doğrulandı.
- **Doğrulanmayanlar (saklanmaz):** (a) L2-EL ile **gerçek ElevenLabs'te uçtan uca arama yapılmadı** (bulutta ağ/anahtar yok); (b) ElevenLabs TTS ağdan gelir: tur gecikmesi EMA'dan farklıdır, **ölçülmedi** (Playground'daki tur süresi ve Lab'daki akışlı ilk ses ölçer); (c) L2 + ElevenLabs'te Ollama'nın büyük LLM'i ile EMA aynı anda bellekte olmadığından bellek yükü L2'den hafif olmalı, ancak ölçülmedi; (d) ses etiketi (`[excited]`) Türkçe okunuşu hâlâ doğrulanmadı; (e) ses/ton ayarı Persona ekranında sunucuya yazılır, Playground'da **açık** aramayı etkilemesi bir sonraki cümleden itibaren beklenir (açık oturumda denenmedi).

## TTS laboratuvarı ve model kıyas matrisi (2026-10-30)
- **Kullanıcı hipotezi (2026-10-30):** Flash v2.5 + ses kimliği (voice_id) ile gecikmeden ödün vermeden "yeterli" tonlama elde edilebilir; ses önemli değil ton önemliyse hızlı Flash/Turbo v2.5 + ses kombinasyonu çözer. Aynı ses için ton denemesi v4'te yapılır. **Bu hipotez ölçülmeden kabul edilmedi;** lab bunu ölçmek için eklendi.
- **Ne eklendi:** Persona ekranında "TTS laboratuvarı": kendi metniniz + model + ses + ton + tekrar sayısı; **akışlı** üretimle ilk ses süresi (canlı hat için asıl ölçü) ve toplam süre ölçülür (medyan), gönderilen karakter ve tahmini maliyet gösterilir. "Tüm modelleri sırayla dene" kıyas matrisini aynı metin/ses/tonla doldurur. Matris: resmî fiyat, resmî gecikme notu, ses etiketi desteği, ton kaldıracı, ölçülen ilk ses/toplam, bu metnin ve aylık çağrı sayısına göre maliyet. API: `GET /api/persona/model-matrix`, `POST /api/persona/tts-lab`. Modeller: Flash v2.5, **Turbo v2.5 (yeni)**, Multilingual v2, v3, v4, v4 Turbo.
- **Fiyat (resmî sayfa, 1.000 karakter, USD, kontrol 2026-10-30):** Flash/Turbo 0,04; Multilingual v2 0,08; v3 0,08; v4 0,08; v4 Turbo 0,04. Resmî gecikme notları: Flash ~75 ms, v4 Turbo ~100 ms çıkarım (~150 ms ilk konuşma, duyuruya göre). Kaynak: elevenlabs.io/pricing/api. **Çelişki (saklanmaz):** bir haber sitesi v4 ile v4 Turbo arasında fiyat farkı olmadığını yazıyor; resmî sayfa 0,08 / 0,04 gösteriyor, resmî sayfa esas alındı. Turbo v2.5 sayfada ayrı satır değil ("Flash / Turbo"); fiyatı oradan alındı. Liste fiyatıdır, plan/kredi/kurumsal anlaşma farklı olabilir; faturayı hesapta doğrulayın.
- **Maliyet kuralı:** v3/v4 ses etiketi metnin başına eklenir ve gönderilen karakter olarak faturalanır; lab bunu `chars`'a dahil eder (varsayım: faturalama gönderilen karakter üzerinden, doğrulanmadı).
- **Doğrulanmayanlar:** ölçümler kullanıcının Mac ağından alınmalı (bulut ElevenLabs'e erişemez); Flash + ayrı sesle ton farkının yeterli olup olmadığı DİNLEMEYLE belirlenir; `eleven_turbo_v2_5` ve `eleven_v4` model kimlikleri hesapta çalışmayabilir (hata lab'da görünür).
