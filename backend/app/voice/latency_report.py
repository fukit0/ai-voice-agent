"""Oturum kayıtlarından profil bazlı gecikme karşılaştırması (core-011 madde 5: A2/A3 ve L2, 5 test araması).

Girdi: data/voice-sessions/*.json (VoiceSession ve RealtimeVoiceSession aynı şemayı yazar). Gecikme tanımı iki hatta da
aynıdır: yerel VAD'in konuşma bitişini yakaladığı andan ajanın ilk sesine kadar (`first_audio_after_end_s`).
Açılış (greeting) turları hariçtir. Bu araç ölçmez, yalnızca kayıtları özetler; ölçümler gerçek aramalardan gelmelidir.
"""
from __future__ import annotations

import json
import statistics
from pathlib import Path

P50_TARGET_S = 1.2        # Faz 1 kapısı: p50 < 1,2 sn
MIN_SESSIONS = 5          # core-011: aynı 5 test araması


def _pct(values: list[float], q: float) -> float:
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def load_sessions(folder: Path, scenario: str | None = None) -> list[dict]:
    out = []
    for path in sorted(folder.glob("*.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if not isinstance(doc, dict) or "turns" not in doc or "profile" not in doc:
            continue
        if scenario and (doc.get("flow") or {}).get("scenario") != scenario:
            continue
        out.append(doc)
    return out


def summarize(sessions: list[dict], profiles: list[str] | None = None) -> dict:
    by_profile: dict[str, dict] = {}
    for doc in sessions:
        pid = doc["profile"]
        if profiles and pid not in profiles:
            continue
        turns = [t for t in doc["turns"] if not t.get("greeting") and "first_audio_after_end_s" in t]
        if not turns:
            continue
        entry = by_profile.setdefault(pid, {"sessions": 0, "values": [], "realtime": False, "session_ids": []})
        entry["sessions"] += 1
        entry["session_ids"].append(doc.get("id"))
        entry["realtime"] = entry["realtime"] or bool(doc.get("stats", {}).get("realtime"))
        entry["values"].extend(float(t["first_audio_after_end_s"]) for t in turns)
    rows = {}
    for pid, e in by_profile.items():
        v = e["values"]
        rows[pid] = {"sessions": e["sessions"], "turns": len(v), "p50_s": round(statistics.median(v), 3),
                     "p95_s": round(_pct(v, 0.95), 3), "min_s": round(min(v), 3), "max_s": round(max(v), 3),
                     "realtime": e["realtime"], "meets_p50_target": statistics.median(v) < P50_TARGET_S,
                     "enough_sessions": e["sessions"] >= MIN_SESSIONS, "session_ids": e["session_ids"]}
    return {"definition": "VAD konuşma bitişinden ajanın ilk sesine (açılış turu hariç)", "p50_target_s": P50_TARGET_S,
            "min_sessions": MIN_SESSIONS, "profiles": dict(sorted(rows.items()))}


def render(report: dict) -> str:
    lines = [f"Gecikme (VAD bitişi -> ilk ses). Hedef p50 < {report['p50_target_s']} sn; en az {report['min_sessions']} arama.",
             f"{'profil':8} {'arama':>5} {'tur':>4} {'p50':>7} {'p95':>7} {'min':>6} {'max':>6}  not"]
    for pid, r in report["profiles"].items():
        notes = []
        if not r["enough_sessions"]:
            notes.append(f"örnek yetersiz ({r['sessions']}/{report['min_sessions']} arama)")
        notes.append("hedefte" if r["meets_p50_target"] else "hedef dışı")
        if r["realtime"]:
            notes.append("realtime: ayrı STT/LLM/TTS yok")
        lines.append(f"{pid:8} {r['sessions']:>5} {r['turns']:>4} {r['p50_s']:>7.2f} {r['p95_s']:>7.2f} "
                     f"{r['min_s']:>6.2f} {r['max_s']:>6.2f}  {'; '.join(notes)}")
    if not report["profiles"]:
        lines.append("(kayıtlı oturum yok: Playground'da senaryoyla arama yapın)")
    return "\n".join(lines)
