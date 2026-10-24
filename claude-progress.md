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
- Passing: setup-001, lab-000, core-003, lab-006, lab-002, lab-001, norm-007, eval-llm, core-001 (9 / 50)
- Current highest-priority unfinished feature: lab-003 (in_progress: Senaryolar ekranı tamam; Playground akış entegrasyonu kaldı)
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
