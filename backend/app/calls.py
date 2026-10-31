"""Aramalar (lab-004): data/voice-sessions/ altındaki test aramalarının listesi, detayı ve profil/arama bazlı kıyası.

Girdi VoiceSession ve RealtimeVoiceSession'ın yazdığı oturum JSON'larıdır (şema: `voice/session.py close()`); bu modül ölçmez,
yalnızca kayıtları özetler. Gecikme tanımı `voice/latency_report.py` ile aynıdır: yerel VAD'in konuşma bitişinden ajanın ilk sesine
kadar (`first_audio_after_end_s`), açılış turu hariç. Eski kayıtlarda `stt`/`llm`/`tts`/`tts_tone` alanları yoktur; ekran bunları
"bilinmiyor" gösterir (profil kimliği yine ayırt eder).
"""
from __future__ import annotations

import statistics
from pathlib import Path
from typing import Any

from .voice.latency_report import MIN_SESSIONS, P50_TARGET_S, _pct, load_sessions

STAGES = (("stt", "stt_s"), ("llm", "llm_s"), ("tts_first", "tts_first_s"), ("tts_total", "tts_total_s"))


def _med(values: list[float]) -> float | None:
    return round(statistics.median(values), 3) if values else None


def _turns(doc: dict) -> list[dict]:
    return [t for t in doc.get("turns", []) if not t.get("greeting")]


def _has_audio(folder: Path, doc: dict) -> bool:
    return (folder / f"{doc.get('id')}.wav").is_file() and not (doc.get("audio") or {}).get("deleted")


def summary(doc: dict, folder: Path) -> dict[str, Any]:
    turns = _turns(doc)
    flow = doc.get("flow") or {}
    answers = flow.get("answers") or []
    transcript = doc.get("transcript") or []
    stats = doc.get("stats") or {}
    first = [float(t["first_audio_after_end_s"]) for t in turns if "first_audio_after_end_s" in t]
    return {
        "id": doc.get("id"), "profile": doc.get("profile"), "started_at": doc.get("started_at"),
        "scenario": flow.get("scenario"), "outcome": flow.get("outcome"),
        "duration_s": transcript[-1].get("t") if transcript else stats.get("seconds_in"),
        "turns": len(turns), "answers": sum(1 for a in answers if not a.get("unanswered")),
        "unanswered": sum(1 for a in answers if a.get("unanswered")),
        "first_audio_p50_s": _med(first), "first_audio_max_s": round(max(first), 3) if first else None,
        **{f"{name}_p50_s": _med([float(t[key]) for t in turns if key in t]) for name, key in STAGES},
        "barge_ins": stats.get("barge_ins", 0), "stt_rejected": stats.get("stt_rejected", 0),
        "stt": doc.get("stt"), "llm": doc.get("llm"), "tts": doc.get("tts"),
        "tts_tone": doc.get("tts_tone"), "tts_speed": doc.get("tts_speed"),
        "phone_filter": bool(doc.get("phone_filter")), "realtime": bool(stats.get("realtime")),
        "has_audio": _has_audio(folder, doc),
        "cost_usd": ((doc.get("usage") or {}).get("cost") or {}).get("total"),
        "gpu_s": ((doc.get("usage") or {}).get("items") or {}).get("gpu_s"),
    }


def _selected(docs: list[dict], profile: str | None, scenario: str | None, outcome: str | None) -> list[dict]:
    out = []
    for d in docs:
        if profile and d.get("profile") != profile:
            continue
        flow = d.get("flow") or {}
        if scenario and flow.get("scenario") != scenario:
            continue
        if outcome and flow.get("outcome") != outcome:
            continue
        out.append(d)
    return out


def list_calls(folder: Path, profile: str | None = None, scenario: str | None = None, outcome: str | None = None,
               limit: int = 200) -> dict:
    """En yeni üstte. `facets`: süzgeç seçenekleri (tüm kayıtlardan, süzgeçten bağımsız)."""
    docs = load_sessions(folder)
    docs.sort(key=lambda d: d.get("started_at") or "", reverse=True)
    facets = {
        "profiles": sorted({d["profile"] for d in docs}),
        "scenarios": sorted({(d.get("flow") or {}).get("scenario") for d in docs if (d.get("flow") or {}).get("scenario")}),
        "outcomes": sorted({(d.get("flow") or {}).get("outcome") for d in docs if (d.get("flow") or {}).get("outcome")}),
    }
    rows = [summary(d, folder) for d in _selected(docs, profile, scenario, outcome)]
    return {"calls": rows[:limit], "total": len(rows), "facets": facets}


def detail(folder: Path, sid: str) -> dict | None:
    for doc in load_sessions(folder):
        if doc.get("id") == sid:
            flow = doc.get("flow") or {}
            stats = doc.get("stats") or {}
            return {
                **summary(doc, folder),
                "transcript": doc.get("transcript") or [], "turns": doc.get("turns") or [],
                "answers": flow.get("answers") or [], "path": flow.get("path") or [], "prompt": flow.get("prompt"),
                "usage": doc.get("usage"),
                "stats": {k: stats.get(k) for k in ("seconds_in", "agent_seconds_out", "utterances", "dropped", "barge_ins",
                                                    "holds", "merged", "stt_rejected", "peak_in_db") if k in stats},
            }
    return None


def _usage_group(docs: list[dict]) -> dict:
    """eval-003: aramalarin `usage` blogundan ortalama maliyet/GPU saniyesi. Blogu olmayan eski aramalar sayilmaz (sifir varsayilmaz)."""
    us = [d["usage"] for d in docs if d.get("usage")]
    costs = [u["cost"]["total"] for u in us if (u.get("cost") or {}).get("total") is not None]
    return {"usage_calls": len(us), "avg_cost_usd": round(statistics.mean(costs), 6) if costs else None,
            "cost_complete": bool(us) and all((u.get("cost") or {}).get("complete") for u in us),
            "avg_gpu_s": round(statistics.mean([u["items"]["gpu_s"] for u in us]), 2) if us else None,
            "avg_stt_minutes": round(statistics.mean([u["items"]["stt_minutes"] for u in us]), 3) if us else None,
            "avg_tts_chars": round(statistics.mean([u["items"]["tts_chars"] for u in us])) if us else None}


def _fp_state(doc: dict) -> str:
    """Arama hangi hızlı yol ayarıyla yapıldı: 'acik' | 'kapali' | 'bilinmiyor' (config bloğu yazılmadan önceki eski kayıtlar)."""
    v = (doc.get("config") or {}).get("fast_path")
    return "bilinmiyor" if v is None else ("acik" if v else "kapali")


FP_LABEL = {"acik": "hızlı yol açık", "kapali": "hızlı yol kapalı", "bilinmiyor": "ayar kaydı yok (eski)"}


def _group(key: str, label: str, docs: list[dict]) -> dict:
    turns = [t for d in docs for t in _turns(d)]
    fast_turns = [t for t in turns if t.get("fast_path")]
    first_fast = [float(t["first_audio_after_end_s"]) for t in fast_turns if "first_audio_after_end_s" in t]
    first_llm = [float(t["first_audio_after_end_s"]) for t in turns if not t.get("fast_path") and "llm_s" in t and "first_audio_after_end_s" in t]
    first = [float(t["first_audio_after_end_s"]) for t in turns if "first_audio_after_end_s" in t]
    outcomes: dict[str, int] = {}
    for d in docs:
        o = (d.get("flow") or {}).get("outcome") or "bitmedi"
        outcomes[o] = outcomes.get(o, 0) + 1
    durations = [s["duration_s"] for s in (summary(d, Path()) for d in docs) if isinstance(s["duration_s"], (int, float))]
    ans = [sum(1 for a in (d.get("flow") or {}).get("answers", []) if not a.get("unanswered")) for d in docs]
    return {
        "key": key, "label": label, "sessions": len(docs), "turns": len(turns),
        # Hızlı yol etkisi: kural yoluyla (LLM'siz) çözülen tur sayısı ve o turların ilk ses süresi, LLM'li turlarınkiyle yan yana
        "fast_turns": len(fast_turns), "fast_share": round(len(fast_turns) / len(turns), 3) if turns else None,
        "first_audio_fast_p50": round(statistics.median(first_fast), 3) if first_fast else None,
        "first_audio_llm_p50": round(statistics.median(first_llm), 3) if first_llm else None,
        "first_audio": ({"p50": round(statistics.median(first), 3), "p95": round(_pct(first, 0.95), 3),
                         "min": round(min(first), 3), "max": round(max(first), 3)} if first else None),
        "stages": {name: _med([float(t[k]) for t in turns if k in t]) for name, k in STAGES},
        "outcomes": outcomes,
        "avg_duration_s": round(statistics.mean(durations), 1) if durations else None,
        "avg_answers": round(statistics.mean(ans), 2) if ans else None,
        "barge_ins_per_call": round(statistics.mean([(d.get("stats") or {}).get("barge_ins", 0) for d in docs]), 2),
        "stt_rejected_total": sum((d.get("stats") or {}).get("stt_rejected", 0) for d in docs),
        **_usage_group(docs),
        "tts": sorted({d["tts"] for d in docs if d.get("tts")}), "tones": sorted({d["tts_tone"] for d in docs if d.get("tts_tone")}),
        "realtime": any((d.get("stats") or {}).get("realtime") for d in docs),
        "meets_p50_target": bool(first) and statistics.median(first) < P50_TARGET_S,
        "enough_sessions": len(docs) >= MIN_SESSIONS,
    }


def compare(folder: Path, group: str = "profile", ids: list[str] | None = None, baseline: str | None = None,
            profile: str | None = None, scenario: str | None = None, outcome: str | None = None) -> dict:
    """`group=profile`: profil başına tüm (süzülmüş) aramalar bir satır; `group=call`: `ids` ile seçilen her arama bir satır.
    Her satıra taban satıra göre fark eklenir (`delta_p50_s`, `delta_pct`); taban verilmezse ilk satırdır."""
    docs = _selected(load_sessions(folder), profile, scenario, outcome)
    if group == "call":
        wanted = list(dict.fromkeys(ids or []))
        by_id = {d.get("id"): d for d in docs}
        groups = [_group(i, f"{by_id[i]['profile']} · {(by_id[i].get('started_at') or '')[5:16].replace('T', ' ')}", [by_id[i]])
                  for i in wanted if i in by_id]
    elif group == "variant":
        by_var: dict[tuple[str, str], list[dict]] = {}
        for d in docs:
            by_var.setdefault((d["profile"], _fp_state(d)), []).append(d)
        order = {"kapali": 0, "acik": 1, "bilinmiyor": 2}
        groups = [_group(f"{p}|{st}", f"{p} · {FP_LABEL[st]}", ds)
                  for (p, st), ds in sorted(by_var.items(), key=lambda kv: (kv[0][0], order[kv[0][1]]))]
    else:
        by_profile: dict[str, list[dict]] = {}
        for d in docs:
            by_profile.setdefault(d["profile"], []).append(d)
        groups = [_group(p, p, ds) for p, ds in sorted(by_profile.items())]
    base = next((g for g in groups if g["key"] == baseline), groups[0] if groups else None)
    for g in groups:
        ref = base
        if group == "variant" and not baseline:       # her profilin açık hali kendi kapalı haliyle kıyaslanır
            ref = None if g["key"].endswith("|bilinmiyor") else next((x for x in groups if x["key"] == f"{g['key'].split('|')[0]}|kapali"), None)
        b50 = (ref or {}).get("first_audio") and ref["first_audio"]["p50"]
        g50 = g["first_audio"] and g["first_audio"]["p50"]
        g["is_baseline"] = ref is not None and g["key"] == ref["key"]
        g["delta_p50_s"] = round(g50 - b50, 3) if b50 is not None and g50 is not None else None
        g["delta_pct"] = round((g50 - b50) / b50 * 100, 1) if b50 and g50 is not None else None
    return {"group": group, "baseline": base["key"] if base else None, "groups": groups, "p50_target_s": P50_TARGET_S,
            "min_sessions": MIN_SESSIONS,
            "definition": "Gecikme: VAD konuşma bitişinden ajanın ilk sesine (açılış turu hariç). Aşamalar tur başına medyandır."}
