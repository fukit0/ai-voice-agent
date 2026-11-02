# Sunum taslağı: Geliştirme alanları ve potansiyel

Hazırlanma: 2026-11-02 · Durum: taslak, slayta henüz işlenmedi · Kod değişikliği yok.
Kaynaklar: `docs/demo-soru-cevap.md` (S6, S7, S23–S27, S29, S38, S39, S43, S48, S50–S52), `claude-progress.md` (Session 038–045), `feature_list.json`, ADR 0003 / 0009 / 0011, `docs/faz-elevenlabs-agent.md`, `evidence/`.
Kural: Rakamların hepsi ölçümden ya da liste fiyatından geliyor. "Ölçülmedi" yazan yere tahmin konmadı. Çaba sütunu tahmindir (tek kişi varsayımı), ölçüm değildir.

---

## 1. Slayt metni (tek sayfa)

**Başlık:** Geliştirme alanları ve potansiyel

**Alt başlık:** Çalışan bir hattımız var. Açıkları da biliyoruz, her birinin ne kadar sürdüğünü de.

| Alan | Şimdi | Hedef | Çaba |
|---|---|---|---|
| Latency (ilk ses p50) | 1,56 sn (17 canlı arama). LLM'e gitmeyen fast path turlarında 0,78 sn | ~1,0 sn | 1–2 hafta |
| Doğal ve konu dışı cevaplar | Cevaba uygun tepki veriyor. Plan dışı soruya hep aynı "not aldım" cümlesi | Kısa cevap verip soruya dönmesi | 1–2 hafta |
| Barge-in ve gürültü | Tarayıcıda 340 ms. Öksürük ve boğaz temizlemeyi ayırt etmesi zayıf. Telefonda ölçülmedi | Gürültüye dayanıklı barge-in, telefonda ölçülmüş | 1–2 hafta |
| Telefon entegrasyonu | Gerçek hatta arama yok, telefon sesi yalnızca simülasyon | Uçtan uca giden arama | 2–4 hafta |
| Ses, ton, dil | 4 ton, ses kütüphanesi. Yalnızca Türkçe. Kör dinleme n=2–3 | Kör dinleme testi. Talep olursa ikinci dil | 2–3 gün, dil başına ölçülmedi |
| Ölçek ve maliyet | $0,035/dk (liste fiyatı). Eşzamanlı yük ölçülmedi | 1/5/10 eşzamanlı load test, Enterprise teklifi | ~1 hafta + teklif süresi |

**Alt satır (küçük punto):** 25.000 dk/ay ≈ $880/ay API maliyeti (liste fiyatı; telefon, sunucu ve ekip maliyeti dahil değil). Maliyetin %94'ü ses üretimi. Çaba tahmindir. "Ölçülmedi" yazan alana sayı konmadı.

---

## 2. Slayt notu (konuşma metni, ~150 kelime)

Bu slayt neyin hazır olduğunu, neyin olmadığını gösteriyor. Bugün ölçtüğümüz rakamlar şunlar: canlı aramada ilk ses p50 1,56 saniye. Dakika maliyeti liste fiyatıyla 0,035 dolar, yani aylık 25.000 dakika yaklaşık 880 dolar API maliyeti ediyor. En büyük açığımız telefon. Tüm denemeleri tarayıcıda yaptık, gerçek hatta arama henüz yok. Bunu 2–4 haftalık bir iş olarak görüyoruz ve telefon rakamlarını o ölçümden sonra vereceğiz. Gecikmede hedef yaklaşık 1 saniye. Fast path turlarında bugün 0,78 saniye görüyoruz; geri kalan yük LLM'de ve tur sonundaki beklemede. Doğallık tarafında ajan artık cevaba göre tepki veriyor; plan dışı sorulara kısa cevap vermesi bir sonraki adım. Barge-in tarayıcıda çalışıyor, ama öksürüğü ayırt etmesi ve telefonda ölçümü eksik. Çaba sütunu tahmindir. "Ölçülmedi" yazan yerde sayı vermiyoruz. Maliyetin %94'ü ses üretiminden geliyor; bu yüzden Enterprise teklifi maliyeti düşürebilecek en büyük kaldıraç. Her satırın kaynağı ve riski ek sayfada; ayrıntılı soru gelirse cevabı oradan veriyoruz.

---

## 3. Ek: alan bazında ayrıntı (yedek slayt ve soru-cevap için)

### 3.1 Latency: ilk ses p50 1,56 sn → ~1,0 sn
- **Şimdi:** A1S'te ilk ses p50 1,56 sn. Bu sayı 17 canlı aramadan, 172 turdan geliyor (S52). LLM çağrılmayan turlarda 0,78 sn. Deepgram'ın toplu yedek yoluna düşen turlarda 2,79 sn (S39; bu iki sayı 3–4 aramaya dayanıyor, örnek az). Bileşenlere göre: tur sonu bekleme ~0,5 sn, streaming STT tur bittikten sonra ~0,19 sn, Haiku p50 0,90–0,97 sn (180 çağrı, `evidence/llm-stall-A1-20261101-*.json`), TTS ilk ses ~0,19 sn (`evidence/latency-probe-A1S-*.json`, tek klip ile 5 tekrar).
- **Hedef:** ~1,0 sn. Plandaki ilk hedef 1,2 sn idi ve o da henüz tutmuyor (S48).
- **Nasıl:** (1) Fast path kapsamını genişletmek. Bugün etiketli setin %12'sini çözüyor ve 193 örnekte 0 yanlış veriyor. Gerçek trafikte kapsamı ölçülmedi. (2) Kısa cevaplarda tur sonu beklemesini bir turn-detection modeliyle kısaltmak. (3) Cevabı ayrıştırmak için daha hızlı bir model denemek. Yerel L2 metin testinde p95 ≈ 0,5 sn veriyor, ama sunucuda çalıştığı doğrulanmadı. (4) Sabit cümlelerin sesini önceden üretmek; bu en fazla ~0,19 sn kazandırır.
- **Çaba:** 1–2 hafta (tahmin). ~1,0 sn'nin tutacağı garanti değil; ancak ölçümle gösterilebilir.
- **Etki:** "Robot gibi bekledi" hissini en çok bu kalem belirliyor.
- **Risk:** Bekleme kısalırsa ajan müşterinin sözünü kesebilir. Fast path genişledikçe yanlış kayıt riski artar; her kural etiketli sette yeniden ölçülmeli.

### 3.2 Konu dışı yönetimi
- **Şimdi:** Müşteri plan dışı bir şey söylerse ajan kısa bir not düşüp soruya geri dönüyor; soruyu cevaplamıyor (ADR 0003, S7). Bir canlı aramada "Ne demek, rica ederim" cümlesine yanlış olarak "Sorunuzu not aldım" dedi (ea40c9d0712a). Welcome Call'da müşteri soru sorabiliyor ama cevap verecek bir bilgi bankası yok.
- **Hedef:** ADR 0009'un 2. adımı. Runtime'da LLM kısa bir cevap üretir, cümle bekleyen soruyu içerir, uzunluk sınırı ve yasak kalıp denetimi uygulanır, timeout olursa sabit metne düşer. Welcome Call için yalnızca onaylı SSS'den cevap verilir.
- **Çaba:** Runtime üretim için ~1 hafta, ölçüm dahil. Bilgi bankası için ek 1–2 hafta. İkisi de tahmin.
- **Etki:** Ajanın robot gibi göründüğü en belirgin an ortadan kalkar.
- **Risk:** LLM yanlış bilgi verebilir; önlem olarak yalnızca onaylı içerikten cevap verilir. Bu turlarda gecikme artar; ne kadar arttığı ölçülmedi.

### 3.3 Konuşmaya bağlı, robotik olmayan cevaplar
- **Şimdi:** hum-001 passing. Ajan sabit "Anladım" yerine cevaba uygun tepki veriyor: yüksek puana, düşük puana, evete, hayıra ayrı. Aynı aramada tepkiyi tekrarlamıyor (4 canlı arama, transkript incelemesi). Runtime'da LLM çağrısı yok, bu yüzden gecikme maliyeti de yok. "Daha insansı" iddiası kör dinlemeyle ölçülmedi (ADR 0009).
- **Hedef:** Tepki havuzunu insan gözden geçirsin. Kör dinleme testi yapılsın (ajan kayıtları karışık sırayla puanlansın). Anlaşılmayan cevapta ajan soruyu doğal biçimde yeniden sorsun.
- **Çaba:** 2–4 gün, dinleyicilerin ayıracağı süre hariç (tahmin).
- **Etki:** Konuşmada "aynı cümleyi tekrarlayan makine" izlenimi azalır.
- **Risk:** Düşük. Yer yer uygunsuz tepki çıkıyor (ör. "Sesini kesmeni istiyorum" sonrası teşekkür).

### 3.4 Barge-in: gerçek ses ve telefon
- **Şimdi:** Tarayıcıda ajan 340 ms içinde susuyor; sınır 500 ms (S6). Gürültü ayrımı 33 gerçek kayıtla test edildi (tek konuşmacı, tek mikrofon). Nefes, kapı ve klavye sesleri ajanı hiç kesmedi (0/5). Öksürük 1/5, "hmm" 1/3, boğaz temizleme 4/5 kesti; gerçek konuşma ise yalnızca 3/5'te kesti. Test `passed:false`, durum blocked (ADR 0011, `evidence/core-016-gercek-20261030-210947.json`). Telefonda ve hoparlör yankısıyla ölçülmedi.
- **Hedef:** Silero VAD ya da kısa bir STT doğrulaması eklemek (ADR 0011'in a/b seçenekleri). Çok konuşmacılı etiketli bir setle yeniden ölçmek. Telefonda ölçmek.
- **Çaba:** 1–2 hafta (tahmin). Telefon ölçümü 3.6'daki işe bağlı.
- **Etki:** Ajanın gereksiz yere susması ve gerçekten araya giren müşteriyi kaçırması azalır.
- **Risk:** Doğrulama adımı barge-in kararını geciktirebilir (500 ms bütçe). Eşikler 33 kayda göre ayarlandığı için aşırı uyum riski var.

### 3.5 Ses ve ton çeşitliliği
- **Şimdi:** Dört ton var (samimi, resmî, enerjik, sakin). Ses stüdyosunda ElevenLabs kütüphanesinden ses seçilip tona atanabiliyor. v4 Turbo kullanıcı dinlemesinde "iyi" bulundu (S48). Flash'ta ton farkı belirgin değil (S29). Kör dinleme puanı n=2–3, yani zayıf veri (S44).
- **Hedef:** Kampanyaya göre ses seçimi. Yeterli dinleyiciyle kör dinleme testi. Kütüphane seslerinin ticari lisansını kontrol etmek.
- **Çaba:** 2–3 gün (tahmin).
- **Etki:** Marka sesi ve kampanya tonu ayarlanabilir hale gelir.
- **Risk:** v4 Turbo'nun gecikme bedeli tam ölçülmedi. Gerçek bir kişinin sesi ancak yazılı izinle klonlanabilir.

### 3.6 Telefon entegrasyonu
- **Şimdi:** Tüm aramalar tarayıcıdan (WebRTC) yapıldı. Telefon filtresi yalnızca simülasyon: 300–3400 Hz bant ve 8 kHz; codec ve paket kaybı yok (core-009). Gerçek hatta arama yapılmadı (sim-005 not_started). Telefon sesiyle STT doğruluğu ölçülmedi (core-014 blocked). Operatör ücreti zaten ödendiği için maliyet hesabına girmedi (S52).
- **Hedef:** SIP trunk ya da Twilio üzerinden giden arama. Telefonda latency, STT doğruluğu ve barge-in ölçümü. Ardından kampanya, arama saati ve yeniden deneme kuralları (plat-003).
- **Çaba:** İlk gerçek arama 1–2 hafta. Kampanya özellikleriyle birlikte 2–4 hafta daha (tahmin; telefon altyapısına erişime bağlı).
- **Etki:** En büyük açık bu. Telefonda yeniden ölçülene kadar diğer rakamların hepsi tarayıcı rakamıdır.
- **Risk:** Telefon ağı ek gecikme getirebilir, 8 kHz ses de STT hatasını artırabilir; ikisi de ölçülmedi.

### 3.7 Çok dilli destek
- **Şimdi:** Yalnızca Türkçe. Senaryolar, sayı ve tarih okuma (trnorm), fast path sözlüğü ve enjeksiyon filtresi Türkçeye göre yazıldı. Başka dil denenmedi ve ölçülmedi. Sağlayıcılar çok dilli olduklarını söylüyor (Deepgram multilingual, ElevenLabs), ama bunu bizim hatta doğrulamadık.
- **Hedef:** Talep olursa tek bir dil için pilot.
- **Çaba:** Ölçülmedi. Kaba tahmin dil başına 1–2 hafta (senaryo çevirisi, kurallar, anlama test seti, ses seçimi); güveni düşük.
- **Etki:** Türkçe dışında konuşan müşteri grupları kapsama girer.
- **Risk:** Türkçe kurallar o dilde olmayacağı için doğruluğun sıfırdan ölçülmesi gerekir.

### 3.8 Ölçek ve maliyet
- **Şimdi:** Dakikası $0,035 (17 canlı A1S araması, 54,2 dk, $1,91, liste fiyatı; S52). Arama başına ortalama ~$0,11; en ucuzu ~$0,02, en pahalısı ~$0,23 (S50). Maliyetin %94'ü TTS. 25.000 dk/ay ≈ $880. Eşzamanlı yük testi yapılmadı (eval-004 not_started). ElevenLabs hesabı Starter planında ve 6 eşzamanlı çağrıyla sınırlı (S52). Gerçek müşterilerin kaçının anketi sonuna kadar götüreceği bilinmiyor; maliyetteki en büyük belirsizlik bu.
- **Hedef:** 1, 5 ve 10 eşzamanlı aramada p50/p90 latency. Plan seçimi (Pro, Business ya da Enterprise).
- **Çaba:** ~1 hafta (tahmin).
- **Etki:** Kampanya günü kapasitesi ve gerçek aylık bütçe netleşir.
- **Risk:** Sağlayıcı rate limit'leri. Yerel profil (L2) için sunucu maliyeti doğrulanmadı; GPU saat fiyatı bir varsayım (S44).

### 3.9 Enterprise indirimi
- **Şimdi:** Elimizde teklif yok. ElevenLabs fiyat ekranında Enterprise için yalnızca "ölçekte indirim" yazıyor, oran yok (S51). Hesaplardaki tüm rakamlar liste fiyatı.
- **Hedef:** ElevenLabs, Deepgram ve Anthropic'ten yazılı teklif almak ve `config/pricing.json`'a işlemek.
- **Çaba:** Mühendislik tarafında iş yok; süre satın alma sürecine bağlı ve bilinmiyor.
- **Etki:** TTS maliyetin %94'ü olduğu için ElevenLabs indirimi toplam maliyeti doğrudan düşürür.
- **Risk:** Minimum hacim ya da taahhüt şartı gelebilir.

---

## 4. "Tatmin olmazlarsa" gelebilecek 8 itiraz ve slayttaki cevap

**1. "Yapay ses fark ediliyor mu?"**
- **Slayttaki cevap:** Bunu müşteriyle ölçmedik. İç dinlemede v4 Turbo sesi iyi bulundu. Kör dinleme testi planlı ve birkaç günlük bir iş. "Bot musun?" diye sorulursa ajan dürüstçe dijital asistan olduğunu söylüyor; amacımız kandırmak değil, rahatsız etmeden anketi tamamlamak.
- **Dayanak:** S48, S44 (n=2–3), S35/core-006. Beyan cümlesinin son metni hukuk ekibinin onayını bekliyor.

**2. "Neden hazır ElevenLabs Agents değil?"**
- **Slayttaki cevap:** İki sebep var. Birincisi maliyet: liste fiyatında yalnızca barındırma $0,08/dk, LLM ve telefon bunun üstüne geliyor. Bizim hattın toplamı $0,035/dk. Ortalama bir arama orada ≥ ~$0,26, bizde ~$0,11. İkincisi kontrol: orada akışı LLM yönetiyor, bizde akış kodda; adım atlanmıyor ve "aranmak istemiyorum" talebi kodla kayda geçiyor. Ses zaten aynı sağlayıcıdan (ElevenLabs).
- **Dürüst sınır:** İki yaklaşımı aynı 20 aramayla henüz kıyaslamadık (Faz 3, ea-001). "Agent daha kötü" demiyoruz. $0,08'e ses üretiminin dahil olduğunu varsaydık, bu doğrulanmadı.
- **Dayanak:** S42, S51, ADR 0009, `docs/faz-elevenlabs-agent.md`.

**3. "Yıllık milyonlarca TL isteyen firmalardan farkımız ne?"**
- **Slayttaki cevap:** 25.000 dk/ay için API maliyeti liste fiyatıyla ~$880/ay, yani ~$10.500/yıl. Senaryo, veri ve ölçüm bizde kalıyor; STT, LLM ve TTS sağlayıcısını tek bir ayarla değiştirebiliyoruz. Aynı test setini (5 persona × 4 yol) firmalara da uygulayıp onları aynı ölçütle karşılaştırabiliriz.
- **Dürüst sınır:** Firmaların kalitesini ve teklif tutarlarını bu çalışmada ölçmedik. Telefon entegrasyonu, yönetim paneli, ölçek testi ve işletme (destek, SLA, ekip zamanı) bizde henüz yok. Bu bir PoC; ürüne dönüşmesi için gereken iş bu slaytta. TL karşılığı güncel kurla hesaplanmalı.

**4. "1,5 saniye bekleme insan gibi değil."**
- **Slayttaki cevap:** Haklısınız, hedefi biz de tutturamadık. p50 1,56 sn. LLM'e gitmeyen turlarda 0,78 sn'ye iniyoruz. Kalan yük LLM'de (~0,95 sn) ve tur sonu beklemede (~0,5 sn). Hedefimiz yaklaşık 1 saniye ve 1–2 haftalık iş.
- **Dürüst sınır:** ~1,0 sn ölçülmüş bir sonuç değil, hedef. Fast path'in gerçek trafikte ne kadar tur çözeceği ölçülmedi.
- **Dayanak:** S38, S39, S52.

**5. "Telefonda hiç denemediniz, gerçek müşteride çalışır mı?"**
- **Slayttaki cevap:** Doğru, telefonda henüz denemedik. Tüm aramalar tarayıcıdan yapıldı; telefon sesi yalnızca simülasyonla test edildi. İlk gerçek arama 1–2 haftalık iş. Telefon latency'si ve doğruluğu için rakamı o ölçümden sonra vereceğiz.
- **Dayanak:** sim-005, core-009, core-014.

**6. "Müşteri soru sorarsa ya da konu dışına çıkarsa ne olacak?"**
- **Slayttaki cevap:** Bugün ajan kibarca not alıp soruya dönüyor, soruyu cevaplamıyor. Sonraki adımda yalnızca onaylı içerikten kısa bir cevap verecek ve soruya geri dönecek. Bu 1–2 haftalık iş.
- **Dürüst sınır:** Bir aramada nezaket cümlesine yanlış olarak "Sorunuzu not aldım" dedi; düzeltmesi yeniden denenmeli.
- **Dayanak:** S7, ADR 0003, ADR 0009, ea40c9d0712a.

**7. "Cevabı yanlış kaydederse? Veriye güvenebilir miyiz?"**
- **Slayttaki cevap:** Ajanın anlama yeteneğini 193 cümleyle, her cümleyi 3 kez sorarak ölçtük. Yerel model, daha önce hiç görmediği cümlelerde %98,7 doğru anladı. Müşteri sözüne gömülü komutlarda 0 yanlış dal çıktı. Ajan anlamadığında tahmin etmiyor, soruyu yeniden soruyor. "Aranmak istemiyorum" kararı kodla güvenceye alınıyor.
- **Dürüst sınır:** Test cümleleri yazıyla hazırlandı, gerçek telefon sesinden gelmiyor. Canlı hattaki bulut modeli (Haiku) %93–96 aldı ve yeniden ölçülmesi bekleniyor.
- **Dayanak:** S26, S27, Session 038.

**8. "Müşteri verisi nereye gidiyor? KVKK?"**
- **Slayttaki cevap:** Canlı hatta (A1S) ses Deepgram'a, metin Anthropic'e, ajanın cümleleri ElevenLabs'a gidiyor. Verinin dışarı çıkmadığı yerel bir alternatif de var: L2, kıyas matrisinde 1. sırada (89,9). Ses kaydı şu an yalnızca test aracı olarak kullanılıyor; production için saklama süresi, maskeleme ve erişim yetkisi işi (plat-002) planda.
- **Dürüst sınır:** L2'nin sunucuda (CUDA) çalıştığı doğrulanmadı. Sağlayıcı sözleşmeleri (veri işleme, verinin tutulduğu yer) hukuk ve satın alma ekipleriyle netleşmeli. Kayıt şu an şifrelenmiyor ve otomatik silinmiyor.
- **Dayanak:** S9, S42, Session 042, Session 044.
