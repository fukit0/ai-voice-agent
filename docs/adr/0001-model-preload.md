# ADR 0001 — Model ön yükleme ("Hazırla") ve sıcak ölçüm zorunluluğu

- Durum: Kabul edildi (2026-10-23)
- İlgili: core-003, lab-006, kıyas matrisi (eval-002), production projeksiyonu (eval-005)

## Bağlam

Demo ve ölçümlerde ilk çağrılar soğuk başlangıç yüzünden yavaş: 2026-10-23'te L2'nin ilk LLM çağrısı
66,7 sn sürdü (Qwen3 belleğe yükleniyor), Chatterbox'ın ilk çağrısı ~48 sn. Soğuk başlangıcın kaynakları:

| Kaynak | Ne zaman olur | Etki |
| --- | --- | --- |
| Diskten belleğe model yükleme | Backend'de ilk çağrı; Ollama'da ilk çağrı | 10–70 sn |
| İlk çıkarımda MPS/MLX çekirdek derleme | Yüklemeden sonraki ilk çıkarım | Birkaç sn |
| Ollama'nın boşta kalan modeli bellekten atması | Varsayılan 5 dk işlem yoksa | Bir sonraki çağrı yine soğuk |
| Backend'in yeniden başlaması | `uvicorn --reload` her dosya değişikliğinde | Python içindeki tüm modeller düşer |
| İndirme | Modelin diskte hiç olmaması | Dakikalar (tek seferlik) |

Production'da modeller süreç ayağa kalkarken yüklenir ve sürekli bellekte durur; kullanıcı hiçbir zaman
soğuk bir modelle konuşmaz. Demo ve kıyas ölçümleri bu koşulu temsil etmeli.

## Karar

1. **Hazırla (warmup):** `POST /api/profiles/{id}/warmup` profilin her bileşenini yükler, bir ısınma
   çıkarımı yapar (çekirdek derleme dahil), ardından ikinci bir çağrıyla **sıcak süreyi** ölçer.
   Arayüzde profil seçicinin yanında "Hazırla" düğmesi ve bileşen bazında ilerleme var.
2. **Soğuk çağrı yasak:** Profil sıcak değilse `/stt`, `/llm`, `/tts` uçları `409 profile_not_warm` döner.
   Bilinçli istisna için `?allow_cold=true` gerekir ve log kaydına `warm: false` yazılır; kıyas
   matrisi bu kayıtları dışarıda bırakır.
3. **Sürekli bellekte tutma:** Ollama çağrıları `keep_alive=-1` (OLLAMA_KEEP_ALIVE ile değişir) kullanır;
   ısınan model boşta kalınca atılmaz. Sağlık kontrolü (`scripts/healthcheck.py`) zaten yüklü bir modeli
   bellekten atmaz.
4. **Tek bilgisayarda bellek bütçesi:** Hazırla, varsayılan olarak hedef profilde kullanılmayan modelleri
   bellekten çıkarır (paylaşılanlar kalır; ör. L2→L4 geçişinde Whisper kalır). Böylece ölçümler bellek
   sıkışmasıyla bozulmaz (2026-10-22'de STT bu yüzden 2,8 sn yerine 44 sn sürmüştü). Bellek yeterliyse
   `keep_others=true` ile birden fazla profil sıcak tutulabilir.
5. **Demo modu:** `scripts/demo.sh` arayüzü derleyip backend'i `--reload` olmadan tek süreçte çalıştırır;
   dosya değişikliği modelleri düşürmez.

## Sonuçlar

- Profil değiştirmek ücretsiz değildir: yeni profil "Hazırla" ile bir kez yüklenir (Qwen ~1 dk, Chatterbox
  ~1 dk). Bu süre demo öncesine alınır, testlerin içine girmez.
- Ölçülen her gecikme sıcak koşulda alınır; production projeksiyonu bu değerleri kullanır.
- Production'da her profilin modelleri ayrı sunucuda sürekli yüklü olacağı için bu kısıt yalnızca
  tek bilgisayarlı PoC'ye özgüdür.

## Ölçüm sonrası ek (2026-10-23, Mac 36 GB)

- L2 hazırlanırken Qwen3 30B (18 GB) ve Chatterbox birlikte bellekteyken Chatterbox'ın sıcak çağrısı
  33–163 sn'ye, Qwen'in zaten sıcak çağrısı 52 sn'ye çıktı (tek başına: 0,4 sn). Neden: birleşik
  bellekte GPU çalışma alanı aşılıyor, sistem swap'e ve sayfa geri yüklemeye düşüyor.
- Bu yüzden Hazırla, tüm modeller yüklüyken son bir kontrol yapar; bu kontrolde yavaşlayan bileşen
  `degraded` işaretlenir ve ölçümlere kapatılır.
- Karar (kullanıcı onayı): L2/L3/L4'te canlı TTS EMA Lightning; Chatterbox yalnızca TTS stüdyosunda tek
  başına yüklenerek kör dinleme testinde kullanılır. Production'da Chatterbox seçilirse ayrı GPU'da çalışır.
