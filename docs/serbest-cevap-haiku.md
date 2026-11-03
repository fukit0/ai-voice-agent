# Serbest cevabın Claude Haiku arka ucu (A1S)

Tarih: 2026-11-03 · Durum: uygulandı, sahte istemci ve sahte HTTP ile test edildi. **Gerçek Haiku ile ÖLÇÜLMEDİ.** Bulut çalışma kopyasından gerçek API çağrısı yapılmadı; Mac'in Linux VM'inden de Mac localhost'una erişilemiyor. Kullanıcı Mac'te aşağıdaki komutla ölçecek. · İlgili: docs/serbest-cevap-qwen.md (mekanizma, istem v3, denetim), ADR 0009 adım 2, core-012 (Haiku düşünme kapatma), eval-003 (maliyet)

## Özet
Artık A1S kullanılıyor (Deepgram nova-3 + `claude-haiku-5-5` + ElevenLabs flash). Konu dışı serbest cevap ise yalnız lokal Qwen ile çalışıyordu. A1S'te Qwen yüklü olmadığı için her karşı soru turunda (`counter`, `clarify`) havuz cümlesi konuşuyordu.

Kullanıcının isteğiyle serbest cevaba ikinci bir arka uç eklendi: **Claude Haiku**. Her şey Qwen yoluyla aynı: aynı sistem istemi (v3), aynı `<musteri>` veri ayracı, aynı çıktı denetimi, aynı havuza düşüş, aynı kategori listesi. Değişen yalnızca istemci, zaman aşımı ve kayıt alanları.

## Arka uç seçimi (`backend` ayarı)
| Değer | Davranış |
|---|---|
| `auto` (varsayılan) | Aramanın profilindeki LLM `anthropic` ise (A1, A1S) **Haiku**. Ollama ise (L1-L5) ya da profil bilinmiyorsa **Qwen** (eski davranış). |
| `haiku` | Profilden bağımsız Haiku. Ollama profilinde de API'ye gider. |
| `qwen` | Profilden bağımsız Qwen. A1S'te Qwen bellekte değilse havuz konuşur (eski davranış). |
| Realtime (A2/A3) | Hiç uygulanmaz. `api_voice` realtime'da üretici vermez, `make_default(realtime=True)` None döner. |

- Model adı: ekrandan girilen `haiku_model` > profilin Anthropic LLM modeli (A1S: `claude-haiku-5-5`) > `haiku_default_model`. Ekranda alan boşsa model profilden gelir.
- Sebep: ayrıştırıcı ile aynı sağlayıcıyı kullanmak. A1S'te ikinci bir yerel model yüklemek ya da Ollama'yı ayakta tutmak gerekmiyor. Kendi kendine karar veren `auto` sayesinde L2 demosunda Qwen yolu hiç değişmiyor.

## Haiku istemcisi (`free_reply.AnthropicChatClient`)
- **Aynı anahtar ve ağ mantığı.** `providers/remote.py`'deki `anthropic_headers()` kullanılıyor: `ANTHROPIC_API_KEY`, isteğe bağlı `ANTHROPIC_WORKSPACE_ID`. Bu yardımcı `AnthropicLLM.complete` içinden çıkarıldı, davranışı aynı kaldı. İstek, paylaşılan bağlantı havuzundan (`remote._request`) gidiyor. A1S'te ayrıştırıcının açtığı TLS bağlantısı yeniden kullanılır; bayat bağlantıda bir kez yeniden denenir.
- **Düşünme kapalı** (`thinking: {"type": "disabled"}`). core-012 ölçümü: Haiku 5.5 kısa `max_tokens`'ı düşünmeye harcayıp boş metinle bitebiliyor. Model `disabled` değerini ya da `temperature` alanını reddederse o alan bir daha gönderilmez (AnthropicLLM ile aynı kural). Düşünme kapatılamaz ve cevap boş gelirse büyütülmüş bütçeyle **tekrar denenmez**, çünkü gecikme artar. Denetim `empty` kuralıyla havuza düşürür.
- **max_tokens 120** (`haiku_max_tokens`, yalnız config'ten değişir). Türkçe ~200 karakterlik iki cümle Claude tokenizer'ında ~60-80 token ediyor (tahmin, ölçülmedi). Denetim 200 karakteri aşan cevabı zaten reddediyor.
- **Zaman aşımı `haiku_timeout_s`, varsayılan 2,0 sn** (aralık 0,3-5, ekrandan değişir). Varsayım şu: ayrıştırıcıda ölçülen Haiku p50 ~0,95 sn, ama o çıktı kısa bir JSON'du. Serbest cevap daha uzun metin üretir, p95 daha yüksek olabilir. Qwen'in 1,5 sn'si Haiku'ya uygulanmaz. Toplam süre ayrıca ölçülür ve sınırı aşan cevap söylenmez (Qwen ile aynı).
- **Soğuk model yok.** Yoklama ve ısınma yapılmaz; `is_warm` ağ çağrısı yapmaz. Anahtar yoksa istek atılmadan havuz konuşur (`reason: no_key`). HTTP hatası (ör. 529 aşırı yük) olursa `error`, httpx zaman aşımında `timeout`.
- **Qwen thinking ayarı Haiku'ya uygulanmaz.** Thinking açık olsa bile Haiku yolunda Ollama istemcisi oluşturulmaz.

## Kayıt ve maliyet
- Tur olayı `free_reply` ve oturum turu (`turns[]`): `reply_source` (qwen | **haiku** | pool), `free_reply_backend` (qwen | haiku), `free_reply_model`, `free_reply_s` (uçtan uca), Haiku'da ayrıca `free_reply_input_tokens`, `free_reply_output_tokens`, `free_reply_cost_usd`. Fiyat bulunamazsa maliyet yazılmaz (sıfır yazılmaz).
- Maliyet: `usage.llm_cost` → `config/pricing.json` `anthropic:claude-haiku-5-5`: $0,10/1M giriş, $0,50/1M çıkış. Mac'teki dosyada `verified: true`, kaynak anthropic.com/claude/haiku (2026-11-01). Bu ekte fiyat yeniden doğrulanmadı.
- Zaman aşımı ya da denetim düşüşünde cevap gelmişse token ve maliyet yine yazılır, çünkü istek ücretlendirildi. httpx istisnasında token bilinmez. API yine de ücretlendirmiş olabilir; rapor bunu `free_reply_tokens` eksik olarak işaretler, bu durumda maliyet alt sınırdır.
- Arama düzeyi `usage`: Haiku'ya gerçekten giden her istek ayrı kalem olur. `items.free_reply_calls`, `free_reply_input_tokens`, `free_reply_output_tokens`, `free_reply_s` ve `cost.by_component.free_reply` yazılır; bu kalem **toplam maliyete dahildir**. `llm_*` alanları yalnız ayrıştırıcıyı sayar. Haiku isteği olmayan aramalarda (L2, Qwen) rapor öncekiyle birebir aynı.
- `config.free_reply`: `backend`, model, zaman aşımı, Haiku'da `max_tokens`.
- Ayarlar ekranının kıyas tablosunda üçüncü satır **Haiku (düşünme yok)** var: tur sayısı, süre, havuza düşüş oranı ve sebepleri. Tablonun üstünde Haiku'nun tahmini toplam maliyeti gösterilir. Aramalar › Tur gecikmeleri › Serbest cevap hücresinin ipucunda model, token ve maliyet görünür.

## Ayar ve API
- `config/free-reply.json`: `backend` "auto", `haiku_model` null, `haiku_default_model`, `haiku_timeout_s` 2,0, `haiku_max_tokens` 120, `backend_note` ve `haiku_note`. Varsayımlar ve "ÖLÇÜLMEDİ" notu bu açıklamalarda yazılı.
- Ekran: **Ayarlar › Konu dışı serbest cevap**. Arka uç seçimi, Haiku modeli (boş bırakılırsa profilden), anahtar durumu ("Anahtar var" ya da "ANTHROPIC_API_KEY yok → havuz"), Haiku zaman aşımı ve ayrı bir "Arka ucu varsayılana dön" düğmesi var. Qwen alanları "Qwen modeli" ve "Qwen zaman aşımı" olarak adlandırıldı.
- API: `PUT /api/free-reply {backend?, haiku_model?, haiku_timeout_s?}` (null → varsayılan). GET yanıtına `backend`, `backends`, `haiku_*` alanları ve `haiku_status` eklendi. `haiku_status` ağ çağrısı yapmaz, yalnız anahtarın varlığına bakar.
- Kategori listesi değişmedi (`counter`, `clarify`). Haiku için kategori genişletme bu işin kapsamında değil.

## Gerçek Haiku ile ölçüm (kullanıcı Mac'te çalıştıracak)
```bash
cd ~/sahibinden-voice-agent
./.venv/bin/python scripts/eval_free_reply.py --runs 3 --backend haiku
```
- Anahtar ortamdan ya da proje kökündeki `.env`'den okunur. Yoksa betik çalışmaz ve net bir hata verir (çıkış kodu 2).
- Aynı 32 vaka × 3 tekrar = 96 istek. Tahmini maliyet ~900 giriş + ~30 çıkış token/istek ile 96 × ~$0,0001 ≈ **$0,01** (tahmin).
- Çıktı: `evidence/free-reply-eval-haiku-<tarih>.json/.md`. Satır başına `backend`, `input_tokens`, `output_tokens`, `cost_usd`; özette token ortalamaları, `cost_usd_total` ve `first_call_s` var. İlk çağrı TLS el sıkışmasını içerir ve p95'i tek başına şişirebilir. Isınma yapılmaz.
- Qwen ile kıyas: `--compare evidence/free-reply-eval-<qwen koşusu>.json`.
- Kabul önerisi (Qwen ile aynı, karar değil): counter+clarify geçme ≥ 0,85, p95 ≤ `haiku_timeout_s`, insan okumasında uydurma ya da söz veren cümle 0. p95 2,0 sn'yi aşarsa ya zaman aşımı yükseltilir ya da düşüş oranı kabul edilir.

## Doğrulama (bulut çalışma kopyası)
- Önce: `PYTHONPATH=.:backend python -m pytest backend/tests -q` → **919 passed, 1 skipped**. Sonra → **953 passed, 1 skipped** (+34: `backend/tests/test_free_reply_haiku.py`). Mevcut testler silinmedi ve değiştirilmedi.
- Frontend: `npx tsc --noEmit` temiz. `npx vitest run` → **25 dosya, 127 test** (önce 24/123; +4: `FreeReplyHaiku.test.tsx`).
- Çıktılar: `evidence/free-reply-haiku-tests-20261103.txt`
- Testlerin kapsadığı konular:
  - Arka uç seçimi: varsayılanlar; auto seçimi (A1S → haiku, L2 → qwen, profil yok → qwen, realtime → None, kapalı → None); zorlanmış seçim; model önceliği (ekran > profil > varsayılan); Qwen thinking açıkken Haiku'da Ollama istemcisi oluşmaması.
  - Üretim ve düşüş: başarılı cevapta token ve maliyet; Qwen ile birebir aynı istem ve ayraç; anahtar yoksa istek atılmadan havuz; zaman aşımı (istisna ve toplam süre, geç gelen cevabın maliyeti); `haiku_timeout_s`'in kullanılması; denetim düşüşü (aday + maliyet); kategori dışında çağrı olmaması; akışta cevap + soru birebir; fiyatı olmayan modelde maliyetin None kalması.
  - İstemci (sahte HTTP): gerçek istemcinin istek gövdesi (URL, başlıklar, `thinking: disabled`, `max_tokens` 120, sistem istemi ayrı alanda, ayraç); reddedilen `temperature`'ın bir daha gönderilmemesi; HTTP 529 → havuz; anahtar yoksa HTTP yok; ayrıştırıcı başlıklarının değişmemesi.
  - Ayar ve API: ayar doğrulaması; API GET/PUT.
  - Maliyet ve kayıt: usage sayacı (yalnız gönderilen Haiku istekleri, Haiku yoksa rapor aynı, toplam maliyete dahil, token eksikliği); `llm_cost`; oturum kaydında alanlar ve usage kalemi; kıyas tablosunda Haiku grubu.
  - Qwen ve eval: Qwen yolunun değişmemesi; eval betiğinin `--fake --backend haiku` koşusu; anahtar yoksa net hata; `--thinking` ile `--backend haiku` reddi.

## Bilinen sınırlar (dürüst durum)
- **Gerçek Haiku ile ölçülmedi.** Haiku'nun Türkçe karşılık kalitesi, denetimden geçme oranı, gerçek süresi (p50/p95), token sayısı ve maliyeti bilinmiyor. 2,0 sn zaman aşımı ve 120 token sınırı varsayım.
- Haiku 5.5'in istem v3'e Qwen gibi uyup uymadığı bilinmiyor. İstem Qwen ölçümlerine göre ayarlandı. Haiku soru cümlesi eklerse ya da puan verirse denetim reddeder (havuz), ama bu oran ölçülmedi.
- Tur gecikmesi A1S'te ayrıştırıcı (~0,95 sn p50) + serbest cevap (ölçülmedi) sırayla. İki Haiku çağrısı art arda gider; konu dışı turda toplam 2-3 sn sessizlik olabilir.
- Kişisel veri: Haiku yolunda müşteri sözü (en çok 300 karakter) Anthropic API'sine gider. Ayrıştırıcı da zaten aynı metni gönderiyor, yeni bir veri türü eklenmedi. Plan gereği gerçek müşteri verisi demo API'lerine gönderilmemeli (KVKK).
- Zaman aşımında istek kesilir ama API ücretlendirmiş olabilir. Bu durumda token bilinmez, maliyet alt sınırdır.
- Gerçek ses ve telefonla denenmedi.

## Demoda anlatım notu
- "A1S'te karşı soruya artık Haiku cevap veriyor. Qwen'in yaptığını aynı istem ve aynı denetimle yapıyor. Ajan puan uydurmuyor, soruyu kod aynen okuyor. Profil Ollama olursa otomatik olarak lokal Qwen'e dönüyor."
- "Her serbest cevap turunun kaydında hangi model konuştu, kaç token harcandı ve tahmini maliyet var. Aramanın maliyet tablosunda bu ayrı bir kalem ve toplama dahil."
- **Bu sınırlamayı bil:** Haiku serbest cevabı gerçek API ile henüz ölçülmedi. Demodan önce Mac'te `--backend haiku` koşusu yapılıp rapor okunmalı; ölçülmeden "ölçüldü" denmez. Haiku 2 sn içinde gelmezse ya da `.env`'de anahtar yoksa ajan sessizce havuz cümlesine düşer. Bu "ilk yükleme" değil, tasarım gereği. Haiku'da soğuk model yok; sorun anahtar, ağ ya da zaman aşımıdır. Konu dışı turda iki Haiku çağrısı art arda gittiği için sessizlik normal turdan uzun olabilir.

## Değişen ve eklenen dosyalar
- Yeni: `backend/tests/test_free_reply_haiku.py`, `frontend/src/FreeReplyHaiku.test.tsx`, `evidence/free-reply-haiku-tests-20261103.txt`, bu doküman
- Değişen: `backend/app/voice/free_reply.py` (`AnthropicChatClient`, `anthropic_client`, `resolve_backend`, `haiku_model`, `haiku_status`, ayarlar, `FreeResult` alanları, `make_default(llm_spec, realtime)`, `thinking_stats` Haiku grubu), `backend/app/providers/remote.py` (`anthropic_headers`, `ANTHROPIC_MESSAGES_URL`; davranış aynı), `backend/app/usage.py` (`add_free_reply`, `llm_cost`, rapor kalemi), `backend/app/voice/session.py` (tur alanları + usage), `backend/app/api_voice.py` (profilin LLM'i), `backend/app/api_free_reply.py`, `config/free-reply.json`, `scripts/eval_free_reply.py` (`--backend haiku`), `frontend/src/FreeReplySettings.tsx`, `frontend/src/api.ts`, `frontend/src/callsApi.ts`, `frontend/src/pages/CallsPage.tsx`, `docs/serbest-cevap-qwen.md` (bu dokümana bağlantı)
- Dokunulmayan: istem metni (v3), denetim kuralları, kategori listesi, `config/pricing.json`, mevcut testler
