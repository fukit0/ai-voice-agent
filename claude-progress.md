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
- Current highest-priority unfinished feature: lab-001 (TTS stüdyosu ve kör dinleme)
- Current blocker: yok (lab-002 notu: mikrofon düğmesi elle denenmedi; BuzzASR indirilmedi)

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
