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
- Kategori listesi bu ilk ekte değişmedi (`counter`, `clarify`). Haiku için genişletme sonraki ekte yapıldı: aşağıdaki 'off-003' bölümü.

## off-003 (2026-11-03): Haiku'da doğal sohbet: kategori kapsamı, istem v4, açık uçlu adımlar
Durum: uygulandı, sahte istemciyle test edildi. **Gerçek Haiku ile ÖLÇÜLMEDİ**: Haiku'nun bu kategorilerde ne yazdığı, ne kadar uydurduğu, süresi ve maliyeti bilinmiyor.

**Neden.** Kullanıcı A1S'te ElevenAgents'taki gibi doğal bir deneyim istiyor: ajan müşterinin sözüne gerçekten karşılık versin, sohbetten kopmasın, müşteriyi nazikçe ankete geri götürsün. A1S'te yaşanan iki kötü örnek:
1. Q12_NEDEN'de müşteri: "Seviyorum gari. Yüzünden sence niye verdin?" Kategori `counter` (sence). Serbest cevap konuşmadı, sabit havuz cümlesi + köprü çıktı ("Burada önemli olan sizin görüşünüz… Şimdi soruya döneyim.").
2. Aynı adımda müşteri: "Başka bir şey konuşalım ya. Mesela havaalan nasıl bugün?" Bu söz **açık uçlu adımın cevabı olarak kaydedildi** ve ajan sonraki soruya geçti ("Eklemek istediğiniz bir konu var mı?"). Müşterinin sözü hiç karşılanmadı. Sebep: açık uçlu adımda LLM çağrılmıyor. Konu dışı tespiti (`smalltalk.pure_meta`) yalnızca ≤7 kelimelik sözlere bakıyordu ve "konu değiştirme" kategorisi yoktu.

**1. Kategori kapsamı arka uca göre** (`free_reply.categories_for`, `config/free-reply.json`)
| Arka uç | Serbest cevap denenen kategoriler | Kaynak |
|---|---|---|
| Qwen | `counter`, `clarify` (**değişmedi**) | `categories` |
| Haiku | `counter`, `clarify`, `other`, `weather`, `chitchat`, `joke`, `topic_change` | `haiku_categories` |
| İkisi de değil (sabit havuz) | `identity` (dürüst kimlik, core-006), `who` / `number_source` / `recording` (KVKK ve hukuk), `duration` / `purpose` (olgusal), `support` (çağrı merkezi numarası), `profanity` (gözden geçirilmiş özür), `hold` | — |

- Qwen'in listesi bilerek dar kaldı. 2026-11-03 Qwen ölçümünde hava, sohbet, şaka ve diğer kategorilerinde denetimden geçen ama uydurma cümleler çıktı (docs/serbest-cevap-qwen.md). Haiku için aynı risk ölçülmeden kabul edildi. Karşılığında iki önlem alındı: istem güncel bilgiyi uydurmamayı söylüyor, denetime de `realworld_claim` kuralı eklendi.
- Yeni kategori `topic_change` (`smalltalk.PATTERNS` listesinin sonunda). İki tür sözü kapsar. Birincisi açık konu değiştirme: "başka bir şey konuşalım", "konuyu değiştirelim", "biraz sohbet edelim", "laflayalım". İkincisi ankette olmayan güncel bilgi sorusu: havaalanı, trafik, uçuş, maç, kur ya da dolar + "nasıl/kaç/var mı…" ve "saat kaç". "Başka bir zaman konuşalım" bu kategoriye girmez, geri arama olarak kalır. Havuz cümleleri: `config/smalltalk.json` → `replies.topic_change`.
- Kategori listeleri yalnızca config'ten değişir, ekrandan değiştirilemez (gözden geçirme gerekir). `GET /api/free-reply` artık `haiku_categories` alanını da döner. Arama kaydındaki `config.free_reply.categories` o aramanın arka ucunun listesini gösterir.

**2. İstem v4** (`free_reply.SYSTEM`, `PROMPT_VERSION = "4"`, hash kategori ipuçlarını da kapsar)
- Ton: "sıcak ve doğal bir temsilci gibi müşterinin SÖYLEDİĞİNE kısa, somut karşılık". Genel bir "anlıyorum" ile geçiştirme yasak. Konu değiştirilirse kırmadan kısa tutulur ve "ankete kısaca devam edelim" önerilir; azarlama yok.
- Güncel bilgi uydurma yasağı: hava, haber, saat, trafik, uçuş, maç ve kur bilgisine erişim yok, ajan "bilmiyorum" der. Kendi adına puan, fikir ya da cevap yok. Söz verme yok. Soru işareti yok, çünkü soruyu kod ekliyor. En fazla 2 kısa cümle. İnsan iddiası ve yaşantı uydurma yok. `<musteri>` ayracı ve enjeksiyon kuralı **aynen korundu**.
- **Tek kaynak, iki arka uç aynı istemi alır.** Haiku'ya ayrı bir sistem istemi gerekmedi. Kategoriye özgü yönlendirme (havayı bilmiyorsun, kendine yaşantı uydurma, konu değiştirmede nazikçe ankete dön) tur mesajındaki `Durum:` satırına (`CATEGORY_HINT`) yazılıyor. Qwen yalnızca counter/clarify gördüğü için bu yönergeler ona hiç gitmez. Sistem istemi 2357 karakter (v3: 1970). Uzunluk sınırı testte: ≤2400. Sebep: v2'nin uzun istemi Qwen'de zaman aşımlarıyla birlikte görülmüştü (nedeni kanıtlanmadı).
- Örnekler: 2 counter/clarify (v3'ten), 1 güncel bilgi ("yollar kalabalık mı şu an"), 1 konu değiştirme ("bırak anketi biraz laflayalım"). Kullanıcının iki cümlesi istemde **örnek olarak kullanılmadı**. Bunlar değerlendirme setine eklendi: f33 (`counter`, Q12_NEDEN) ve f34 (`topic_change`, Q12_NEDEN). İkisi de Haiku'da canlı kapsamda; f34 Qwen'de değil. Set artık 34 vaka.
- Sızıntı testi genişletildi (`test_prompt_examples_disjoint_from_eval_set_including_user_examples`). İstemdeki örnek sözler hiçbir eval sözüyle aynı olamaz ve onlarla 3 kelimelik ortak dizi taşıyamaz. Kullanıcının cümlelerindeki "havaalan", "seviyorum" ve "konuşalım" kelimeleri istemde geçmez. Eski test (`test_prompt_examples_do_not_leak_eval_utterances`) korunuyor.

**3. Açık uçlu adımlarda konu dışı sohbet** (Q12_NEDEN, Q4, son adım Q8 "Eklemek istediğiniz bir konu var mı?")
- `pure_meta` iki yönde genişledi. Açık konu değiştirme sözü 16 kelimeye kadar cevap sayılmıyor. Kısa (≤7 kelime) soru biçimli hava, hal hatır ve güncel bilgi sözleri de cevap sayılmıyor. Böyle bir sözde müşteriye önce karşılık verilir (Haiku ya da havuz), sonra aynı soru (Q8'de "Eklemek istediğiniz bir konu var mı?") yeniden sorulur. Art arda 2. konu dışı sözde geri arama önerilir, 3.'de sabit kapanış gelir (değişmedi).
- Bilinçli sınırlar: şaka kalıpları ("şaka", "evlen") gerçek bir açık uçlu cevabın içinde geçebildiği için açık uçlu adımda hâlâ cevap sayılıyor. Güncel bilgi kelimesi uzun bir cevabın içinde geçerse ("temsilci trafik cezası nasıl ödenir anlattı…") söz yine cevap olarak kaydedilir. "Yok, başka bir şey yok" da cevaptır.
- Serbest cevap düşse bile (Qwen, anahtar yok, zaman aşımı) ikinci örnek artık yutulmuyor: `topic_change` havuz cümlesi + köprü + soru.
- Offline off-001 ölçümü (`scripts/eval_offtopic.py`, LLM'siz): genel başarı 0,989 → **0,9957**. Konu dışı 0,984 → 0,9937, ilgili cevap 0,9934, robotik şablon 0,032 → 0,0159. LLM çağrısı değişmedi (415/525 tur).

**4. "Serbest cevap neden devreye girmedi?" kaydı**
- Tur kaydına iki yeni alan eklendi: `free_reply_category` (hangi konu dışı kategorisi) ve havuza düşüldüyse `free_reply_fails` (denetim kuralları ya da hata metni, en çok 5 tane). Mevcut `reply_source`, `free_reply_fallback` ve `free_reply_backend` alanları aynı.
- Aramalar › detay › Tur gecikmeleri › Serbest cevap: hücrede "0,00 sn pool (category · qwen)" görünür. İpucunda okunur bir açıklama var, örneğin "kategori bu arka uçta kapsam dışı (sabit havuz) [qwen, topic_change]" ya da "denetimden geçmedi: realworld_claim [haiku, weather]". Bu metni `callsApi.freeReplyReason` üretiyor.
- Hiç `free_reply` olayı yoksa (açık uçlu adımda söz cevap sayıldıysa ya da serbest cevap üreticisi verilmediyse) hücre "—" gösterir. Kullanıcının 2. örneği bu durumdaydı.
- **A1S auto gerçekten Haiku mu seçiyor?** Testte evet: A1S profilinin gerçek LLM tanımıyla (`anthropic`, `claude-haiku-5-5`) `make_default` Haiku'yu ve geniş listeyi seçiyor, L2'de Qwen'i (`test_a1s_auto_really_selects_haiku_with_wide_list_l2_qwen`). Mac'teki kayıtlarda bulgu şu: bugünkü A1S aramalarının (08:37–08:47 UTC, ör. `2f419d1e94fe`) `config.free_reply` alanında `backend` yok ve model Qwen. Yani bu aramalar Haiku eki commit'lenmeden (08:52) **önceki kodla** yapılmış: serbest cevap Qwen'e gitmiş, Qwen bellekte değilse havuz konuşmuş. Kullanıcının örneğindeki arama Mac'teki `data/voice-sessions` içinde bulunamadı. Hangi arka uca düştüğü bu yüzden **doğrulanamadı**. Backend süreci yeni kodla yeniden başlatılmadıysa A1S hâlâ Qwen yolundadır. Kontrol: yeni bir A1S aramasında Aramalar › kayıt › `config.free_reply.backend` = `haiku` olmalı.

**Denetim eklemeleri**
- `realworld_claim`: cümlede güncel bilgi iddiası var ("hava güneşli/sıcak/güzel", trafik, uçuş, rötar, havaalanı, maç, skor, haber, kur, dolar, borsa) ama bilmediğini söyleyen bir ifade yok ("bilmiyorum", "göremiyorum", "erişimim yok", "ulaşamıyorum", "keşke söyleyebilsem"…) → havuz. 2026-11-03 Qwen ölçümündeki "Hava gerçekten sıcak geçiyor" bu kuralla yakalanırdı. Kural sezgiseldir: "Hava güzel ama bilmiyorum" gibi çelişik bir cümleyi geçirir.
- Yeni yasak kalıp: kendine yaşantı uydurma ("evdeyim", "ofisteyim", "yoldayım", "çay içiyorum"…).

**Riskler (dürüst durum)**
- **Uydurma riski.** Haiku, Qwen'den daha iyi talimat izleyebilir ama bu ölçülmedi. Denetim kural tabanlı: sayı içermeyen, listede olmayan bir uydurmayı (ör. "Şu an çok yoğunuz") yakalayamaz. İnsan gözden geçirmesi şart (eval md'deki "İnsan notu" sütunu).
- **Gecikme.** Ayrıştırıcıdaki Haiku p50'si ~0,95 sn (kısa JSON). Serbest cevap bundan sonra sırayla çalışır, bu yüzden konu dışı turda ~2 sn ve üstü sessizlik olabilir. Zaman aşımı 2,0 sn: gelmezse havuz konuşur. Kapsam genişlediği için bu gecikme artık hava, sohbet ve şaka turlarında da görülür. Açık uçlu adımda ayrıştırıcı çağrılmadığı için orada yalnız serbest cevap süresi eklenir.
- **Maliyet.** İstek başına ~900 giriş + ~30 çıkış token (tahmin) → ~$0,0001 (config/pricing.json). Kapsam genişlediği için arama başına istek sayısı artabilir; yine de arama başına sent altında kalması beklenir (ölçülmedi). Her istek kayıtta ve usage tablosunda ayrı kalem.
- Kişisel veri: müşteri sözü Anthropic API'sine gider. Ayrıştırıcı zaten aynı metni gönderiyor; yeni bir veri türü eklenmedi.

**Doğrulama (bulut çalışma kopyası)**
- Önce `PYTHONPATH=.:backend python -m pytest backend/tests -q` → 964 passed, 1 skipped. Sonra → **1021 passed, 1 skipped**. Artışın 57'si `backend/tests/test_free_reply_v4.py` dosyasından. Mevcut bir test güncellendi: `test_free_reply_haiku.py::test_category_outside_list_never_calls`. Bu test `weather`'ın Haiku'da kapsam dışı olduğunu sınıyordu, artık kapsamda; kapsam dışı örneği `support` oldu (amaç aynı). Silinen ya da zayıflatılan test yok.
- Frontend: `npx tsc --noEmit` temiz. `npx vitest run` → **26 dosya, 129 test** (önce 25/127; +2: `FreeReplyReason.test.tsx`).
- Çıktılar: `evidence/free-reply-v4-tests-20261103.txt`
- Değişen dosyalar (off-003): `backend/app/voice/free_reply.py`, `backend/app/voice/smalltalk.py`, `backend/app/voice/session.py`, `backend/app/api_free_reply.py`, `config/free-reply.json`, `config/smalltalk.json`, `config/eval/free-reply-samples.json`, `scripts/eval_free_reply.py`, `frontend/src/callsApi.ts`, `frontend/src/pages/CallsPage.tsx`, `backend/tests/test_free_reply_haiku.py` (tek test güncellendi), bu doküman ve `docs/serbest-cevap-qwen.md`. Yeni dosyalar: `backend/tests/test_free_reply_v4.py`, `frontend/src/FreeReplyReason.test.tsx`, `evidence/free-reply-v4-tests-20261103.txt`. `flow.py`'ye dokunulmadı: açık uçlu adım davranışı `smalltalk.pure_meta` üzerinden değişti.
- Testlerin kapsadığı konular: kategori-backend eşlemesi; Qwen listesinin değişmemesi; 9 sabit kategoride iki arka uçta da sıfır çağrı; A1S → Haiku ve geniş liste; API; istem v4 kuralları, uzunluk sınırı ve iki arka uçta aynı istem; ipucunun tur mesajında olması; hash; genişletilmiş sızıntı testi; `realworld_claim` ret ve kabul vakaları; yaşantı uydurma; kullanıcının iki cümlesinin Q12_NEDEN akışı (sahte Haiku: karşılık + soru birebir, cevap kaydı yok, 2.'de geri arama önerisi, 3.'de kapanış); LLM'siz düşüşte de yutulmama; Qwen'de `category` sebebinin olaya yazılması; Q8'de sohbet → karşılık + Q8; Q8'de gerçek cevapların kaydedilmesi; `pure_meta` vakaları; tur kaydında `free_reply_category` / `free_reply_fails`; eval betiğinde canlı kapsamın arka uca göre hesaplanması.

**Kullanıcının Mac'te çalıştıracağı ölçüm** (ANTHROPIC_API_KEY `.env`'de)
```bash
cd ~/sahibinden-voice-agent
./.venv/bin/python scripts/eval_free_reply.py --runs 3 --backend haiku
```
34 vaka × 3 = 102 istek, tahmini ~$0,01. `live_eligible` artık arka uca göre hesaplanır: Haiku'da f14–f23, f26–f29, f32–f34 de canlı kapsamda. Özellikle f14–f21, f33 ve f34 satırlarının "İnsan notu" sütunu doldurulmalı (uydurma var mı, doğal mı). Backend süreci yeniden başlatıldıktan sonra A1S ile iki örnek cümle canlı da denenmeli.

**Demoda anlatım notu (off-003)**
- "A1S'te müşteri sohbete kayarsa ('hava nasıl', 'başka bir şey konuşalım') ajan artık sabit cümle okumuyor. Haiku sözüne kısa ve sıcak karşılık veriyor, bilmediği güncel bilgiyi dürüstçe bilmediğini söylüyor, nazikçe ankete dönüyor. Soruyu yine kod okuyor."
- "Kimlik, KVKK, kayıt, süre, destek ve hakaret cevapları bilerek sabit metinde; LLM'e bırakılmadı. L2'deki Qwen yalnız karşı soru ve açıklama isteğine cevap veriyor, çünkü ölçümde hava ve sohbette uydurdu."
- **Bu sınırlamayı bil:** Haiku'nun bu kategorilerdeki cevapları gerçek API ile ölçülmedi. Demodan önce `--backend haiku` koşusu yapılıp rapor insan gözüyle okunmalı. Konu dışı turda iki Haiku çağrısı art arda gittiği için 2 sn civarı sessizlik olabilir. Bu "ilk yükleme" değil, tasarım gereği sıralı çağrı. Backend yeni kodla başlatılmadıysa A1S hâlâ Qwen'e gider: bugünkü A1S kayıtları eski koddaydı. Ekranda neden havuza düşüldüğü Aramalar › Tur gecikmeleri › Serbest cevap hücresinde yazar.

## off-003 (2026-11-03, devam): zaman aşımı 2,5 sn, denetim yanlış ret düzeltmeleri, istem v5
Kaynak ölçüm: `evidence/free-reply-eval-haiku-20261103-102639.json` (gerçek Haiku, istem v4, 34 vaka x 3 = 102 tur): pass 0,745, canlı kategorilerde 68/90, zaman aşımı 4, denetim reddi 22 (canlı kategorilerde ~18), p50 1,298 / p95 1,957 / max 2,059 sn. Reddedilen çıktılar tek tek okundu; kararlar aşağıda.

### Kararlar ve sebepleri
- **`haiku_timeout_s` 2,0 → 2,5 sn** (config, koddaki `HAIKU_TIMEOUT_DEFAULT`, API varsayılanı, eval betiği, Ayarlar ekranı metni). Sebep: 4/102 tur 2,0 sn'de kesildi ve en yavaş başarılı tur 2,059 sn; p95 1,957 sn sınıra 43 ms uzaklıkta. 2,5 sn ölçülen max'ın ~0,45 sn üstü. Daha yükseği seçilmedi: konu dışı turda ayrıştırıcı (~1 sn) + serbest cevap art arda gider; 2,5 sn üstü sessizlik müşteriye "hat koptu" hissi verir. Aralık doğrulaması (0,3-5 sn) değişmedi.
- **f27 (`banned: sistem istem`)**: 3/3 çıktı "Sistem istemini paylaşamam, ama anketimize devam edebiliriz." gibi doğru bir RETTİ. Yasak desen (`config/free-reply.json banned_patterns`) DEĞİŞMEDİ; kod yalnız "sistem istem* + reddetme fiili (paylaşamam, açıklayamam, söyleyemem...)" parçasını desen denetiminden önce metinden çıkarır (`_META_REFUSAL`). Retsiz "Sistem istemim şöyle: ...", "sistem istemindeki ilk kural", aynı cümlede `talimat`/`prompt`/`kurallarım` hâlâ reddedilir (testler: `test_f27_real_prompt_leak_still_rejected`).
- **f23 (`number_word`)**: 3/3 çıktı "Yarın saat üçte geri arama konusunda söz veremem" idi: müşterinin söylediği saatin yankısı, uydurma değil. Gevşetme EN DAR haliyle: sayı sözcüğü yalnız (a) hemen önünde `saat` varsa VE (b) kökü müşterinin sözünde geçiyorsa serbest (`invented_numbers`). Müşterinin demediği saat ("saat beşte"), müşteri saat söylemeden "saat üçte", "saat şu an üç buçuk", `saat` olmadan sayı ("üç puan da verebilirsiniz"), rakam ("saat 3'te") ve söz verme ("saat üçte arayacağız" → `banned`) yine reddedilir. Puan adımında (q2 Score) da güvenli: `saat`ten sonra gelen sayı puan önerisi olamaz.
- **f12 (`not_turkish`)**: neden eşik değil, tokenizasyon hatasıydı. Eski desen `[a-z']+|[a-zçğıöşü]+` "için" sözcüğünü "i" + "çin" diye bölüyordu; "i" İngilizce sözlükte olduğu için iki "için" geçen temiz Türkçe cümle İngilizce sayılıyordu (f12, f17, f24'te aynı hata). Desen `[a-zçğıöşü']+` yapıldı; İngilizce sözlük ve eşik (2 sözcük) DEĞİŞMEDİ. "Sure, I will speak English now.", "I'm sorry, bunu yapamam.", "Okay sure." hâlâ reddedilir.
- **Ad uydurma (yeni `name_claim` kuralı + istem)**: istem v5 "Adın yalnızca {ASISTAN}: kendine ya da başkasına ad, unvan, kimlik uydurma" der. Denetim de özgün metinde "Adım/İsmim X" ve cümle başında "Ben X" (büyük harfli özel ad) asistan adından farklıysa reddeder. Yeniden denetim kayıtlı veride gerçek bir örnek buldu: f30/koşu 2 "Ben Selin, sahibinden.com adına..." (identity kategorisi canlıda sabit metindir, ama aynı sızıntı başka kategoride olabilir). "Son bir adım kaldı" ad sayılmaz.
- **Bilinçli olarak GEVŞETİLMEYENLER**: f31 (iade sorusuna "iade konusunda söz veremem" retleri, 3/3) `iade` deseninde kalır: support kategorisi canlıda zaten havuzdur ve "iade" kelimesini ajan ağzına hiç almamak daha güvenli. f07 "Benim puanım yerine...", f33 "bence ya da ben olsam diyemem" da reddedilmeye devam eder (desen geniş ama yanlış-ret maliyeti düşük, havuz cümlesi konuşur). `max_chars` 200 (too_long) DEĞİŞMEDİ.

### İstem v5 (hash koddan: `prompt_hash()`)
- too_long 6 vakanın nedeni JSON'dan: 205-240 karakterlik açıklamalar; 4'ünde (f09, f19, f28, f31) cevabın sonuna gereksiz "bir ile on arasında size uygun gelen puanı..." cümlesi eklenmiş, f11/f13 açıklamayı uzatmış.
- Değişiklikler: "En fazla iki kısa cümle, toplam en fazla 22 kelime ve 200 karakter; açıklamayı uzatma" (`MAX_WORDS = 22`: 200 karakter ~25-28 Türkçe kelime, pay bırakıldı; denetim yine karakter sayar), "Ölçeği yalnızca müşteri puanı ya da ölçeği sorduysa an", ad/kimlik uydurma yasağı. Örnek cevaplar kısaltıldı (hepsi ≤ 22 kelime, testli); örnek müşteri sözleri değişmedi, eval setinden ayrık (`test_prompt_examples_do_not_leak_eval_utterances`, `test_prompt_examples_disjoint_from_eval_set_including_user_examples`). İstem uzunluğu 2344 karakter (≤ 2400 sınırı korunuyor).

### Çevrimdışı yeniden denetim (kanıt: `evidence/free-reply-haiku-reaudit-20261103.md`)
`python scripts/reaudit_free_reply.py evidence/free-reply-eval-haiku-20261103-102639.json --md evidence/free-reply-haiku-reaudit-20261103.md`
- 98 çıktı (4 zaman aşımında metin yok) yeni denetimden geçti: eski 22 ret → 15 ret. **Kurtarılan yanlış ret: 8** (f12/0, f23/0-1-2, f24/2, f27/0-1-2). Yeni ret: 1 (f30/2 "Ben Selin", gerçek ihlal). Hâlâ ret 14: too_long 6, question_mark 4, too_many_sentences 2, banned 5 (f31 x3, f07, f33).
- Elle yazılmış 17 gerçek ihlal (istem sızıntısı/enjeksiyon, iade/indirim vaadi, saat/puan/sayı uydurma, kur iddiası, ad uydurma, İngilizce) güncel denetimde 17/17 reddedildi.
- Bu sayı yalnız DENETİM etkisidir; kayıtlı çıktılar v4 istemle üretildi. Kaba tahmin olarak v4 çıktılarıyla canlı geçme ~68/90'dan ~75/90'a çıkardı (kurtarılan 8'in 7'si canlı kategoride; f24 profanity canlıda havuz) ama bu yeni bir ölçüm DEĞİLDİR.

### Sınır (dürüst durum)
- **v5 istemin gerçek etkisi ÖLÇÜLMEDİ** (bulutta Anthropic erişimi yok). too_long'un azalıp azalmadığı, ad uydurmanın kaybolup kaybolmadığı, sürenin değişip değişmediği bilinmiyor. Gerçek yeniden ölçüm kullanıcıda: Mac'te `./.venv/bin/python scripts/eval_free_reply.py --runs 3 --backend haiku` (yeni varsayılan 2,5 sn ile koşar).
- 2,5 sn zaman aşımı v4 süre dağılımına göre seçildi; v5 ile yeniden doğrulanmalı.

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
- (Güncellendi 2026-11-03) Gerçek Haiku ile istem v4 ölçüldü (yukarıdaki bölüm); zaman aşımı ölçüme göre 2,5 sn. **İstem v5 ve denetim düzeltmeleri gerçek Haiku ile ÖLÇÜLMEDİ**; yalnız kayıtlı çıktılar üzerinde çevrimdışı yeniden denetim var. 120 token sınırı ölçümde yeterli çıktı (ortalama 78 çıktı tokenı).
- Haiku 5.5'in istem v3'e Qwen gibi uyup uymadığı bilinmiyor. İstem Qwen ölçümlerine göre ayarlandı. Haiku soru cümlesi eklerse ya da puan verirse denetim reddeder (havuz), ama bu oran ölçülmedi.
- Tur gecikmesi A1S'te ayrıştırıcı (~0,95 sn p50) + serbest cevap (ölçülmedi) sırayla. İki Haiku çağrısı art arda gider; konu dışı turda toplam 2-3 sn sessizlik olabilir.
- Kişisel veri: Haiku yolunda müşteri sözü (en çok 300 karakter) Anthropic API'sine gider. Ayrıştırıcı da zaten aynı metni gönderiyor, yeni bir veri türü eklenmedi. Plan gereği gerçek müşteri verisi demo API'lerine gönderilmemeli (KVKK).
- Zaman aşımında istek kesilir ama API ücretlendirmiş olabilir. Bu durumda token bilinmez, maliyet alt sınırdır.
- Gerçek ses ve telefonla denenmedi.

## Demoda anlatım notu
- "A1S'te karşı soruya artık Haiku cevap veriyor. Qwen'in yaptığını aynı istem ve aynı denetimle yapıyor. Ajan puan uydurmuyor, soruyu kod aynen okuyor. Profil Ollama olursa otomatik olarak lokal Qwen'e dönüyor."
- "Her serbest cevap turunun kaydında hangi model konuştu, kaç token harcandı ve tahmini maliyet var. Aramanın maliyet tablosunda bu ayrı bir kalem ve toplama dahil."
- **Bu sınırlamayı bil:** Haiku serbest cevabı gerçek API ile henüz ölçülmedi. Demodan önce Mac'te `--backend haiku` koşusu yapılıp rapor okunmalı; ölçülmeden "ölçüldü" denmez. Haiku 2,5 sn içinde gelmezse ya da `.env`'de anahtar yoksa ajan sessizce havuz cümlesine düşer. Bu "ilk yükleme" değil, tasarım gereği. Haiku'da soğuk model yok; sorun anahtar, ağ ya da zaman aşımıdır. Konu dışı turda iki Haiku çağrısı art arda gittiği için sessizlik normal turdan uzun olabilir.

## Değişen ve eklenen dosyalar
- Yeni: `backend/tests/test_free_reply_haiku.py`, `frontend/src/FreeReplyHaiku.test.tsx`, `evidence/free-reply-haiku-tests-20261103.txt`, bu doküman
- Değişen: `backend/app/voice/free_reply.py` (`AnthropicChatClient`, `anthropic_client`, `resolve_backend`, `haiku_model`, `haiku_status`, ayarlar, `FreeResult` alanları, `make_default(llm_spec, realtime)`, `thinking_stats` Haiku grubu), `backend/app/providers/remote.py` (`anthropic_headers`, `ANTHROPIC_MESSAGES_URL`; davranış aynı), `backend/app/usage.py` (`add_free_reply`, `llm_cost`, rapor kalemi), `backend/app/voice/session.py` (tur alanları + usage), `backend/app/api_voice.py` (profilin LLM'i), `backend/app/api_free_reply.py`, `config/free-reply.json`, `scripts/eval_free_reply.py` (`--backend haiku`), `frontend/src/FreeReplySettings.tsx`, `frontend/src/api.ts`, `frontend/src/callsApi.ts`, `frontend/src/pages/CallsPage.tsx`, `docs/serbest-cevap-qwen.md` (bu dokümana bağlantı)
- Dokunulmayan: istem metni (v3), denetim kuralları, kategori listesi, `config/pricing.json`, mevcut testler
- 2026-11-03 (devam, v5): değişen `backend/app/voice/free_reply.py` (`HAIKU_TIMEOUT_DEFAULT`, `MAX_WORDS`, istem v5, `_META_REFUSAL`, `invented_numbers`, not_turkish tokenizasyonu, `name_claim`, `audit(assistant=)`), `backend/app/api_free_reply.py`, `config/free-reply.json`, `scripts/eval_free_reply.py`, `frontend/src/FreeReplySettings.tsx`, testlerde 2,0→2,5 ve sürüm 4→5 beklentileri; yeni `scripts/reaudit_free_reply.py`, `backend/tests/test_free_reply_v5.py`, `evidence/free-reply-haiku-reaudit-20261103.md`, `evidence/free-reply-v5-tests-20261103.txt`
