# ADR 0007 — Realtime hibrit profillerin (A2, A3) değerlendirmesi

Tarih: 2026-10-28 · Özellikler: core-018, core-019, core-023 (core-011 girdisi) · Durum: değerlendirildi, üretim adayı DEĞİL

## Kanıt (kullanıcının canlı aramaları, Mac mikrofonu; örneklem kullanıcı kararıyla küçük tutuldu)
- A2 (OpenAI gpt-realtime-2.1-mini): `eaee33b00412`, `16f223f13f0c`, `4d016cb8ac1d` (+ önceki `d227e6c2553e`). Yerel tur yönetimi hatasız çalıştı
  ("Cancellation failed" 0, sahte tur açılışı yok), sabit giriş sesi 4/4 aramada kelimesi kelimesine (verbatim 1,0) çalındı.
  Ama: (1) model okunacak soruyu değiştirdi/uydurdu (verbatim 0,03–0,27; "nerde kaldık söyle bana"), (2) cevabı yanlış anladı
  ("Müsaitim" → refuse, görüşme yanlış kapandı; konuşulanı "kesinlikle anlamıyor"), (3) dış sesleri konuşma sayıyor.
- A3 (Gemini 3.8 Live): `47e1691a1c69`, `d507e150fcf6`. Fonksiyon çağrısı çalışıyor (10/10, çağrısız tur 0) ve metni sadık okuyor
  (verbatim ≈ 1,0) ama Türkçe anlama zayıf: giriş transkriptinde "suerte", "schwer", "locos", "Chumphon", "목동매는"; söz kesme zayıf.
- Ayrıntılı gecikme: `evidence/core-011-latency-compare.json`, `core-023-a3-report.json`.

## Karar
1. **A2 ve A3 üretim adayı değildir.** Sebep ses kalitesi değil **anlama**: Türkçe kısa cevap ve gürültü altında hatalı niyet/değer,
   ve (A2) modelin akıştan kopması. Bunlar akışı deterministik tutan hibrit yöntemle bile gizlenemiyor.
2. **Üretim yönü: cascade (STT → LLM → TTS) profilleri.** Anlama ölçülebilir ve STT geçidiyle korunabiliyor (ADR 0006: Deepgram referans);
   sabit yasal metinler önceden üretilmiş sesle (core-019 mekanizması cascade'de de kullanılabilir). Açık sorunlar: A1 TTS kalitesi/hızı (core-025), yerel STT öksürük sorunu (core-016).
3. **A2/A3 PoC'de "referans/üst sınır" olarak kalır** (en düşük ilk-ses gecikmesi, doğallık karşılaştırması); demo anlatısı: hız kazanımı var, anlama ve akış sadakati bedeli büyük.
4. Yapılan A2 iyileştirmeleri (yerel tur yönetimi, transkripsiyon ipucunun kaldırılması, sabit ses, yabancı transkript guard'ı) korunur;
   kalan model davranışı sorunları core-024/core-026'da, öncelik düşük.

## Sınırlar (demoda saklanmaz)
- Örneklem küçük (A2 4, A3 2 arama), tek konuşmacı, evde ortam gürültüsü; istatistiksel sonuç değil, tutarlı kalitatif bulgu.
- Sabit sesin tekrar-sorma (önekli metin) düzeltmesi canlı doğrulanmadı (aramalar düzeltmeden önce yapıldı).
- Karar kullanıcı gözlemine dayanır ("modeller çok kötü"); sayısal anlama doğruluğu ölçülmedi.

## Ek (2026-10-28, core-024): A2 sapma önlemleri
Seçenekler: (a) out-of-band response, (b) sabit TTS'in tüm sabit sorulara genişletilmesi, (c) sapmada yeniden söyleme. Seçilen: (b) + bağlam temizliği + YesNo transkript çapraz kontrolü; (a) denenmedi (API desteği ve gecikme ölçülmedi), (c) gereksiz: sabit ses verbatim 1,0, model yalnız TTS hatasında konuşur ve sapma `speech_deviation` olayıyla izlenir.
Gerekçe: sapmanın kaynağı modelin soruyu yeniden yorumlaması ve eski müşteri seslerinin bağlamda kalmasıydı (d227e6c2553e, eaee33b00412); ikisi de modeli sorudan ve eski sesten uzak tutarak ele alındı. Kapsam: yalnız A2 PoC, üretim adayı değil. Doğrulama bekliyor: 10 canlı A2 araması. Maliyet: dinamik metinli turlarda ilk TTS üretimi gecikmesi.

## Ek 2 (2026-10-28): core-024 sonrası iki canlı A2 araması (126f5d20c82a, 5e921568e5e9)
- Sabit ses: 33 turda verbatim 1,0, sapma olayı 0 (kod olarak sağlandı).
- Anlama: giriş adımında "İlgilenmek istemiyorum" devam olarak bildirildi (yanlış dal); q4'te müşterinin söylemediği metin bildirildi; 29 cevap bildiriminin 10'u (%34) geçersiz. İlk ses gecikmesi sabit seslerde çoğunlukla 2-5 sn (dinamik metinde ilk TTS üretimi), en kötüsü 10,7 sn.
- Tasarım açığı: müşteri transkripti cevap bildiriminden sonra geliyor; transkriptle çapraz kontrol bayat metne bakıyor.
- Karar: realtime modellere daha fazla zaman ayrılmaz (kullanıcı kararı; cascade'e göre düşük başarı). Üretim yönü cascade (ADR 0006) değişmedi. core-024 düşük öncelik, core-011 kapatıldı.
