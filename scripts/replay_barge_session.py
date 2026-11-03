#!/usr/bin/env python3
"""Söz kesme kararını kayıtlı bir oturumdan offline yeniden oynatır (docs/soz-kesme-analizi-a75c42b14e09-981040abd23b.md).

Girdi: data/voice-sessions/<id>.wav (stereo, sol = ham mikrofon = VAD girişi, sağ = tarayıcıya giden ajan sesi) ve aynı adlı .json
(oturumun vad ayarları: threshold_db, barge_frames, barge_margin_db, voiced_min). Sol kanal üretimdeki Endpointer + BargeTracker'dan
çerçeve çerçeve geçirilir; söz kesme kapısı ajan sesinin çaldığı aralıklarda açılır (sağ kanal > -60 dBFS, 400 ms tutma).

SINIR: ajan durumu ('thinking'/'speaking') kayıtta yoktur, sağ kanaldan YAKLAŞIK çıkarılır; gerçek bir kesmeden sonra ajan sesi
susar, araç ajanın sustuğunu görünce kapıyı kapatır. Sayılar oturum istatistiğiyle ±1-2 olay farklı olabilir (rapor bunu yazar).

Kullanım:
  python scripts/replay_barge_session.py data/voice-sessions/<id>.wav            # mevcut kural
  python scripts/replay_barge_session.py <wav> --peak-strong 0                    # 2026-11-03 öncesi kural (karşılaştırma)
  python scripts/replay_barge_session.py <wav> --detail 131.5:140.2               # aralıktaki yüksek çerçevelerin özellikleri
"""
from __future__ import annotations

import argparse
import json
import sys
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.voice.speechlike import features, is_voiced  # noqa: E402
from backend.app.voice.vad import FRAME, BargeTracker, Endpointer, level_db  # noqa: E402


def load(path: Path) -> tuple[np.ndarray, np.ndarray]:
    with wave.open(str(path)) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), "<i2").reshape(-1, 2).astype(np.float32) / 32768.0
    return x[:, 0], x[:, 1]


def replay(wav: Path, vad_cfg: dict, peak_strong: float | None = None, hang_ms: int = 400, detail: tuple[float, float] | None = None) -> dict:
    left, right = load(wav)
    v = Endpointer()
    if vad_cfg.get("threshold_db") is not None:
        v.configure(threshold_db=vad_cfg["threshold_db"])
    v.configure(barge_frames=vad_cfg.get("barge_frames"), barge_margin_db=vad_cfg.get("barge_margin_db"),
                voiced_min=vad_cfg.get("voiced_min"), peak_strong=peak_strong)
    g = BargeTracker(v)
    hang, last_agent, quiet, muted = hang_ms // 20, -10 ** 9, 0, False
    events, lines = [], []
    for i in range(len(left) // FRAME):
        fl, fr = left[i * FRAME:(i + 1) * FRAME], right[i * FRAME:(i + 1) * FRAME]
        t = round(i * FRAME / 16000, 2)
        if level_db(fr) > -60:
            last_agent, quiet = i, 0
        else:
            quiet += 1
        if muted and quiet >= 10:          # kesmeden sonra ajan sustu: bir sonraki ajan sesi yeni tur
            muted = False
        active = (i - last_agent) <= hang and not muted
        v.feed(fl)
        if not active:
            g.reset()
            continue
        verdict = g.update(fl, t)
        if detail and detail[0] <= t <= detail[1] and v.level > v.barge_level_db:
            pk, z, hf = features(fl)
            lines.append(f"{t:7.2f} müşteri {v.level:6.1f} dBFS ajan {level_db(fr):6.1f} | perde {pk:.2f} zcr {z:.3f} ≥400Hz {hf:.2f} "
                         f"sesli={'E' if is_voiced(fl, peak_strong=v.peak_strong) else '-'} koşu={g.run} sesli_sayısı={g.voiced}")
        if verdict == "barge":
            events.append({"t_first_loud": round(g.t0, 2), "t_cut": t, "kind": "barge", "cut_ms": round((t - g.t0) * 1000) + 20})
            muted = True
            g.reset()
        elif verdict == "blocked":
            events.append({"t_cut": t, "kind": "blocked"})
    return {"settings": v.settings(), "events": events, "barge": sum(e["kind"] == "barge" for e in events),
            "blocked": sum(e["kind"] == "blocked" for e in events), "detail": lines}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("wav", type=Path)
    ap.add_argument("--peak-strong", type=float, default=None, help="0 = 2026-11-03 öncesi kural; boş = mevcut varsayılan")
    ap.add_argument("--detail", default=None, help="başlangıç:bitiş (sn)")
    a = ap.parse_args()
    meta = a.wav.with_suffix(".json")
    vad_cfg = json.loads(meta.read_text(encoding="utf-8")).get("vad", {}) if meta.exists() else {}
    det = tuple(map(float, a.detail.split(":"))) if a.detail else None
    r = replay(a.wav, vad_cfg, a.peak_strong, detail=det)
    print("\n".join(r["detail"]))
    print(json.dumps({k: r[k] for k in ("settings", "barge", "blocked", "events")}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
