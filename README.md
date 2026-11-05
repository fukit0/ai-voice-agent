# Sahibinden Sesli Anket Ajanı — Lab (PoC)

Müşteriyi arayıp kısa bir anket soran, insan gibi konuşmasını hedeflediğimiz sesli ajanın **test ve kıyas laboratuvarı**. Bu repo iki şey içerir:

- **Backend (FastAPI):** ses hattı (STT → LLM → TTS), deterministik anket akışı (`FlowDriver`), profiller, ölçüm ve kayıt.
- **Dashboard / Lab (React + Vite):** ajanla konuşma, kayıtlı aramaları inceleme, profilleri kıyaslama, ses/STT/LLM test araçları ve ayarlar.

> Bu doküman yeni bir geliştiricinin dashboard'u **kurup çalıştırıp kullanabilmesi** için yazıldı. Karar gerekçeleri `docs/adr/` ve `docs/` altında, sunum soruları `docs/demo-soru-cevap.md` içinde.

---

## 1. Mimari (kısa)

```
Mikrofon ─▶ STT ─▶ FlowDriver (kural + fast path) ─▶ LLM (yalnız gerektiğinde) ─▶ TTS ─▶ Hoparlör
                         │
                         └─ Anlaşılmayan / konu dışı söz ─▶ Serbest cevap (LLM) + kod anket sorusunu ekler
```

- **Akışı kod yönetir**, LLM değil: hangi soruyu soracağımıza, ne zaman kapatacağımıza kod karar verir. LLM yalnız müşterinin cümlesini anlamlandırır ve konu dışı sözlere kısa cevap yazar.
- **Fast path:** "evet / hayır / 7" gibi net cevaplar LLM'e gitmeden kuralla çözülür (daha hızlı ve ucuz).
- **Serbest cevap:** konu dışı veya anlaşılmayan sözlere LLM insan gibi kısa bir cevap verir; anket sorusunu **kod** ekler. Çıktı denetimi (yasak kalıp, rakam, soru işareti, uzunluk vb.) kapatılamaz. Ayar: Ayarlar ekranı.

### Profiller

| Profil | STT | LLM | TTS | Not |
|---|---|---|---|---|
| L1–L3, L2 | local | local (Ollama/Qwen) | local (Chatterbox) | Maliyetsiz, tek ses/ton |
| L2-EL | local | local | ElevenLabs | |
| A1 | Deepgram | Claude Haiku 5.5 | ElevenLabs | API |
| **A1S** | Deepgram (streaming) | Haiku 5.5 | ElevenLabs (streaming) | **Demo profili** |
| A2, A3 | realtime (speech-to-speech) | — | — | Anlama zayıf kaldı |

Profil tanımları: `config/profiles.yaml`.

---

## 2. Gereksinimler

| Gerekli | Not |
|---|---|
| macOS (Apple Silicon) | Lokal modeller için; `requirements.txt` bu ortamdan üretildi |
| Python 3.11 + [uv](https://github.com/astral-sh/uv) | venv ve paket kurulumu |
| Node.js + npm | Frontend (`npm ci`) |
| [Ollama](https://ollama.com) | Lokal LLM profilleri ve Qwen serbest cevap için |
| API anahtarları | A1 / A1S için: Deepgram, Anthropic, ElevenLabs |
| Mikrofon | Playground'da canlı konuşma için |

Yalnız API profillerini (A1S) deneyecekseniz Ollama ve lokal modeller şart değildir.

---

## 3. Kurulum (adım adım)

### Adım 1 — Repoyu alın
```bash
git clone <repo-url> sahibinden-voice-agent
cd sahibinden-voice-agent
```

### Adım 2 — API anahtarlarını girin
```bash
cp .env.example .env     # .env git'e girmez
```
`.env` içinde doldurun:
```
DEEPGRAM_API_KEY=...        # STT (A1/A1S)
ANTHROPIC_API_KEY=...       # LLM (Haiku)
ELEVENLABS_API_KEY=...      # TTS
ANTHROPIC_WORKSPACE_ID=...  # yalnız anahtar bir workspace'e bağlı değilse (400: "not scoped to a workspace")
# İsteğe bağlı: ELEVENLABS_VOICE_ID (Persona > Ses stüdyosu'ndan da atanabilir), OPENAI_API_KEY, GEMINI_API_KEY, OLLAMA_URL
```

### Adım 3 — Ortamı hazırlayın ve doğrulayın
```bash
./init.sh
```
`init.sh` sırayla: `.venv` oluşturur, `requirements.txt` ve `npm ci` ile bağımlılıkları kurar, **backend + frontend testlerini** koşar, Ollama'yı (yoksa) başlatır ve model sağlık kontrolü yapar. Çıktı `evidence/init-<zaman>.log` dosyasına yazılır.

| Komut | Ne yapar |
|---|---|
| `SKIP_MODEL_CHECKS=1 ./init.sh` | Yalnız ortam + testler (API profilleri için yeterli) |
| `SKIP_INSTALL=1 ./init.sh` | Bağımlılık kurulumunu atla |
| `FULL_CHECK=1 ./init.sh` | Chatterbox dahil tam model kontrolü |
| `MODELS_ONLINE=1 ./init.sh` | Eksik modeli Hugging Face'ten indir (varsayılan çevrimdışı) |
| `RUN_START_COMMAND=1 ./init.sh` | Kontrollerden sonra Lab'i başlat |

İlk kurulumda modeller `~/.cache/huggingface` altına iner (uzun sürebilir); sonra tekrar inmez.

### Adım 4 — Lab'i başlatın
```bash
scripts/dev.sh     # Geliştirme: FastAPI (8000, --reload) + Vite (5173) → http://localhost:5173
scripts/demo.sh    # Demo/ölçüm: arayüzü derler, backend tek süreç, --reload YOK → http://localhost:8000
```
Kod değiştiriyorsanız `dev.sh`. **Gecikme ölçümü veya demo için `demo.sh`**: `--reload` backend'i yeniden başlatıp ısıtılmış modelleri bellekten attığı için ölçümü bozar (ADR 0001).

---

## 4. Dashboard'u kullanma

Sol menüde beş grup altında 11 ekran var.

### Genel
- **Genel Bakış** (`/overview`): görüşme sayısı, tamamlanma, süre, tepki süresi, söz kesme, sonuç dağılımı.

### Arama
- **Playground** (`/playground`): ajanla mikrofonla konuşun.
  1. Profil (demo için **A1S**) ve senaryo seçin.
  2. **Hazırla** ile modelleri/bağlantıları ısıtın (soğuk ilk istek yavaştır; ölçümden önce şart).
  3. Konuşmayı başlatın; canlı transkript ve **tur başına STT / LLM / TTS gecikmesi** görünür.
  4. Bitince görüşme **Aramalar** ekranına kaydedilir.

### Kayıtlar & Raporlar
- **Aramalar** (`/calls`): liste ve detay: transkript, ses kaydı, çıkarılan cevaplar, tur gecikmeleri. Kıyas koşusu aramaları `synthetic` etiketlidir.
- **Kıyas matrisi** (`/matrix`): koşular ve dinleme puanlarından dolan ağırlıklı karşılaştırma (`config/matrix.json`).

### Yapılandırma
- **Senaryolar** (`/scenarios`): anket adımları, okunacak metinler, cevaba göre akış; okunuş önizlenir.
- **Persona** (`/persona`): ajan adı, ton, hitap, cümle uzunluğu sınırı, onay sözleri; oluşan istem canlı görünür. Tona ses **Ses stüdyosu**ndan atanır.
- **Ayarlar** (`/settings`): **Serbest cevap** (sistem istemi, en çok 8000 karakter; yedek metin; backend seçimi; Haiku zaman aşımı), tepki ve söz kesme (barge-in) ayarları.

### Lab araçları
- **TTS stüdyosu** (`/tts`): ses ve tonları dinleyin, karşılaştırın.
- **STT test** (`/stt`): ses klipleriyle tanıma hatasını ve gürültüye tepkiyi ölçün.
- **LLM testi** (`/llm`): etiketli cümlelerle doğru cevabın çıkarılıp çıkarılmadığını ölçün.
- **Kıyas koşusu** (`/benchmark`): profilleri **simüle müşteri** ile toplu koşturun. **"Ses kaydı"** kutusu işaretliyse WAV'lar `/api/voice/recordings/{sid}.wav` altında saklanır.

### Tipik iş akışları
| Amaç | Adımlar |
|---|---|
| Demo yapmak | `scripts/demo.sh` → Playground → A1S → Hazırla → konuş → Aramalar'da göster |
| Gecikme ölçmek | `demo.sh` → Hazırla → en az 10–15 arama → Genel Bakış (p50/p95) + Aramalar (tur kalemleri) |
| Profil kıyaslamak | Kıyas koşusu → dinleme puanı gir → Kıyas matrisi |
| Konu dışı cevabı ayarlamak | Ayarlar > Serbest cevap > istemi düzenle → `scripts/eval_free_reply.py` ile ölç |
| Senaryo metni değiştirmek | Senaryolar → düzenle → önizle → Playground'da dene |

---

## 5. Testler

```bash
PYTHONPATH=.:backend python -m pytest backend/tests -q      # backend
cd frontend && npx tsc --noEmit && npx vitest run            # frontend tip + birim
cd frontend && npm run e2e                                   # Playwright E2E
```
Son bilinen sonuç: backend **1124 geçti, 1 atlandı**; frontend **135 geçti**. Testleri sırf geçsin diye silmeyin/zayıflatmayın.

---

## 6. Ölçüm betikleri (`scripts/`)

| Betik | Ne ölçer |
|---|---|
| `latency_probe.py` | Tek klip, tekrarlı gecikme kalemleri |
| `session_latency.py` | Kayıtlı oturumlardan gecikme özeti |
| `stt_eval.py` | STT doğruluğu / gürültü |
| `eval_llm.py`, `eval_prompt.py` | Etiketli cümlede anlama doğruluğu |
| `eval_free_reply.py` | Serbest cevap kalitesi (`--backend haiku\|qwen`, `--runs`, `--system-file`) |
| `reaudit_free_reply.py` | Eski sonuçları güncel denetimle yeniden denetle |
| `eval_barge_gate.py`, `replay_barge_session.py` | Söz kesme eşikleri |
| `healthcheck.py` | Model sağlık kontrolü |

Çıktılar `evidence/` altına, örnek setler `config/eval/` altında.

---

## 7. Metrikler (sunum seti)

> **Okurken dikkat:** Sayılar **metin tabanlıdır, insan dinleme notu yoktur**. A1S rakamları **test aramalarından** gelir (gerçek müşteri trafiği değil). n<20 olanlar yön göstergesidir.

### 7.1 Veri hacmi
| Metrik | Değer |
|---|---|
| Kayıtlı oturum | 497 (129 canlı + 368 Kıyas koşusu) |
| Etiketli cümle (anlama) | 193 (her biri 3 kez) |
| STT ses klibi | 57 |
| Canlı A1S araması (sunum seti) | 17 (54,2 dk) |
| Serbest cevap turu | 1.206 (12 ölçüm: 7 Qwen + 5 Haiku) |

### 7.2 Gecikme (konuşma bitişinden ajanın ilk sesine, p50)
Hedef **p50 ≤ 1,20 sn** (müşterinin duyduğu bekleme, sessizlik tespiti ~0,5 sn kadar daha uzundur).

| Profil | p50 | p95 | n |
|---|---|---|---|
| L2 · local | 1,27 sn | 1,90 | 125 |
| A3 · realtime | 1,43 | 2,57 | 10 |
| **A1S · API + streaming** | **1,56** | 3,28 | 17 canlı arama |
| L2-EL | 1,61 | 2,93 | 94 |
| A2 · realtime | 2,62 | 27,5 | 19 |
| A1 · API | 2,90 | 4,20 | 45 |
| L3 · BuzzASR | 2,92 | 3,93 | 12 |

Hiçbir profil 1,2 sn hedefini tutmadı; **A1S demo profilidir** (L2 daha hızlı ama tek ses/ton).

**Tur başına kalemler (medyan, sn):**

| Profil | STT | LLM | TTS ilk ses |
|---|---|---|---|
| L2 | 0,53 | 0,44 | 0,28 |
| A1S | 0,45 | 0,95 | 0,19 |
| A1 | 1,07 | 1,09 | 0,73 |

Büyük kalem LLM. Streaming (A1 2,90 → A1S 1,56 sn) ve connection warm-up (soğuk LLM çağrısı 1,75–2,6 sn → ~1,0 sn) farkı yarattı. **Fast path** kapsamı %12 (21/172 tur): bu turlarda 0,97 sn, LLM'li turlarda 1,59 sn.

### 7.3 Maliyet (liste fiyatı, A1S)
| Kalem | $/dk | Pay |
|---|---|---|
| TTS (ElevenLabs v4 Turbo) | 0,0336 | %95 |
| STT (Deepgram) | 0,0015 | %4 |
| LLM (Haiku 5.5) | 0,0002 | %0,6 |
| **Toplam** | **≈ 0,035** | |

- Ortalama anket ~**11 sent**; 25.000 dk/ay varsayımıyla ≈ **$882/ay** (telefon operatörü hariç).
- 1.000 arama: en iyi ~$34, ortalama ~$113, en kötü ~$225.
- Alternatif ElevenLabs Agents ≈ $0,105/dk (A1S'in ~3 katı).

### 7.4 Serbest cevap kalitesi (34 vaka × 3 deneme = 96 tur, prompt v7)
| Backend | Denetimi geçen | p50 | p95 | Not |
|---|---|---|---|---|
| **Haiku** | **93/96 (%96,9)** | 1,41 sn | 2,21 | 1 zaman aşımı, ~$0,021 |
| Qwen (local, ısıtılmış) | 69/96 (%71,9) | 0,70 sn | 1,16 | Rakam (10), soru işareti (7), anlamsız cevap geçebilir; üretime hazır değil |

- Soğuk Qwen ilk istekte ~94 sn model yükler → eval öncesi `warm_up_ollama` şart (zaman aşımı 28 → 0). Canlı aramada başlangıç ısıtması **henüz yok**.
- Haiku prompt sürümleri: v4 68/90 → v6 87/96 → v7 93/96.

---

## 8. Bilinen sınırlar

- Sayılar metin tabanlı; **insan dinleme notları boş**, "insan gibi hissettirme" ölçülmedi.
- A1S ölçümleri küçük örneklem ve test aramaları.
- p50 ≤ 1,0 sn hedefi doğrulanmadı; 1,2 sn'yi hiçbir profil tutmadı.
- Qwen ile geniş kapsamlı serbest cevap üretime hazır değil; `realworld_claim` denetimi "bilgi veremem" ifadesinde yanlış pozitif veriyor (düzeltilmedi).
- "Anketi kim cevaplayabilir (eş, üçüncü kişi)" iş kuralı tanımsız; `facts` / istemle tanımlanmalı.
- Söz kesme düzeltmesi backend yeniden başlatması ister (yeni oturum JSON'unda `"peak_strong": 0.9` görmelisiniz).
- Genesys Audio Connector uygunluğu bilinmiyor.
- Demoda "ilk yükleme" bahanesi yerine bu sınırları bilerek anlatın: `docs/demo-soru-cevap.md`.

---

## 9. Dizin yapısı
```
backend/app/        FastAPI; voice/ (flow, free_reply, recording), evalrun, api_*.py
backend/tests/      Backend testleri
frontend/src/       React ekranları (pages/), screens.ts (menü tek kaynak)
config/             profiles.yaml, free-reply.json, persona.json, scenarios/, prompts/, eval/
scripts/            dev/demo, ölçüm ve kıyas betikleri
docs/               ADR'ler, serbest cevap, kıyas ses kaydı, demo soru-cevap
evidence/           Ölçüm ve init kanıt dosyaları
data/               voice-sessions (oturum JSON + WAV)
```

## 10. Çalışma kuralları (CLAUDE.md özeti)
1. Oturum başında `claude-progress.md`, `feature_list.json`, `git log --oneline -5` okunur; `./init.sh` koşulur.
2. Aynı anda **tek özellik**; çalıştırılabilir kanıt olmadan `passing` yazılmaz.
3. Karar değişiklikleri sebebiyle `docs/demo-soru-cevap.md`'ye ve PoC Planı'na işlenir.
4. Bitirirken progress log, feature durumu ve kırık/doğrulanmamış listesi güncellenir; commit atılır.

## 11. Sorun giderme
| Belirti | Çözüm |
|---|---|
| İlk istek çok yavaş | Playground'da **Hazırla**; Qwen için eval/arama öncesi ısıtma |
| `400: not scoped to a workspace` | `.env` içine `ANTHROPIC_WORKSPACE_ID` ekleyin |
| Ollama yanıt vermiyor | `ollama serve`; `OLLAMA_URL` kontrol |
| Model bulunamadı | `MODELS_ONLINE=1 ./init.sh` |
| Ölçümler tutarsız | `dev.sh` değil `demo.sh` kullanın |
| Mikrofon çalışmıyor | Tarayıcıda mikrofon izni verin; `localhost` üzerinden açın |
