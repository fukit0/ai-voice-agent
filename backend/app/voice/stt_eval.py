"""core-020: Türkçe kısa cevap / kod karışımı STT ölçümü ve STT geçidi (sttguard) eşik raporu.

Girdi: klip manifesti (JSON liste ya da CSV): file (wav yolu, manifest klasörüne göre), text (beklenen yazı; öksürük/gürültü için boş),
category (on | evet_hayir | rakam | kod_karisimi | uzun | gurultu | oksuruk ...). Boş referans = "kabul edilmemesi gereken" klip.
Çıktı: sağlayıcı bazında WER, yabancı yazı ve halüsinasyon oranları; geçit için doğru/yanlış reddetme ve eşik taraması.
Ölçüm gerçek klip gerektirir; bu modül hesabı yapar, klipleri toplamaz (core-013 kayıtları).
"""
from __future__ import annotations

import csv
import json
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ..providers.audio import decode_audio
from ..wer import normalize_tr, wer
from . import sttguard

NOISE_CATEGORIES = {"gurultu", "oksuruk", "bogaz", "sessiz", "noise", "cough"}
MIN_CLIPS = 50


@dataclass
class Clip:
    file: str
    text: str
    category: str

    @property
    def should_reject(self) -> bool:
        """Beklenen yazısı olmayan (öksürük/gürültü) klip: geçit bunu reddetmeli."""
        return not self.text.strip() or self.category in NOISE_CATEGORIES


def load_manifest(path: Path) -> list[Clip]:
    path = Path(path)
    if path.suffix == ".csv":
        rows = list(csv.DictReader(path.read_text(encoding="utf-8").splitlines()))
    else:
        rows = json.loads(path.read_text(encoding="utf-8"))
    clips = [Clip(file=str(path.parent / r["file"]), text=r.get("text", "") or "", category=r.get("category", "diger") or "diger")
             for r in rows]
    missing = [c.file for c in clips if not Path(c.file).exists()]
    if missing:
        raise FileNotFoundError(f"{len(missing)} klip bulunamadı, ilki: {missing[0]}")
    return clips


def transcribe_all(clips: list[Clip], stt) -> list[dict]:
    """Her klibi sağlayıcıyla çevirir; sttguard'ın baktığı ek alanlar (güven, logprob...) saklanır."""
    out = []
    for c in clips:
        audio, rate = decode_audio(Path(c.file).read_bytes())
        res = stt.transcribe(audio, rate)
        out.append({"file": c.file, "category": c.category, "reference": c.text, "hypothesis": res.text,
                    "seconds": round(res.seconds, 3), "extra": {k: v for k, v in (res.extra or {}).items()
                                                               if isinstance(v, (int, float))},
                    "should_reject": c.should_reject})
    return out


def _is_wrong(r: dict) -> bool:
    """Cevap klibi için yanlış yazım (guard'ın yakalaması istenen), gürültü klibi için herhangi bir yazı."""
    if r["should_reject"]:
        return bool(r["hypothesis"].strip())
    return normalize_tr(r["hypothesis"]) != normalize_tr(r["reference"])


def guard_decision(r: dict, thresholds: dict | None = None) -> str | None:
    t = thresholds or {}
    saved = (sttguard.MIN_CONFIDENCE, sttguard.MIN_AVG_LOGPROB, sttguard.MAX_COMPRESSION)
    try:
        sttguard.MIN_CONFIDENCE = t.get("min_confidence", saved[0])
        sttguard.MIN_AVG_LOGPROB = t.get("min_avg_logprob", saved[1])
        sttguard.MAX_COMPRESSION = t.get("max_compression", saved[2])
        return sttguard.check(r["hypothesis"], r["extra"])[1]
    finally:
        sttguard.MIN_CONFIDENCE, sttguard.MIN_AVG_LOGPROB, sttguard.MAX_COMPRESSION = saved


def guard_rates(rows: list[dict], thresholds: dict | None = None) -> dict:
    """Doğru reddetme = hatalı/gürültü klibini reddetti; yanlış reddetme = doğru yazılmış klibi reddetti."""
    bad = [r for r in rows if _is_wrong(r)]
    # Gürültü/öksürük klibinde STT'nin boş dönmesi doğru sonuçtur (yazı yok); geçidin boş metni "empty" diye reddetmesi
    # yanlış ret sayılmaz. Yanlış ret yalnızca doğru yazılmış cevap klibi içindir.
    good = [r for r in rows if not _is_wrong(r) and not r["should_reject"]]
    rej_bad = sum(1 for r in bad if guard_decision(r, thresholds))
    rej_good = sum(1 for r in good if guard_decision(r, thresholds))
    return {"bad_clips": len(bad), "good_clips": len(good),
            "true_reject_rate": round(rej_bad / len(bad), 3) if bad else None,
            "false_reject_rate": round(rej_good / len(good), 3) if good else None}


def threshold_sweep(rows: list[dict]) -> list[dict]:
    """Güven / logprob / sıkıştırma eşiklerini küçük bir ızgarada tarar; yanlış reddetme ≤ %5 olanlardan en çok hatalıyı yakalayanı önerir."""
    grid = []
    for conf in (0.3, 0.4, 0.5, 0.6, 0.7):
        for lp in (-1.5, -1.25, -1.0, -0.75):
            for cr in (2.0, 2.4, 2.8):
                th = {"min_confidence": conf, "min_avg_logprob": lp, "max_compression": cr}
                grid.append({**th, **guard_rates(rows, th)})
    return grid


def recommend(grid: list[dict], max_false_reject: float = 0.05) -> dict | None:
    ok = [g for g in grid if g["false_reject_rate"] is not None and g["true_reject_rate"] is not None
          and g["false_reject_rate"] <= max_false_reject]
    return max(ok, key=lambda g: (g["true_reject_rate"], -g["false_reject_rate"]), default=None)


def summarize(rows: list[dict]) -> dict:
    answers = [r for r in rows if not r["should_reject"]]
    per_cat: dict[str, dict[str, Any]] = {}
    for cat in sorted({r["category"] for r in rows}):
        sub = [r for r in answers if r["category"] == cat]
        w = [wer(r["reference"], r["hypothesis"]).wer for r in sub]
        w = [x for x in w if x is not None]
        per_cat[cat] = {"clips": sum(1 for r in rows if r["category"] == cat),
                        "mean_wer": round(statistics.mean(w), 3) if w else None}
    reasons = [guard_decision(r) for r in rows]
    n = len(rows) or 1
    all_w = [wer(r["reference"], r["hypothesis"]).wer for r in answers]
    all_w = [x for x in all_w if x is not None]
    return {"clips": len(rows), "enough_clips": len(rows) >= MIN_CLIPS,
            "mean_wer": round(statistics.mean(all_w), 3) if all_w else None,
            "exact_match_rate": round(sum(1 for r in answers if not _is_wrong(r)) / (len(answers) or 1), 3),
            "foreign_script_rate": round(reasons.count("foreign_script") / n, 3),
            "hallucination_rate": round(reasons.count("hallucination_phrase") / n, 3),
            "noise_transcribed_rate": round(sum(1 for r in rows if r["should_reject"] and r["hypothesis"].strip())
                                            / (sum(1 for r in rows if r["should_reject"]) or 1), 3),
            "p50_seconds": round(statistics.median(r["seconds"] for r in rows), 3) if rows else None,
            "by_category": per_cat, "guard_default": guard_rates(rows)}


def evaluate(clips: list[Clip], providers: dict[str, Any], transcribe: Callable = transcribe_all) -> dict:
    report: dict[str, Any] = {"min_clips": MIN_CLIPS, "clips": len(clips), "providers": {}}
    for name, stt in providers.items():
        rows = transcribe(clips, stt)
        grid = threshold_sweep(rows)
        report["providers"][name] = {**summarize(rows), "recommended_thresholds": recommend(grid),
                                     "rows": rows}
    return report


def render(report: dict) -> str:
    lines = [f"STT ölçümü: {report['clips']} klip (hedef ≥ {report['min_clips']})."]
    lines.append(f"{'sağlayıcı':14} {'WER':>6} {'tam':>6} {'yabancı':>8} {'halüs.':>7} {'gürültü→yazı':>13} {'doğru red':>10} {'yanlış red':>11}")
    for name, p in report["providers"].items():
        g = p["guard_default"]
        f = lambda v: "-" if v is None else f"{v:.3f}"  # noqa: E731
        lines.append(f"{name:14} {f(p['mean_wer']):>6} {f(p['exact_match_rate']):>6} {f(p['foreign_script_rate']):>8} "
                     f"{f(p['hallucination_rate']):>7} {f(p['noise_transcribed_rate']):>13} {f(g['true_reject_rate']):>10} "
                     f"{f(g['false_reject_rate']):>11}")
        if not p["enough_clips"]:
            lines.append(f"  ! örnek yetersiz ({p['clips']}/{report['min_clips']} klip): sonuç karar için kullanılamaz")
        rec = p["recommended_thresholds"]
        if rec:
            lines.append(f"  önerilen eşik: güven {rec['min_confidence']}, logprob {rec['min_avg_logprob']}, sıkıştırma {rec['max_compression']}"
                         f" (doğru red {rec['true_reject_rate']}, yanlış red {rec['false_reject_rate']})")
    return "\n".join(lines)
