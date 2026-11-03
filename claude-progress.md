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
- Passing: setup-001, lab-000, core-003, lab-006, lab-002, lab-001, norm-007, eval-llm, core-001, lab-003, core-002, core-004, core-013, core-008 (14 / 54)
- Blocked: core-011 (A3 Türkçe kalite dinleme + A2/A3 vs L2 gecikme; kullanıcı), core-014 (gerçek ses kaydı + modeller; kullanıcı)
- Current highest-priority unfinished feature: core-012 (kullanıcı kararıyla beklemede; eval-llm üretim prompt'unu ölçmüyor), sonra core-005/core-006, lab-004
- Partial (not_started ama kısmen yapıldı, ayrıntı feature_list notes): scn-001/004/005/006/007, sim-001/002/003/004, eval-003, core-005/006/009
- Current blocker: core-011 ve core-014 kullanıcı eylemi bekliyor (canlı/gerçek ses doğrulaması). Doğrulanmamış: mikrofon düğmesi, BuzzASR indirme, telefon turu (8 kHz) gerçek modelle, gerçek insan dinlemesi, normalize metnin gerçek TTS ile dinlenmesi, Mac tarayıcısında normalize önizleme

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

### Session 015 (öneri 1, 2, 4: KVKK/STT düzeltmeleri, core-014, STT karşılaştırma araçları)
- (1) giris adımına llmHint (anket.json) ve flow.py INTENTS/refuse/unclear/off_topic metinleri; build_messages adıma özel kuralı ekler. Birim test: prompt içeriği + 'devam' seçimiyle KVKK atlanır. GERÇEK LLM ile doğrulanmadı; realtime hatta iletilmiyor.
- (2) feature_list: core-014 (STT kelime hataları, not_started) eklendi; core-012 notlarına oturum örnekleri eklendi.
- (4) Karşılaştırma araçları: /api/stt/compare channel (mix/left/right) ve prompt alanları (aynı MLX Whisper modeli ipuçsuz/ipuçlu yan yana); MlxWhisperSTT initial_prompt seçeneği (varsayılan kapalı); STT test ekranı Kanal + Alan ipucu; WAV artık çevrilmeden gider (toWav kanalları ortalayıp stereo seçimi bozuyordu). Karşılaştırmanın KENDİSİ yapılmadı: gerçek model ve gerçek kayıt Mac'te gerekli (önceki oturumda ses kaydı yoktu).
- Doğrulama (bulut): pytest 297, vitest 41, tsc temiz, Playwright 12/12. Bir kez düşen kayıt e2e testi: senaryo listesi yarışı (testte), bekleme eklendi, 8/8.
- Kullanıcı adımı: Mac'te npm run build + backend yeniden başlat; Playground'da kayıt aç, 2-3 görüşme yap; STT test ekranında WAV yükle, Kanal=Sol, modelleri seç, ipucu yaz, Karşılaştır; sonuçları paylaş.

### Session 016 (feature_list envanteri)
- not_started görünen 40 madde Haiku yardımcı oturumuyla tarandı; ana bulgular kodda elle doğrulandı. Sonuç: core-008 -> passing (gerçek test araması: evidence/core-008-session-3568fd3933eb.json, logs/provider-calls.jsonl; JSONL yerine çağrı JSONL'ı + oturum JSON'u olarak karşılandı, sapma notlandı); core-014 -> blocked (kullanıcı kaydı/Mac gerekir); 13 kısmi madde not_started kaldı ama notes alanına mevcut kapsam ve eksikler yazıldı (scn-001/004/005/006/007, sim-001/002/003/004, eval-003, core-005/006/009). Kalan 25 madde gerçekten başlanmamış.
- Durum: 14 passing / 2 blocked / 38 not_started (54). Açık karar: core-009 (kayıt 8 kHz filtreli mi, 16 kHz ham mı).
- Not: yardımcı oturum buluttaki kopyayı taradığı için bazı kanıt dosyalarını (lab-006 ADR, evidence/*.json) bulamadı; Mac'te mevcutlar (docs/adr/0001, evidence/).

## Session 017 - core-011 gecikme karsilastirma araci (2026-10-26)
- Eklendi: backend/app/voice/latency_report.py, scripts/session_latency.py, test (test_realtime.py). Olcmez, kayitli oturumlari ozetler.
- Eldeki gercek veri yetersiz (<5 arama): A1 3.55s, A2 2.41s, L2 1.43s, L3 3.14s p50; hepsi 1.2s hedefi disinda. Kanit: evidence/core-011-latency-compare.json.
- Acik: A3 Playground'da fonksiyon cagrisi 0 (oturum 796d1ea27377); A2 8.8s aykiri tur; Turkce ses kalitesi dinlemesi; 5'er aramalik olcum. core-011 BLOCKED kalir.

## Session 018 - core-015 giris esigi / mikrofon hassasiyeti (2026-10-27)
- Kullanici sikayeti: en kucuk sesler soz kesiyor. Uygulandi: ekrandan esik kaydiricisi + Otomatik, dBFS gosterge ve esik cizgisi, soz kesme sure/marj (gelismis), canli veri kanali komutu, oturum JSON kaydi, OpenAI esleme / Gemini uyarisi.
- Dogrulama (bulut): pytest 309, vitest 42, tsc temiz, Playwright 12/12. Mac venv bu VM'den calistirilamadi; Mac'te `.venv/bin/python -m pytest` kullanici/sonraki oturumda.
- Sentetik gurultu karsilastirmasi: evidence/core-015-vad-noise.json (varsayilan 23 gurultu kesmesi -> -35/-30 dBFS'de 0; -25'te konusma da kesmez).
- Acik: Mac'te gercek mikrofonla elle dogrulama (madde 6), gercek gurultu WAV'i, OpenAI esleme dogrulamasi, otomatik kalibrasyon ve speaking/thinking icin ayri esik (sonraki adim). core-015 BLOCKED (elle dogrulama bekliyor).

## Session 019 - core-015 dogrulandi (2026-10-27)
- Kullanici Mac'te gercek mikrofonla denedi: 'esik calisiyor'. core-015 PASSING (kanit: kullanici beyani; sayisal gercek-gurultu olcumu yok).
- Geri bildirim: esigi gecen her ses (oksuruk) ajani hala boluyor -> yeni ozellik core-016 (akilli soz kesme, not_started). Bu oturumda uygulanmadi (tek aktif ozellik kurali).

## Session 020 - canli test bulgulari: Opus analizi + hizli duzeltmeler (2026-10-28)
- Kullanici 15+ gozlem bildirdi (STT: bogaz temizleme/Cince/Rusca/'on'; A2: Cancellation failed, 'dinlemek isterim', tam anlayamadim dongusu, 10 sn ses yok; A3 dinlemede kaliyor; L2 bozuk transkript). Opus 5.5 analizi 43 oturum + 4 WAV uzerinden kok nedenleri cikardi.
- Hizli duzeltmeler uygulandi (core-017, bulut: pytest 321, Playwright 12/12; CANLI DOGRULANMADI -> core-017 blocked): STT gecidi, VAD min_ms 160, Gemini cagri kapisi, A2 yari-dupleks + interrupt_response=False + cancel yalniz aktifken, realtime cevap kurali + yumusak donusum, gozlemlenebilirlik alanlari.
- Yeni feature'lar: core-018 (A2 yerel tur yonetimi), core-019 (sabit metin TTS), core-020 (STT olcum seti + gecit esikleri), core-021 (puan politikasi, URUN KARARI), core-022 (sessiz hat), core-023 (A3 yeniden degerlendirme). Akilli soz kesme (oksuruk) core-016'da.
- Not: ornek aramalar (core-011) core-017 duzeltmeleri canli dogrulandiktan sonra yapilmali; aksi halde A3/A2 olcumleri anlamsiz.

## Session 021 - core-018..023 (2026-10-28)
- Kullanici hedefi: core-018..023 tamamlansin. Kararlar: core-021 -> puan politikasi 'netlestir' ve demoda DEGISTIRILEBILIR; core-019 -> sabit metinler OpenAI TTS.
- core-018: A2 tur yonetimi yerel VAD'a alindi (turn_detection=null, END -> commit + yalniz-fonksiyon cevap istegi, DROP/yeni dinleme -> clear, soz kesmede 400 ms halka tamponu). Profil secenegi local_turns=false eski yola doner. BLOCKED: 5 canli arama (hoparlor/kulaklik) bekliyor.
- core-019: voice/fixedaudio.py; acilis + guvenlik_scripti OpenAI TTS (gpt-4o-mini-tts, marin) ile uretilip data/fixed-audio/ onbellegine yazilir; model bu adimlarda konusmaz; hata -> modele geri dus + olay. BLOCKED: gercek ses, STT benzerligi >= 0,98 (10 arama) ve gecikme olcumu bekliyor; ADR yazilmadi.
- core-020: voice/stt_eval.py + scripts/stt_eval.py (WER, yabanci yazi/halusinasyon, sttguard dogru/yanlis red, esik taramasi). BLOCKED: >= 50 gercek klip yok.
- core-021: score_policy clarify|free (Playground secicisi), realtime dahil ayni kural. BLOCKED: llm-eval canli uyum olcumu (>= %95) yapilmadi.
- core-022: SilenceGuard (6 sn / kisa DROP sonrasi 3 sn; tekrar sor -> kapanis_sessiz). PASSING, sapma: tarayici e2e yerine oturum duzeyi entegrasyon testi; canli denenmedi.
- core-023: voice/realtime_report.py + scripts/realtime_report.py (A2/A3 cagri orani, tamamlama, transkript dili). BLOCKED: canli 5 arama yok; core-017 canli dogrulanmadan anlamsiz.
- Dogrulama (bulut): pytest 357, vitest 43 (yeni: puan politikasi secici), tsc temiz, Playwright 12/12. Eski testler degisti (silinmedi): test_realtime'daki sunucu VAD testleri local_turns=False ile calistirilir (varsayilan degisti).
- Sonraki kullanici adimi: Mac'te npm run build + backend yeniden basla; A2'de 5 arama (core-018/019), A3'te 5 arama (core-017/023), `scripts/realtime_report.py A3`, STT klipleri toplayip `scripts/stt_eval.py`; sonuclari paylasin, ilgili feature'lar passing'e cekilir.

## Session 022 - core-020 STT olcumu (2026-10-28)
- Kullanici 56 klip kaydetti (scripts/make_stt_manifest.py + record_stt_clips.sh) ve scripts/stt_eval.py'yi L2/L3/A1 icin calistirdi: evidence/core-020-stt-eval.json.
- Bulgu: Deepgram en iyi; Whisper tabanli L2/L3 oksuruge metin uyduruyor, geçit yetmiyor; BuzzASR tekrar dongusu. Eklendi: sttguard repetition_loop kurali; stt_eval yanlis-ret tanimi duzeltildi (gurultuye bos donus dogru). ADR 0006 yazildi. core-020 PASSING (sapma: duz large-v3 olculmedi).
- Dogrulama (bulut): pytest 362. Kalan: core-018/019 (A2 5 arama; ilk A2 oturumunda sabit ses calismadi - backend yeniden baslatilmamis olabilir), core-021 (llm-eval), core-023 (A3 5 arama) BLOCKED.

## Session 023 - son fix sonrasi canli oturumlarin incelenmesi (2026-10-28)
- Kullanici geri bildirimi: A1 TTS bozuk/yavas; A2 okudugu ile akis farkli, cevap yanlis soruya bagli (d227e6c2553e); A3 soz kesme zayif + yabanci kelimeler (47e1691a1c69); L2/L3 (3377b67086f0, 83e8400e8ed4) sorunsuz bildirildi.
- A2 kok neden: anket 'giris' adimi sabit-ses listesinde degildi (model KVKK metnini yorumladi, verbatim 0,148, akis musaitlik=hayir). Duzeltme: 'giris' eklendi. A3: realtime oturumda sttguard yabanci yazi transkriptini kayda almaz.
- Yeni feature'lar: core-024 (A2 metin sapmasi genel cozum), core-025 (A1 TTS kalite/hiz), core-026 (A3 soz kesme + transkript dili). Hepsi not_started.
- pytest 363. Ilk A2 oturumunda yeni kod calisiyordu (silences sayaci var) ama fixed_audio_turns yoktu: nedeni yukaridaki liste eksigi. Yeniden A2 denemesi gerekli.

## Session 024 - ilk canli A2 sonrasi duzeltmeler (2026-10-28)
- Oturum eaee33b00412: sabit giris sesi calisti (verbatim 1,0) fakat (1) ilk uretim 7,6 sn, (2) OpenAI transkripsiyon prompt'u kullanici transkripti olarak geri dondu (prompt kaldirildi, sttguard'a eklendi), (3) tekrar-sorma metni modele kaldi (verbatim 0,027; onekli sabit tekrarlar da sabit sese alindi), (4) 'Musaitim' -> refuse (core-024'e yazildi, cozulmedi).
- pytest 365. Canli yeniden deneme gerekli; core-018/019 hala blocked.

## Session 025 - A2/A3 degerlendirme kapanisi (2026-10-28)
- Kullanici: 'bu kadar kayit yeterli, modeller cok kotu'. A2: dis sesleri aliyor + KVKK 'dinlemek istemiyorum' sonlandirdi (eaee), 'nerde kaldik soyle bana' akistan kopma (16f2), konusulani anlamiyor (4d01). A3: yabanci kelimeler, anlamiyor (d507).
- Karar ADR 0007: A2/A3 uretim adayi degil; uretim yonu cascade (ADR 0006 STT, sabit yasal metin on-uretilmis ses); A2/A3 referans/ust sinir.
- core-018 PASSING, core-023 PASSING (orneklem kullanici karariyla kucuk, sapma notlu). core-019 BLOCKED (tek eksik: tekrar-sorma duzeltmesi canli dogrulanmadi), core-021 BLOCKED (tek eksik: llm-eval veya acik feragat). core-020, core-022 passing.

## Session 026 - core-019 ve core-021 kapanisi (2026-10-28)
- Kullanici A2 aramasi 832a49d28511 (giris sabit ses verbatim 1,0; tekrar-sorma 1,0) ve eval-llm-20261028-095926.json (L2 29/30, A1 29/30, ayni tek hata) sagladi. core-019 ve core-021 PASSING (sapmalar notlarda: kucuk orneklem, L3 dahil degil, tekrar-sorma yolu belirsiz).
- core-018..023 hepsi passing. Acik: core-016, core-017 (canli dogrulama), core-024/025/026, core-011 kapanisi, core-012 beklemede.

- (Session 026 duzeltme) core-019 tekrar-sorma dogrulanmadigi icin BLOCKED'a geri alindi; core-021 passing (L3 LLM'i L2 ile ayni, ayri kosu gereksiz).

## Session 027 - A2 "tekrar tekrar basa donuyor" (5bf3c50abbb4) (2026-10-28)
- Bulgu: sabit ses 4 turda calisti (fixed_audio_turns=4, verbatim 1,0; onekli tekrar-sorma dahil) ama akis 'giris'ten cikmadi: model arac argumanini {"answer":"devam","value_json":"devam"} verdi (intent yok) -> 'anlasilmadi' -> giris metni yeniden okundu.
- Duzeltme: realtime.parse_tool_args, 'answer' degeri INTENTS anahtari degilse onu cevap degeri sayar (intent="answer"). Yeni test; pytest 366 gecti. Mac'e aktarildi (realtime.py, test_realtime.py).
- core-019 PASSING (tekrar-sorma sabit sesle canli dogrulandi; 10 arama STT benzerligi olcutu yapilmadi, sapma notta). Canli yeniden deneme: A2'de 'Evet/devam' cevabinin artik ilerledigi dogrulanmali (core-024).

## Session 028 - core-024 kodlamasi (2026-10-28)
- Yapildi: tum sabit sorular sabit sesle (DEFAULT_STEPS '*'), cevap sonrasi musteri ses ogelerinin baglamdan silinmesi (conversation.item.delete), cevap istegine soru metni, YesNo transkript capraz kontrolu (flow.crosscheck_yesno), speech_deviation olayi. test_core024.py 7 test; toplam 373 gecti.
- Dogrulanmadi: canli A2. core-024 NOT_STARTED kalir; kapanis icin 10 A2 aramasi (verbatim >=0,95 her turda; 'Musaitim' ve 'Dinlemek istemiyorum' dogru dala gitmeli).
- Bilinen risk: dinamik metinli sabit turlarda ilk uretim gecikmesi; onbellek isitma henuz otomatik degil.

## Session 029 - realtime kapanisi, siradaki is core-012 (2026-10-28)
- 126f5d20c82a ve 5e921568e5e9 (A2) kontrol edildi: sabit ses verbatim 1,0 (33 tur), ama dogru dal olcutu gecmedi (yanlis dal, uydurma deger, %34 gecersiz bildirim, transkript gecikmesi). Karar: realtime'a daha fazla zaman ayrilmaz; core-024 dusuk oncelik (not_started), core-011 PASSING (sapmalar notta), ADR 0007 Ek 2.
- Siradaki: core-012 (cascade LLM prompt olcumu ve dondurma).

## Session 030 - core-012 uygulamasi (2026-10-28)
- Yapildi: prompt_eval.py (uretim promptunu olcer), 114 ornekli donmus veri seti, 4 prompt surumu (config/prompts), oturum loguna prompt surum/hash, scripts/eval_prompt.py, ADR 0008 (+ADR 0003 duzeltmesi). 379 test gecti (yeni 6).
- core-012 BLOCKED: gercek L2/A1 olcumu Mac'te yapilmali. Komut: ./.venv/bin/python scripts/eval_prompt.py L2 A1 (once --limit 20 --repeats 1). Sonuca gore aktif surum secilir ve dondurulur.
- Realtime: core-011 passing (fc8dd58), core-024 dusuk oncelik.

## Session 031 - core-012 olcum 1 (2026-10-28)
- Kullanici iki kanit verdi. Tam kosuda hicbir surum hedefi gecmedi (L2 en iyi v4 %93,0; A1 en iyi v4 %87,1). Puanlayici hatasi (clarify) duzeltilip yeniden puanlandi. A1'de ~%12 bos cikti.
- v5 + 79 orneklik donmus holdout eklendi; scripts/rescore_prompt_eval.py; saglayici stop_reason kaydi. 382 test gecti.
- core-012 BLOCKED: kalan komut: ./.venv/bin/python scripts/eval_prompt.py L2 A1 --variants v4 v5 --dataset config/eval/prompt-holdout.json

## Session 032 - core-012 holdout olcumu (2026-10-28)
- Holdout: L2 v5 %91,1 (en iyi), A1 %81,4; hedef saglanmadi. A1 bos ciktilarin kok nedeni bulundu (Haiku dusunme + max_tokens=120) ve duzeltildi (thinking disabled, yeniden deneme); uretim ajanini da etkileyen gercek hata. 385 test gecti.
- core-012 BLOCKED: karar bekliyor (ADR 0008 Olcum 2 sonu): A1 yeniden olcum / deterministik on-filtre / sapma notuyla kapanis.

## Session 033 - core-012 on-filtre (2026-10-28)
- negative_yesno_fix + mask_schema_words eklendi (kademeli hat), 387 test gecti. Holdout ham ciktilari yeniden puanlandi: L2 v5 %94,9. Maskeleme icin yeni kosu gerekiyor.
- core-012 BLOCKED. Komutlar: eval_prompt.py L2 A1 --variants v5 --dataset config/eval/prompt-holdout.json ; eval_prompt.py L2 A1 --variants v5

## Session 034 - core-012 olcum 3 (2026-10-29)
- Kullanici on-filtre sonrasi iki kanit verdi (holdout ve ana set, L2/A1 v5 x 3). L2 v5: holdout %98,7 / sema %100 / injection 0 / p95 0,57 sn (hedef tuttu); ana set %98,2 / sema %100 / p95 0,50 sn ama injection yanlis dal 3 (tek ornek p030 x3). A1: sema %98,7-98,8, holdout tam %93,2, p95 ~16 sn (sağlayici zaman asimi/baglanti hatalari, tek '2' degeri).
- Maskeleme etkisi olculdu: holdout'taki 'intent X yaz' injection'lari 9 -> 0. Olumsuz-cevap duzeltmesi p024 ('istemiyorum' yalin) bilincli olarak refuse kaliyor.
- core-012 BLOCKED (sapma: L2 ana set injection p030; A1 sema/gecikme). Karar bekliyor: (a) sapma notuyla kapat ve v5'i dondur, (b) p030 icin 'talimat/gormezden gel' deterministik ozel durum ekle ve L2 ana seti yeniden kos.

## Session 035 - core-012 p030 kurali (2026-10-29)
- Kullanici 'p030 kural ekle' dedi. flow.injection_guard (kademeli hat): cumle baslangicinda talimat gecersiz kilma komutu varsa unclear. Cevrimdisi: 193 ornekte yalniz p030, p049 etkilenir (ikisi beklenen unclear). 388 test gecti.
- Dogrulanmadi: gercek L2 ana set kosusu. Komut: ./.venv/bin/python scripts/eval_prompt.py L2 --variants v5 . A1 sema %100 sapmasi icin ayrica feragat gerekir. core-012 BLOCKED.

## Session 036 - core-012 olcum 4 (2026-10-29)
- injection_guard sonrasi L2 v5 ana set: tam %99,1, sema %100, injection yanlis dal 0, p95 0,53 sn (evidence/eval-prompt-20261029-185426.json). Holdout (olcum 3) da gecmisti. Tek kalan: A1 sema %100 / gecikme sapmasi.
- core-012 BLOCKED: kullanici A1 sapmasini kabul ederse v5 dondurulup passing yapilir.

## Session 037 - core-005 persona (2026-10-29)
- Yapildi: persona modulu (config/persona.json + data/persona.json), API (/api/persona, preview, reset, report), 'Persona' ekrani, serbest sohbet istemi/acilis, {ASISTAN}, kademeli hatta onay sozu, cumle uzunlugu raporu. 402 backend + 46 frontend test gecti; ekran tarayicida gorulup denendi.
- Dogrulanmadi: gercek L2 hatta 5 test aramasi ve transkript incelemesi (verification 1-2). core-005 BLOCKED bu yuzden.
- Sirada: Mac'te uygulamayi yeniden baslat (frontend/dist guncel), /persona'dan kaydet, Playground'da 5 arama yap, 'Cumle uzunlugu raporu'ndan Raporu getir, sonuclari bana ver.

## Session 038 - core-005 ton -> ses (2026-10-30)
- Kullanici hedefi: farkli tonlar demoda sasirtmali; ElevenLabs dogrula, Flash v2.5 yetmezse hangi model arastir (Opus ile).
- Yapildi: tone_voice.py + config/tone-voice.json (saglayici/model/ton -> parametre), TTS `synthesize(..., tone=)` (EMA hiz; Chatterbox exaggeration/cfg_weight/temperature; ElevenLabs stability/style/speed, v3/v4 ses etiketi, ton basina ses kimligi, seed), persona tonlari enerjik/sakin, VoiceSession tts_tone, API /api/persona/tones + /tone-demo, Persona ekraninda Ton demosu, scripts/verify_elevenlabs_tones.py. 426 backend (1 skip: torch yok) + 50 frontend test gecti.
- Arastirma (ADR 0010): ses etiketi yalniz v3/v4/v4 Turbo; Flash v2.5 yalniz stability+hiz+ses secimi; Multilingual v2 style ekler; en guclu kaldirac ayri ses (Voice Library / Voice Design).
- DOGRULANMADI: ElevenLabs (bulut proxy/anahtar yok) — modeller arasi gercek ton farki, Turkce etiket kalitesi, v4 Turbo gecikmesi; Chatterbox ton testi (torch yok). Sayilar baslangic tahmini.
- Sirada (kullanici, Mac): `python scripts/verify_elevenlabs_tones.py`, klipleri dinle; Persona > Ton demosu'nu ElevenLabs profilinde dene; sonucu bana ver, tablo kalibre edilsin.
- 2026-10-30 (Session 038 devam): Kullanici dinledi: ton farki v4'te hissediliyor, Flash v2.5'te belirgin degil. Demo modeli v4 (Turbo). Olculmedi: v4 Turbo canli hat gecikmesi, report.json sayilari. Oneri: ElevenLabs ses secici (onay bekliyor).
- 2026-10-30: ElevenLabs dogrulamasi calisti (kullanici Mac'inde): evidence/elevenlabs-tones-20261030-113531 (4 model x 4 ton, hata yok). Kaba olcu Flash/Multilingual'da daha buyuk fark, dinlemede fark v4'te; tam klip uretim suresi Flash 0,6 sn, v4 Turbo 1,4 sn, v3 3-4 sn. Karar: demo v4 Turbo. Acik: akisli ilk ses suresi, etiket Turkce okunusu.
- 2026-10-30 (Session 038 devam): Ses secici eklendi (ton basina ElevenLabs sesi; GET /voices, PUT /tones/voices, POST /voices/add; VoicePicker.tsx). Ton demosu varsayilan model v4 Turbo. 430 backend + 53 frontend test gecti. DOGRULANMADI: gercek hesapla liste/onizleme/'Hesabima ekle', kutuphane ses lisansi. Sirada (kullanici, Mac): uygulamayi yeniden baslat, Persona > Ses secici'den enerjik/sakin icin ses ata, Ton demosu'nu v4 Turbo ile dinle.
- 2026-10-30 (Session 038 devam): TTS laboratuvari + model kiyas matrisi (config/elevenlabs-models.json, /api/persona/model-matrix, /tts-lab, TtsLab.tsx): metin+model+ses+ton, akisli ilk ses suresi, maliyet, aylik tahmin; Turbo v2.5 eklendi. Fiyatlar resmi sayfadan (0,04/0,08 $ per 1K). 433 backend + 56 frontend test gecti. DOGRULANMADI: gercek ElevenLabs ile lab olcumleri (kullanici Mac'inde), Flash+ses ile ton yeterliligi, eleven_turbo_v2_5/eleven_v4 model kimlikleri. Sirada (kullanici): uygulamayi yeniden baslat, Persona > TTS laboratuvari > Tum modelleri sirayla dene; matris + dinleme sonucunu bana ver.
- 2026-10-30 (Session 038 devam): Ses secici ElevenLabs ses kutuphanesi gibi yenilendi (istek: 'voice secmek icin daha guzel arayuz, arama olsun, preview bu ekranda'): VoicePicker.tsx yeniden yazildi (300 ms beklemeli arama, kaynak/cinsiyet/yas/kullanim suzgeci, siralama, 'Daha fazla yukle', satir ici oynat + ilerleme cubugu, ton rozeti, 'Ton ata' menusu, altta yapiskan 'Ozel onizleme': metin+model(v4 Turbo varsayilan)+ton, ilk ses suresi ve maliyet; /tts-lab kullanir). GET /api/persona/voices gender/age/use_case/sort/page + yapisal alanlar + has_more. 434 backend (1 skip) + 61 frontend test gecti, tsc temiz; bulut Chromium'da acik/koyu/telefon ekran goruntusu (sahte API). Kararlar/sinirlar docs/adr/0010 ve docs/demo-soru-cevap.md'de: kutuphane sesi ozel metinle uretilmeden once 'Hesabima ekle' gerekir (varsayim, dogrulanmadi); sayfalama yalniz kutuphane; suzgec parametre adlari belgeye gore. DOGRULANMADI: gercek hesapla liste/suzgec/klip/ekleme, Turkce arama kalitesi, kutuphane ses lisansi. Sirada (kullanici, Mac): uygulamayi yeniden baslat (scripts/demo.sh), Persona > Ses kutuphanesi'nde ara/dinle/ata, 3-4 sesi Hesabima ekle, Ozel onizleme'yi v4 Turbo ile dene; sonucu bana ver.
- 2026-10-30 (Session 038 devam): Persona ekrani sadelestirildi (istek: 'cok karmasik, sonsuz scroll; elevenlabs ayarlarini popup'a koy'): VoicePicker + TtsLab + ToneDemo Persona sayfasindan cikarildi; yeni VoiceStudio.tsx sekmeli acilir pencere (Ses kutuphanesi / Laboratuvar / Ton demosu; ilk acilista yuklenir, kapaninca durum korunur, Esc/x/arka plan kapatir, govde kaymasi kilitli, telefonda tam ekran) ve Persona'da kisa 'Ses studyosu' karti. Stiller frontend/src/studio.css'te (Mac'te styles.css yazma izni vermedi; genel dosyaya dokunulmadi). Persona sayfa yuksekligi bulut Chromium'da ~1230 px. 61 -> 65 frontend test (VoiceStudio.test.tsx: 4), 434 backend, tsc ve vite build temiz; acik/koyu/telefon ekran goruntusu (sahte API). DOGRULANMADI: gercek hesapla ekran; odak tuzagi yok (aria-modal + Escape var). Sirada (kullanici, Mac): uygulamayi yeniden baslat, Persona > Ses stüdyosunu aç, kutuphane/laboratuvar/ton demosunu dene.
- 2026-10-30 (Session 038 devam): L2-EL profili eklendi (istek: 'L2 TTS'ini EMA yerine ElevenLabs ile dene; Persona'dan ses/ton secince profillere direk etki etsin'): config/profiles.yaml L2-EL = L2'nin STT+LLM'i + elevenlabs/eleven_v4_turbo; STT/LLM onbellekte L2 ile paylasilir. Persona'dan atanan ses bir sonraki cumlede etki eder (tone_voice.resolve_voice her cumlede okunur; A1'i de etkiler). Yeni 'Genel ses' yuvasi (voices.default; Ses studyosu'nda 'Genel ses icin sec'); ses onceligi: ton env > tona atanan > Genel ses > ELEVENLABS_VOICE_ID. ELEVENLABS_VOICE_ID artik zorunlu env degil (readiness_issues eksik tonlari soyler; ses yoksa Turkce ProviderError, /tts-lab 400 no_voice). test_profiles.py'de iki beklenti bilincli guncellendi (L2-EL listede; A1 missing_env'den VOICE_ID cikti). 438 backend + 66 frontend test, tsc temiz; profil yukleyicisinden gercek L2-EL TTS'i sahte HTTP ile dogrulandi (enerjik -> kendi ses + [excited], sakin -> Genel ses + [calm]). DOGRULANMADI: gercek ElevenLabs ile uctan uca arama, L2-EL tur gecikmesi (EMA'dan farki), acik oturumda canli ses degisimi. Sirada (kullanici, Mac): uygulamayi yeniden baslat, Persona > Ses studyosu'nda bir 'Genel ses' ata, Playground'da L2-EL'i sec (Hazirla), arama yap; tur suresini L2 ile karsilastir ve bana ver.

## Session 2026-10-30 (akşam): lab-004 Aramalar + kıyas

- Kullanıcı isteği: "yaptığım aramalar için kıyasları görmek istiyorum" → feature_list'te lab-004 (F7.4) uygulandı, durum **blocked** (gerçek arama doğrulaması kullanıcıda).
- Yeni: `backend/app/calls.py`, `api_calls.py`, `frontend/src/pages/CallsPage.tsx`, `callsApi.ts`, `calls.css`; `voice/session.py` oturum kaydına stt/llm/tts/tts_tone/tts_speed ekledi.
- Doğrulandı: backend 444 test, frontend 73 test, tsc/build temiz, ekran görüntüleri (sahte veri). Mac'te pytest çalıştırılamadı (bu oturumun Mac kabuğunda .venv yok); dosya özetleri cloud ile eşit.
- Doğrulanmadı: gerçek aramalarla liste/detay/ses oynatma; L2 vs L2-EL gerçek kıyas (örnek sayısı ≥5 gerekir).
- Not: Mac'te `frontend/src/api.ts` ve `styles.css` yazılamıyor; yeni kod ayrı dosyalarda (`callsApi.ts`, `calls.css`).
- Sonraki: kullanıcı L2 ve L2-EL ile birkaç gerçek arama yapar → /calls'ta Kıyas'a bakar → lab-004 passing.

## Session 2026-10-30 (akşam, 2): KVKK sorusunda yalın "İstemiyorum" düzeltmesi (core-012 bulgusu)

- Canlı kayıt 45e4e7002bc2 (L2+EL): "Aydınlatma metnini dinlemek ister misiniz?" -> "İstemiyorum." -> görüşme kapandı (katilmak_istemedi). Beklenen: devam. Ayrıca aynı kayıtta STT 4.7 sn + LLM 12.3 sn (soğuk model olasılığı; doğrulanmadı).
- Yapıldı: (1) `giris` adımına `bareNo: "devam"`; `flow.bare_no_fix` deterministik koruma (kademeli + realtime yol), açık ret sözleri refuse kalır; llmHint'e yalın "istemiyorum" eklendi. (2) `retryText`: yeniden sorma/sessizlik tekrarında yalnız soru cümlesi (`FlowDriver.retry_of`). (3) `backend/tests/test_giris_bare_no.py` 14 test. Backend 458 geçti.
- Doğrulanmadı: gerçek LLM/STT ile yeniden deneme; ElevenLabs ile kısa tekrar cümlesinin sesi; core-012 holdout yeniden ölçümü (set bilerek değiştirilmedi).
- Sonraki: kullanıcı Mac'te "İstemiyorum." ve "Debiyorum." (STT çöpü) ile dener.

## Session 2026-10-30 (gece): core-016 akıllı söz kesme (blocked: gerçek kayıt bekliyor)

- Yapıldı: `voice/speechlike.py` (perde periyodikliği + sıfır geçiş + ≥400 Hz payı), `vad.BargeTracker` (session.py ve realtime.py ortak), `voiced_min` ayarı, `stats.barge_blocked` + `barge_blocked` olayı, Gemini için "etkisiz" notu, `voice/synthsounds.py`, `scripts/eval_barge_gate.py`, ADR 0011, 21 yeni test (backend 479 geçti).
- Sentetik ölçüm: konuşma 9/9 keser (160 ms); öksürük/boğaz/klavye/kapı/nefes 0/30 keser; süzgeçsiz 24/30 keser. Kapı bulgusu sonrası 3. özellik eklendi (aşırı uyum riski, ADR'de).
- Beklenti değişikliği: 9 eski söz kesme testi beyaz gürültüyü "konuşma" sayıyordu; perdeli konuşma benzeri sese çevrildi (test zayıflatılmadı; core-015 seviye testi voiced_min=0 ile korundu).
- Doğrulanmadı: gerçek öksürük/klavye/kapı kayıtları, 'hmm', WebRTC/telefon yolunda 500 ms, OpenAI realtime canlı, Playground arayüzünde voiced_min/barge_blocked gösterimi yok.
- Sonraki: kullanıcı core-013 kaydıyla etiketli kayıt toplar (`cough_1.wav`, `speech_1.wav` ...) → `python scripts/eval_barge_gate.py --dir <klasör>` → sonuca göre eşik/Silero kararı.

### core-016 gerçek kayıt turu (2026-10-30 gece)
- Kullanıcı 33 gerçek kayıt aldı (`kayitlar/barge/`, git'e EKLENMEZ: kişisel ses). İlk sürüm başarısız: `evidence/core-016-gercek-20261030-210436.json`.
- Düzeltme: HF alt sınırı kaldırıldı -> HF_MAX 0,30; PEAK_MIN 0,60 -> 0,75; sentetik ses gerçek spektruma yaklaştırıldı (testler gevşetilmedi). 479 test geçti. Yeniden ölçüm (aynı kayıtlar, bulutta): `evidence/core-016-gercek-20261030-210947.json`: nefes/kapı/klavye 0, öksürük 1/5, hmm 1/3, boğaz 4/5, konuşma 3/5 -> `passed:false`.
- Hâlâ bozuk/doğrulanmamış: boğaz temizleme, hmm, öksürük (1), konuşma kayıtlarının seviyesi (2/5 eşik altı), Gemini'de etkisiz, tek konuşmacı aşırı uyum. Durum `blocked` kalır.
- Sonraki: daha yüksek sesli/çok konuşmacılı kayıt + kısa STT/Silero doğrulaması (ADR 0011 seçenek a/b); söz kesme eşiğini canlı ayarda yeniden düşür.

## Session 2026-10-30 (gece 2): ui-001 önyüz yenileme (passing, açıklı)
- Kullanıcı: core-016 `blocked` kalsın; önyüz tamamen yenilensin; yerleşik tarayıcıdaki referans uygulama (sahibinden-demo.intalkive.com: Genel Bakış, Görüşmeler + detay, Başarı Kriterleri, Canlı İzleme, Senaryolar, Ayarlar) incelendi.
- Yapılan: `theme.css` (koyu/açık tema, sarı vurgu), gruplu menü (`screens.ts` group/icon), `App.tsx` kabuğu (durum hapları, Yeni Arama, tema anahtarı, mobil çekmece), yeni `OverviewPage` (KPI + grafikler, /api/calls'tan), yeni `SettingsPage`, `icons.tsx`, `theme.ts`.
- Kanıt: tsc temiz, vitest 81 geçti, playwright lab 6 geçti, `evidence/ui-001-*.png`.
- Bilinçli test değişikliği: App.test "sekiz ekran" -> "on ekran, gruplu"; e2e smoke ekran listesi 10'a çıktı (ekran sayısı arttığı için, gevşetme değil).
- Açık: voice e2e 3 test eski (Ayşe/Elif adı), Mac'te gerçek veriyle görsel kontrol, kalan sayfaların tek tek göz kontrolü, referanstaki Canlı İzleme/Kuyruk/Geri Arama/Başarı Kriterleri formu (backend yok).
- Çalıştırma: `cd frontend && npm run build` sonra backend'i başlat (dist/ eskidir).

## Session 2026-10-30 (gece 3): lab-005 kıyas matrisi (passing, açıklı)
- Kullanıcı: "lab-005 tamamla". Tek aktif özellik.
- Yapılan: `backend/app/matrix.py` (puan kuralları, ağırlık ayrıştırma, toplama, lisans eleme), `api_matrix.py` (`GET /api/matrix?weights=...`, önbelleksiz, 422 hatalı ağırlık), `config/matrix.json` (ağırlıklar, eşikler, lisans tablosu), `frontend/src/matrixApi.ts`, `pages/MatrixPage.tsx` (kaydırıcılar, Yenile, pencereye dönünce yenileme, kapsam, lisans rozetleri), `/matrix` artık yer tutucu değil.
- Kararlar: puan tek yerde (backend); veri yoksa kriter eksik, sayı uydurulmaz; kapsam < %50 ise toplam yok; yalnızca commercial_ok=false eler; "+ ipucu" STT varyantı hariç.
- Kanıt: backend 491 geçti (+12), vitest 86 geçti (+5), playwright lab 6 geçti, `evidence/lab-005-*.png` (sentetik veri). Tablo yatay taşma düzeltildi.
- Açık: gerçek veriyle Mac'te görsel/uçtan uca kontrol; kaynak kullanımı ölçülmüyor (eval-003); lisans tablosu doğrulanmadı; voice e2e 3 eski test (Ayşe/Elif); Mac'te pytest kurulu değil (testler bulutta koşuldu).
- Sonraki: eval-002 (seçilen yığın kaydı) bu matrisi kullanabilir.

## Session 2026-10-30 (gece 4): core-006 sessizlik / müsait değilim / bot musun (passing, açıklı)
- Kullanıcı: "sıradaki moscow must feature'ı implemente et" -> öncelik sırasında ilk başlanmamış must: core-006 (core-012/014/005/lab-004/core-016/017 blocked).
- Bulgu: sessiz hat core-022'de zaten bağlıydı (envanter notu eskiydi); geri arama dalı vardı ama LLM'e bağlıydı; "bot musun" cevabı yoktu (off_topic'e düşüp "anketimize devam edelim" diyordu).
- Yapılan: `flow.identity_question` + `FlowDriver._identity` (LLM'siz dürüst cevap, bekleyen soru tekrar, en fazla 3), `flow.callback_fix` (müsait değilim -> randevu, açık ret ve geçerli cevap korunur, Evet/Hayır'dan önce çalışır).
- Kanıt: `backend/tests/test_core006.py` 42 test; backend 533 geçti; `evidence/core-006-20261030.json` (sahte modeller).
- Sapma: sessizlik 6 sn (kabul 8 sn der), sebep core-022 canlı bulgusu. Demo S35.
- Açık: gerçek LLM/STT/mikrofonla doğrulama; realtime profillerde kimlik cevabı modele bağlı; dijital asistan beyanının hukuki metni.
- Sonraki must adayları: eval-001/003/002 (başlanmamış); scn-001.. (Faz 2).


## Session 2026-10-30 (gece 5): eval-001 kiyas duzenegi (passing, acikli)
- Kullanici: "core-006 passing zaten. not_started olan bi feature" -> eval-001. Kararlar (kullanici): musteri sesleri ElevenLabs ile uretilip diske kaydedilir; 4 yol = tam katilim, ret, geri arama, belirsiz cevaplar.
- Yapilan: `config/eval/personas.json` + `paths.json`, `backend/app/evalrun.py` (klip uretimi/onbellek, persona etkileri, headless VoiceSession kosucusu, kosu yonetimi), `api_evalrun.py` (/api/evalrun/*), `frontend` Kiyas kosusu ekrani (/benchmark), `ElevenLabsTTS.synthesize(voice=)`, `VoiceSession.meta`.
- Kanit: test_evalrun.py 14, BenchmarkPage.test.tsx 5; backend 547, vitest 91, build, playwright lab 6 (smoke 11 ekran); evidence/eval-001-20261030.json (sahte modeller).
- Acik: gercek ElevenLabs ile set uretimi ve gercek profille kosu dogrulanmadi; yankı/barge-in/gercek zamanli oynatma olculmuyor; realtime desteklenmiyor; Mac'te git HEAD.lock sorunu nedeniyle core-006 ve eval-001 commit edilemedi.
- Sonraki: eval-003 (maliyet/kaynak), eval-002.

## Session 2026-10-31 (gece 6): eval-003 arama basina maliyet ve kaynak olcumu (passing, acikli)
- Kullanici: "eval-003 tamamla". Mevcut durum: provider-calls.jsonl sagliyordu; arama toplami, GPU sn, fiyat listesi, maliyet yoktu.
- Yapilan: `usage.py` (sayac, MeteredLLM, report), `config/pricing.json`, `LLMResult.input_tokens` (Ollama prompt_eval_count, Anthropic usage.input_tokens), VoiceSession entegrasyonu + oturum JSON `usage`, calls.py (cost_usd, gpu_s, detay usage, grup ortalamalari), Aramalar ekrani (Kaynak ve maliyet, Maliyet/arama, GPU sn).
- Kararlar: veri yoksa null (sifir degil); yerel bilesen API maliyeti 0 ama GPU sn ayri; eksik fiyat/token 'eksik' bayragi; fiyatlar dosyada ve dogrulama durumu isaretli.
- Kanit: test_usage.py 11, CallsPage.test.tsx +3; backend 558, vitest 94, build, playwright lab 6; evidence/eval-003-20261031.json (sahte saglayicilar).
- Acik: gercek API/yerel aramada dogrulama; Haiku fiyati resmi sayfadan; realtime oturumlari olculmuyor; kiyas matrisi kaynak kriteri; Mac'te commit.
- Sonraki: eval-002 (secilen yigin kaydi), lab-005 matrisine kaynak kriterini baglamak.

## Session 2026-10-31 (gun): maliyet projeksiyonu + A1S streaming (core-027, blocked: gercek olcum bekliyor)
- Kullanici: aylik 25.000 dk icin tum profillerin maliyeti; kurumsal fiyat; production gecikme. Maliyet tablosu sohbette verildi (A1 ~$710-1.230, A2 ~$830-1.000 (en kotu $6.700), A3 ~$490-2.150, yerel $0 API + GPU; kurumsal teklif yok, tahmin).
- Bulgu: her API cagrisi yeni TLS baglantisi aciyordu; Deepgram toplu REST, ElevenLabs tam cumle bekliyordu => A1 p50 3,29 sn (L2 1,42 sn). Karsilastirma adil degildi.
- Yapilan (Opus alt ajani + ben): ortak httpx.Client, ElevenLabs akisli TTS, Deepgram canli STT + toplu yedek, A1S profili, usage akis suresi, scripts/latency_probe.py. Backend 631, vitest 94, playwright 6.
- Duzeltme: cloud kopyasi Mac'ten eskiydi; tar trnorm.py/test_trnorm.py'yi geriletti, git checkout ile geri alindi ve bulut kopyasi Mac'ten esitlendi.
- Acik: gercek ortamda olcum (latency_probe A1 vs A1S, sonra 5 gercek arama); Anthropic prompt caching yapilmadi; A2/A3 usage sayaci yok.

## Session 2026-10-31 (aksam): core-027 devam - baglanti isitma + istem onbellegi (opt-in)
- Kullanici: "1 ve 2 ile basla". Gercek olcum (latency_probe) LLM'i darbogaz gosterdi (1,0-1,3 sn; soguk ilk cagri 1,75-2,6 sn).
- Yapilan: registry.prewarm + api_voice.offer entegrasyonu, AnthropicLLM.prewarm, prompt_cache secenegi (varsayilan kapali, reddedilirse duz metne doner), latency_probe --prewarm / --llm-cache. Backend 639 gecti.
- Not: onbellek asgarisi Haiku 5.5 icin 512 token; istemimiz sinirda, kazanc beklenmiyor, olculerek karar verilecek.
- Acik: Mac'te --prewarm ve --llm-cache olcumu; A1S ile 5 gercek arama; alternatif hizli LLM olcumu; yerel LLM'li hibrit.

## Session 2026-10-31 (gece): core-027 - LLM'siz hizli yol + arka plan isitma
- Kullanici: "basla" (1: kapali sozlukte LLM'siz yol, 2: LLM isitmasini arka plana al).
- Yapilan: flow.fastpath_obj (yalniz tam-cumle eslesme; belirsizde LLM), FlowDriver.fast_path (profil `fast_path`, yalniz A1S), 'fast_path' olayi; api_voice: STT/TTS isitma kabulden once, LLM isitma arka planda (_BG_TASKS). Etiketli 114+79 ornekte kapsam 23/193, yanlis 0. Backend 669 gecti, 1 atlandi.
- Karar: bayrak LLM secenegi degil profil alani (LLM ornegi A1 ile paylasilsin, mevcut test bozulmasin).
- Acik/dogrulanmadi: hizli yolun canli kapsami ve gecikme kazanci olculmedi (etiketli kume zor ornek agirlikli, gercek trafikte kapsam daha yuksek beklenir ama KANITSIZ); arka plan isitma ilk turla yarisirsa LLM soguk kalabilir (olculmedi); 5 gercek arama hala yok. core-027 blocked.

## Session 2026-10-31 (gece 2): core-027 canli olcum + production maliyet tablosu
- Kanit: evidence/latency-probe-A1S-20261031-195514.json; canli oturumlar 6691940aaf71, a04a5d13893b, af0654aa5741, f6fed9f9d747 (4 arama, 70 tur).
- Bulgu: ilk ses p50 1,53 sn (hedef 1,2 tutmuyor). LLM'siz turlar 0,78 sn (16 tur, cikarim), LLM'li 1,80, Deepgram yedek 2,79 sn (8 tur). 16 yedek: 8 bos, 5 zaman asimi, 3 dusuk guven.
- Maliyet (3 tamamlanan arama, 16,9 dk, $0,66): ~$0,039/dk, TTS %94, STT %5, LLM %0,6; 25.000 dk ~ $975 (liste fiyati). Bilinmeyenler tablosu PoC plani eki 2026-10-31-gece'de.
- Acik: 'fast_path' turda kayitli degil; Deepgram yedek nedenleri; kesilen cumle karakter sayaci; ElevenLabs plan/kredi, telefon operatoru maliyeti. core-027 blocked.

## Session 2026-10-31 (gece 3): ElevenLabs modelini ekrandan degistirme
- Istek: ElevenLabs iceren tum profillerde (L2-EL, A1, A1S) model ekrandan degissin.
- Yapilan: profiles.py kalici override (data/profile-tts-models.json; yalniz elevenlabs-models.json'daki gecerli modeller; load_profiles uygular, boylece arama, benchmark, matris, studyo ayni modeli kullanir; streaming bayragi korunur). API: GET /api/profiles/tts-models, PUT /api/profiles/{id}/tts-model (null = varsayilana don). Arayuz: profil seciciye 'ElevenLabs modeli' listesi (fiyat/1k karakter) + 'Varsayilana don'. pricing.json'a eleven_v3 ve eleven_v4 liste fiyati eklendi (dogrulanmadi).
- Dogrulama: backend 674 gecti, vitest 96, tsc, build. Tarayicida elle denenmedi.
- Sinirlar: degisiklik yeni aramalara uygulanir (acik arama eski modelle surer); farkli model yeni baglanti/isitma ister; v3 canli hat icin yavas (model matrisi notu).

## Session 2026-10-31 (gece 4): akisli TTS ekrandan ac/kapa
- Istek: L2-EL'de de streaming acilabilsin, ekrandan.
- Yapilan: ElevenLabs'li profillerde 'Akisli TTS' kutusu (profil secici). Kalici override data/profile-tts-streaming.json; API PUT /api/profiles/{id}/tts-streaming (null = yaml varsayilani); /api/profiles satirina tts_streaming ve tts_streaming_default. load_profiles(apply_overrides=False) yaml tanimini verir; test_profile_a1s.py artik bunu kullanir (test gevsetilmedi: ayni kontroller, yalniz ekran secimlerinden bagimsiz).
- Dogrulama: backend 677 gecti, vitest 97, tsc, build. Tarayicida elle denenmedi; L2-EL akisli ilk ses olculmedi.
- Sinir: yeni aramalara uygulanir; A1 da acilabilir ama o zaman 'akissiz referans' olmaz.

## Session 2026-10-31 (gece 5): profil karar kaydi (eleme gerekcesi) + ElevenLabs ayarlari Ayarlar'a tasindi
- Istek: kiyas kosusu sonrasi bazi modeller elenecek; neden elendigi profil bazinda demoda anlatilacak. Ayrica ElevenLabs model/akis ayarlari Ayarlar menusu altina.
- Yapilan: backend/app/decisions.py (data/profile-decisions.json; durum aday/secildi/elendi; elendi/secildi icin gerekce zorunlu, en az 15 karakter; karar anindaki toplam/kapsam/kriter puani 'snapshot' olarak saklanir). API: PUT /api/matrix/decisions/{profil}, GET /api/matrix/decisions/report (profil bazli Markdown, lisans nedeniyle elenenler icin otomatik gerekce). Kiyas matrisi sayfasinda 'Profil kararlari' paneli + 'Demo ozetini goster'; tabloda karar rozeti. ElevenLabs modeli ve Akisli TTS ust cubuktan Ayarlar > Ses (ElevenLabs) bolumune tasindi (ElevenLabsSettings.tsx).
- Dogrulama: backend 684 gecti, vitest 100, tsc, build. Tarayicida elle denenmedi.
- Acik: gercek kiyas kosusu ve eleme kararlari sen yapinca kaydedilecek; karar metinleri demo-soru-cevap'a su an elle kopyalanmiyor (rapor ekranindan alinir). Elenen profil kiyas kosusu listesinden otomatik cikmaz (yalniz kayit).

## Session 2026-11-01: hizli yol ekrandan ayar + acik/kapali olcumlerin ayri gorunmesi
- Istek: hizli yol (LLM'siz) ayar olsun; acik/kapaliyken olcumler ayri yapilip ekranda gorulsun; demoda fark net anlatilsin. (Baglam: 2865daf46143 aramasinda L2-EL'de 'ON' LLM'de anlasilmadi.)
- Yapilan: profil bazli kalici ayar (data/profile-fast-path.json; cascade profillerde; PUT /api/profiles/{id}/fast-path; Ayarlar > Cevap anlama). Arama kaydina config bloğu (fast_path, tts_streaming, stt_streaming) ve kural turlarina turda fast_path:true yazilir; kural turlari llm_s yazmaz (LLM suresi istatistigi kirlenmez). Kiyas kosusu da ayari uygular (run kaydinda fast_path). Aramalar > Kiyas > 'Profil + hizli yol': ayni profilin acik ve kapali aramalari ayri satirlarda; kapaliya gore fark, 'LLM'siz tur' payi, 'ilk ses: LLM'siz / LLM'li'. config'i olmayan eski aramalar 'ayar kaydi yok (eski)' satirinda, kiyaslanmaz.
- Dogrulama: backend 690 gecti, vitest 103, tsc, build. Gercek aramayla acik/kapali olcum YAPILMADI.
- Not: onceki 'llm_s == 0' cikarimi (4 A1S aramasi) eski kayit; yeni kayitta fast_path alani var.
- Acik: L2-EL ve L2 icin ayar acik/kapali en az 5'er arama/kosu; acik uclu adimda yalniz sayi cevabi (kullanici 2 numarali oneriyi 'persona prompt yeter mi' diye sordu: yetmez, OpenText LLM'e gitmez); 2865daf46143 q12 erken kapanma (kullanici atladi).

## Session 2026-11-01 (2): kiyas kosusunu tum prompt surumleriyle kosan script
- Istek: L2'yi kiyas kosusunda tum ayristirici prompt surumleri (v1-v5) icin kosturan script; sonuclar analiz icin paylasilacak.
- Yapilan: scripts/eval_variants.py (profil, surumler, hizli yol on/off [varsayilan KAPALI: surum etkisi izole], telefon filtresi, persona/yol alt kumesi). FlowDriver.prompt_variant (None = aktif sürüm), evalrun.run_call/execute prompt_variant parametresi; oturum kaydindaki flow.prompt hangi surumle yapildigini yazar. Cikti: tablo + evidence/eval-variants-<profil>-<tarih>.json (arama basina musterinin soyledigi, ajanin kaydettigi cevaplar, transkript, tur sureleri).
- Dogrulama: backend 691 gecti (sahte saglayicilarla script akisi test edildi). GERCEK L2 koşusu yapilmadi.
- Sinir: her surum seti bir kez kosar (tekrar yok) => tek orneklem, 20 arama/surum; kucuk farklar gurultu olabilir.

## Session 038 - A1 v5 sapmasinin nedeni (2026-11-01)
- Karar: kullanici "once A1'i yeniden olc" secti (v5 aktivasyonundan once). Not: Haiku thinking duzeltmesi (thinking disabled) zaten olcum 3'ten ONCE uygulanmisti; A1 sapmasinin nedeni thinking degil.
- Kanit analizi (evidence/eval-prompt-20261029-181602.json holdout, -183538.json ana set; A1 v5): p50 ~1,1 sn, p95 ~15,9 sn. Yavas cagrilar %10-14 (34/237, 37/342), 18-55 sn; hepsinde stop_reason=end_turn, ~16 cikti tokeni, yalniz text blogu -> dusunme/uzun cikti DEGIL; sunucu ya da baglanti takilmasi. Hata/zaman asimi yok (60 sn sinirinin altinda).
- Sema ihlali: holdout'ta 3/237 (h020 'onay vermiyorum' YesNo icin value '2' dondu, rep 1). Ayri model hatasi, takilmayla ilgisiz.
- Uretim etkisi: canli cagrida 18-55 sn sessizlik kabul edilemez; aday cozum kisa okuma zaman asimi (~5 sn) + bir kez yeniden deneme (istek idempotent). Henuz uygulanmadi, once neden ayrilacak.
- Eklendi: scripts/llm_stall_probe.py (paylasilan keep-alive baglanti vs her cagrida yeni baglanti; takilma yalniz 'shared'da ise bayat baglanti). Bulut/VM'den calistirilamadi (API anahtari 401). DOGRULANMADI: gercek kosu. Komut (Mac): ./.venv/bin/python scripts/llm_stall_probe.py A1 --calls 60 ; bayat baglanti icin ayrica --pause 15 --calls 30
- Olcum (Mac, 2026-11-01): scripts/llm_stall_probe.py A1 v5, 180 cagri (60 shared + 60 fresh, pause 0; 30 + 30, pause 15). Takilma YOK: 0 cagri >5 sn, 0 hata; p50 0,90-0,97 sn, p95 1,18-1,77 sn, max 2,17 sn; shared ile fresh farksiz, 15 sn bosta kalma da bayat baglanti uretmedi. Kanit: evidence/llm-stall-A1-20261101-100258.json, -101859.json.
- Sonuc: 29 Ekim'deki 18-55 sn takilmalar (%10-14) sirali tek cagri kosusunda yeniden uretilemedi -> bayat baglanti ve thinking elendi; en olasi gecici API/ag olayi, ama KANITLANMADI. Kisa zaman asimi + yeniden deneme eklenmedi (neden dogrulanmadi). Siradaki: eval_prompt.py A1 --variants v5 (ana set ve holdout) yeniden; p95 ~1-2 sn cikarsa gecikme sapmasi kapanir, kalan yalniz sema %98,7.

## Session 039 - ElevenLabs Agent ayri faza tasindi (2026-11-01)
- Kullanici ElevenLabs'ta bir agent olusturdu; senaryoyu agent'a verip aramayi onun yonlendirmesini istiyor. Karar: ayri faz (Faz 3), ea-001 not_started. Kurulum notlari, mimari fark ve riskler docs/faz-elevenlabs-agent.md'de.
- Dogrulanmadi: agent ile gercek arama, workflow/arac ekranlari, Turkce kalite, maliyet. Girdi bekleniyor: agent kimligi, arac tanimi.

## Session 040 - hibrit konusma katmani karari + hum-001 (2026-11-01)
- Karar (kullanici): "hibrit ile devam", akisi LLM yonetmez; LLM cevaplari daha insansi hale getirilir. Sebepler ve uygulama sirasi: docs/adr/0009-hibrit-konusma-katmani.md; demo cevabi S43.
- Yapildi (hum-001): persona.reaction/bucket_of, reaction_rate, reactions havuzu (config/persona.json: 6 kova, 3-4 cumle), FlowDriver tepki secimi (rng, tekrarsiz, 'reaction' olayi), Persona ekraninda kova ve oran duzenleme. 703 backend + 104 frontend test gecti, tsc ve build temiz.
- Dogrulanmadi: gercek aramada dinleme; 'daha insansi' iddiasi olculmedi. Cumle havuzu henuz kullanici gozden gecirmesinden gecmedi. hum-001 BLOCKED.
- Siradaki (onay bekliyor): calisma anı LLM uretimi (plan disi soru, anlasilmayan cevapta tekrar); A1 v5 olcumunun yeniden alinmasi (eval_prompt.py A1 --variants v5, ana set + holdout).

## Session 041 - Kiyas matrisi bosluklari (2026-11-01)
- Kullanici: "olculmedi olan alan kalmamali, gercek matrisi gorelim". Gercek veriyle matris hesaplandi: Cevap dogrulugu hicbir profilde yoktu (kosular evidence/'taydi, matris data/llm-evals/ okuyordu) ve Kaynak kullanimi hic hesaplanmiyordu.
- Yapildi: scripts/import_llm_evidence.py (6 gercek LLM kosusu data/llm-evals/'e alindi, yeni sayi uretmez); Kaynak kullanimi = arama basi API $ + GPU sn x varsayilan GPU saat fiyati (config/matrix.json, 1 $/sa VARSAYIM, dogrulanmadi); "uygulanamaz" (L5/realtime'da STT, realtime'da ayri LLM) olculmedi'den ayrildi ve agirlik paydasindan cikar. 706 backend + 105 frontend test gecti.
- Matris sonrasi KALAN BOS (9 hucre, yeni olcum gerekir): L3/L4/L5 kaynak (yeni arama), L4/L5 gecikme (yeni arama), L2-EL/A2/A3 dogallik (insan dinleme puani), A2/A3 kaynak (realtime kullanim kaydi + fiyat yok). Dogallik n=2-3, L3 WER n=2: ince.
- L1 kosusu (kullanici, 26/40 iptal): q3'te "Hayir, katilmadim." gemma4:e4b tarafindan 3 kez anlasilmadi -> sistem_sonlandirdi; tamamlanan 26 cagrida >2 cevap yok. LLM testi (%76,7) ile tutarli. Matriste L1 83,5 puanla ust sirada: matris anket TAMAMLAMA'yi olcmuyor (kriter eksik, oneri).

## Session 042 - Kiyas matrisine "Anket tamamlama" kriteri (2026-11-01)
- Kullanici: L1 hicbir sey anlamiyor ama 2. siradaydi; tamamlanma orani sirayi degistirir, hemen yap. Eklendi: completion kriteri = Kiyas kosularinda (data/eval-runs, status=ok) yolun beklenen sonucuna ulasan cagri orani (tam_katilim->tamamlandi, ret->katilmak_istemedi, geri_arama->geri_arama; belirsiz yol sayilmaz). Agirlik 25 (config/matrix.json), digerleri degismedi; toplam %100'e normalize.
- Gercek sonuc: L2 77/77, L2-EL 58/60, A1 30/30, L1 6/20 (yalniz geri_arama), L4 0/30. L1 toplam 83,5 -> 72,8 (2. -> 4. sira); L2 89,9 ile 1., L2-EL 81,0 (dogallik eksik, kapsam %80), A1S 75,4 (tamamlama eksik).
- Testler: eski iki test (parse_weights, gecersiz agirlik 422) kriter listesi 6'ya ciktigi icin GIRDIsi guncellendi (completion:0 eklendi), amaci ayni; 2 yeni test (beklenen sonuc sayimi, tamamlayamayan profil dusuyor). 708 backend + 105 frontend gecti.
- Duzeltme: sunumdaki "L1, L4 icin kayitli arama yok" ifadesi YANLISTI; ikisinin de Kiyas kosusu var (L1 6/20, L4 0/30). Sunum duzeltildi.
- Hala bos: L3/L5/A1S/A2/A3 tamamlama (Kiyas kosusu yok), L5 gecikme+kaynak, L3/A2/A3 kaynak, L2-EL/A2/A3 dogallik (dinleme puani).

## Session 043 - core-010: STT'siz hat (L5) kodu (2026-11-01)
- Kullanici: L5 hazirlanamiyor; sebep: STT'siz profilde sesli arama ve Kiyas kosusu bilerek reddediliyordu (core-010 baslamamisti). Karar (kullanici): "1'i yap" = core-010'u gercekten yap.
- Yapildi: bkz. feature_list core-010 notlari. Ses OpenAI uyumlu uc noktadan input_audio olarak gider; model JSON'a transcript ekler, ayni korumalar (enjeksiyon, olumsuz evet/hayir, kimlik sorusu) transkript uzerinde calisir; bos transkript = anlasilmadi. 718 backend test gecti (10 yeni), 1 regresyon yakalanip duzeltildi (offer dogrulamasi LLM ornegi yerine profil bayragina bakiyor).
- Dogrulanmadi / acik: Ollama'nin bu modelle ses kabul edigi (varsayim), dogruluk, gecikme kazanci, gurultude metin uydurma (STT gecidi yok; tek savunma istem). core-010 'passing' DEGIL.
- Not: backend/app/providers/base.py, local.py?, config/profiles.yaml Mac klasorunde yerinde yazmaya kapaliydi; kopyala-yeniden adlandir ile guncellendi (icerik ayni, yalniz bu degisiklikler).
- Mac yoklamasi (14:47, evidence/audio-llm-gemma4-12b-20261101-144734.json): 15 cagri, hata yok, ama 15/15 bos cevap, p50 5,9 sn. Ses yolunun CALISTIGI kanitlanmadi (bos cevap = model sesi duymadi ya da dusunmeye token harcadi). Tani eklendi (reasoning_effort=none + bos cevapta finish_reason/reasoning_chars). L5 icin hicbir gecikme/dogruluk iddiasi yok.
- core-010 BLOCKED (15:13): reasoning_effort=none ile model cevap veriyor (JSON %100, sicak p50 ~1,1 sn) ama dogruluk yetersiz: evet/hayir 4/10 (4 'hayir' -> 'evet': TEHLIKELI, yanlis kayit), rakam 0/14; esik %95. Kanit: evidence/audio-llm-gemma4-12b-20261101-151243.json, -151302.json. L5 matriste 'elendi' olarak kaydedildi (gerekce kayitli, ekrandan geri alinabilir). Denenmeyen: baska model/tasima.
- L5 canli (3 oturum, kullanici): hepsi q3'te ters kapandi. Kok neden 1: model value'yu transkriptten ONCE yaziyordu (f42e: transkript 'hayir', value=true). Duzeltme: transcript ilk alan + kapali sozlukte kural modelin value'sunu ezer (audio_override olayi, 3 yeni test, 721 backend gecti). Kok neden 2 (duzeltilemedi): yanlis duyma (64e9: 'katilmadim' -> 'evet'; 6d28: 'sa'); bu modelin isitme hatasi. Bekleyen: ayni 3 cumleyle yeniden canli deneme.

## Session 044 — UI düzeltmeleri
- Kıyas matrisi: sınıfsız düğmeler tarayıcı varsayılanı (gri kutu) görünüyordu → `theme.css`'e taban `button` stili eklendi. Tablo hücrelerindeki rozetler komşu hücreyle çakışıyordu → hücre içeriği alt alta (skor / n / rozet), mükerrer `.mx-table min-width` birleştirildi.
- Playground: "Konuşmayı kaydet (ses)" varsayılan AÇIK (kullanıcı kararı 2026-11-01; core-013'teki ilk karar gizlilik için kapalıydı — demoda gerekçeyi söyle: kayıtlar yalnızca bu bilgisayarda data/voice-sessions/, her kayıt tek tıkla silinebilir, kutu işaretsiz bırakılınca kayıt alınmaz). Kayıt kutusu sadeleşti (oynatıcı · İndir · Sil); mikrofon eşiği/söz kesme ayarları tek bir "Mikrofon ayarları" açılır bölümüne toplandı.
- Test: frontend 106 geçti (1 yeni test: işaret kaldırılınca record:false), tsc temiz.
- Açık: Aramalar listesinde "Kaynak" rozeti/filtresi (Canlı / Kıyas koşusu) kararı bekliyor.
- Session 044 (devam): oturum kimliği kopyalama düğmesi (`CopyIdButton`: Playground kayıt kutusu, Aramalar listesi satırı ve detay başlığı; pano API'si yoksa textarea yedeği). Sol üst boşluk: `.brand` yüksekliği topbar ile aynı 64 px ve kenar boşluğu -12 px (çizgi kenardan kenara). Kıyas koşusu panelleri: `.page > .panel` arası 18 px boşluk (kenarlıklar yapışıyordu). Test: frontend 107 geçti.
- Session 044 (devam 2): Persona ekranına kapsam notu ("Neye etki eder?": anket / yalnız serbest sohbet / realtime) ve alan etiketleri; test eklendi (frontend 108). Kod incelemesi: `persona.system_prompt` yalnızca `VoiceSession` serbest sohbet yolunda (flow=None, kademeli profil) kullanılıyor; Playground ilk senaryoyu otomatik seçtiği için pratikte işlevsiz. Demo notu S47. DİKKAT (süreç): bulut→Mac senkronda aynı staged yol adıyla ikinci yazma eski içeriği bırakabiliyor; her sync sonrası md5 doğrula, gerekirse yeni dosya adıyla gönder (theme.css bu yüzden iki kez eksik kaldı).
- Session 044 (devam 3): lab-004 ve hum-001 `passing`. Kanıt: kullanıcının canlı A1S aramaları 59685a0edc32, 087a5df79e68, 488d98ab8e28, ea40c9d0712a (data/voice-sessions JSON+WAV). Transkript incelemesi: tepki tekrarı yok; ilk ses medyanı 1,3–2,16 sn (hedef 1,2 sn tutmuyor). Eksik/kısıt: `reaction` olayı oturum JSON'unda yok; gecikme artışı için taban karşılaştırması yok. core-027 için 4/5 arama; blocked. TTS: bu aramalar eleven_v4_turbo (enerjik/sakin) ile yapıldı. Not: ea40c9d0712a'da "Ne demek, rica ederim" → "Sorunuzu not aldım" yanlış cevabı (off_topic köprüsü düzeltmesi sonrası yeniden denenmeli).
- Session 044 (devam 4): Kullanıcı A1S TTS'ini (eleven_v4_turbo) onayladı; core-025 notuna işlendi (durum not_started kaldı, sebep notta). Sunum "Elediklerimiz" slaytı L5 ölçümüyle güncellendi (artifact v7). Demo S48, S49 eklendi.
- Session 044 (devam 5): Fiyat doğrulama: config/pricing.json (ElevenLabs herkese açık sayfa, Deepgram pay-as-you-go, Haiku 5.5 resmî sayfa) `verified: true`, kaynaklar ve tarih (2026-11-01) işlendi. Kullanıcının ElevenLabs hesap sayfalarına (subscription/api, agents) giriş yapılamadı (giriş gerekiyor; kimlik bilgisi girmedim). Maliyet senaryosu: demo S50. Sunum slaytları (maliyet, gecikme, ölçümler, gecikme kalemleri, bilinmeyenler) henüz güncellenmedi.
- Session 044 (devam 6): Kullanıcı ElevenLabs hesap fiyat ekranlarını paylaştı (TTS API, ElevenAgents): TTS API fiyatları kamuya açık sayfayla aynı çıktı. ElevenAgents: $0,08/dk barındırma + LLM + telefon; eşzamanlılık 4–40 (plana göre). Demo S51, ea-001 notu. Sunum slaytları hâlâ eski rakamlarda (kullanıcı onayı bekleniyor).

- Session 044 (devam): Demo v2 slaytları güncellendi (maliyet, gecikme, ölçümler, bileşenler, bilinmeyenler): 17 canlı A1S araması, p50 1,56 sn, $0,035/dk, 477 oturum. Kıyas koşusu A1S gecikmesi (p50 ~2,7) simüle/toplu STT olduğundan temsil etmiyor. ElevenLabs Starter plan: kredi azalıyor, demo öncesi yükle. Açık: core-027 (1,2 sn hedefi tutmadı), core-016 canlı barge-in provası, A1 v5 yeniden ölçüm.

- Session 045: STT test ekranına 'Müşteri + Ajan ayrı (referanssız)' eklendi (lab-002 EK). Bulut: backend 724, vitest 109, tsc temiz. Mac'te gerçek stereo kayıtla doğrulanmadı. Açık: mono kayıtta diarization yok; konuşma sırası (diyalog) gösterilmiyor.
- Session 045 (devam): STT test 'Ses çözülemedi: Format not recognised' düzeltildi. Backend: libsndfile okuyamazsa ffmpeg yedeği (m4a/AAC, WAV adlı başka biçim); frontend: sunucu çözemezse tarayıcıda WAV'a çevirip bir kez yeniden dener, çeviri artık stereo korur (önceden m4a mono olup Müşteri+Ajan ayrı modunu bozardı). Bulut: backend 725, vitest 111. Kullanıcının hatalı dosyasıyla Mac'te doğrulanmadı.
- Session 045 (devam 2): STT test 'float division by zero' (500) düzeltildi: kullanıcının dosyası çözülüyor ama 0 örnek veriyordu (yarım kalmış WAV başlığı olasılığı; dosya doğrulanmadı). read_audio 0 örnekte ffmpeg dener, yine boşsa 400 'Ses çözülemedi: ses boş ...' (bayt sayısı ve ffmpeg çıktısı mesajda); API 0 sn sesi 400 ile reddeder. Bulut: backend 726. Kullanıcının dosyasıyla Mac'te doğrulanmadı.
- Session 045 (devam 3): STT test ekranı: işlem sürerken spinner + geçen süre ('Model çalışıyor… N sn'), sonuçlarda 'TXT indir' (frontend/src/sttExport.ts; model başına bölüm, Müşteri/Ajan ayrı modunda etiketli satırlar). Bulut: vitest 115, tsc temiz. Mac'te gerçek koşuyla görülmedi. Not: spinner yalnızca 'çalışıyor' gösterir; model içi ilerleme yüzdesi yok (sunucu tek istekte döner).
- Session 045 (devam 4): STT test yükleme sınırı 25 MB/180 sn -> 200 MB/20 dk (SVA_STT_MAX_MB, SVA_STT_MAX_SECONDS ile ayarlanır). Sebep: stereo görüşme kayıtları 25 MB'ı aşıyor. Risk: uzun sesi yerel modeller (Whisper, BuzzASR) yavaş işler; BuzzASR'ın uzun sesi parçalayıp parçalamadığı doğrulanmadı. Bulut: backend 727.
- Session 045 (devam 5): STT test sınırı 1 GB / 2 saat (1 saatlik görüşme kaydı için). Riskler: bellek (1 sa stereo 44,1 kHz ≈ 1,3 GB float32 + kopyalar), süre (mlx-whisper RTF ~0,13: kanal başına ~8 dk; Müşteri+Ajan ayrı modunda iki kanal), her koşu sesi data/stt-runs altına yazar (1 sa stereo 16 kHz ≈ 230 MB). 1 saatlik gerçek dosyayla doğrulanmadı.

- Session 046 (2026-11-02, müdür sunumu hazırlığı, Opus ajanlarıyla): (1) off-001 passing (offline): konu dışı + bağlama bağlı karşılık, commit 85b74c0, 802 backend test; canlı LLM/telefon doğrulanmadı. (2) STT yavaşlık analizi (oturum 888090ca1304): yavaşlık akışta değil toplu yedekte (düşük güven/akış zaman aşımı); docs/stt-yavaslik-analizi.md. (3) docs/elevenlabs-workflow-gecis.md: anket tamamen ElevenAgents workflow'u olarak (bizim servis çağrısı yok); 20 madde doğrulanmadı. (4) Sunuma 'Geliştirme alanları' slaytı eklendi (v38); docs/sunum-gelistirme-alanlari.md. Açık: onay_tekrar koşulu uygulanmıyor, q100 devre dışı; stream_finish_timeout_s ayarı ölçülmeli; A1S zaman aşımı 11-01'de 275, bugün 1.

- Session 046 (devam): off-002 (blocked): lokal Qwen ile serbest cevap (commit a035d11, ADR 0009 adım 2), yalnızca konu dışı/meta turlarda; sahte istemciyle 881 backend + 117 frontend test geçti; GERÇEK QWEN ile ölçülmedi, Mac'te scripts/eval_free_reply.py --runs 3 çalıştırılacak. Maliyet slaydı (8) ElevenAgents tahmini güncellendi: 6,65 dk görüşme LLM $0,17 -> ~$0,105/dk, A1S'in ~3 katı.

- Session 046 (devam 2): off-002 gerçek Qwen ölçümü (Mac, 96 tur): geçen 0,75, p50 0,78 / p95 1,23 sn. counter+clarify iyi; weather/chitchat/joke/other uydurma cümleler -> canlı kategoriler yalnızca counter+clarify. off-002 passing (yalnız bu kapsam). Backend 882 test geçti (bulut).

- Session 046 (devam 3): serbest cevap istemi v2 (6 few-shot örnek; eski istemin 2 örneği eval setiyle aynıydı, v1 ölçümü şişmiş olabilir). 883 backend test geçti (bulut). v2 ile gerçek Qwen koşusu bekleniyor: scripts/eval_free_reply.py --runs 3; off-002 tekrar blocked.

- Session 046 (devam 4): Qwen thinking ayarı eklendi (7ddf760, sahte istemciyle test; gerçek ölçülmedi). v2 istem gerçek ölçümde geriledi (zaman aşımı 1 -> 19/96, p50 0,78 -> 1,37 sn counter+clarify); istem v3 (3 örnek). 907 backend test geçti (bulut). v3 gerçek koşu bekleniyor.
- Session 046 (devam 5): istem v3 gerçek ölçüm: counter+clarify 32/42 geçti, zaman aşımı 6, p50 0,98 sn; ilk vaka (f01) 3/3 zaman aşımı (ısınma şüphesi). Öneri: ısınma turu + timeout 2,0 sn; uygulanmadı. off-002 blocked.

- Session 046 (devam 6): 'Cevaba bağlı tepkiler' aç/kapa ayarı (a72116c). Oturum 05d1cd392eb3 (L2-EL) analizi: yavaşlık LLM düşünmesi değil; STT 9,95 sn + Qwen 5,4 sn, ikisi de ~20 dk boşta kalmış yerel modellerin ilk çağrısı (soğuk/ısınma şüphesi, kanıtlanmadı); docs/llm-yavaslik-05d1cd392eb3.md. AÇIK HATA: müşteri yeniden konuşunca atılan tur (barge-in, turn_id) akışa cevabı yine de kaydedip bir sonraki adıma geçiyor (session.py _flow_reply / _on_frame) -> müşteri KVKK sorusunu tekrar duydu. Düzeltilmedi. Yerel sağlayıcılar için arama başı ısınma yok (registry.prewarm yalnız uzak).

- Session 046 (devam 7): (a) Söz kesme: canlı kayıtlarda bağıran/yüksek sesli konuşma süzgeçte engelleniyordu; düzeltildi (cd820c2), offline yeniden oynatmayla doğrulandı, canlı yeniden deneme bekliyor; ikinci olası neden (çok kısa söylemler) kanıtlanamadı. (b) Haiku ile serbest cevap + istem v4 + kategori genişletme (4742bbe, 922428e; off-003 blocked: gerçek Haiku ölçümü yok). 1021 backend, 129 vitest (bulut). Backend yeniden başlatılmalı.

- Session 046 (devam 8): gerçek Haiku serbest cevap ölçümü (istem v4): canlı 68/90 geçti, zaman aşımı 4, p50 1,30 / p95 1,96 sn, ~$0,0002/tur; off-003 passing. Denetim yanlış reddi: too_long (6), not_turkish (f12), number_word (f23). Uzun cümlede söz kesme şikayeti cd820c2 ile kapanıyor (230e02c), backend yeniden başlatıldığı doğrulanmadı.

- Session 046 (devam 9): off-003 istem v5 ve denetim düzeltmeleri. Haiku zaman aşımı 2,0 -> 2,5 sn (ölçüm p95 1,957 / max 2,059 sn). Yanlış retler: f27 istem reddi, f23 saat yankısı, f12/f17/f24 'için' tokenizasyon hatası düzeltildi; gerçek ihlaller testli olarak hâlâ ret; yeni name_claim ('Ben Selin'). İstem v5 (22 kelime, ölçeği yalnız sorulunca, ad uydurma yasağı). Çevrimdışı yeniden denetim: 8 yanlış ret kurtarıldı, 17/17 ihlal yakalandı (evidence/free-reply-haiku-reaudit-20261103.md). 1057 backend geçti (1 skip), 129 vitest, tsc temiz (bulut). v5'in gerçek Haiku etkisi ÖLÇÜLMEDİ: Mac'te eval --backend haiku koşulmalı; backend yeniden başlatılmalı.

- Session 046 (devam 11): off-004 passing (yalnız sahte istemci) — serbest cevap anket cevabı olmayan her turda + düzenlenebilir sistem istemi. Kullanıcı isteği: havuz değil, anlamlı cevap ve ankette tutma; örnek Q3X'te 'Eşim yaptı galiba görüşmeyi, ben cevaplasam olur mu' -> eskiden 'tam anlayamadım'. free_reply: istem v6 (DEFAULT_SYSTEM düzenlenebilir + sabit FRAME + config facts), system_prompt/fallback_text/use_pool_fallback_only ayarları (4000 karakter, kontrol karakteri temizliği, boş=varsayılan), prompt_hash özel istemi kapsar ve tur kaydına yazılır, sondaki soru kırpılır (çift soru yok), META_REFUSAL 'talimatlarımı paylaşamam' kalıbı, name_claim 'asistanım, Selin'. flow: _retry ve sayısız _clarify_score geniş kapsamda LLM karşılığı + retry_of; başarısızlıkta nötr yedek (KVKK/olgusal kategorilerde havuz). Geniş kapsam yalnız Haiku (Qwen ölçümü uydurma). API + FreeReplySettings istem düzenleyici (sayaç, kaydet/geri al/varsayılana sıfırla, etkin istem önizleme, yedek cümle). eval --system-file. Testler: backend 1097 geçti/1 atlandı (yeni test_free_reply_wide.py 34), vitest 134, tsc temiz. 7 test beklentisi bilinçli güncellendi (docs/serbest-cevap-genis-kapsam.md 'Test güncellemeleri'). ÖLÇÜLMEDİ: gerçek Haiku ile geniş kapsam (uydurma, gecikme); backend yeniden başlatılmalı. Demo S62.

- Session 046 (devam 10): eval-006 passing — kıyas koşusunda isteğe bağlı ses kaydı. StereoRecorder'a sanal zaman çizelgesi (timeline="virtual": ajan bloğu biter, müşteri klibi sonra yerleşir, çakışma yok; canlı "wall" kipi değişmedi), evalrun.run_call(record_audio) + JSON audio {synthetic:true}, POST /api/evalrun/runs record_audio (varsayılan false, koşu kaydına işlenir, aramada has_audio), BenchmarkPage "Ses kaydını sakla" onay kutusu + "Aramalar'da dinle". Testler: backend 1063 geçti/1 atlandı, vitest 131, tsc temiz. Doküman docs/kiyas-ses-kaydi.md, demo S61. DOĞRULANMADI: gerçek profil/klip setiyle koşu ve kulakla dinleme, tarayıcıda uçtan uca.

- Session 046 (devam 9): gerçek Haiku v5 ölçümü: canlı 69/90, too_long 0, p50 1,18 sn; question_mark reddi 4->12 (Haiku kendi sorusunu ekliyor), f27 'talimat' reddi, f30 'Selin' name_claim kaçağı, f12 3/3 zaman aşımı. Düzeltmeler bekliyor.

- Session 046 (devam 10): geniş kapsam (off-004) kullanıcı kararıyla yerel Qwen için de açıldı (wide_scope_backends haiku+qwen). 17 eski-mod testi use_pool_fallback_only=False'a sabitlendi, silinmedi. Qwen geniş kapsamda ölçülmedi.

- Session 046 (devam 11): geniş kapsam gerçek ölçüm: Haiku varsayılan 87/96 (p50 1,15 sn), Haiku özel istem 56/96, Qwen varsayılan 83/96 (p50 0,83 sn), Qwen özel istem 54/96. Bulgular: 'benim fikrim' yanlış reddi, 4000 karakter sınırı istem.txt'yi (5483) kesti, tam-ajan istemi cevap uzunluğu kuralı olmadığı için reddediliyor, Qwen kalitesi pass oranından kötü.
