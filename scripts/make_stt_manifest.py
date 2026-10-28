"""STT ölçüm seti için manifest üretir ve kayıt listesini yazdırır (core-020).

    python3 scripts/make_stt_manifest.py            # data/stt-clips/manifest.json
Her satır için bir WAV kaydedilir (dosya adı manifestteki file). Öksürük/gürültü satırlarında text boştur: STT'nin yazıya
dökmemesi ya da STT geçidinin reddetmesi beklenir. Kayıt için: scripts/record_stt_clips.sh
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SETS = [
    ("on", ["on"] * 5),
    ("evet_hayir", ["evet"] * 5 + ["hayır"] * 4 + ["evet evet", "yok", "olabilir"]),
    ("rakam", ["sıfır", "bir", "iki", "üç", "dört", "beş", "altı", "yedi", "sekiz", "dokuz", "on", "yedi", "sekiz", "dokuz"]),
    ("kod_karisimi", ["okay", "okey", "tamam okay", "yes", "ok", "okay devam"]),
    ("kisa_cumle", ["dinlemek isterim", "hatırlıyorum", "müsaitim", "devam", "evet müsaitim", "hayır istemiyorum",
                    "yarın saat on beşte", "sekiz puan veriyorum", "biraz sonra arayın", "beni aramayın"]),
    ("oksuruk", [""] * 4),
    ("gurultu", [""] * 5),
]
rows, n = [], 0
for cat, texts in SETS:
    for t in texts:
        n += 1
        rows.append({"file": f"c{n:02d}.wav", "text": t, "category": cat})
out = ROOT / "data" / "stt-clips"
out.mkdir(parents=True, exist_ok=True)
(out / "manifest.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"{len(rows)} satır -> {out / 'manifest.json'}")
for r in rows:
    print(f"{r['file']}  [{r['category']:12}] {r['text'] or '(öksürük / boğaz temizleme / nefes / masaya vurma — metin yok)'}")
