"""Kıyas matrisi (lab-005, plan F6.2/F7.5): profil başına kriter puanları ve ağırlıklı toplam.

Girdiler Lab'in zaten ürettiği kayıtlardır; bu modül ÖLÇMEZ, yalnızca toplar ve puanlar. Hiçbir kriter için sayı uydurulmaz: veri yoksa
kriter "eksik" kalır, toplam yalnızca verisi olan kriterlerin ağırlığına bölünür ve `coverage` (verisi olan ağırlık payı) açıkça döner.

Kriter ← kaynak ← 0-100 puan kuralı
- latency     ← data/voice-sessions (calls.compare, profil bazlı p50)      ← p50 ≤ 1,2 sn → 100, ≥ 3,0 sn → 0, arası doğrusal (config/matrix.json)
- naturalness ← data/tts-sessions kör dinleme puanları (naturalness 1-5)   ← (ortalama-1)/4×100; profilin TTS'iyle (provider+model, ya da kimlik) eşleşen puanlar
- accuracy    ← data/llm-evals (summary.full_rate, en yeni koşu)           ← full_rate×100; profilin LLM'iyle (provider+model) eşleşen
- wer         ← data/stt-runs (ok sonuçların wer ortalaması)               ← (1-WER)×100, 0'a kırpılır; profilin STT'siyle (provider+model, "+ ipucu" varyantı hariç) eşleşen
- resources   ← ölçülmüyor (eval-003 başlamadı)                            ← her zaman eksik
Lisans eleme: profilin herhangi bir bileşeni için config'te commercial_ok=false ise satır elenir; null/yok = belirsiz uyarısı (elenmez).
Sıralama: yalnızca elenmemiş ve kapsamı ≥ min_coverage olan satırlar sıralanır; diğerlerinde toplam yoktur (az veriyle birinci olamasın).
"""
from __future__ import annotations

import json
import os
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import calls, stt_runs, tts_studio as studio
from .profiles import load_profiles

ROOT = Path(__file__).resolve().parents[2]

CRITERIA: list[dict[str, str]] = [
    {"id": "latency", "label": "Gecikme", "source": "Aramalar (ilk ses p50)", "rule": "p50 ≤ 1,2 sn → 100, ≥ 3,0 sn → 0"},
    {"id": "naturalness", "label": "Doğallık (kör dinleme)", "source": "TTS stüdyosu dinleyici puanları", "rule": "(ortalama−1)/4×100"},
    {"id": "accuracy", "label": "Cevap doğruluğu", "source": "LLM testi (tam doğru oranı)", "rule": "oran×100"},
    {"id": "wer", "label": "STT hatası (WER)", "source": "STT test koşuları", "rule": "(1−WER)×100"},
    {"id": "resources", "label": "Kaynak kullanımı", "source": "ölçülmüyor (eval-003)", "rule": "—"},
]
IDS = [c["id"] for c in CRITERIA]


def config_path() -> Path:
    return Path(os.environ.get("SVA_MATRIX", ROOT / "config" / "matrix.json"))


def load_config() -> dict[str, Any]:
    cfg = json.loads(config_path().read_text(encoding="utf-8"))
    cfg.setdefault("weights", {i: 0 for i in IDS})
    cfg.setdefault("min_coverage", 0.5)
    cfg.setdefault("latency", {"full_score_s": 1.2, "zero_score_s": 3.0})
    cfg.setdefault("license", {})
    return cfg


def parse_weights(text: str | None, defaults: dict[str, float]) -> dict[str, float]:
    """`latency:30,naturalness:25,...`; verilmeyen kriter varsayılanını korur. Hatalıysa ValueError (API 422 döner)."""
    out = {i: float(defaults.get(i, 0)) for i in IDS}
    for part in filter(None, (text or "").split(",")):
        key, _, raw = part.partition(":")
        key = key.strip()
        if key not in IDS:
            raise ValueError(f"Bilinmeyen kriter: {key or part}")
        try:
            val = float(raw)
        except ValueError:
            raise ValueError(f"Ağırlık sayı olmalı: {part}") from None
        if val < 0 or val != val or val > 1000:
            raise ValueError(f"Ağırlık 0-1000 arası olmalı: {part}")
        out[key] = val
    if sum(out.values()) <= 0:
        raise ValueError("En az bir kriterin ağırlığı sıfırdan büyük olmalı.")
    return out


# ---------- puan kuralları (saf) ----------
def clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def latency_score(p50: float, full_s: float, zero_s: float) -> float:
    if zero_s <= full_s:
        raise ValueError("zero_score_s, full_score_s'ten büyük olmalı")
    return round(clamp((zero_s - p50) / (zero_s - full_s) * 100), 1)


def naturalness_score(mean_rating: float) -> float:
    return round(clamp((mean_rating - 1) / 4 * 100), 1)


def wer_score(wer: float) -> float:
    return round(clamp((1 - wer) * 100), 1)


def accuracy_score(rate: float) -> float:
    return round(clamp(rate * 100), 1)


def combine(scores: dict[str, float | None], weights: dict[str, float], min_coverage: float) -> dict[str, Any]:
    """Ağırlıklı toplam yalnızca verisi olan kriterler üzerinden; `coverage` = verisi olan ağırlık / toplam ağırlık."""
    total_w = sum(weights.values())
    have = {k: s for k, s in scores.items() if s is not None and weights.get(k, 0) > 0}
    avail_w = sum(weights[k] for k in have)
    coverage = avail_w / total_w if total_w else 0.0
    total = round(sum(weights[k] * s for k, s in have.items()) / avail_w, 1) if avail_w and coverage >= min_coverage else None
    return {"total": total, "coverage": round(coverage, 3),
            "missing": [k for k in IDS if weights.get(k, 0) > 0 and scores.get(k) is None]}


# ---------- veri toplama ----------
def _key(spec: dict | None) -> tuple[str, str] | None:
    return (spec["provider"], spec.get("model") or "") if spec else None


def tts_rows() -> list[dict]:
    root = studio.sessions_dir()
    if not root.is_dir():
        return []
    rows: list[dict] = []
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        rows.extend(studio._resolved_rows(folder.name))
    return rows


def stt_results() -> list[dict]:
    out: list[dict] = []
    for summary in stt_runs.list_runs(limit=500):
        run = stt_runs.get_run(summary["id"]) or {}
        out.extend(r for r in run.get("results", []) if r.get("status") == "ok" and r.get("wer") is not None)
    return out


def llm_runs() -> list[dict]:
    root = stt_runs.data_dir() / "llm-evals"
    if not root.is_dir():
        return []
    runs = []
    for p in root.glob("*.json"):
        try:
            runs.append(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue          # bozuk koşu dosyası tabloyu düşürmesin
    return sorted(runs, key=lambda r: r.get("created_at", ""), reverse=True)


def _tts_match(row: dict, pid: str, spec: dict | None) -> bool:
    if row.get("profile") == pid:
        return True
    if not spec or row.get("provider") != spec["provider"]:
        return False
    return not spec.get("model") or row.get("model") == spec["model"]


def build(weights_text: str | None = None) -> dict[str, Any]:
    cfg = load_config()
    weights = parse_weights(weights_text, cfg["weights"])
    lat_cfg = cfg["latency"]
    profiles = load_profiles()
    latency = {g["key"]: g for g in calls.compare(stt_runs.data_dir() / "voice-sessions", "profile")["groups"]}
    nat_rows, wer_rows, llms = tts_rows(), stt_results(), llm_runs()
    pct = {k: round(v / sum(weights.values()) * 100, 1) for k, v in weights.items()}

    rows = []
    for pid, prof in profiles.items():
        metrics: dict[str, dict | None] = {i: None for i in IDS}
        g = latency.get(pid)
        if g and g.get("first_audio"):
            p50 = g["first_audio"]["p50"]
            metrics["latency"] = {"value": p50, "unit": "sn", "score": latency_score(p50, lat_cfg["full_score_s"], lat_cfg["zero_score_s"]),
                                  "n": g["sessions"], "note": None if g["enough_sessions"] else "örnek az (<5 arama)"}
        mine = [r for r in nat_rows if _tts_match(r, pid, prof.components.get("tts"))]
        if mine:
            mean = statistics.mean(r["naturalness"] for r in mine)
            metrics["naturalness"] = {"value": round(mean, 2), "unit": "/5", "score": naturalness_score(mean), "n": len(mine),
                                      "note": f"insansı {statistics.mean(r['humanlike'] for r in mine):.2f}/5"}
        stt = prof.components.get("stt")
        if stt:
            hits = [r for r in wer_rows if r["provider"] == stt["provider"] and r["model"] == (stt.get("model") or "")]
            if hits:
                w = statistics.mean(r["wer"] for r in hits)
                metrics["wer"] = {"value": round(w, 4), "unit": "WER", "score": wer_score(w), "n": len(hits), "note": f"{len(hits)} koşu"}
        llm = prof.components.get("llm")
        if llm:
            for run in llms:
                hit = next((x for x in run.get("results", []) if x.get("provider") == llm["provider"] and x.get("model") == (llm.get("model") or "")
                            and x.get("status") == "ok" and x.get("summary", {}).get("full_rate") is not None), None)
                if hit:
                    rate = hit["summary"]["full_rate"]
                    metrics["accuracy"] = {"value": rate, "unit": "oran", "score": accuracy_score(rate), "n": run.get("n_samples"),
                                           "note": f"koşu {run.get('id')}"}
                    break
        comps = [("STT", stt), ("LLM", llm), ("TTS", prof.components.get("tts"))] if prof.mode != "realtime" else [("Realtime", prof.realtime)]
        components, lic = [], []
        for kind, spec in comps:
            if not spec:
                continue
            k = _key(spec)
            entry = cfg["license"].get(f"{k[0]}:{k[1]}")
            components.append({"kind": kind, "provider": k[0], "model": k[1]})
            lic.append({"kind": kind, "model": f"{k[0]}:{k[1]}", "license": (entry or {}).get("license", "Tabloda yok"),
                        "commercial_ok": (entry or {}).get("commercial_ok"), "verified": bool((entry or {}).get("verified"))})
        eliminated = any(x["commercial_ok"] is False for x in lic)
        unknown = [x["model"] for x in lic if x["commercial_ok"] is None]
        res = combine({i: (metrics[i] or {}).get("score") for i in IDS}, weights, cfg["min_coverage"])
        rows.append({"profile": pid, "name": prof.name, "mode": prof.mode, "components": components, "metrics": metrics,
                     "total": None if eliminated else res["total"], "coverage": res["coverage"], "missing": res["missing"],
                     "eliminated": eliminated, "license": lic, "license_unknown": unknown, "rank": None})

    ranked = sorted((r for r in rows if r["total"] is not None), key=lambda r: (-r["total"], -(r["metrics"]["latency"] or {}).get("score", 0)))
    for i, r in enumerate(ranked, 1):
        r["rank"] = i
    return {"criteria": [{**c, "weight": weights[c["id"]], "weight_pct": pct[c["id"]]} for c in CRITERIA], "weights": weights,
            "defaults": cfg["weights"], "min_coverage": cfg["min_coverage"], "rows": rows,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "notes": ["Kaynak kullanımı ölçülmüyor (eval-003 başlamadı): bu kriter her satırda eksiktir ve toplam kalan ağırlığa bölünür.",
                      "Lisans tablosu model kartlarından canlı doğrulanmadı; yalnızca açıkça commercial_ok=false olan eler."]}
