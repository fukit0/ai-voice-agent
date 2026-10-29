# ADR 0010 - TTS ton/duygu kontrolü analizi (Chatterbox, ElevenLabs) — karar bekliyor

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

## Öneri (uygulanmadı)
1. Ton → TTS parametre eşlemesi `config/tone-voice.json`'da tutulur, ekrandan düzenlenebilir: ElevenLabs samimi {stability 0,35; style 0,3}, resmî {stability 0,7; style 0}; Chatterbox samimi {exaggeration 0,6; cfg_weight 0,4}, resmî {0,3; 0,5}. **Sayılar başlangıç tahminidir, dinleyerek kalibre edilir.**
2. TTS stüdyosunda sabit `seed` ile aynı cümleyi samimi/resmî iki ton için yan yana üretme (kör dinleme).
3. Chatterbox'ta en belirgin fark için referans klip seçimi (samimi/resmî) ayrı bir seçenek.
4. EMA'da ton değişmez (tek ses, duygu yok); yalnız hız.
5. Canlı hatta ElevenLabs Flash v2.5 ile `style` gecikmesi ölçülür; kabul edilmezse yalnız `stability`.

## Sınırlar
- ElevenLabs `style`'ın Flash v2.5'te işe yarayıp yaramadığı ve v3 etiketlerinin Türkçe kalitesi doğrulanmadı.
- Duygu/ton algısı öznel; kör dinleme ile ölçülmeli.

Kaynaklar: resemble-ai/chatterbox README ve mtl_tts.py; elevenlabs.io/docs (voice settings default, convert API, models, prompting).
