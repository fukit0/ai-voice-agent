# ADR 0009 - Persona (core-005)

Durum: kabul (2026-10-29). Ilgili: core-005, scn-010 (ses secimi, Faz 2), ADR 0003 (FlowDriver).

## Karar
Persona, kodda sabit metin yerine duzenlenebilir bir yapilandirma: ad, ton (samimi/resmi), hitap tarzi, en cok cumle, cumle basina en cok kelime, dogal onay sozleri, yasak kaliplar, ek kurallar. Varsayilan config/persona.json, ekrandan yapilan duzenleme data/persona.json (gitignore). Ekran: 'Persona'.

## Nedenleri
- Demoda 'ajanin tavrini degistirebiliyor muyuz' sorusu kesin gelecek (Demo S1); koda dokunmadan gosterilebilmeli.
- Persona uc yerde etkili: serbest sohbet istemi + acilis, senaryodaki {ASISTAN}, kademeli hatta cevap sonrasi onay sozu. Akis ve yasal metinler persona'dan bagimsizdir (sabit, onayli metin).
- Onay sozleri LLM'e urettirilmez: sabit liste sirayla secilir; boylece KVKK/ yasal metin ve akis davranisi degismez, test edilebilir kalir.
- Dogrulama kodda (validate): ad yalniz harf (TTS okunusu), sinirlar, onay sozu kelime siniri; ekran sorunu aninda gosterir.
- Cumle uzunlugu rapor olarak olculur (kayitli aramalardan), istemde 'kisa konus' demek yetmez; ortalama kelime ve sinir asan cumleler gorunur.

## Ret edilenler
- Onay sozlerini LLM'e urettirmek: ek gecikme, kontrolsuz icerik, her turda yeniden denetim.
- Persona'yi senaryo JSON'una gommek: senaryodan bagimsiz degistirilemez; ses ve tavir ayri ayarlar (Demo S1).

## Sinirlar (demoda soylenecek)
- Realtime hibrit hatta onay sozu eklenmez (model sesi/sabit ses akisi ayri; core-024 dusuk oncelik).
- Hitap tarzi yalniz serbest sohbet istemine girer; senaryodaki {HITAP} aramayi baslatirken verilen degerdir.
- Gercek hatta 5 test aramasinin transkript incelemesi yapilmadi (core-005 bu yuzden blocked).
