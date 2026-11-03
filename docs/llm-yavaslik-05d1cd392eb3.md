# 05d1cd392eb3: LLM yavaşlık analizi (salt okuma, 2026-11-03)

Profil L2-EL: mlx whisper-large-v3-turbo, Ollama qwen3:30b-a3b-instruct (think:false), ElevenLabs. Kaynaklar: oturumun json ve wav dosyaları, logs/provider-calls.jsonl.

## Turlar

| Tur | Müşteri | STT sn | LLM sn | Not |
|---|---|---|---|---|
| 3 | "dinlemek istemiyorum." | 9,95 | 5,40 | Selamlamayı kesti. Sonuç atıldı |
| 5 | (1,9 sn, metin kaydedilmemiş) | 1,26 | – | Beklerken yeniden konuştu. STT reddi, "anlayamadım" |
| 7 | "Müsaade Mehmet." | 0,67 | 0,56 | Havuz cevabı verildi |

Müşteri yaklaşık 15,8 sn sessiz bekledi (wav'da söz 35,2. sn'de bitiyor, ajan 51,0. sn'de konuşuyor). Bugünkü normal Qwen turlarında LLM 0,36–1,13 sn, STT 0,56–0,74 sn.

## Kanıtlı

1. Beklemenin büyük kısmı STT: 1,66 sn'lik ses 9,95 sn'de çözüldü (normalin yaklaşık 15 katı). LLM bundan sonra başladı.
2. LLM'deki 5,4 sn "düşünme" değil: think:false, çıktı toplam 27 token, giriş çağrı başına yaklaşık 700 token. Tekrar deneme ya da hata yok.
3. İkisi de oturumun ilk yerel çağrısıydı ve öncesinde yaklaşık 20 dk boşta kalmışlardı (son çağrı 07:53). Sonraki çağrılar normal.
4. Müşterinin yeniden konuşması (barge-in) 5,4 sn'lik cevabın atılmasına yol açtı. Ama akış cevabı yine de "devam" olarak kaydetti ve sessizce "musaitlik" adımına geçti. Müşteri KVKK sorusunu yeniden duydu. Bu ayrı bir hata.
5. 1 Kasım probu (A1 Haiku) bu durumu açıklamıyor: 180 çağrıda en uzun süre 2,17 sn.

## Kanıtlanamayanlar

- Boşta kalma sonrasında macOS'in belleği sıkıştırması ya da swap'e atması, ya da Mac'te başka bir yük olması. Bunu gösteren log yok.
- `warm: true` koda sabit yazılmış ve Ollama `load_duration` kaydedilmiyor, yani soğuk model ölçülmüyor.

## Öneriler (öncelik sırasıyla)

1. Demodan önce "Hazırla"yı çalıştır, bir deneme araması yap ve aramalar arasında 10 dk'dan uzun boşluk bırakma. Alternatif: demoyu A1S ile yap.
2. Yerel STT ve LLM için arama başında ısınma çağrısı ekle.
3. Ollama süre alanlarını kaydet ve `warm` değerini gerçek durumdan yaz.
4. Atılan turun akışa cevap kaydetmesini engelle.
5. Bekleme yaklaşık 3 sn'yi geçerse dolgu cümlesi söylet.
