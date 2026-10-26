# Progress Log

<!--
This filename is kept for compatibility with the course examples. The file is
agent-agnostic: Codex, Claude Code, OpenHands, and other coding agents can use
it. Read it at session startup and update it before handoff through the
repository's agent instructions; no agent updates it automatically.
-->

This is a generic repository-local session progress log. The
`claude-progress.md` filename is a historical course convention, not a
Claude Code requirement. Any coding agent can use it when the repository's
instructions tell it to read the file at startup and update it before handoff;
agents do not update it automatically.

## Current Verified State

- Repository root: ~/sahibinden-voice-agent (git, main)
- Standard startup path: `./init.sh` (bağımlılık + testler + hızlı model kontrolü); `scripts/dev.sh` Lab'i başlatır (http://localhost:5173)
- Standard verification path: `python -m pytest -q backend`, `npm --prefix frontend test`, `npm --prefix frontend run e2e` (build sonrası), `scripts/healthcheck.py`
- Passing: setup-001, lab-000, core-003, lab-006, lab-002, lab-001, norm-007, eval-llm, core-001, lab-003, core-002, core-004 (12 / 51)
- Current highest-priority unfinished feature: core-004 (anket yürütme, FlowDriver ile büyük ölçüde var; gerçek model ölçümü eksik) ve core-005/lab-004
- Current blocker: yok. Doğrulanmamış: mikrofon düğmesi, BuzzASR indirme, telefon turu (8 kHz) gerçek modelle, gerçek insan dinlemesi, normalize metnin gerçek TTS ile dinlenmesi, Mac tarayıcısında normalize önizleme

## Session Log

### Session 001

- Date: 2026-10-22
- Goal: Plan -> feature_list.json, lokal model ortamının doğrulanması (setup-001)
- Completed: setup-001 passing
- Verification run: `FULL_CHECK=1 ./init.sh` -> 4/4 PASS
- Evidence captured: evidence/healthcheck-20261022-180150.json
- Commits: 1e16b86..(bu commit)
- Files or artifacts updated: feature_list.json, init.sh, scripts/healthcheck.py, requirements.txt, .gitignore
- Known risk or unresolved issue: Chatterbox MPS'te RTF 6.5 (gerçek zamandan ~6 kat yavaş); "forcing EOS" uyarısı verdi ama cümle tam okundu (dinlenerek doğrulandı). Repo henüz GitHub'a gönderilmedi.
- Next best step: lab-000 Lab uygulaması iskeleti

### Session 002

- Date: 2026-10-22
- Goal: lab-000 Lab uygulaması iskeleti
- Completed: lab-000 passing (Mac ./init.sh log'u evidence/init-20261023-095125.log, Mac tarayıcı doğrulaması, bulut e2e)
- Verification run: pytest (2), vitest (4), vite build, Playwright e2e (1), init.sh baseline, dev.sh proxy — hepsi geçti (bulut çalışma alanında, aynı kaynak)
- Evidence captured: evidence/lab-000-verification.json, evidence/lab-000-e2e.png, evidence/lab-000-mac-verification.json, evidence/healthcheck-20261022-193554.json, evidence/lab-000-mac-*.jpg (Mac tarayıcı doğrulaması)
- Commits: (bu commit)
- Files or artifacts updated: backend/, frontend/, scripts/dev.sh, init.sh, requirements.txt (pytest), .gitignore, feature_list.json
- Known risk or unresolved issue: E2E için Mac'te `npx playwright install chromium` gerekir. Repo GitHub'a henüz gönderilmedi.
- Next best step: core-003 sağlayıcı soyutlaması (Lab ekranlarının ve ajanın ortak model katmanı)

### Session 003

- Date: 2026-10-23
- Goal: lab-000'ı Mac log'uyla kapatmak; core-003 sağlayıcı soyutlaması ve profiller
- Completed: lab-000 passing (evidence/init-20261023-095125.log); core-003 passing
- Verification run: pytest 13, vitest 7, build (bulut); Mac'te gerçek modellerle /api/profiles/{L1,L2,A1,A2,L5} çağrıları, arayüzde profil seçici
- Evidence captured: evidence/core-003-verification.json, evidence/core-003-mac-*.jpg
- Commits: a75644e, (bu commit)
- Files or artifacts updated: backend/app/providers/, backend/app/profiles.py, backend/app/api_profiles.py, config/profiles.yaml, .env.example, frontend/src (ProfileContext, ProfileSelector, ActiveProfile), testler
- Known risk or unresolved issue: gemma4:e4b, gpt-oss:20b, gemma4:12b Ollama'da yok (L1/L4/L5 LLM'i çalışmaz). Qwen soğuk yükleme ~67 sn. A2 realtime sağlayıcısı yok (lab-003). uvicorn --reload dosya değişince uzun süren isteği keser.
- Next best step: lab-002 STT test ekranı (sağlayıcı katmanını kullanır)

## Session 004 (2026-10-23)
- lab-006 passing: L2 (mlx-whisper + Qwen3 instruct + EMA) Hazırla 44.9 sn -> Sıcak; sıcak çağrılar STT 0.76 / LLM 0.12 / TTS 0.06 sn; L1 soğuk -> 409 profile_not_warm; 5.8 dk sonra modeller bellekte (load_seconds=0).
- Karar: canlı profillerde TTS = EMA; Chatterbox 36 GB'ta Qwen3 30B ile birlikte çalışamıyor, yalnızca TTS stüdyosunda tek başına (lab-001).
- Bilinen sınırlama: boşta sonrası ilk LLM çağrısı 2.8 sn (OS sayfalama, swap ~16 GB). Aday: keep-warm ping.
- Sıradaki: lab-002 (STT test ekranı), lab-001 (TTS stüdyosu + kör dinleme).

### Session 004 devamı (lab-002)
- Yapıldı: STT test backend (api_stt, wer, stt_runs), arayüz (SttPage, wav.ts), yalnızca-STT Hazırla (?components=stt), bulutta pytest 44 / vitest 15 / build. Mac'te mlx-whisper ile gerçek koşu: 0.72 sn, RTF 0.13, kaydet/aç/ses çalma doğrulandı. Kanıt: evidence/lab-002-verification.json (kısmi).
- Kalan: (1) ikinci model ile yan yana koşu, (2) mikrofon kaydı elle denemesi, ardından lab-002 passing.
- Ayrıca CLAUDE.md'ye yeni kural eklendi: kararlar ve sınırlamalar Demo Sunumu'na, PoC Planı dokümanı oturum sonunda güncellenecek (lab-002 kapanınca yapılacak).

### Session 004 sonu (lab-002 passing)
- lab-002 passing: mlx-whisper vs Deepgram nova-3, WER ve süre yan yana, kayıt/aç. Kanıt: evidence/lab-002-verification.json.
- Ek düzeltmeler: yalnızca-STT Hazırla (?components=stt), WER'de kesme işareti, init.sh için localStorage ortam sorunu, vite include .test.ts, healthcheck Ollama model seçimi (L2 modeli).
- Doğrulanmamış: mikrofon kaydı düğmesi, BuzzASR (indirme gerekli: MODELS_ONLINE=1).
- Sıradaki: lab-001 TTS stüdyosu (Chatterbox tek başına yüklenecek).

### Session 005 sonu (lab-001 passing)
- lab-001 passing: 10 cümle x 3 model (EMA, ElevenLabs flash v2.5, Chatterbox) = 30/30 klip; ilk ses + RTF loglandı; klipler -22..-20 dBFS; kör dinleme (model adı yok, dinleyiciye göre farklı sıra), puanlar ve CSV. Kanıt: evidence/lab-001-verification.json (oturum 20261023-164026-d6f5b2).
- Ölçümler: EMA ilk ses 0.19 sn / RTF 0.05; ElevenLabs 0.57 sn / RTF 0.15; Chatterbox (tek başına) 10.8 sn / RTF 1.85.
- Düzeltmeler: stüdyo Hazırla yalnızca TTS bileşenini ısıtır; ANTHROPIC_WORKSPACE_ID başlığı (anahtar çalışma alanına bağlıysa); BuzzASR için scripts/fetch_models.py ve açıklayıcı hata; yarım kalan oturum 'interrupted'.
- Doğrulanmamış/açık: gerçek insan dinlemesi yapılmadı (puanlar otomatik test); telefon turu Mac'te gerçek modelle denenmedi; backend bir kez Chatterbox üretirken durdu (neden bilinmiyor); mikrofon düğmesi; BuzzASR indirme; ANTHROPIC_WORKSPACE_ID gerekli (LLM'li A1 için).
- Sıradaki: norm-007 (Türkçe sayı/tarih normalizasyonu) veya eval-llm; kör dinleme gerçek dinleyicilerle yapılacak.

### Session 006 sonu (norm-007 passing)
- norm-007 passing: backend/app/trnorm.py (bağımlılıksız, kurala dayalı). Kapsam: sayı, para (kuruş, 'milyon TL'), tarih, ISO tarih, saat, telefon (gruplu: "sıfır beş yüz otuz iki, yüz yirmi üç, kırk beş, altmış yedi"), yüzde, oda (3+1), m²/km/kg, sıra sayısı, eksi; ek uyumu para ve birimlerde (TL'ye -> liraya). Kanıt: evidence/norm-007-verification.json, evidence/norm-007-preview.png.
- Entegrasyon: POST /api/tts/normalize (önizleme), stüdyoda 'Metni okunur Türkçeye çevir' (varsayılan açık; oturumda normalize_text / text_normalized / spoken), dinleyiciye özgün cümle gösterilir. Not: session['normalize'] lab-001'in ses seviyesi alanı olduğundan metin alanları ayrı adlandırıldı.
- Doğrulama: bulutta pytest 144, vitest 24, build, Playwright e2e 2 (stüdyo önizlemesi gerçek backend + SPA). Mac'te modül gerçek dosyalarla çalıştırıldı.
- Doğrulanmamış/açık: Mac backend kapalıydı, Mac tarayıcısında önizleme denenmedi; normalize edilmiş metin EMA/ElevenLabs ile dinlenerek doğrulanmadı; '3.5' noktalı ondalık, yazıyla sayılar, genel ek üretimi (scn-008) kapsam dışı; backend'in yeniden başlatılması gerekir.
- Varsayılan stüdyo cümle seti artık ham '23.10.2026', '1.500 TL', '0532 123 45 67' içerir (normalizasyon demosu için).
- Sıradaki: eval-llm (30 örnek cevapla LLM fonksiyon çağrısı testi).

### Session 006 düzeltme (telefon okunuşu)
- Geri bildirim: EMA ham '0532 123 45 67' metnini doğru okuyor; trnorm'un rakam rakam çevirisi ('sıfır beş üç iki, bir iki üç…') daha kötü sonuç veriyordu. Karar değişti: telefon artık gruplu okunur ('sıfır beş yüz otuz iki, yüz yirmi üç, kırk beş, altmış yedi'; '+90' -> 'artı doksan'; grup içi baştaki sıfır korunur).
- Doğrulama: pytest 145, vitest 24, build, Playwright e2e 2 (bulut). Açık: EMA/ElevenLabs ile dinleyerek A/B (ham vs normalize) yapılmadı; EMA'nın kendi ön işlemesi olabilir, telefonda ham metin daha iyi çıkarsa sağlayıcı bazında 'telefonu çevirme' seçeneği eklenebilir.

### Session 007 (eval-llm, in_progress)
- Yapıldı: 30 örnekli veri seti (config/eval/llm-samples.json), backend/app/llm_eval.py, backend/app/api_eval.py (/api/eval/llm/{models,samples,run,runs}), 'LLM testi' ekranı (/llm), scripts/eval_llm.py (terminal + kanıt dosyası).
- Karar: native tool-calling yerine JSON çıktı sözleşmesi (LLMProvider.complete tüm profillerde aynı, adil kıyas). Kesin doğrulama: "9" metni sayı sayılmaz; bool sayı değil. 'Doğru dal' = LLM çıktısından deterministik flow motorunun seçeceği dal; geçersiz çıktı = dal yok (motor yeniden sorar).
- Doğrulama (bulut, sahte LLM): pytest 189, vitest 28, build, Playwright 4. Mükemmel sahte model %100; özensiz model (sayıyı metin yazan) normalize %50; çöp çıktı %0; bozuk model hata izole.
- ENGEL: bulut oturumundan Mac'teki Ollama/Anthropic'e ulaşılamıyor; gerçek model koşusu yok, o yüzden eval-llm 'passing' DEĞİL.
- Kullanıcı eylemi: Mac'te `./.venv/bin/python scripts/eval_llm.py L2 --limit 5` sonra `scripts/eval_llm.py L2 A1` (anahtar .env'de; L1/L4 için `ollama pull gemma4:e4b` / `gpt-oss:20b`). Çıktı evidence/eval-llm-*.json; bana verin, passing'e çekeyim.
- 2026-10-24 gerçek koşu (Mac): L2 qwen3:30b 30 örnek -> JSON %100, normalize %96, dal %97, tam %97, p50 0.45 / p95 0.61 sn. Tek hata s12 'hı hı' (model unclear dedi). Kanıt: evidence/eval-llm-20261024-130722.json.
- A1 claude-haiku-5-5: 'temperature is deprecated' 400 -> AnthropicLLM düzeltildi (04d9340). Kalan: `scripts/eval_llm.py L2 A1` yeniden; ardından eval-llm passing. L1/L4 modelleri Ollama'da yok.

### Session 007 sonu (eval-llm passing)
- eval-llm passing: Mac gerçek koşu (30 örnek) L2 qwen3:30b tam doğru %97 (p50 0.43 sn); A1 claude-haiku-5-5 tam doğru %97 (p50 0.94 sn, JSON %97). İkisi de Faz 1 kapısının (>= %90) üstünde. Kanıt: evidence/eval-llm-20261024-131946.json.
- Ortak hata: s12 'hı hı'. Haiku bu örnekte boş çıktı verdi (JSON yok), qwen 'unclear' dedi. Beklenen değer değiştirilmedi.
- Doğrulanmamış/açık: L1/L4/L5 LLM'leri (Ollama'da yok); gürültülü STT çıktısıyla ölçüm; native tool-calling; 30 örnek istatistiksel garanti değil.
- Sıradaki: core-001 (tarayıcıdan mikrofonla konuşma).

### Session 007 eki (eval-llm, L1/L4/L5)
- Mac gerçek koşu, 30 örnek: L5 gemma4:12b %100 (p50 0.80 sn); L1 gemma4:e4b %77 (p50 0.22 sn; evet/hayır'ı "true" metni yazdı, kesin doğrulamada geçersiz); L4 gpt-oss:20b %70 (p50 3.3 sn; 9 örnekte boş çıktı). Kanıt: evidence/eval-llm-20261024-133017.json, -133504.json.
- %90 kapısını geçenler: L2 Qwen3 30B (%97), A1 Haiku 5.5 (%97), L5 gemma4:12b (%100). Geçemeyenler: L1, L4.
- Doğrulanmamış: gpt-oss boş çıktısının nedeni (muhakeme bütçesi şüphesi); L1 için gevşek ayrıştırıcı denenmedi (ölçüm gevşetilmedi). L5 sesi doğrudan alan profil olduğu için bu metin testi onu tam temsil etmez (core-010).

### Session 007 sonu (core-001 passing)
- core-001: Playground'da mikrofonla ajanla konuşma. Backend: backend/app/voice/{vad,session,rtc}.py + api_voice.py (/api/voice/offer|sessions|{id}); frontend: src/voice.ts, src/pages/PlaygroundPage.tsx (Başlat/Durdur, durum, transkript, tur gecikmesi, söz kesme sayacı, 409 -> Hazırla ipucu). Karar: Pipecat yerine aiortc (docs/adr/0002-webrtc-aiortc.md).
- Doğrulama (bulut): pytest 206, vitest 31, build, Playwright 5 — yeni e2e gerçek Chromium + sahte mikrofon WAV + gerçek WebRTC: bağlanır, selam, konuşma STT'ye ulaşır, ajan sesi alınır, Durdur kapatır. Kanıt: evidence/core-001-playground.png.
- Doğrulanmamış: gerçek mikrofon ve gerçek modellerle gecikme (Faz 1 p50 < 1,2 sn), hoparlörde yankı, gürültülü ortamda enerji tabanlı VAD (Silero sonraki adım), 3'ten fazla oturum.
- Kullanıcı eylemi (Mac): `pip install aiortc` (requirements.txt'e eklendi), backend'i yeniden başlat, /playground'da L2'yi Hazırla, kulaklıkla Başlat.

### Session 008 (lab-003, in_progress)
- Referans: kullanıcı demo firmasının senaryo panelini (sahibinden-demo.intalkive.com/senaryolar) kendi oturumuyla açtı; /api/scenarios yanıtından Anket senaryosu birebir alındı (33 adım, dallar, 11 sonuç, 16 yer tutucu) -> config/scenarios/anket.json. Parola repoya/dokümana yazılmadı.
- Yapıldı: backend/app/scenario.py (veri, doğrulama, yer tutucu, next_step), api_scenarios.py (/api/scenarios list/detay/PUT-DELETE metin/preview), 'Senaryolar' ekranı (/scenarios, 7 ekran), testler (pytest 220, vitest 35, Playwright 6).
- Karar: akış (dallar) sabit, yalnız metin düzenlenir (referansla aynı); metin düzenlemeleri data/scenario-overrides/. Genel çıkışlar (ret, aranma yasağı, sessiz hat) dal tablosunda görünmez, motorda GLOBAL_EXITS.
- Hata ayıklama: e2e'nin gerçek data/ klasörüne düzenleme yazması (test sızıntısı) -> lab sunucusu artık SVA_DATA_DIR=/tmp/sva-lab-e2e ile açılıyor.
- Açık: Playground'un senaryoyu akış motoruyla yürütmesi (aktif düğüm, çıkarılan cevaplar, telefon filtresi), Welcome Call senaryosu (referans API yanıtı kesildi), realtime profiller. Passing DEĞİL.

### Session 008 sonu (lab-003 passing)
- Playground senaryo modu: oturum FlowDriver ile yürür (backend/app/voice/flow.py, ADR 0003). Olaylar: node (aktif düğüm), understood, answer, outcome, finished, phone_filter. API: /api/voice/offer {scenario, phone_filter, values}, POST /api/voice/{id}/phone-filter, datachannel komutu {type:'phone_filter'}. Telefon filtresi: voice/phone.py (bant sınırı, müşteri ve ajan sesi).
- Hata bulundu/düzeltildi: açık uçlu cevaplar doğrulamadan geçemiyordu (check_value OpenText eksikti) — test yakaladı. Fake LLM değer kuralına göre cevap veriyor (SVA_FAKE_PROVIDERS).
- Doğrulama (bulut): pytest 232, vitest 37, build, Playwright 7; kanıt evidence/lab-003-scenarios.png, lab-003-playground.png.
- Doğrulanmamış: gerçek mikrofon + gerçek modellerle anket tamamlama, STT gürültüsünde cevap çıkarma, sessiz hat, realtime profiller (A2/A3), Welcome Call senaryosu.
- Kullanıcı eylemi (Mac): backend yeniden başlat, Hazırla L2, /playground'da senaryo seçili Başlat; kulaklık kullan. Tamamlanan anketin cevapları data/voice-sessions/*.json içinde (flow.answers, flow.path).

### Session 008 eki (feature list)
- Yeni özellik core-011 (should, öncelik 21): Realtime profiller A2/A3'ün Playground'da desteği (hibrit: model sesi yönetir, fonksiyon çağrısıyla cevap bildirir, flow motoru akışı yürütür). Nedeni: kademeli Playground STT/LLM/TTS aşamalarına bağlı; realtime modeller speech-to-speech olduğu için ayrı adaptör gerekir. Sonraki öncelikler 1 kaydırıldı (toplam 51 özellik). Henüz başlanmadı.

### Session 009 (core-002 passing)
- Söz kesme: ajan konuşurken 160 ms (BARGE_FRAMES=8) kesintisiz yüksek ses -> çıkış kuyruğu boşaltılır; olayda cut_ms. Ölçüm: aiortc istemcisi 327-342 ms, gerçek Chromium 340 ms (sınır 500 ms); BARGE_FRAMES 10 iken ~380 ms'ydi, tarayıcı payı için 8'e indirildi. Kanıt: evidence/core-002-measurements.json.
- Söz sırası (Smart Turn, PoC): düğüme göre bitiş sessizliği (600 / açık uçlu 1200 ms); yarım cümlede (bağlaç/dolgu/virgül) 1,5 sn bekle + devam gelirse sesleri birleştirip yeniden çöz; süre dolarsa cevapla. Arayüz göstergeleri eklendi. Karar ve sınırlar: docs/adr/0004-turn-taking.md.
- Doğrulama: pytest 252 (yeni test_turntaking.py 20), vitest 38, Playwright 8 (yeni: tarayıcıda söz kesme).
- Doğrulanmamış: gerçek insan sesi/STT/hoparlör (yanki), gürültü, öğrenilmiş turn modeli yok; yarım cümlede ek gecikme p50 hedefinin dışında.
- Kullanıcı eylemi (Mac): kulaklıkla Playground'da ajan konuşurken araya girin ("söz kesme: n · son: X ms" görünür); "evet ama" deyip 1 sn susup devam edin ("devamını bekliyor" çıkmalı).

### Session 010 (core-004 passing)
- Eksik olan, FlowDriver birim testlerinin ses oturumu seviyesinde kanitiydi: backend/tests/test_survey_e2e.py (2 test) konusma sesi -> VAD -> STT -> akis -> kaydedilen oturum JSON'u zincirini iki dalda kosar (A: 18 turda tamamlandi; B: iki tekrar sorma sonra gorusmeyi_hatirlamiyor). Cevap tipleri (bool/int/saniye/metin) kayitta dogrulanir.
- Dogrulama: pytest 254 gecti (bulut ortami sifirlanmisti, bagimliliklar pip ile yeniden kuruldu; backend/requirements.txt bulutta yok, Mac'te var).
- Dogrulanmamis: gercek LLM ile cikarim (betikli), gercek mikrofon, Welcome Call senaryosu, sessiz hat.

### Session 011 (Welcome Call senaryosu)
- Referans panel oturumu kapaliydi; kullanici yeniden giris yapinca /api/scenarios tam (63 KB) cekildi. Onceki ham veri 50.000 karakterde kesikti; eksik kuyruk eklenip JSON dogrulandi (birlestirme sonrasi json.loads basarili).
- config/scenarios/welcome.json: 'Welcome Call · Premium Plus Magaza', 24 adim, 9 sonuc, ornek profil (taahhutlu, 2FA kapali, afis-branda var). S.validate() hatasiz.
- Yeni adim turu CheckIn (flow.py): bool cevap; soru varsa not alinir (QUESTION_NOTED), cevap uretilmez; belirsizse 2 tekrar sonra atlanir. Etiket 'Bilgilendirme + soru' (Senaryolar + Playground).
- Dogrulama: pytest 265 (yeni test_welcome.py 11), vitest 38, tsc temiz, Playwright 10 (yeni: Welcome sekmesi, Playground welcome).
- Not: bulut ortami sifirlanmisti; e2e icin LAB_PYTHON=python3 ve 'npm run build' gerekti (webServer dist'ten sunar).
- Dogrulanmamis: gercek LLM ile CheckIn ayrimi, gercek mikrofonla tam Welcome Call, profil-bagimli dallar (taahhutsuz profil adimlari 'applicable:false', profil secimi UI'si yok), sessiz hat.

### Session 012 (core-011 realtime profiller — BLOCKED: canli dogrulama)
- Hibrit realtime hatti kuruldu (ADR 0005): voice/realtime.py (OpenAIRealtime, GeminiLive, FakeRealtime, RealtimeVoiceSession), FlowDriver.handle_structured (ayni sik tip denetimi), /api/voice/offer realtime dali, Playground realtime gecikme tablosu, profil durumu (realtime hazir = anahtar var).
- Dogrulama (bulut): pytest 286 (yeni test_realtime.py 22), vitest 39, Playwright 11 (yeni: realtime profil Chromium e2e).
- BLOCKER: OpenAI/Google API'lerine bulut ve Mac VM'inden erisim yok. Canli dogrulama icin kullanici eylemi: Mac'te (VM disinda) `.venv/bin/python scripts/realtime_smoke.py` calistirip evidence/core-011-live-smoke.json ve data/realtime-smoke/*.wav ciktisini paylasmak (ses dosyalarini dinleyip Turkce kaliteyi degerlendirmek). Sonra core-011 kalan maddeleri: A3 Turkce guvenilirlik, A2/A3 vs L2 gecikme karsilastirmasi.
- Yan degisiklik: e2e fixture'a RT profili eklendi; spec varsayilan profili V1'e sabitler.

### Session 013 (core-011 canli smoke sonucu — hala BLOCKED, kismen dogrulandi)
- Kullanici canli smoke'u Mac'te calistirdi. Ilk calisma: websockets eksikti (venv'e kuruldu). Ikinci: A2 fonksiyon cagrisinda anahtar adini 'answer' yazdi (0/8) -> parse_tool_args'a alias toleransi + test (pytest 287), commit 57d62b9. Ucuncu calisma: A2 8/8, A3 8/8 (tip gecerli + dogru).
- Olcumler (tek atis): ilk ses A2 0.74 sn / A3 0.89 sn; AYNEN SOYLE sadakati A2 1.0 / A3 0.976; fonksiyon cagrisi turu A2 0.64-0.83 sn, A3 0.41-0.91 sn. Kanit: evidence/core-011-live-smoke.json.
- Gozlem: A2 anahtar adi sapmasi calismalar arasi degisti (non-deterministik); tolerans kalici, gercek akis testinde tekrar izlenmeli.
- Dogrulanmamis/kalan: Turkce ses kalitesi (WAV dinleme - kullanici), Playground'da gercek A2/A3 ile tam senaryo, A2/A3 vs L2 5 aramalik gecikme, 8 vakalik kucuk orneklem.

### Session 014 (core-013 ses kaydı — passing)
- Kullanıcı isteği: konuşmaların ses kayıtları saklanabilsin. Kayıt taşıma katmanında (rtc.py): ham mikrofon (sol) + tarayıcıya giden ajan çerçeveleri (sağ) -> stereo 16 kHz WAV, kapanışta oturum JSON'unun yanına yazılır; JSON'a audio meta alanı. Varsayılan kapalı (offer.record). GET/DELETE /api/voice/recordings/<id>; Playground onay kutusu + oynatıcı + sil.
- Doğrulama (bulut): pytest 292 (yeni 5), vitest 40 (yeni 1; mevcut 3 beklentiye record:false eklendi, davranış değişmedi), tsc temiz, Playwright 12 (yeni: kayıt stereo WAV, iki kanalda enerji, oynatıcı, silme).
- Ek inceleme (kod değişikliği YOK): kayıtlı L2 oturumu 3568fd3933eb ve diğerleri incelendi. Bulgular: (a) giris adımında 'Dinlemek istemiyorum' / 'Müsaade değilim' LLM'de refuse çıkıp görüşmeyi kapatıyor (kapanis_ret) — doğru yorum: dinleme tercihi = devam; (b) STT hataları ('Katılman', 'Buyurun davetin', 'Ben adım') off_topic sayılınca 'Sorunuzu not aldım' yersiz söyleniyor; (c) 'olabilir' evet/hayır sorusunda anlaşılamıyor. core-012 beklemede; (a)-(c) core-012 ölçüm setine örnek olarak alınacak, STT kelime hataları lab-002/STT kalitesi konusudur.
- Dikkat: Mac çalışma ağacında kullanıcıdan gelen commit'lenmemiş backend/app/trnorm.py ve backend/tests/test_trnorm.py değişiklikleri var; bu commit'e katılmadı.
- Doğrulanmamış: gerçek mikrofonla kaydı dinleme; üretim için şifreleme/erişim/saklama süresi.
