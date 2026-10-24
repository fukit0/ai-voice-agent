# Demo Soru-Cevap

Demoda gelebilecek sorular ve dürüst, kısa cevaplar. Her cevapta "bugün çalışan" ile "mimari destekliyor ama yapılmadı" ayrılır.

## S1. "X modeli beğendim ama ses tonunu ve tavrını beğenmedim. Başka bir insan sesi veya persona seçebilir miyim?"

**Kısa cevap:** Evet. "Ses" ve "tavır" iki ayrı ayardır, ikisi bağımsız değişir ve değiştirmek modeli (STT, LLM, TTS yığınını) değiştirmeyi gerektirmez. Bugün arayüzden seçim yok: ses `.env` ile, tavır prompt ile değişir. Arayüzden seçim Faz 2'de (scn-010).

| Ne değişecek | Nereden | Bugün | Faz |
|---|---|---|---|
| **Tavır:** hitap, sıcaklık, cümle uzunluğu, onay sözleri | Persona promptu (LLM tarafı) | Henüz yazılmadı (core-005) | Faz 1 |
| **Ses tınısı:** kim konuşuyor | TTS ses seçimi | ElevenLabs: `ELEVENLABS_VOICE_ID` ile tek ses. EMA ve Chatterbox: varsayılan tek ses | Arayüzden seçim: Faz 2 (scn-010) |
| **Hız ve vurgu** | TTS parametreleri + metin yazımı (kısa cümle, noktalama) | Bağlı değil | Faz 2 (scn-010) |

**Sağlayıcıya göre ses seçeneği:**
- **ElevenLabs (API):** Hazır ses kütüphanesi vardır; ses kimliğini değiştirmek yeterlidir. Kendi sesimizi klonlamak sağlayıcı planına ve izne bağlıdır. PoC'de yalnızca tek ses denendi.
- **Chatterbox (lokal):** Referans ses klibinden klonlama ve duygu şiddeti ayarı sağlayıcının belgelenmiş özelliğidir; bizim entegrasyonda bağlı değil. Bu Mac'te canlı hatta zaten kullanılamıyor (ilk ses 10,8 sn, RTF 1,85), yalnızca stüdyoda.
- **EMA Lightning (lokal):** Entegrasyonda varsayılan tek ses kullanılıyor. Başka ses seçeneği olup olmadığı doğrulanmadı.

**Yeni ses ya da persona nasıl karar verilir:** TTS stüdyosunda (lab-001) aynı cümleler yeni sesle üretilir ve mevcut seslerle kör dinlemeye konur; dinleyiciler doğallık, insan gibilik ve telaffuz hatasını puanlar. Tavır değişikliği 5 test aramasının transkriptinde gözden geçirilir (core-005).

**Bilinen sınırlamalar ve kurallar (demoda açıkça söylenecek):**
- Gerçek bir kişinin sesi yalnızca o kişinin yazılı izniyle klonlanır (KVKK, rıza). Ünlü ya da üçüncü kişi sesi kullanılmaz.
- Persona insanı taklit etmek demek değil: "bot musun?" sorusuna dürüst cevap verilir (core-006). Dijital asistan beyanı hukuk kararına bağlı, açık soru.
- Ses değiştirince gecikme ve maliyet değişebilir (ilk ses süresi, karakter başı ücret); kör dinlemeyle birlikte ölçülür.
- Canlıda gösterilemez: bugün ses değişikliği `.env` düzenleyip backend'i yeniden başlatmayı gerektirir. "İlk yükleme bahanesi" değil, henüz yapılmamış bir özellik olarak anlat.

## S2. "LLM müşterinin cevabını doğru anlıyor mu? Hangi model yeterince güvenilir?"

**Kısa cevap:** 30 örnek müşteri cevabıyla ölçüyoruz; sonuç iki sayı: **doğru normalize** (ör. "iki buçuk milyon" → 2.500.000) ve **doğru dal** (flow motorunun seçeceği yol). Kapı: tam doğru oran ≥ %90 (Faz 1). Ekran: "LLM testi".

- **Nasıl ölçüyoruz:** LLM yalnızca `{"intent","value"}` JSON'u üretir; dalı LLM değil deterministik flow motoru seçer. Böylece LLM yanlış anlasa bile akış kırılmaz, yeniden sorulur.
- **Veri seti:** 4 soru tipi (puan, evet/hayır, seçenek, fiyat) + özel durumlar (tekrar iste, ret, belirsiz, konu dışı, sonra ara). Cümleler konuşma tanıma çıktısı gibi: küçük harf, dolgu sözcük, tuzaklı ("on üzerinden yedi", "daha önce verdim ama son üç ayda vermedim").
- **Kesin doğrulama:** "9" yazısı sayı sayılmaz, 1 ile true karışmaz. Production flow motoru da tip bekler; gevşek ölçüm göz boyar.
- **Sınırlama (açıkça söyle):** Native tool-calling ölçülmedi; tüm modellere aynı JSON sözleşmesi verildi (adil kıyas için). 30 örnek eğilim gösterir, istatistiksel garanti değildir. Gürültülü gerçek STT çıktısıyla ve gerçek müşteri cümleleriyle genişletilecek (Faz 1).
- **Bugün durum:** Ekran ve ölçüm hattı sahte modellerle test edildi; gerçek model sonuçları Mac'te koşturulunca eklenecek. Bunu "henüz koşulmamış bir ölçüm" olarak anlat, bahane gibi değil.

## S3. "Tarayıcıdan konuşurken gecikme ve söz kesme nasıl çalışıyor? Neden Pipecat yok?"
- Hat: tarayıcı mikrofonu → WebRTC (Opus) → 16 kHz → konuşma bitişi tespiti → STT → LLM → cümle cümle TTS → tarayıcı. Ajan ilk cümleyi LLM cevabı bitmeden okumaya başlar; her turun STT/LLM/TTS süresi ekranda görünür.
- Söz kesme: ajan konuşurken siz konuşmaya başlarsanız ajan anında susar (çıkış kuyruğu boşaltılır).
- Karar değişti: plan Pipecat diyordu; bunun yerine doğrudan aiortc (Pipecat'in de altındaki kütüphane). Sebep: mevcut sağlayıcı/ölçüm düzeneğimizi yeniden yazmamak, modelsiz CI. Üretim (telefon/SIP) için Pipecat/LiveKit yeniden değerlendirilir (ADR 0002).
- Demoda bilin (bahane değil, sınır): konuşma bitişi enerji tabanlı, gürültülü odada yanlış tetikleyebilir; hoparlörde ajan kendi sesini duyup kendini kesebilir, **kulaklık kullanın**; bitiş için 0,6 sn beklenir, bu gecikmenin parçasıdır. Gerçek mikrofon + gerçek modellerle p50 < 1,2 sn henüz ölçülmedi; "ölçtük" demeyin.

## S4. "Senaryoyu kim, nasıl değiştirir? Akışı kodsuz kurabiliyor muyuz?"
- Senaryolar ekranında müşterinin örnek anketi (33 adım) birebir yüklü: adımlar gruplu, her adımın okunacak metni düzenlenir, yer tutucular ({HITAP}, {Q2}…) eklenir, "Asistan böyle okuyacak" satırı sayı ve tarihleri Türkçe okunuşa çevirerek gösterir; "Orijinal metne dön" ile geri alınır.
- Sınır (bilerek): **akış (hangi cevapta nereye gidileceği) şimdilik düzenlenemez**, yalnızca görüntülenir; referans demo da böyle. Akış editörü Faz 2'dedir. Demoda "kodsuz akış kurulur" demeyin, "kodsuz metin düzenlenir, akış sabit" deyin.
- Senaryo şu an referans firmanın örnek senaryosunun kopyasıdır; Sahibinden'in onaylı metinleri değildir. Welcome Call senaryosu henüz alınmadı.
