# ADR 0009 — Hibrit konuşma katmanı: akışı kod yönetir, cümle doğallığını LLM/havuz artırır

Tarih: 2026-11-01 · Durum: kabul edildi (kullanıcı kararı) · İlgili: ADR 0003 (FlowDriver), ADR 0005 (realtime hibrit), Faz 3 (docs/faz-elevenlabs-agent.md)

## Karar
Ajanı daha insansı yapmak için akışı (FlowDriver) LLM ile DEĞİŞTİRMİYORUZ. Durum, dal, cevap kaydı, tip denetimi ve DNC kod tarafında kalır. İnsansılık konuşma katmanında artırılır: cevaba bağlı tepkiler, çeşitlilik, plan dışı sorulara kısa cevap ve geri dönüş, anlaşılmadığında doğal tekrar. LLM bu katmanda cümle ÜRETİR ya da cümle havuzunu yazar; akışı yönetmez.

## Sebepler
- İnsansılığı çoğunlukla gecikme, ses/tonlama, tur alma ve cümle çeşitliliği belirler; akışı kimin yönettiği değil.
- Bir anketin asıl çıktısı doğru toplanmış cevaplardır. Akışı LLM'e vermek adım atlama, yanlış dal, yanlış kayıt riskini ve her turda LLM gecikmesini getirir (hızlı yol kazancı kaybolur). DNC gibi yasal sonuçların kodla garanti edilmesi gerekir.
- Hibrit, esnekliğin güvenli kısmını (doğal cümle) alır; riskli kısmını (karar) koddan çıkarmaz.

## Uygulama sırası
1. (hum-001, yapıldı) Cevaba bağlı tepki havuzu: kovalar (düşük/orta/yüksek puan, evet, hayır, diğer), aynı aramada tekrarsız, `reaction_rate` ile bazen sessiz. LLM tarafından yazılan, insan gözden geçirmesine açık havuz; çalışma anında LLM çağrısı YOK, gecikme maliyeti sıfır. Ekrandan düzenlenir (Persona).
2. (sonraki, onay bekliyor) Çalışma anında LLM ile üretim: plan dışı soru cevabı, geçiş cümleleri, anlaşılmayan cevapta doğal tekrar. Kısıtlar: bekleyen soruyu içermeli, uzunluk sınırı, yasak kalıp denetimi, zaman aşımında havuza/sabit metne düşüş. Gecikme bütçesi ayrıca ölçülür.
3. (sonraki) Açık uçlu adımlarda anlaşılmazsa yeniden sorma: LLM yargıcı (ayrı prompt, etiketli set gerekir).

## Demoda söylenecek
"İnsansılığı gecikme, ses ve cümle katmanında artırıyoruz; cevap doğruluğunu ve yasal sonuçları kodla garanti ediyoruz." Karşı tezin (akış LLM'de) farkı Faz 3'te aynı 5 persona x 4 yol ile ölçülecek; ölçülene kadar "agent daha iyi/kötü" denmez.

## Sınırlar (dürüst durum)
- Tepki havuzu elle/LLM ile yazıldı, dinleyici testinden geçmedi; "daha insansı" iddiası ölçülmedi. Ölçüt önerisi: aramada tekrar eden tepki sayısı (kodla ölçülebilir) + kör dinleme puanı.
- Çalışma anı LLM üretimi henüz yok; plan dışı sorularda hâlâ sabit metinler konuşur.
