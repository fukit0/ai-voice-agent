#!/bin/bash
# Manifestteki her satır için mikrofondan 3 sn kayıt alır (16 kHz mono WAV). Gerekli: ffmpeg (brew install ffmpeg).
# Kullanım: bash scripts/record_stt_clips.sh [başlangıç_no]   (kaldığınız yerden devam için)
cd "$(dirname "$0")/.." || exit 1
python3 - "$@" <<'PY'
import json, subprocess, sys, time
tty = open("/dev/tty")          # heredoc stdin'i doldurduğu için Enter'ı terminalden okuruz
start = int(sys.argv[1]) if len(sys.argv) > 1 else 1
rows = json.load(open("data/stt-clips/manifest.json"))
for i, r in enumerate(rows, 1):
    if i < start:
        continue
    what = r["text"] or "ÖKSÜRÜN / boğazınızı temizleyin / nefes alın / masaya vurun"
    print(f"\n[{i}/{len(rows)}] {r['category']}: SÖYLEYİN -> «{what}»   (Enter'a basın, 1 sn sonra kayıt başlar)", end=" ", flush=True)
    tty.readline()
    time.sleep(1)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "avfoundation", "-i", ":0", "-t", "3", "-ar", "16000", "-ac", "1",
                    f"data/stt-clips/{r['file']}"], check=True)
    print("  kaydedildi:", r["file"])
PY
