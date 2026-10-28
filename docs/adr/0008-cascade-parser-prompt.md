# ADR 0008 — Kademeli hat cevap ayrıştırma isteminin ölçümü ve dondurulması (core-012)

Durum: uygulama tamam, ölçüm bekliyor (2026-10-28). Not: plan metninde "ADR 0006" yazıyordu; 0006 STT seçimine verildiği için bu karar 0008.

## Karar
- Ölçülen şey ajanın kullandığı istemdir: `flow.build_messages` + `FlowDriver.handle_structured`. Eski `llm_eval` kendi promptu ve şemasıyla ayrıydı (dnc yoktu), bu yüzden ADR 0003'teki "ölçümler doğrudan geçerli" cümlesi düzeltildi.
- İstem sürümleri `config/prompts/cascade-parser.json`: v1 mevcut, v2 few-shot, v3 tipe özel kurallar + `<musteri>` ayraçlı müşteri sözü (injection), v4 = v2+v3. Aktif sürüm config'te; sürüm adı + hash her cascade oturum loguna (`flow.prompt`) yazılır.
- Veri seti `config/eval/prompt-samples.json`: 114 örnek, gerçek anket/welcome adımları, altı adım tipi (her biri ≥12), altkümeler: normal, dnc, multi, injection, noisy. Beklenen değerler model çıktısı görülmeden yazıldı ve sha256 ile dondurulur; test hash'i doğrular.
- Intent öncelik sırası (v3 kuralı): dnc > refuse > callback > repeat > answer. Injection tutumu: müşteri sözü talimat değildir; cevaplanabilir içerik yoksa unclear; ölçütte yanlış dal 0.
- Kabul: tam doğruluk ≥ %95, şema geçerliliği %100, injection yanlış dal 0, L2 p95 ≤ 0,8 sn (L2 ve A1, 3 tekrar).

## Reddedilen / ertelenen
- Ayrı eval promptu tutmak (üretimden sapar). Native tool-calling (sağlayıcılar arası karşılaştırma bozulur; ayrı ölçüm).
- 'LLM testi' ekranında varyant seçimi: bu turda yapılmadı, komut satırı aracı (`scripts/eval_prompt.py`) var.

## Bilinen sınırlar
- Ölçüm sonucu henüz yok; aktif sürüm (v1) kanıtsız. Seçim ölçümden sonra bu ADR'ye yazılır.
- `clarify` puan politikası sözlü iki sayı ve okunamayan sayı durumunda modelden bağımsız netleştirir; veri setinde bu iki örnek ilk ölçümden önce değiştirildi.
- Veri seti tek yazar, metin bazlı (gerçek STT çıktısı değil); noisy altküme yalnızca 7 örnek.
