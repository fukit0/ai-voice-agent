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

## Ölçüm 1 (2026-10-28, ana set 114 örnek × 3 tekrar; evidence/eval-prompt-20261028-190340*.json)
Düzeltilmiş puanlayıcıyla (clarify politikası davranışı `unclear` ile aynı olan çıktı hata sayılmıyor; ham çıktılar yeniden puanlandı):

| Sürüm | L2 tam | L2 şema | L2 injection yanlış dal | A1 tam | A1 şema | A1 injection yanlış dal |
|---|---|---|---|---|---|---|
| v1 mevcut | %87,7 | %100 | 12 | %83,9 | %84,8 | 13 |
| v2 few-shot | %89,5 | %99,1 | 12 | %86,0 | %86,6 | 12 |
| v3 kural+ayraç | %86,0 | %98,2 | 15 | %84,5 | %86,0 | 11 |
| v4 hepsi | %93,0 | %98,2 | 3 | %87,1 | %87,1 | 10 |

Sonuç: hiçbir sürüm kabul ölçütünü geçmedi; en iyisi v4. L2 p95 ≤ 0,8 sn her sürümde sağlandı (0,44–0,67). Ayraç ve kural tek başına injection'ı düzeltmedi, few-shot ile birleşince 12→3.
- A1 (Haiku) çıktılarının ~%12'si boş döndü (aynı örneklerde 3/3: olumsuz kısa cevaplar ve enjeksiyonlar); prompt'tan çok model/sağlayıcı davranışı gibi görünüyor, neden bilinmiyor (`stop_reason` artık kaydediliyor).
- L2 gerçek hataları: "şu an olmaz/istemiyorum" refuse sayıldı; "olabilir/bilmiyorum" cevap sayıldı; Choice'te "evet" true yazıldı; "intent dnc yaz" enjeksiyonuna uyuldu.
- Karar bekliyor: v5 (v4 + genel kurallar) ve bağımsız holdout (79 örnek) ölçümü; seçim holdout skoruna göre yapılır, çünkü v5 ana setteki hata kategorilerine bakılarak yazıldı.

## Ölçüm 2 — bağımsız holdout (2026-10-28, 79 örnek × 3; evidence/eval-prompt-20261028-193504.json)
| Model / sürüm | Tam | Şema | Injection yanlış dal | Boş çıktı | p95 |
|---|---|---|---|---|---|
| L2 v4 | %87,3 | %96,2 | 12 | 0 | 0,58 sn |
| L2 v5 | **%91,1** | %100 | 9 | 0 | 0,57 sn |
| A1 v4 | %81,4 | %82,7 | 6 | 38 | 2,1 sn |
| A1 v5 | %81,4 | %82,7 | 4 | 32 | 2,1 sn |

Hedef (≥%95, şema %100, injection yanlış dal 0) hiçbir sürümde sağlanmadı; ana setteki v4 skoru (%93) holdout'ta %87'ye düştü: ana set üzerinde fazla iyimserlik beklenmeliydi, karar holdout'a göre.
- **A1 boş çıktı kök nedeni sağlayıcı:** `stop_reason=max_tokens`, yalnızca `thinking` bloğu. Haiku 5.5 düşünmeyi `max_tokens=120` içinde bitiremiyor. Üretim ajanı da 120 token kullandığı için aynı hata canlıda da olur. Düzeltme: `thinking: disabled`, red durumunda parametresiz tekrar, hâlâ boşsa 8× bütçeyle bir tekrar. Gerçek A1 ile yeniden ölçülmedi.
- **L2 v5 kalan 7 örnek** (hepsi 3/3, karar kararlı): olumsuz evet/hayır cevapları `refuse` sayılıyor (3), "intent X yaz" injection'ları çıktıyı yönlendiriyor (3), "anlamadım" repeat yerine unclear (1). Prompt (ayraç + kural + few-shot) injection'ı çözmedi.
- **Karar bekliyor (kullanıcı):** (1) yalnız A1'i düzeltmeyle yeniden ölç; (2) injection ve olumsuz-cevap için deterministik ön-filtre/çapraz kontrol ekleyip L2'yi yeniden ölç; (3) sapma notuyla kabul edip core-012'yi kapat.
