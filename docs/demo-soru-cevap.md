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

## S5. "Ajan anketi gerçekten kendisi mi yürütüyor? Cevabı nasıl anlıyor?"
- Playground'da senaryoyu seçip konuşursunuz; sağda **aktif düğüm** (hangi soruda olduğu) ve **çıkarılan cevaplar** (Q2 = 8, "sekiz veririm") canlı görünür; altta her turun STT / LLM / TTS gecikmesi.
- Akışı bir motor yönetir (hangi cevapta nereye gidileceği JSON'da sabit); LLM sadece müşterinin cümlesinden cevabı çıkarır. Bu yüzden aynı cevap her zaman aynı dala gider ve test edilebilir. LLM cevabı tip kontrolünden geçmezse "anlaşılamadı" sayılır.
- Anlaşılmazsa en fazla iki kez farklı biçimde tekrar sorar; hâlâ olmazsa puan sorularında "cevap yok" diye geçer, evet/hayır sorusunda nazikçe kapatır. "Tekrar eder misiniz" hakkı harcamaz. "Beni aramayın" ve ret doğrudan ilgili kapanışa gider.
- **Telefon filtresi:** sesi 300–3400 Hz'e kısıtlar (müşterinin telefondan duyacağı/göndereceği kalite). Bu bir yaklaşıktır: gerçek operatör codec'i ve paket kaybı yoktur; "telefonda test ettik" demeyin, "telefon bandında test ettik" deyin.
- Bilmeniz gereken sınırlar: gerçek mikrofon + gerçek modellerle uçtan uca anket tamamlama henüz bizim tarafımızdan ölçülmedi; sessiz hat kapanışı ve OpenAI/Gemini realtime profiller Playground'da yok; Welcome Call senaryosu alınmadı.

## S6. "Müşteri araya girerse ne olur? Duraksayıp düşünürse ajan lafını keser mi?"
- **Araya girme:** Ajan konuşurken müşteri konuşmaya başlarsa ajan yaklaşık **0,3 sn içinde** susar ve dinler (ölçüm: gerçek tarayıcıda 340 ms, sınır 500 ms). Ekranda "söz kesme: n · son: X ms" görünür. Öksürük/tık gibi çok kısa sesler söz kesme sayılmaz.
- **Duraksama:** 0,6 sn'ye kadar duraksama turu bitirmez; "neden bu puanı verdiniz" gibi açık uçlu sorularda bu süre 1,2 sn. Müşteri "evet ama…" gibi yarım cümleyle susarsa ajan hemen atlamaz, 1,5 sn devamını bekler; devam gelirse iki konuşma birleştirilip tek cevap sayılır.
- Bilin (bahane değil sınır): bu bir **öğrenilmiş Smart Turn modeli değil, kurallı bir yaklaşımdır** (enerji tabanlı ses tespiti + bağlaç/dolgu listesi). Ölçümü sentetik sesle yaptık; gerçek insan sesi, gürültülü ortam ve **hoparlör yankısı** (ajan kendi sesini duyup kendini kesebilir; kulaklık kullanın) ayrıca denenmeli. Yarım cümlede cevap gecikmesi 1,2 sn hedefinin dışındadır (bekleme payı). Silero/Smart Turn gibi bir model sonraki adımdır.

## S7. "İkinci senaryo (Welcome Call) neden anket gibi puan sormuyor? Müşteri soru sorarsa ajan cevaplıyor mu?"
- Welcome Call bir **bilgilendirme çağrısı**: yeni açılan Premium Plus mağazayı arar, paket/taahhüt/ilan kuralları/web sitesi/afiş-branda/güvenlik konularını anlatır, her bölümün sonunda "sormak istediğiniz bir şey var mı?" diye teyit alır. Referans firmanın panelindeki senaryonun birebir kopyası (24 adım, 9 sonuç).
- **Bilin (bahane değil sınır):** Müşteri soru sorarsa ajan bunu **kaydeder ve "Sorunuzu not aldım" der, cevaplamaz**: serbest soruya cevap verecek bir bilgi bankası PoC'de yok (Faz 2). Bunu demoda önden söyleyin; "ajan her şeyi cevaplar" izlenimi vermeyin.
- Senaryo profile bağlıdır (taahhütlü/taahhütsüz, 2FA açık/kapalı, afiş-branda hakkı). PoC örnek profili sabit: taahhütlü, 2FA kapalı, afiş-branda var; taahhütsüz dalın adımları bu profilde devre dışıdır ve Playground'da profil seçici henüz yok.
- Soru mu onay mı ayrımını LLM yapıyor; betikli testlerde doğrulandı, gerçek modellerle ölçülmedi.

## S8. "OpenAI / Gemini realtime (konuşan-model) profilleri çalışıyor mu? Neden cascade'e göre daha yavaş görünebilir?"
- **Dürüst durum:** Hibrit hat kuruldu ve **sahte sağlayıcıyla** uçtan uca test edildi (gerçek tarayıcı, WebRTC, senaryo, söz kesme). **Gerçek OpenAI/Gemini ile henüz denenmedi**: PoC ortamından bu servislere erişim yok; canlı doğrulama Mac'te `scripts/realtime_smoke.py` ile yapılacak. Bu sonuç gelmeden "A2/A3 çalışıyor" denmez; Türkçe ses kalitesi (özellikle Gemini) ayrıca dinlenerek değerlendirilir.
- **Yöntem:** Model sesi yönetir ama **akışı biz yönetiriz**: soruyu verdiğimiz metinle seslendirir, müşterinin cevabını bir fonksiyon çağrısıyla bildirir, bizim akış motoru tipini doğrular ve sonraki soruyu seçer. Böylece cascade ile aynı senaryo ve aynı ölçüt kullanılır.
- **Gecikme:** Bu yöntem OpenAI'da tur başına iki model gidiş-dönüşü demektir (önce cevabı bildir, sonra konuş); serbest bırakılmış "saf" realtime'dan yavaştır. Bu **bilinçli bir takas**: doğruluk ve kıyaslanabilirlik için deterministik akış. Playground'da bu profillerde STT/LLM/TTS ayrımı yoktur; yalnızca konuşma bitişinden ilk sese uçtan uca süre (ve cevabı bildirme / seslendirme kırılımı) gösterilir.
- **Sınır:** Müşteri serbest soru sorarsa ajan cevaplamaz, not alır (bilgi bankası Faz 2).
